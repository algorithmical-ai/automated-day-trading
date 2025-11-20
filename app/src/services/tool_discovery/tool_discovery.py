"""
Tool Discovery Service for automatically discovering available MCP tools
"""

import asyncio
from typing import Dict, Any, Optional, Set
from app.src.common.loguru_logger import logger
from app.src.config.constants import MARKET_DATA_MCP_URL, MCP_AUTH_HEADER_NAME, MARKET_DATA_MCP_TOKEN


class ToolDiscoveryService:
    """Service to discover and cache available MCP tools using MCP protocol"""

    _base_url: str = MARKET_DATA_MCP_URL
    _auth_header_name: str = MCP_AUTH_HEADER_NAME
    _auth_token: Optional[str] = MARKET_DATA_MCP_TOKEN
    _refresh_interval: int = 300
    _available_tools: Set[str] = set()
    _tool_metadata: Dict[str, Dict[str, Any]] = {}
    _running: bool = False
    _lock: Optional[asyncio.Lock] = None

    @classmethod
    def configure(cls, refresh_interval: int = 300):
        """Configure refresh interval without creating instances"""
        cls._refresh_interval = refresh_interval

    @classmethod
    def _ensure_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def discover_tools(cls) -> bool:
        """Discover available tools from MCP server - disabled since MCP protocol fails with 500 errors"""
        # MCP protocol is consistently failing with 500 errors from the server
        # Tool discovery is optional since HTTP fallback works fine
        # Tools can be called directly via HTTP even without discovery
        logger.debug("Tool discovery via MCP protocol disabled (server returns 500 errors). HTTP fallback will be used for tool calls.")
        return False


    @classmethod
    async def get_available_tools(cls) -> Set[str]:
        """Get the current list of available tools"""
        async with cls._ensure_lock():
            return cls._available_tools.copy()

    @classmethod
    async def is_tool_available(cls, tool_name: str) -> bool:
        """Check if a specific tool is available"""
        async with cls._ensure_lock():
            return tool_name in cls._available_tools

    @classmethod
    async def get_tool_metadata(cls, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific tool"""
        async with cls._ensure_lock():
            return cls._tool_metadata.get(tool_name)

    @classmethod
    async def get_all_tools_info(cls) -> Dict[str, Any]:
        """Get information about all discovered tools"""
        async with cls._ensure_lock():
            return {
                "available_tools": sorted(list(cls._available_tools)),
                "tool_count": len(cls._available_tools),
                "tool_metadata": cls._tool_metadata,
            }

    @classmethod
    async def discovery_job(cls):
        """Background job that periodically refreshes the tool list"""
        logger.info("Tool discovery service started (MCP protocol disabled - using HTTP fallback)")
        cls._running = True

        # Discovery disabled - MCP protocol doesn't work with this server
        # HTTP fallback in mcp_client handles tool calls directly
        logger.info("Tool discovery via MCP protocol disabled. Tools will be called directly via HTTP.")
        
        # Keep the service running but don't attempt discovery
        # This allows the service to be re-enabled later if needed
        while cls._running:
            try:
                await asyncio.sleep(cls._refresh_interval)
                # Discovery disabled - just sleep and continue
                if cls._running:
                    logger.debug("Tool discovery refresh skipped (MCP protocol disabled)")
            except Exception as e:
                logger.exception(f"Error in tool discovery job: {str(e)}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying

    @classmethod
    def stop(cls):
        """Stop the discovery service"""
        cls._running = False
        logger.info("Tool discovery service stopped")
