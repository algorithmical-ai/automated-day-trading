"""MCP server entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any, Dict, List, Optional

from starlette.applications import Starlette
from starlette.responses import JSONResponse

from app.src.common.loguru_logger import logger
from app.src.services.mcp.clients import MCPToolClient, MarketDataClient
from app.src.services.mcp.config import (
    MCPClientSettings,
    ServerSettings,
    get_settings,
)
from app.src.services.mcp.tools import register_tools

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined]
except ModuleNotFoundError as exc:  # pragma: no cover - defensive import guard
    raise ImportError(
        "The `mcp` package is required to run the Workflow Manager MCP server. "
        "Install dependencies via `pip install -r requirements.txt` or "
        "`conda env update -f environment.yml`."
    ) from exc


settings: ServerSettings = get_settings()
client_settings = MCPClientSettings.model_validate(settings.mcp_clients)


class AllowAnyHostASGIWrapper:
    """ASGI wrapper to allow any host header (for Heroku compatibility).

    Uvicorn validates the Host header, but on Heroku the Host header can be any
    subdomain. This wrapper modifies the scope to bypass validation.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        # For HTTP requests, ensure the server tuple matches what uvicorn expects
        # This helps bypass host header validation
        if scope.get("type") == "http":
            # Set server to match the bound host/port to bypass validation
            # Uvicorn validates by comparing Host header to server tuple
            current_server = scope.get("server")
            if current_server:
                # Keep the port but set host to 0.0.0.0 to match our binding
                scope["server"] = ("0.0.0.0", current_server[1])
            else:
                scope["server"] = ("0.0.0.0", 8000)

        await self.app(scope, receive, send)


class HeaderTokenAuthMiddleware:
    """Simple header-based bearer token authentication middleware."""

    def __init__(self, app: Any, *, header_name: str, expected_token: str) -> None:
        self.app = app
        self._header_name = header_name.lower()
        self._expected_token = expected_token
        self._expected_bearer = f"bearer {expected_token}".lower()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_value = self._extract_header(scope)
        if header_value is None:
            await self._reject(scope, receive, send, "Missing authentication header.")
            return
        normalized = header_value.lower()
        if normalized != self._expected_bearer and header_value != self._expected_token:
            await self._reject(scope, receive, send, "Invalid authentication token.")
            return

        await self.app(scope, receive, send)

    def _extract_header(self, scope: Any) -> Optional[str]:
        for name_bytes, value_bytes in scope.get("headers", ()):
            if name_bytes.decode("latin1").lower() == self._header_name:
                return value_bytes.decode("latin1").strip()
        return None

    async def _reject(self, scope: Any, receive: Any, send: Any, detail: str) -> None:
        response = JSONResponse(
            {"error": "unauthorized", "detail": detail},
            status_code=401,
        )
        await response(scope, receive, send)


