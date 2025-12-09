"""
MCP Tool Definitions
This module contains all tool definitions for the MCP server.
Add new tools here to expose them via the MCP server.
"""

from __future__ import annotations

from typing import Any, Dict

from app.src.common.loguru_logger import logger
from app.src.common.alpaca import AlpacaClient
from app.src.services.candidate_generator.alpaca_screener import AlpacaScreenerService
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.market_data.market_data_service import MarketDataService
from app.src.services.technical_analysis.technical_analysis_lib import (
    TechnicalAnalysisLib,
)


# Tool handler functions

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


async def enter(ticker: str, action: str) -> dict[str, Any]:
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

    invalid_tickers = {"PENDING", "N/A", "NULL", "NONE", ""}
    if ticker in invalid_tickers or not ticker or len(ticker) < 1:
        raise ValueError(
            f"Invalid ticker '{ticker}'. "
            f"Please provide a valid stock ticker symbol (e.g., AAPL, MSFT, TSLA)"
        )

    if action not in ["buy_to_open", "sell_to_open"]:
        raise ValueError(
            f"Invalid action '{action}'. "
            f"Must be either 'buy_to_open' or 'sell_to_open'"
        )

    try:
        enter_trade_result = await MarketDataService.enter_trade(
            ticker=ticker, action=action
        )
        if enter_trade_result is None:
            raise ValueError(f"No enter trade result available for {ticker}")

        # Remove datetime_price from indicators in the response (used internally only)
        if "analysis" in enter_trade_result and "indicators" in enter_trade_result["analysis"]:
            indicators = enter_trade_result["analysis"]["indicators"]
            if isinstance(indicators, dict) and "datetime_price" in indicators:
                indicators.pop("datetime_price")

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


async def exit(ticker: str, enter_price: float, action: str) -> dict[str, Any]:
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
    )

    if action not in ["BUY_TO_CLOSE", "SELL_TO_CLOSE"]:
        raise ValueError(
            f"Invalid action '{action}'. Must be either 'BUY_TO_CLOSE' "
            f"(for short) or 'SELL_TO_CLOSE' (for long)"
        )

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

        # Remove datetime_price from indicators in the response (used internally only)
        if "indicators" in exit_trade_result:
            indicators = exit_trade_result["indicators"]
            if isinstance(indicators, dict) and "datetime_price" in indicators:
                indicators.pop("datetime_price")

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


async def get_alpaca_screened_tickers() -> dict[str, Any]:
    """
    Get all screened tickers from Alpaca (most actives, gainers, losers).
    This provides the current market movers that could be used for placing trades.

    Returns:
        Dict containing:
            - most_actives: List of most active ticker symbols
            - gainers: List of top gaining ticker symbols
            - losers: List of top losing ticker symbols
            - all: Combined list of all screened tickers (unique)
    """
    logger.debug("get_alpaca_screened_tickers tool called")

    try:
        screened_data = await AlpacaScreenerService().get_all_screened_tickers()

        return {
            "most_actives": sorted(list(screened_data.get("most_actives", set()))),
            "gainers": sorted(list(screened_data.get("gainers", set()))),
            "losers": sorted(list(screened_data.get("losers", set()))),
            "all": sorted(list(screened_data.get("all", set()))),
            "count": {
                "most_actives": len(screened_data.get("most_actives", set())),
                "gainers": len(screened_data.get("gainers", set())),
                "losers": len(screened_data.get("losers", set())),
                "all": len(screened_data.get("all", set())),
            },
        }
    except Exception as e:
        logger.error(f"Error getting screened tickers: {str(e)}", exc_info=True)
        raise ValueError(f"Error fetching screened tickers: {str(e)}") from e


