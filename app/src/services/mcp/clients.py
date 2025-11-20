"""Clients for interacting with external MCP servers."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, Optional

import httpx

from app.src.common.loguru_logger import logger

try:
    from mcp.client.sse_client import SSEClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback if mcp package unavailable
    SSEClient = None  # type: ignore[assignment]
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, Implementation, ListToolsResult

from app.src.config import constants


class MCPClientError(RuntimeError):
    """Raised when invoking an MCP tool fails."""


class MCPToolClient:
    """Generic MCP tool client with SSE or HTTP fallback."""

    def __init__(
        self,
        *,
        server_url: str,
        server_name: str,
        auth_token: Optional[str] = None,
        timeout: float = 30.0,
        shared_auth_header_name: str = constants.MCP_AUTH_HEADER_NAME,
        shared_auth_token: Optional[str] = constants.MCP_AUTH_BEARER_TOKEN,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._server_name = server_name
        self._auth_token = auth_token
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._shared_auth_header_name = shared_auth_header_name
        self._shared_auth_token = shared_auth_token
        self._client_info = Implementation(name="workflow-manager", version="1.0.0")

    async def _ensure_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            headers = self._build_headers(include_accept=True)
            self._http_client = httpx.AsyncClient(
                base_url=self._server_url, timeout=self._timeout, headers=headers
            )
        return self._http_client

    async def close(self) -> None:
        """Close any open resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        if SSEClient is not None:
            try:
                return await self._call_tool_via_sse(tool_name, arguments)
            except Exception as sse_exc:  # noqa: BLE001
                logger.debug(
                    "SSE invocation failed for tool %s: %s; falling back to Streamable HTTP",
                    tool_name,
                    sse_exc,
                )
        try:
            return await self._call_tool_via_streamable_http(tool_name, arguments)
        except Exception as streamable_exc:
            logger.debug(
                "Streamable HTTP invocation failed for tool %s: %s; falling back to HTTP endpoint",
                tool_name,
                streamable_exc,
            )
            return await self._call_tool_via_http(tool_name, arguments)

    async def list_tools(self) -> ListToolsResult:
        """List tools exposed by the MCP server."""
        errors: list[str] = []

        if SSEClient is not None:
            try:
                return await self._list_tools_via_sse()
            except Exception as sse_exc:  # noqa: BLE001
                msg = (
                    f"SSE list_tools failed for {self._server_name}: {sse_exc}. "
                    "Attempting Streamable HTTP."
                )
                errors.append(msg)
                logger.debug(msg)

        try:
            return await self._list_tools_via_streamable_http()
        except Exception as streamable_exc:  # noqa: BLE001
            msg = (
                f"Streamable HTTP list_tools failed for {self._server_name}: {streamable_exc}. "
                "Attempting HTTP fallback."
            )
            errors.append(msg)
            logger.debug(msg)

        try:
            return await self._list_tools_via_http()
        except Exception as http_exc:  # noqa: BLE001
            errors.append(f"HTTP list_tools failed for {self._server_name}: {http_exc}")
            logger.error(
                "All list_tools transports failed for {}. Errors: {}",
                self._server_name,
                errors,
            )
            raise MCPClientError("; ".join(errors)) from http_exc

    async def _call_tool_via_sse(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        if SSEClient is None:  # pragma: no cover
            raise MCPClientError("SSE client unavailable and HTTP fallback disabled.")
        headers = self._build_headers(include_accept=True)
        async with SSEClient(
            server_name=self._server_name,
            server_url=self._server_url,
            extra_headers=headers or None,
            timeout=self._timeout,
        ) as client:
            response = await client.call_tool(tool_name, arguments=arguments)
        payload = getattr(response, "content", None) or getattr(response, "data", None)
        if payload is None:
            raise MCPClientError(f"No content returned from tool {tool_name}")
        if isinstance(payload, str):
            return json.loads(payload)
        if isinstance(payload, dict):
            return payload
        # Some implementations return list of tool outputs
        if isinstance(payload, list) and payload:
            maybe_text = (
                payload[0].get("text") if isinstance(payload[0], dict) else None
            )
            if maybe_text:
                try:
                    return json.loads(maybe_text)
                except json.JSONDecodeError as exc:
                    raise MCPClientError(
                        f"Unable to decode tool response: {maybe_text}"
                    ) from exc
        raise MCPClientError(f"Unexpected tool response type: {type(payload)}")

    async def _call_tool_via_http(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = await self._send_jsonrpc_request(
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )
        result_payload = payload.get("result")
        if result_payload is None:
            raise MCPClientError(
                f"Tool call failed for {tool_name}: {payload.get('error') or payload}"
            )
        call_result = CallToolResult.model_validate(result_payload)
        return self._normalize_tool_result(call_result, tool_name)

    async def _call_tool_via_streamable_http(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        headers = self._build_headers(include_accept=True)

        async with streamablehttp_client(
            self._server_url,
            headers=headers or None,
            timeout=self._timeout,
        ) as (read_stream, write_stream, _get_session_id):
            session = ClientSession(
                read_stream,
                write_stream,
                client_info=self._client_info,
            )
            await self._initialize_session(session)
            result = await session.call_tool(tool_name, arguments)
            return self._normalize_tool_result(result, tool_name)

    async def _list_tools_via_streamable_http(self) -> ListToolsResult:
        headers = self._build_headers(include_accept=True)

        async with streamablehttp_client(
            self._server_url,
            headers=headers or None,
            timeout=self._timeout,
        ) as (read_stream, write_stream, _get_session_id):
            session = ClientSession(
                read_stream,
                write_stream,
                client_info=self._client_info,
            )
            await self._initialize_session(session)
            return await session.list_tools()

    async def _list_tools_via_sse(self) -> ListToolsResult:
        if SSEClient is None:  # pragma: no cover
            raise MCPClientError("SSE client unavailable.")
        headers = self._build_headers(include_accept=True)
        async with SSEClient(
            server_name=self._server_name,
            server_url=self._server_url,
            extra_headers=headers or None,
            timeout=self._timeout,
        ) as client:
            return await client.list_tools()

    async def _list_tools_via_http(self) -> ListToolsResult:
        payload = await self._send_jsonrpc_request(
            method="tools/list",
            params={},
        )
        result_payload = payload.get("result")
        if result_payload is None:
            raise MCPClientError(
                f"Unable to list tools for {self._server_name}: {payload.get('error') or payload}"
            )
        return ListToolsResult.model_validate(result_payload)

    def _normalize_tool_result(
        self, result: CallToolResult, tool_name: str
    ) -> Dict[str, Any]:
        if result.isError:
            raise MCPClientError(
                f"Tool call {tool_name} failed with error response: {result.content}"
            )
        if result.structuredContent and isinstance(result.structuredContent, dict):
            return result.structuredContent
        if result.content:
            first = result.content[0]
            if isinstance(first, dict):
                maybe_text = first.get("text")
            else:
                maybe_text = getattr(first, "text", None)
                if maybe_text:
                    try:
                        return json.loads(maybe_text)
                    except json.JSONDecodeError as exc:
                        raise MCPClientError(
                            f"Unable to decode tool response text for {tool_name}: {maybe_text}"
                        ) from exc
        raise MCPClientError(f"Unexpected tool response format from {tool_name}")

    @staticmethod
    def _format_bearer_token(token: str) -> str:
        token = token.strip()
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"

    def _build_headers(self, *, include_accept: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if include_accept:
            headers["Accept"] = "application/json, text/event-stream"
        if self._shared_auth_token and self._shared_auth_header_name:
            headers[self._shared_auth_header_name] = self._format_bearer_token(
                self._shared_auth_token
            )
        if self._auth_token:
            headers["Authorization"] = self._format_bearer_token(self._auth_token)
        return headers

    async def _initialize_session(self, session: ClientSession) -> None:
        try:
            await asyncio.wait_for(session.initialize(), timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            raise MCPClientError(
                f"Timed out initializing Streamable HTTP session with {self._server_name}"
            ) from exc

    async def _send_jsonrpc_request(
        self, *, method: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        client = await self._ensure_http_client()
        try:
            response = await client.post(
                self._server_url,
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": method,
                    "params": params,
                },
            )
        except httpx.ReadTimeout as exc:
            raise MCPClientError(
                f"{method} timed out after {self._timeout}s while calling {self._server_name}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise MCPClientError(
                f"{method} timed out while calling {self._server_name}"
            ) from exc
        except httpx.RequestError as exc:
            raise MCPClientError(
                f"{method} request failed for {self._server_name}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise MCPClientError(
                f"{method} failed with status {response.status_code}: {response.text}"
            )
        payload = response.json()
        if "error" in payload and payload["error"]:
            raise MCPClientError(f"{method} returned error: {payload['error']}")
        return payload


class MarketDataClient:
    """Client facade over Market Data MCP server."""

    def __init__(self, tool_client: MCPToolClient) -> None:
        self._tool_client = tool_client

    async def get_market_clock(self) -> Dict[str, Any]:
        return await self._tool_client.call_tool("get_market_clock", {})

    async def get_quote(self, ticker: str) -> Dict[str, Any]:
        return await self._tool_client.call_tool("get_quote", {"ticker": ticker})

    async def get_market_data(self, ticker: str) -> Dict[str, Any]:
        return await self._tool_client.call_tool("get_market_data", {"ticker": ticker})

    async def get_sentiment(self, ticker: str) -> Dict[str, Any]:
        return await self._tool_client.call_tool("get_sentiment", {"ticker": ticker})
