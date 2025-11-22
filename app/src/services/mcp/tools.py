"""
MCP Tool Definitions
This module contains all tool definitions for the MCP server.
Add new tools here to expose them via the MCP server.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.src.common.loguru_logger import logger
from app.src.services.mcp.clients import MarketDataClient
from app.src.services.webhook.send_signal import send_signal_to_webhook


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
    async def send_webhook_signal(
            ticker: str,
            action: str,
            indicator: str,
            enter_reason: str = "",
            is_golden_exception: bool = False,
            portfolio_allocation_percent: float | None = None,
        ) -> dict[str, Any]:
        """
            Send a trading signal to configured webhook(s).
            This allows external applications to send their own signals using their own indicators.

            Args:
                ticker: Stock ticker symbol (e.g., AAPL, MSFT)
                action: Trading action - must be one of:
                    - "BUY_TO_OPEN" (open long position)
                    - "SELL_TO_OPEN" (open short position)
                    - "BUY_TO_CLOSE" (close short position)
                    - "SELL_TO_CLOSE" (close long position)
                indicator: Name/identifier of the indicator/strategy sending the signal
                enter_reason: Optional reason for entry (used for BUY_TO_OPEN/SELL_TO_OPEN)
                is_golden_exception: Optional flag indicating if this is a golden/exceptional entry
                portfolio_allocation_percent: Optional portfolio allocation percentage (0.0 to 1.0)

            Returns:
                Dict containing success status and message

            Raises:
                ValueError: If ticker, action, or indicator is invalid
            """
        ticker = ticker.upper()
        action = action.upper().strip()
        indicator = indicator.strip()

        logger.debug(
                f"send_webhook_signal tool called for ticker: {ticker}, " f"action: {action}, indicator: {indicator}"
            )

        try:
            # Call the webhook signal sender
            await send_signal_to_webhook(
                    ticker=ticker,
                    action=action,
                    indicator=indicator,
                    enter_reason=enter_reason,
                    is_golden_exception=is_golden_exception,
                    portfolio_allocation_percent=portfolio_allocation_percent,
                )

            return {
                    "success": True,
                    "ticker": ticker,
                    "action": action,
                    "indicator": indicator,
                    "message": f"Signal sent successfully for {ticker} {action}",
                }

        except ValueError as e:
            logger.error(f"Validation error sending signal: {str(e)}", exc_info=True)
            raise ValueError(f"Invalid signal parameters: {str(e)}") from e
        except Exception as e:
            logger.error(
                    f"Error sending webhook signal for {ticker} {action}: {str(e)}",
                    exc_info=True,
                )
            raise ValueError(f"Error sending webhook signal: {str(e)}") from e

    logger.info("Registered MCP tools")