async def get_quote(ticker: str) -> dict[str, Any]:
    """
    Get latest quote for a ticker from Alpaca API.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")

    Returns:
        Dict containing flattened quote data with timestamp converted to EST
    """
    from datetime import datetime
    import pytz
    
    ticker = ticker.upper().strip()

    invalid_tickers = {"PENDING", "N/A", "NULL", "NONE", ""}
    if ticker in invalid_tickers or not ticker or len(ticker) < 1:
        raise ValueError(
            f"Invalid ticker '{ticker}'. "
            f"Please provide a valid stock ticker symbol (e.g., AAPL, MSFT, TSLA)"
        )

    logger.debug(f"get_quote tool called for ticker: {ticker}")

    try:
        quote_response = await AlpacaClient.quote(ticker)

        if quote_response is None:
            return {
                "success": False,
                "ticker": ticker,
                "quote": None,
                "message": f"No quote data available for {ticker}",
            }

        # Flatten the nested structure: extract quote data from nested dict
        # Original: {"quote": {"quotes": {ticker: {...}}}}
        # Target: {"success": true, "ticker": ticker, "quote": {...}}
        nested_quotes = quote_response.get("quote", {}).get("quotes", {})
        quote_data = nested_quotes.get(ticker, {})
        
        # Convert timestamp from GMT to EST if present
        if "t" in quote_data and quote_data["t"]:
            try:
                # Parse the ISO 8601 timestamp (GMT/UTC)
                gmt_time = datetime.fromisoformat(quote_data["t"].replace("Z", "+00:00"))
                # Convert to EST (US/Eastern timezone)
                est_tz = pytz.timezone("US/Eastern")
                est_time = gmt_time.astimezone(est_tz)
                # Format back to ISO 8601 string with timezone
                quote_data["t"] = est_time.isoformat()
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to convert timestamp to EST for {ticker}: {e}")
                # Keep original timestamp if conversion fails

        return {
            "success": True,
            "ticker": ticker,
            "quote": quote_data,
        }
    except Exception as e:
        logger.error(f"Error getting quote for {ticker}: {str(e)}", exc_info=True)
        raise ValueError(f"Error fetching quote for {ticker}: {str(e)}") from e


async def get_market_data(ticker: str, limit: int = 200) -> dict[str, Any]:
    """
    Get historical bars for a ticker from Alpaca API.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")
        limit: Number of bars to retrieve (default: 200, max: 1000)

    Returns:
        Dict containing bars data
    """
    ticker = ticker.upper().strip()

    invalid_tickers = {"PENDING", "N/A", "NULL", "NONE", ""}
    if ticker in invalid_tickers or not ticker or len(ticker) < 1:
        raise ValueError(
            f"Invalid ticker '{ticker}'. "
            f"Please provide a valid stock ticker symbol (e.g., AAPL, MSFT, TSLA)"
        )

    if not isinstance(limit, int) or limit <= 0 or limit > 1000:
        raise ValueError(
            f"Invalid limit: {limit}. Must be a positive integer between 1 and 1000"
        )

    logger.debug(
        f"get_market_data tool called for ticker: {ticker}, limit: {limit}"
    )

    try:
        bars_data = await AlpacaClient.get_market_data(ticker, limit=limit)

        if bars_data is None:
            return {
                "success": False,
                "ticker": ticker,
                "bars": None,
                "message": f"No market data available for {ticker}",
            }

        # bars_data contains {"bars": {...}, "bars_est": {...}}
        # Extract the EST-converted bars array for the ticker
        bars_est_dict = bars_data.get("bars_est", {})
        ticker_bars_est = bars_est_dict.get(ticker, [])

        return {
            "success": True,
            "ticker": ticker,
            "bars": ticker_bars_est,
        }
    except Exception as e:
        logger.error(
            f"Error getting market data for {ticker}: {str(e)}", exc_info=True
        )
        raise ValueError(
            f"Error fetching market data for {ticker}: {str(e)}"
        ) from e


async def calculate_technical_indicators(ticker: str) -> dict[str, Any]:
    """
    Calculate all technical indicators for a ticker using TA-Lib.
    Fetches market data from Alpaca API and computes comprehensive technical analysis.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")

    Returns:
        Dict containing all technical indicators
    """
    ticker = ticker.upper().strip()

    invalid_tickers = {"PENDING", "N/A", "NULL", "NONE", ""}
    if ticker in invalid_tickers or not ticker or len(ticker) < 1:
        raise ValueError(
            f"Invalid ticker '{ticker}'. "
            f"Please provide a valid stock ticker symbol (e.g., AAPL, MSFT, TSLA)"
        )

    logger.debug(f"calculate_technical_indicators tool called for ticker: {ticker}")

    try:
        indicators = await TechnicalAnalysisLib.calculate_all_indicators(ticker)

        return {
            "success": True,
            "ticker": ticker,
            "indicators": indicators,
        }
    except Exception as e:
        logger.error(
            f"Error calculating technical indicators for {ticker}: {str(e)}",
            exc_info=True,
        )
        raise ValueError(
            f"Error calculating technical indicators for {ticker}: {str(e)}"
        ) from e


