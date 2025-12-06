"""Clean Streamable HTTP-based MCP server implementation."""

import json
import os
from typing import Any, Dict

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.src.common.loguru_logger import logger
from app.src.services.mcp.config import ServerSettings, get_settings
from app.src.services.mcp.tools import get_tool_registry

settings: ServerSettings = get_settings()


class MCPServer:
    """Simple MCP server using Streamable HTTP transport."""

    def __init__(self):
        self.tools = {}
        self.initialized = False
        self._register_tools()

    def _register_tools(self):
        """Register all tools from the tool registry."""
        tool_registry = get_tool_registry()
        for tool_name, tool_info in tool_registry.items():
            self.tools[tool_name] = tool_info
            logger.info(f"Registered tool: {tool_name}")

    async def handle_initialize(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        self.initialized = True
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
            },
            "serverInfo": {
                "name": "automated-trading-system",
                "version": "1.0.0",
            },
        }

    async def handle_tools_list(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        tools_list = []
        for tool_name, tool_info in self.tools.items():
            tool_def = {
                "name": tool_name,
                "description": tool_info.get("description", ""),
                "inputSchema": tool_info.get(
                    "inputSchema",
                    {
                        "type": "object",
                        "properties": {},
                    },
                ),
            }
            tools_list.append(tool_def)
        return {"tools": tools_list}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool_info = self.tools[tool_name]
        handler = tool_info["handler"]

        try:
            result = await handler(**arguments)
            # Ensure result is JSON-serializable
            if not isinstance(result, dict):
                result = {"result": result}
            json_str = json.dumps(result, ensure_ascii=False, default=str)
            return {"content": [{"type": "text", "text": json_str}]}
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
            error_msg = str(e)
            return {
                "content": [{"type": "text", "text": json.dumps({"error": error_msg})}],
                "isError": True,
            }

    async def handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a JSON-RPC request."""
        method = request_data.get("method")
        params = request_data.get("params", {})
        request_id = request_data.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            else:
                raise ValueError(f"Unknown method: {method}")

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except Exception as e:
            logger.error(f"Error handling request {method}: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                },
            }


# Global server instance
mcp_server = MCPServer()


async def mcp_endpoint(request):
    """Main MCP endpoint for Streamable HTTP transport."""
    # Handle CORS preflight requests
    if request.method == "OPTIONS":
        return JSONResponse(
            {},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-MCP-Proxy-Auth",
                "Access-Control-Max-Age": "86400",
            },
        )

    # Check for MCP Inspector proxy
    proxy_auth = request.headers.get("X-MCP-Proxy-Auth")
    if proxy_auth:
        logger.info("MCP Inspector proxy detected (X-MCP-Proxy-Auth header present)")

    # Check authentication if configured
    if settings.mcp_auth_bearer_token:
        auth_header_name = str(settings.mcp_auth_header_name).lower()
        auth_header = request.headers.get(auth_header_name)

        if not auth_header and not proxy_auth:
            return JSONResponse(
                {"error": "unauthorized", "detail": "Missing authentication header"},
                status_code=401,
            )

        if auth_header:
            expected = f"bearer {settings.mcp_auth_bearer_token}".lower()
            if (
                auth_header.lower() != expected
                and auth_header != settings.mcp_auth_bearer_token
            ):
                return JSONResponse(
                    {"error": "unauthorized", "detail": "Invalid authentication token"},
                    status_code=401,
                )

    # Only accept POST requests
    if request.method != "POST":
        return JSONResponse(
            {"error": "Method not allowed", "detail": "Only POST requests are supported"},
            status_code=405,
        )

    try:
        # Read and parse request body
        body = await request.body()
        if not body:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
                status_code=400,
            )

        request_data = json.loads(body)
        logger.info(
            f"Received MCP request: method={request_data.get('method')}, id={request_data.get('id')}"
        )

        # Process the request
        response = await mcp_server.handle_request(request_data)
        logger.info(f"Processed request, response id={response.get('id')}")

        # Return JSON-RPC response
        return JSONResponse(
            response,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-MCP-Proxy-Auth",
            },
        )

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Error handling MCP request: {e}", exc_info=True)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)},
            },
            status_code=500,
        )


async def health_check(_request):
    """Health check endpoint."""
    return JSONResponse(
        {
            "status": "healthy",
            "service": "automated-trading-system-mcp",
            "auth_configured": bool(settings.mcp_auth_bearer_token),
        }
    )


# Create Starlette app
app = Starlette(
    routes=[
        Route("/health", health_check, methods=["GET"]),
        Route("/mcp", mcp_endpoint, methods=["POST", "OPTIONS"]),
    ]
)


async def main():
    """Main entry point for running the MCP server."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except (ValueError, TypeError):
        logger.warning(
            f"Invalid PORT environment variable: '{port_str}', defaulting to 8000"
        )
        port = 8000

    # Detect Heroku deployment
    dyno = os.environ.get("DYNO")
    is_heroku = bool(dyno)
    
    if is_heroku:
        # On Heroku, get app name from various possible env vars
        heroku_app_name = (
            os.environ.get("HEROKU_APP_NAME") or
            os.environ.get("APP_NAME") or
            None
        )
        
        if heroku_app_name:
            public_url = f"https://{heroku_app_name}.herokuapp.com"
        else:
            # If we can't determine the app name, provide instructions
            public_url = "https://YOUR-APP-NAME.herokuapp.com"
        
        logger.info("=" * 70)
        logger.info("🚀 MCP Server starting on Heroku")
        logger.info(f"📦 DYNO: {dyno}")
        logger.info(f"🔌 Internal binding: {host}:{port}")
        logger.info(f"🌐 Public URL pattern: {public_url}")
        logger.info(f"📡 MCP Endpoint: {public_url}/mcp")
        logger.info(f"🏥 Health Check: {public_url}/health")
        logger.info("=" * 70)
        if "YOUR-APP-NAME" in public_url:
            logger.info("⚠️  To get your Heroku app URL, run: heroku info --app YOUR-APP-NAME")
            logger.info("   Or check: https://dashboard.heroku.com/apps/YOUR-APP-NAME/settings")
        logger.info(f"✅ Use this URL in MCP clients: {public_url}/mcp")
        logger.info(
            f"🔐 Authentication: {'ENABLED' if settings.mcp_auth_bearer_token else 'DISABLED'}"
        )
        if settings.mcp_auth_bearer_token:
            logger.info(f"🔑 Auth Header: {settings.mcp_auth_header_name}")
    else:
        logger.info(f"Starting MCP server on {host}:{port}")
        logger.info(f"MCP endpoint: http://{host}:{port}/mcp")
        logger.info(f"Health check: http://{host}:{port}/health")
        logger.info(
            f"Authentication: {'ENABLED' if settings.mcp_auth_bearer_token else 'DISABLED'}"
        )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


def main_sync():
    """Synchronous entry point."""
    import asyncio

    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
