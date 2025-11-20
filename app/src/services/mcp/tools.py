"""
MCP Tool Definitions
This module contains all tool definitions for the MCP server.
Add new tools here to expose them via the MCP server.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.src.common.loguru_logger import logger
from app.src.services.mcp.clients import MarketDataClient


async def list_discovered_tools(tool_registry: Any) -> Dict[str, Any]:
    """
    List all discovered tools from upstream MCP servers.
    
    Args:
        tool_registry: The tool registry instance to query
        
    Returns:
        Dictionary containing tools grouped by source
    """
    snapshot = await tool_registry.snapshot()
    if not snapshot:
        # If no tools discovered yet, return empty result
        return {"sources": {}}
    return {"sources": snapshot}


def register_tools(
    app: Any, 
    tool_registry: Any, 
    market_client: Optional[MarketDataClient] = None
) -> None:
    """
    Register all tools with the MCP server.
    
    This function should be called after creating the FastMCP app instance
    to register all available tools.
    
    Args:
        app: FastMCP app instance
        tool_registry: Tool registry instance
        market_client: Optional market data client for tool implementations
    """

    @app.tool()
    async def list_tools() -> Dict[str, Any]:
        """
        List all discovered tools from upstream MCP servers.
        
        This tool allows clients to discover what tools are available
        from connected MCP servers.
        
        Returns:
            Dictionary with 'sources' key containing tools grouped by source name
        """
        return await list_discovered_tools(tool_registry)

    # Add more tools here as needed
    # Example:
    # @app.tool()
    # async def my_custom_tool(param1: str, param2: int) -> Dict[str, Any]:
    #     """Description of what the tool does."""
    #     # Implementation here
    #     return {"result": "value"}

    @app.tool()
    async def get_market_clock() -> Dict[str, Any]:
        """Get the current market clock."""
        # Implementation here
        return await market_client.get_market_clock()

    logger.info("Registered MCP tools")
