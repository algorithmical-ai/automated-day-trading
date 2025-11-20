"""
Tool Discovery Service for automatically discovering available MCP tools
"""

import asyncio
from typing import Dict, Any, Optional, Set
from common.loguru_logger import logger
from config.constants import MARKET_DATA_MCP_URL, MCP_AUTH_HEADER_NAME, MARKET_DATA_MCP_TOKEN
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Implementation


class ToolDiscoveryService:
    """Service to discover and cache available MCP tools using MCP protocol"""

    def __init__(self, refresh_interval: int = 300):  # Refresh every 5 minutes
        self.base_url = MARKET_DATA_MCP_URL
        self.auth_header_name = MCP_AUTH_HEADER_NAME
        self.auth_token = MARKET_DATA_MCP_TOKEN
        self.refresh_interval = refresh_interval
        self.available_tools: Set[str] = set()
        self.tool_metadata: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self._lock = asyncio.Lock()

    async def discover_tools(self) -> bool:
        """Discover available tools from MCP server - disabled since MCP protocol fails with 500 errors"""
        # MCP protocol is consistently failing with 500 errors from the server
        # Tool discovery is optional since HTTP fallback works fine
        # Tools can be called directly via HTTP even without discovery
        logger.debug("Tool discovery via MCP protocol disabled (server returns 500 errors). HTTP fallback will be used for tool calls.")
        return False
        
        # Below code is commented out - MCP protocol discovery doesn't work with this server
        # Uncomment if server MCP protocol support is fixed
        """
        try:
            # Prepare headers for authentication
            headers = {}
            if self.auth_token:
                headers[self.auth_header_name] = self.auth_token

            # Use streamablehttp_client to get streams
            async with streamablehttp_client(
                url=self.base_url, headers=headers if headers else None, timeout=30.0
            ) as (read_stream, write_stream, _):

                # Create client info for the session
                client_info = Implementation(
                    name="automated-day-trading",
                    version="1.0.0"
                )
                
                # Create client session with the streams and client info
                async with ClientSession(
                    read_stream, 
                    write_stream,
                    client_info=client_info
                ) as session:
                    # Initialize the session
                    await session.initialize()

                    # Use MCP protocol to list tools
                    result = await session.list_tools()

                    discovered_tools = set()
                    tool_metadata = {}

                    # Extract tools from the result
                    if hasattr(result, "tools") and result.tools:
                        for tool in result.tools:
                            tool_name = (
                                tool.name if hasattr(tool, "name") else str(tool)
                            )
                            discovered_tools.add(tool_name)

                            # Store tool metadata
                            tool_info = {
                                "name": tool_name,
                            }

                            # Extract description if available
                            if hasattr(tool, "description"):
                                tool_info["description"] = tool.description

                            # Extract input schema if available
                            if hasattr(tool, "inputSchema"):
                                tool_info["inputSchema"] = tool.inputSchema

                            tool_metadata[tool_name] = tool_info

                    # Update cached tools
                    async with self._lock:
                        old_count = len(self.available_tools)
                        self.available_tools = discovered_tools
                        self.tool_metadata = tool_metadata

                        if discovered_tools:
                            logger.info(
                                f"Tool discovery complete: {len(discovered_tools)} tools available (was {old_count})"
                            )
                            logger.debug(
                                f"Available tools: {sorted(self.available_tools)}"
                            )
                            return True
                        else:
                            logger.warning("MCP server returned no tools")
                            return False

        except (Exception, BaseException) as e:
            # If MCP protocol fails, log but don't fail completely
            # The HTTP fallback in mcp_client will still work
            error_str = str(e)
            if "500" in error_str or "Internal Server Error" in error_str or "BrokenResourceError" in error_str:
                logger.warning(f"MCP protocol discovery failed, will use HTTP fallback: {error_str[:150]}")
            else:
                logger.exception(f"Error discovering tools via MCP protocol: {str(e)}")
            return False
        """

    async def get_available_tools(self) -> Set[str]:
        """Get the current list of available tools"""
        async with self._lock:
            return self.available_tools.copy()

    async def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available"""
        async with self._lock:
            return tool_name in self.available_tools

    async def get_tool_metadata(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific tool"""
        async with self._lock:
            return self.tool_metadata.get(tool_name)

    async def get_all_tools_info(self) -> Dict[str, Any]:
        """Get information about all discovered tools"""
        async with self._lock:
            return {
                "available_tools": sorted(list(self.available_tools)),
                "tool_count": len(self.available_tools),
                "tool_metadata": self.tool_metadata,
            }

    async def discovery_job(self):
        """Background job that periodically refreshes the tool list"""
        logger.info("Tool discovery service started (MCP protocol disabled - using HTTP fallback)")
        self.running = True

        # Discovery disabled - MCP protocol doesn't work with this server
        # HTTP fallback in mcp_client handles tool calls directly
        logger.info("Tool discovery via MCP protocol disabled. Tools will be called directly via HTTP.")
        
        # Keep the service running but don't attempt discovery
        # This allows the service to be re-enabled later if needed
        while self.running:
            try:
                await asyncio.sleep(self.refresh_interval)
                # Discovery disabled - just sleep and continue
                if self.running:
                    logger.debug("Tool discovery refresh skipped (MCP protocol disabled)")
            except Exception as e:
                logger.exception(f"Error in tool discovery job: {str(e)}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying

    def stop(self):
        """Stop the discovery service"""
        self.running = False
        logger.info("Tool discovery service stopped")
