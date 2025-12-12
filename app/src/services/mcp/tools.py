"""
MCP Tool Definitions
This module contains all tool definitions for the MCP server.
Add new tools here to expose them via the MCP server.
"""

from __future__ import annotations

from typing import Any, Dict

from app.src.common.loguru_logger import logger
from app.src.services.bandit.bandit_decision_service import BanditDecisionService


# Tool handler functions

async def can_proceed(
    ticker: str,
    indicator: str,
    current_price: str,
    action: str,
    confidence_score: str,
) -> dict[str, Any]:
    """
    Determine if a trade should proceed based on intraday performance using a Bandit Algorithm.
    
    Uses Thompson Sampling to balance exploration (trying new tickers) with exploitation
    (favoring historically successful tickers). Penalizes tickers that perform poorly
    during the current day and rewards tickers that perform well.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")
        indicator: Trading indicator/strategy name (e.g., "momentum", "penny_stocks")
        current_price: Current price as string (e.g., "150.25")
        action: Trade action - one of:
            - "buy_to_open" (enter long position)
            - "sell_to_open" (enter short position)
            - "sell_to_close" (exit long position - always returns True)
            - "buy_to_close" (exit short position - always returns True)
        confidence_score: Signal confidence between "0" and "1"

    Returns:
        Dict containing:
            - decision: bool - True if trade should proceed, False otherwise
            - ticker: str - The ticker symbol
            - indicator: str - The indicator name
            - action: str - The action requested
            - reason: str - Explanation of the decision
            - confidence_score: float - The parsed confidence score
            - current_price: float - The parsed current price
            - timestamp: str - Decision timestamp in EST
            - intraday_stats: dict - Current day's success/failure counts

    Raises:
        ValueError: If any parameter is invalid
    """
    logger.debug(
        f"can_proceed tool called: ticker={ticker}, indicator={indicator}, "
        f"action={action}, price={current_price}, confidence={confidence_score}"
    )

    try:
        # Parse string parameters to appropriate types
        try:
            price_float = float(current_price)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid current_price '{current_price}'. Must be a valid number."
            ) from e

        try:
            confidence_float = float(confidence_score)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid confidence_score '{confidence_score}'. Must be a number between 0 and 1."
            ) from e

        # Call the BanditDecisionService
        result = await BanditDecisionService.can_proceed(
            ticker=ticker,
            indicator=indicator,
            current_price=price_float,
            action=action,
            confidence_score=confidence_float,
        )

        return result.to_response_dict()

    except ValueError as e:
        logger.error(f"Validation error in can_proceed: {str(e)}", exc_info=True)
        raise ValueError(f"Invalid parameters: {str(e)}") from e
    except Exception as e:
        logger.error(f"Error in can_proceed: {str(e)}", exc_info=True)
        raise ValueError(f"Error processing can_proceed request: {str(e)}") from e


def get_tool_registry() -> Dict[str, Dict[str, Any]]:
    """
    Get the tool registry with all available tools.

    Returns:
        Dictionary mapping tool names to tool definitions
    """
    return {
        "can_proceed": {
            "handler": can_proceed,
            "description": "Determine if a trade should proceed based on intraday performance using a Bandit Algorithm (Thompson Sampling). Penalizes poorly performing tickers and rewards well-performing ones. Exit actions (sell_to_close, buy_to_close) always return True.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, TSLA)",
                    },
                    "indicator": {
                        "type": "string",
                        "description": "Trading indicator/strategy name (e.g., momentum, penny_stocks)",
                    },
                    "current_price": {
                        "type": "string",
                        "description": "Current price as string (e.g., '150.25')",
                    },
                    "action": {
                        "type": "string",
                        "description": "Trade action - buy_to_open, sell_to_open, sell_to_close, or buy_to_close",
                        "enum": ["buy_to_open", "sell_to_open", "sell_to_close", "buy_to_close"],
                    },
                    "confidence_score": {
                        "type": "string",
                        "description": "Signal confidence between '0' and '1' (e.g., '0.85')",
                    },
                },
                "required": ["ticker", "indicator", "current_price", "action", "confidence_score"],
            },
        },
    }