class WorkflowFastMCP(FastMCP[Any]):
    """FastMCP variant that enforces header-based authentication."""

    def __init__(
        self,
        *args: Any,
        header_name: str,
        bearer_token: Optional[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._workflow_auth_header_name = header_name
        self._workflow_auth_token = bearer_token
        if not bearer_token:
            logger.warning(
                "MCP authentication token is not configured. Incoming connections will not be authenticated."
            )

    def _wrap_with_auth(self, starlette_app: "Starlette") -> "Starlette":
        if self._workflow_auth_token:
            starlette_app.add_middleware(
                HeaderTokenAuthMiddleware,
                header_name=self._workflow_auth_header_name,
                expected_token=self._workflow_auth_token,
            )
        return starlette_app

    def sse_app(self, mount_path: str | None = None) -> "Starlette":
        app = super().sse_app(mount_path)
        return self._wrap_with_auth(app)

    def streamable_http_app(self) -> "Starlette":
        app = super().streamable_http_app()
        return self._wrap_with_auth(app)


class ToolRegistry:
    """Thread-safe registry of discovered tools from remote MCP servers."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tools: Dict[str, List[Dict[str, Any]]] = {}

    async def update(self, source: str, tools: List[Dict[str, Any]]) -> None:
        async with self._lock:
            self._tools[source] = tools

    async def snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        async with self._lock:
            return {key: list(value) for key, value in self._tools.items()}

    async def get(self, source: str) -> List[Dict[str, Any]]:
        async with self._lock:
            return list(self._tools.get(source, []))


tool_registry = ToolRegistry()

# Queue for async workflow initialization
initialization_queue: asyncio.Queue[str] = asyncio.Queue()

app = WorkflowFastMCP(
    name="automated-trading-system",
    header_name=settings.mcp_auth_header_name,
    bearer_token=settings.mcp_auth_bearer_token,
)

market_tool_client = MCPToolClient(
    server_url=client_settings.market_data_url,
    server_name=client_settings.market_data_name,
    auth_token=client_settings.market_data_token,
    shared_auth_header_name=settings.mcp_auth_header_name,
    shared_auth_token=settings.mcp_auth_bearer_token,
)

market_client = MarketDataClient(market_tool_client)


# Tool sources configuration - add more MCP clients here as needed
_TOOL_SOURCES = [
    ("market-data", market_tool_client),
]

# Register all tools with the app
register_tools(app, tool_registry, market_client)


async def _refresh_tool_registry() -> None:
    """Fetch tool inventories from upstream MCP servers."""
    for source, client in _TOOL_SOURCES:
        try:
            # Add timeout to prevent hanging
            tools_result = await asyncio.wait_for(
                client.list_tools(), timeout=10.0  # 10 second timeout per source
            )
            serialized = [
                (
                    tool.model_dump(mode="json")
                    if hasattr(tool, "model_dump")
                    else dict(tool)
                )
                for tool in tools_result.tools
            ]
            await tool_registry.update(source, serialized)
            logger.info("Discovered {} tools for {}", len(serialized), source)
            if serialized:
                logger.debug("Tool metadata for {}: {}", source, serialized)
            else:
                logger.info("Tool metadata for {} is empty.", source)
        except asyncio.TimeoutError:
            logger.warning("Tool discovery for {} timed out after 10 seconds", source)
        except Exception as exc:
            logger.warning("Failed to discover tools for {}: {}", source, exc)


async def _periodic_tool_discovery() -> None:
    """Periodically discover tools exposed by upstream MCP servers."""
    interval = max(settings.tool_discovery_interval_seconds, 60)
    logger.info("🔍 Tool discovery service starting (interval: {}s)", interval)
    # Give the server a moment to fully start before initial discovery
    await asyncio.sleep(2)
    logger.info("🔍 Starting initial tool discovery...")
    await _refresh_tool_registry()
    logger.info("🔍 Initial tool discovery complete. Next refresh in {}s", interval)
    while True:
        await asyncio.sleep(interval)
        logger.info("🔍 Periodic tool discovery refresh...")
        await _refresh_tool_registry()
        logger.info("🔍 Tool discovery refresh complete. Next refresh in {}s", interval)


async def _initialization_worker() -> None:
    """Background worker that processes initialization queue."""
    logger.info("🚀 Automated Trading System initialization worker started")
    while True:
        try:
            pass
        except asyncio.CancelledError:
            logger.info(
                "🛑 Automated Trading System initialization worker shutting down"
            )
            break
        except Exception as exc:
            logger.error("❌ Unexpected error in initialization worker: {}", exc)
            await asyncio.sleep(1)  # Brief pause before continuing


async def main() -> None:
    """
    Run the MCP server using the configured transport.

    This is the async entry point that can be called from other async contexts.
    """
    transport = settings.transport
    if transport == "streamable-http":
        await _run_streamable_with_discovery()
    elif transport == "stdio":
        await _refresh_tool_registry()
        # stdio transport needs to be run in a separate process
        # so we'll use the synchronous app.run()
        app.run("stdio")
    else:
        await _run_sse_with_discovery()


def main_sync() -> None:
    """
    Synchronous entry point for running the MCP server from command line.

    This wraps the async main() function for use when called directly.
    """
    asyncio.run(main())


async def _run_streamable_with_discovery() -> None:
    import uvicorn
    
    # Patch uvicorn Server to disable host header validation for Heroku compatibility
    # Uvicorn validates Host header in the Server class before forwarding to ASGI app
    try:
        from uvicorn.server import Server
        
        # Store original _should_check_host method if it exists
        if hasattr(Server, '_should_check_host'):
            original_should_check_host = Server._should_check_host
            
            def patched_should_check_host(self, headers):
                # Always return False to disable host checking
                return False
            
            Server._should_check_host = patched_should_check_host
            logger.info("✅ Patched uvicorn Server._should_check_host to bypass validation")
        else:
            # Try patching the protocol's host validation
            # The host validation might be in the protocol implementation
            logger.info("ℹ️  uvicorn Server._should_check_host not found, using ASGI wrapper approach")
    except (ImportError, AttributeError) as e:
        logger.warning(f"⚠️  Could not patch uvicorn host validation: {e}")
        logger.warning("⚠️  Host header validation may still cause issues on Heroku")

    # Get host and port from environment (Heroku compatibility)
    host = os.environ.get("HOST", "0.0.0.0")
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except (ValueError, TypeError):
        logger.warning(
            f"⚠️  Invalid PORT environment variable: '{port_str}', defaulting to 8000"
        )
        port = 8000

    logger.info(f"🔧 Environment: HOST={host}, PORT={port} (from env: '{port_str}')")

    # Initialize database and start executor at server startup
    logger.info("Starting Automated Trading System MCP server.")
    logger.info(f"🌐 MCP Server will listen on {host}:{port}")
    logger.info(
        f"🔐 Authentication: {'ENABLED' if settings.mcp_auth_bearer_token else 'DISABLED'}"
    )
    if settings.mcp_auth_bearer_token:
        logger.info(f"   Header: {settings.mcp_auth_header_name}")
        logger.info(f"   Token: {'*' * min(len(settings.mcp_auth_bearer_token), 8)}...")
    logger.info(f"🔗 MCP endpoint will be available at: http://{host}:{port}/mcp")

    # Get the Starlette app and run it with uvicorn
    starlette_app = app.streamable_http_app()

    # Wrap the ASGI app to allow any host header (for Heroku compatibility)
    # This bypasses uvicorn's host header validation
    wrapped_app = AllowAnyHostASGIWrapper(starlette_app)
    logger.info(
        "✅ Wrapped ASGI app with AllowAnyHostASGIWrapper for Heroku compatibility"
    )

    # Log registered routes for debugging
    logger.info(
        f"📋 Registered routes: {[route.path for route in starlette_app.routes if hasattr(route, 'path')]}"
    )

    # Add a health check endpoint (before other routes to avoid conflicts)
    from starlette.routing import Route

    async def health_check(request: Any) -> JSONResponse:
        """Health check endpoint for Heroku"""
        return JSONResponse(
            {
                "status": "healthy",
                "service": "automated-trading-system-mcp",
                "port": port,
                "auth_configured": bool(settings.mcp_auth_bearer_token),
            }
        )

    # Add health check route - insert at beginning to ensure it's checked first
    try:
        health_route = Route("/health", health_check, methods=["GET"])
        # Check if health route already exists
        existing_health = [
            r
            for r in starlette_app.routes
            if hasattr(r, "path") and r.path == "/health"
        ]
        if not existing_health:
            starlette_app.routes.insert(0, health_route)  # Insert at beginning
            logger.info("✅ Health check endpoint added at /health")
        else:
            logger.info("ℹ️  Health check endpoint already exists")
    except Exception as e:
        logger.warning(f"⚠️  Could not add health check endpoint: {e}")

    # Track background tasks - use a dict to avoid closure issues
    background_tasks: Dict[str, Optional[asyncio.Task]] = {
        "discovery": None,
        "initialization": None,
    }

    # Add startup event to Starlette app
    @starlette_app.on_event("startup")
    async def startup_event():
        # Start background tasks after server is ready
        # Use create_task to ensure this doesn't block startup
        logger.info(
            "🚀 MCP Server startup event fired - scheduling background tasks..."
        )
        try:
            background_tasks["discovery"] = asyncio.create_task(
                _periodic_tool_discovery()
            )
            background_tasks["initialization"] = asyncio.create_task(
                _initialization_worker()
            )
            # Don't await - let them run in background
            logger.info(
                "✅ Background tasks scheduled: discovery={}, initialization={}",
                background_tasks["discovery"] is not None,
                background_tasks["initialization"] is not None,
            )
        except Exception as e:
            logger.exception("❌ Error scheduling background tasks: {}", e)

    @starlette_app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Shutting down Automated Trading System MCP server.")
        for task_name, task in background_tasks.items():
            if task:
                logger.info(f"Cancelling {task_name} task")
                task.cancel()
        for task_name, task in background_tasks.items():
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await market_tool_client.close()
        logger.info("Automated Trading System MCP server shutdown complete.")

    logger.info("⚙️  Creating uvicorn config...")
    # Create config - uvicorn validates Host header by default
    # For Heroku, we wrap the app to handle host header validation
    # Note: uvicorn's host validation happens before the ASGI app receives the request
    # so we handle it in the ASGI wrapper
    config = uvicorn.Config(
        wrapped_app,  # Use wrapped app instead of starlette_app
        host=host,
        port=port,
        log_level="info",
        server_header=False,  # Disable server header
    )
    logger.info("✅ Uvicorn config created")

    logger.info("⚙️  Creating uvicorn server...")
    server = uvicorn.Server(config)
    logger.info("✅ Uvicorn server object created")

    logger.info(f"🚀 Starting uvicorn server on {host}:{port}")
    # Get Heroku app URL from environment or construct from request
    heroku_app_name = os.environ.get("HEROKU_APP_NAME", "automated-day-trading")
    logger.info(
        f"📡 MCP server ready. Connect to: https://{heroku_app_name}.herokuapp.com/mcp"
    )
    logger.info(
        f"💡 Note: FastMCP streamable HTTP may mount at root '/' - check registered routes above"
    )

    try:
        logger.info("🔄 About to call server.serve()...")
        await server.serve()
        logger.info("🔄 server.serve() completed (unexpected)")
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.exception(f"❌ Fatal error running MCP server: {e}")
        raise


async def _run_sse_with_discovery() -> None:
    import uvicorn

    # Get host and port from environment (Heroku compatibility)
    host = os.environ.get("HOST", "0.0.0.0")
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except (ValueError, TypeError):
        logger.warning(
            f"⚠️  Invalid PORT environment variable: '{port_str}', defaulting to 8000"
        )
        port = 8000

    logger.info(f"🔧 Environment: HOST={host}, PORT={port} (from env: '{port_str}')")

    # Initialize database and start executor at server startup
    logger.info("Starting Automated Trading System MCP server.")

    # Get the Starlette app and run it with uvicorn
    starlette_app = app.sse_app()

    # Track background tasks - use a dict to avoid closure issues
    background_tasks: Dict[str, Optional[asyncio.Task]] = {
        "discovery": None,
        "initialization": None,
    }

    # Add startup event to Starlette app
    @starlette_app.on_event("startup")
    async def startup_event():
        # Start background tasks after server is ready
        # Use create_task to ensure this doesn't block startup
        logger.info(
            "🚀 MCP Server startup event fired - scheduling background tasks..."
        )
        try:
            background_tasks["discovery"] = asyncio.create_task(
                _periodic_tool_discovery()
            )
            background_tasks["initialization"] = asyncio.create_task(
                _initialization_worker()
            )
            # Don't await - let them run in background
            logger.info(
                "✅ Background tasks scheduled: discovery={}, initialization={}",
                background_tasks["discovery"] is not None,
                background_tasks["initialization"] is not None,
            )
        except Exception as e:
            logger.exception("❌ Error scheduling background tasks: {}", e)

    @starlette_app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Shutting down Automated Trading System MCP server.")
        for task_name, task in background_tasks.items():
            if task:
                logger.info(f"Cancelling {task_name} task")
                task.cancel()
        for task_name, task in background_tasks.items():
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await market_tool_client.close()
        logger.info("Automated Trading System MCP server shutdown complete.")

    config = uvicorn.Config(
        starlette_app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    logger.info(f"🚀 Starting uvicorn server on {host}:{port}")
    # Get Heroku app URL from environment or construct from request
    heroku_app_name = os.environ.get("HEROKU_APP_NAME", "automated-day-trading")
    logger.info(
        f"📡 MCP server ready. Connect to: https://{heroku_app_name}.herokuapp.com/mcp"
    )
    logger.info(
        f"💡 Note: FastMCP streamable HTTP may mount at root '/' - check registered routes above"
    )

    try:
        logger.info("🔄 Server starting...")
        await server.serve()
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.exception(f"❌ Fatal error running MCP server: {e}")
        raise


if __name__ == "__main__":
    main_sync()