async def is_market_open() -> dict[str, Any]:
    """
    Check if the market is currently open.

    Returns:
        Dict containing:
        {
            "is_open": bool,
            "message": str
        }
    """
    logger.debug("is_market_open tool called")

    try:
        is_open = await AlpacaClient.is_market_open()

        return {
            "success": True,
            "is_open": is_open,
            "message": "Market is open" if is_open else "Market is closed",
        }
    except Exception as e:
        logger.error(f"Error checking market status: {str(e)}", exc_info=True)
        raise ValueError(f"Error checking market status: {str(e)}") from e


async def get_market_clock() -> dict[str, Any]:
    """
    Get market clock status including open/close times.

    Returns:
        Dict containing market clock data
    """
    logger.debug("get_market_clock tool called")

    try:
        clock = await AlpacaClient.clock()

        if not clock:
            return {
                "success": False,
                "clock": None,
                "message": "No market clock data available",
            }

        return {
            "success": True,
            "clock": clock,
        }
    except Exception as e:
        logger.error(f"Error getting market clock: {str(e)}", exc_info=True)
        raise ValueError(f"Error getting market clock: {str(e)}") from e


def get_tool_registry() -> Dict[str, Dict[str, Any]]:
    """
    Get the tool registry with all available tools.

    Returns:
        Dictionary mapping tool names to tool definitions
    """
    return {
        "send_webhook_signal": {
            "handler": send_webhook_signal,
            "description": "Send a trading signal to configured webhook(s). This allows external applications to send their own signals using their own indicators.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT)",
                    },
                    "action": {
                        "type": "string",
                        "description": "Trading action - must be one of: BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, SELL_TO_CLOSE",
                    },
                    "indicator": {
                        "type": "string",
                        "description": "Name/identifier of the indicator/strategy sending the signal",
                    },
                    "enter_reason": {
                        "type": "string",
                        "description": "Optional reason for entry",
                        "default": "",
                    },
                    "is_golden_exception": {
                        "type": "boolean",
                        "description": "Optional flag indicating if this is a golden/exceptional entry",
                        "default": False,
                    },
                    "portfolio_allocation_percent": {
                        "type": "number",
                        "description": "Optional portfolio allocation percentage (0.0 to 1.0)",
                        "default": None,
                    },
                },
                "required": ["ticker", "action", "indicator"],
            },
        },
        "enter": {
            "handler": enter,
            "description": "Analyze a ticker for entry signal (buy-to-open or sell-to-open). Forces computation of all required data (quotes, indicators, sentiment) if needed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT)",
                    },
                    "action": {
                        "type": "string",
                        "description": "Trading action - either 'buy_to_open' (for long) or 'sell_to_open' (for short)",
                        "enum": ["buy_to_open", "sell_to_open"],
                    },
                },
                "required": ["ticker", "action"],
            },
        },
        "exit": {
            "handler": exit,
            "description": "Analyze if it's the right time to exit a trade. Uses the same logic as the exit monitoring service to determine exit conditions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT)",
                    },
                    "enter_price": {
                        "type": "number",
                        "description": "Entry price of the trade",
                    },
                    "action": {
                        "type": "string",
                        "description": "Exit action - either 'BUY_TO_CLOSE' (for short positions) or 'SELL_TO_CLOSE' (for long positions)",
                        "enum": ["BUY_TO_CLOSE", "SELL_TO_CLOSE"],
                    },
                },
                "required": ["ticker", "enter_price", "action"],
            },
        },
        "get_alpaca_screened_tickers": {
            "handler": get_alpaca_screened_tickers,
            "description": "Get all screened tickers from Alpaca (most actives, gainers, losers). This provides the current market movers that could be used for placing trades.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        "get_quote": {
            "handler": get_quote,
            "description": "Get latest quote for a ticker from Alpaca API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, TSLA)",
                    },
                },
                "required": ["ticker"],
            },
        },
        "get_market_data": {
            "handler": get_market_data,
            "description": "Get historical bars for a ticker from Alpaca API. Fetches latest bars in descending order, then sorts in ascending order.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, TSLA)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of bars to retrieve (default: 200, max: 1000)",
                        "default": 200,
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
                "required": ["ticker"],
            },
        },
        "calculate_technical_indicators": {
            "handler": calculate_technical_indicators,
            "description": "Calculate all technical indicators for a ticker using TA-Lib. Fetches market data from Alpaca API and computes comprehensive technical analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, TSLA)",
                    },
                },
                "required": ["ticker"],
            },
        },
        "is_market_open": {
            "handler": is_market_open,
            "description": "Check if the market is currently open.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        "get_market_clock": {
            "handler": get_market_clock,
            "description": "Get market clock status including open/close times.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
