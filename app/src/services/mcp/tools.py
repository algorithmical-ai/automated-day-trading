"""
MCP Tool Definitions
This module contains all tool definitions for the MCP server.
Add new tools here to expose them via the MCP server.
"""

from __future__ import annotations

from typing import Any, Optional

from app.src.common.loguru_logger import logger
from app.src.services.mcp.clients import MarketDataClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.market_data.market_data_service import MarketDataService


def register_tools(
    app: Any,
    tool_registry: Any,
    market_client: Optional[MarketDataClient] = None,  # noqa: ARG001
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
            f"send_webhook_signal tool called for ticker: {ticker}, "
            f"action: {action}, indicator: {indicator}"
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

    @app.tool()
    async def enter(
        ticker: str, action: str
    ) -> dict[str, Any]:  # pylint: disable=protected-access
        """
        Analyze a ticker for entry signal (buy-to-open or sell-to-open).
        Forces computation of all required data (quotes, indicators, sentiment) if needed.

        Args:
            ticker: Stock ticker symbol (e.g., AAPL, MSFT)
            action: Trading action - either "buy_to_open" (for long)
            or "sell_to_open" (for short)

        Returns:
            Dict containing entry signal details if signal found,
            or detailed analysis if no signal.
            Includes: ticker, entry_score, portfolio_allocation,
            indicators, is_golden, golden_reason
        """
        ticker = ticker.upper().strip()
        action = action.lower().strip()

        # Validate ticker - reject placeholder/invalid values
        invalid_tickers = {"PENDING", "N/A", "NULL", "NONE", ""}
        if ticker in invalid_tickers or not ticker or len(ticker) < 1:
            raise ValueError(
                f"Invalid ticker '{ticker}'. "
                f"Please provide a valid stock ticker symbol (e.g., AAPL, MSFT, TSLA)"
            )

        # Validate action
        if action not in ["buy_to_open", "sell_to_open"]:
            raise ValueError(
                f"Invalid action '{action}'. "
                f"Must be either 'buy_to_open' or 'sell_to_open'"
            )  # noqa: C0301

        try:

            enter_trade_result = await MarketDataService.enter_trade(
                ticker=ticker, action=action
            )
            if enter_trade_result is None:
                raise ValueError(f"No enter trade result available for {ticker}")

            return enter_trade_result
        except ValueError as e:
            logger.error(
                f"Validation error analyzing {ticker} for {action}: {str(e)}",
                exc_info=True,
            )
            raise ValueError(f"Invalid analysis parameters: {str(e)}") from e
        except Exception as e:
            logger.error(
                f"Error analyzing {ticker} for {action}: {str(e)}", exc_info=True
            )
            raise ValueError(
                f"Error analyzing ticker {ticker} for {action}: {str(e)}"
            ) from e

    @app.tool()
    async def exit(
        ticker: str, enter_price: float, action: str
    ) -> dict[str, Any]:  # noqa: A001
        """
        Analyze if it's the right time to exit a trade.
        Uses the same logic as the exit monitoring service to determine exit conditions.

        Args:
            ticker: Stock ticker symbol (e.g., AAPL, MSFT)
            enter_price: Entry price of the trade
            action: Exit action - either "BUY_TO_CLOSE" (for short positions) or
            "SELL_TO_CLOSE" (for long positions)

        Returns:
            Dict containing exit decision (exit_decision: bool), reason, profit_pct,
            current_price, stop_loss_price, and other relevant trade details
        """
        ticker = ticker.upper()
        action = action.upper().strip()

        logger.debug(
            f"exit tool called for ticker: {ticker}, "
            f"enter_price: {enter_price}, action: {action}"
        )  # noqa: C0301

        # Validate action
        if action not in ["BUY_TO_CLOSE", "SELL_TO_CLOSE"]:
            raise ValueError(
                f"Invalid action '{action}'. Must be either 'BUY_TO_CLOSE' "
                f"(for short) or 'SELL_TO_CLOSE' (for long)"
            )

        # Validate enter_price
        if not isinstance(enter_price, (int, float)) or enter_price <= 0:
            raise ValueError(
                f"Invalid enter_price: {enter_price}. Must be a positive number"
            )

        try:
            exit_trade_result = await MarketDataService.exit_trade(
                ticker=ticker, enter_price=enter_price, action=action
            )
            if exit_trade_result is None:
                raise ValueError(f"No exit trade result available for {ticker}")

            return exit_trade_result
        except ValueError as e:
            logger.error(
                f"Validation error analyzing {ticker} for {action}: {str(e)}",
                exc_info=True,
            )
            raise ValueError(f"Invalid analysis parameters: {str(e)}") from e
        except Exception as e:
            logger.error(
                f"Error analyzing {ticker} for {action}: {str(e)}", exc_info=True
            )
            raise ValueError(
                f"Error analyzing ticker {ticker} for {action}: {str(e)}"
            ) from e

    logger.info("Registered MCP tools")
