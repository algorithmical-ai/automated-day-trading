"""
MCP Client for interacting with Market Data Analyzer API
Uses MCP protocol with StreamableHTTP transport, with HTTP fallback
"""

import json
import asyncio
import time
import aiohttp
from typing import Optional, Dict, Any
from app.src.common.loguru_logger import logger
from app.src.config.constants import (
    DEBUG_DAY_TRADING,
    MARKET_DATA_MCP_URL,
    MCP_AUTH_HEADER_NAME,
    MARKET_DATA_MCP_TOKEN,
)
from app.src.services.tool_discovery.tool_discovery import ToolDiscoveryService


class MCPClient:
    """Client for interacting with MCP tools using MCP protocol"""

    _base_url: str = MARKET_DATA_MCP_URL
    _auth_header_name: str = MCP_AUTH_HEADER_NAME
    _auth_token: Optional[str] = MARKET_DATA_MCP_TOKEN
    _tool_discovery_cls: Optional[type] = ToolDiscoveryService
    _last_request_time: float = 0.0
    _min_request_interval: float = 0.1  # 100ms minimum between requests

    @classmethod
    def configure(
        cls,
        *,
        tool_discovery_cls: Optional[type] = ToolDiscoveryService,
        base_url: Optional[str] = None,
        auth_header_name: Optional[str] = None,
        auth_token: Optional[str] = None,
    ):
        """Configure MCP client for classmethod-only usage"""
        if base_url:
            cls._base_url = base_url
        if auth_header_name:
            cls._auth_header_name = auth_header_name
        if auth_token is not None:
            cls._auth_token = auth_token
        if tool_discovery_cls is not None:
            cls._tool_discovery_cls = tool_discovery_cls

    @classmethod
    def _extract_result_payload(cls, data: Any) -> Any:
        """Unwrap MCP JSON-RPC responses to expose the underlying tool payload."""
        if not isinstance(data, dict):
            return data

        # Standard JSON-RPC response structure
        result = data.get("result")
        if not isinstance(result, dict):
            return data

        content = result.get("content")
        if isinstance(content, list):
            for chunk in content:
                if not isinstance(chunk, dict):
                    continue
                text = chunk.get("text")
                if isinstance(text, str) and text.strip():
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Failed to decode MCP content as JSON. Returning raw text. Payload preview: %s",
                            text[:200],
                        )
                        return {"content_text": text}
        return result

    @classmethod
    async def _call_mcp_tool_http(
        cls, tool_name: str, params: Dict[str, Any], retry_on_503: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Call MCP tool using HTTP POST with JSON-RPC format (MCP protocol)
        MCP Inspector uses this format, so we should use it first

        Args:
            tool_name: Name of the MCP tool to call
            params: Parameters for the tool
            retry_on_503: If True, will retry on 503 errors with exponential backoff
        """
        # Rate limiting: ensure minimum interval between requests
        current_time = time.time()
        time_since_last = current_time - cls._last_request_time
        if time_since_last < cls._min_request_interval:
            await asyncio.sleep(cls._min_request_interval - time_since_last)
        cls._last_request_time = time.time()

        max_retries = 3 if retry_on_503 else 1
        base_delay = 2.0  # Start with 2 second delay

        for attempt in range(max_retries):
            try:
                headers = {"Content-Type": "application/json"}
                if cls._auth_token:
                    headers[cls._auth_header_name] = cls._auth_token

                # Use MCP JSON-RPC format (same as MCP Inspector)
                # POST to base_url with tools/call method
                jsonrpc_body = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": params},
                }

                # Use longer timeout since API can take 5-10 seconds
                timeout = aiohttp.ClientTimeout(total=30)  # 30 second timeout
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        cls._base_url, json=jsonrpc_body, headers=headers
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return cls._extract_result_payload(data)
                        elif (
                            response.status == 503
                            and retry_on_503
                            and attempt < max_retries - 1
                        ):
                            # 503 Service Unavailable - server is overloaded, retry with backoff
                            delay = base_delay * (2**attempt)  # 2s, 4s, 8s
                            logger.warning(
                                f"Server overloaded (503) calling {tool_name}, "
                                f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            # Handle error response - check if it's HTML or JSON
                            content_type = response.headers.get(
                                "Content-Type", ""
                            ).lower()
                            error_text = await response.text()

                            # Detect HTML responses (Heroku error pages)
                            if (
                                "text/html" in content_type
                                or error_text.strip().startswith("<!DOCTYPE")
                                or error_text.strip().startswith("<html")
                            ):
                                if response.status == 503:
                                    if attempt < max_retries - 1:
                                        delay = base_delay * (2**attempt)
                                        logger.warning(
                                            f"Server overloaded (503) calling {tool_name}, "
                                            f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                                        )
                                        await asyncio.sleep(delay)
                                        continue
                                    else:
                                        logger.warning(
                                            f"Server overloaded (503) calling {tool_name} after {max_retries} attempts - "
                                            f"MCP server is experiencing high load"
                                        )
                                else:
                                    logger.error(
                                        f"HTTP Error calling {tool_name} (MCP JSON-RPC): {response.status} - Server returned HTML error page"
                                    )
                            else:
                                # Try to extract meaningful error message from JSON response
                                try:
                                    error_json = json.loads(error_text)
                                    # Check if it's a JSON-RPC error response
                                    if "error" in error_json:
                                        error_data = error_json.get("error", {})
                                        error_msg = error_data.get(
                                            "message", str(error_data)
                                        )
                                        error_code = error_data.get("code", "unknown")
                                        logger.error(
                                            f"JSON-RPC Error calling {tool_name}: {error_code} - {error_msg}"
                                        )
                                    else:
                                        error_msg = str(error_json).replace("\n", " ")[
                                            :200
                                        ]
                                        logger.error(
                                            f"HTTP Error calling {tool_name} (MCP JSON-RPC): {response.status} - {error_msg}"
                                        )
                                except (json.JSONDecodeError, ValueError):
                                    error_msg = error_text[:200]
                                    logger.error(
                                        f"HTTP Error calling {tool_name} (MCP JSON-RPC): {response.status} - {error_msg}"
                                    )
                            return None
            except asyncio.TimeoutError as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Timeout calling {tool_name} (30s timeout exceeded), retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    f"Timeout calling {tool_name} after {max_retries} attempts - external server may be overloaded or slow"
                )
                return None
            except asyncio.CancelledError:
                logger.warning(
                    f"Request to {tool_name} was cancelled (likely due to timeout or shutdown)"
                )
                raise  # Re-raise CancelledError so it propagates properly
            except aiohttp.ClientError as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"HTTP client error calling {tool_name}, retrying in {delay}s: {str(e)}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.exception(f"HTTP client error calling {tool_name}: {str(e)}")
                return None
            except Exception as e:  # pylint: disable=broad-except
                logger.exception(f"Unexpected exception calling {tool_name}: {str(e)}")
                return None

        return None

    @classmethod
    async def _call_mcp_tool(
        cls, tool_name: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generic method to call MCP tools - uses HTTP directly since MCP protocol fails with 500 errors"""
        # Check if tool is available via discovery service
        if cls._tool_discovery_cls:
            is_available = await cls._tool_discovery_cls.is_tool_available(tool_name)
            if not is_available:
                logger.debug(
                    f"Tool {tool_name} not found in discovered tools list, trying anyway..."
                )

        # Since MCP protocol is consistently failing with 500 errors, use HTTP directly
        # The server appears to not be handling our MCP protocol requests correctly
        # MCP Inspector might be using a different approach or version
        return await cls._call_mcp_tool_http(tool_name, params)

    @classmethod
    async def call_tool(
        cls, tool_name: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generic method to call any discovered MCP tool by name"""
        return await cls._call_mcp_tool(tool_name, params)

    @classmethod
    async def get_market_clock(cls) -> Optional[Dict[str, Any]]:
        """Get market clock status"""
        if DEBUG_DAY_TRADING:
            return {"clock": {"is_open": True}}
        return await cls._call_mcp_tool("get_market_clock", {})

    @classmethod
    async def get_alpaca_screened_tickers(cls) -> Optional[Dict[str, Any]]:
        """Get screened tickers (gainers, losers, most_actives)"""
        return await cls._call_mcp_tool("get_alpaca_screened_tickers", {})

    @classmethod
    async def get_quote(cls, ticker: str) -> Optional[Dict[str, Any]]:
        """Get quote for a ticker"""
        params = {"ticker": ticker}
        return await cls._call_mcp_tool("get_quote", params)

    @classmethod
    async def enter(cls, ticker: str, action: str) -> Optional[Dict[str, Any]]:
        """Call enter() MCP tool"""
        params = {"ticker": ticker, "action": action}
        return await cls._call_mcp_tool("enter", params)

    @classmethod
    async def exit(
        cls, ticker: str, enter_price: float, action: str
    ) -> Optional[Dict[str, Any]]:
        """Call exit() MCP tool"""
        params = {"ticker": ticker, "enter_price": enter_price, "action": action}
        return await cls._call_mcp_tool("exit", params)

    @classmethod
    async def get_market_data(cls, ticker: str) -> Optional[Dict[str, Any]]:
        """Get market data for a ticker including technical analysis and datetime_price"""
        params = {"ticker": ticker}
        return await cls._call_mcp_tool("get_market_data", params)
