"""
Real-Time Quote Utilities for Trading Indicators

Provides real-time Alpaca quotes for fast-moving penny stocks to capture opportunities
that would be missed with the 2-minute latency of MCPClient.get_market_data()
"""

import os
import asyncio
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone
import pytz
import aiohttp

from app.src.common.loguru_logger import logger
from app.src.services.mcp.mcp_client import MCPClient


class RealtimeQuoteUtils:
    """Utility class for fetching real-time quotes for penny stocks"""

    # Threshold for penny stock treatment (stocks below this price get real-time quotes)
    PENNY_STOCK_PRICE_THRESHOLD = 5.0

    # Alpaca API configuration
    _alpaca_api_key = os.environ.get("REAL_TRADE_API_KEY", "")
    _alpaca_api_secret = os.environ.get("REAL_TRADE_SECRET_KEY", "")
    _alpaca_quotes_url = "https://data.alpaca.markets/v2/stocks/quotes"

    # Shared session for API calls (class-level to reuse connections)
    _alpaca_session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def get_realtime_alpaca_quote(cls, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote from Alpaca API for fast-moving penny stocks.
        This bypasses the 2-minute latency of MCPClient.get_market_data().

        Returns:
            Dict with bid/ask prices or None if unavailable
        """
        if not cls._alpaca_api_key or not cls._alpaca_api_secret:
            return None

        try:
            # Use shared session for efficiency
            if cls._alpaca_session is None or cls._alpaca_session.closed:
                cls._alpaca_session = aiohttp.ClientSession()

            url = cls._alpaca_quotes_url
            params = {
                "symbols": ticker,
                "limit": 1,
                "feed": "sip",
                "sort": "desc",
            }
            headers = {
                "accept": "application/json",
                "APCA-API-KEY-ID": cls._alpaca_api_key,
                "APCA-API-SECRET-KEY": cls._alpaca_api_secret,
            }

            async with cls._alpaca_session.get(
                url,
                params={k: str(v) for k, v in params.items()},
                headers=headers,
                timeout=aiohttp.ClientTimeout(
                    total=5
                ),  # Fast timeout for real-time quotes
            ) as response:
                if response.status != 200:
                    logger.debug(
                        f"Alpaca quotes API returned status {response.status} for {ticker}"
                    )
                    return None

                data = await response.json()
                quotes_dict = data.get("quotes", {})
                ticker_quotes = quotes_dict.get(ticker, [])

                if not ticker_quotes or len(ticker_quotes) == 0:
                    return None

                # Get the most recent quote (first in desc order)
                latest_quote = ticker_quotes[0]

                # Convert UTC timestamp to EST
                utc_timestamp_str = latest_quote.get("t")
                utc_timestamp = None
                est_timestamp = None

                if utc_timestamp_str:
                    try:
                        # Parse UTC timestamp (format: "2025-12-01T20:04:38.011885147Z")
                        # Replace 'Z' with '+00:00' for ISO format parsing
                        utc_timestamp_str_clean = utc_timestamp_str.replace(
                            "Z", "+00:00"
                        )
                        utc_timestamp = datetime.fromisoformat(utc_timestamp_str_clean)

                        # Ensure we have UTC timezone (fromisoformat should handle this)
                        if utc_timestamp.tzinfo is None:
                            utc_timestamp = utc_timestamp.replace(tzinfo=timezone.utc)

                        # Convert UTC to EST (America/New_York timezone, automatically handles DST)
                        est_tz = pytz.timezone("America/New_York")
                        est_timestamp = utc_timestamp.astimezone(est_tz)
                    except (ValueError, AttributeError) as e:
                        logger.debug(
                            f"Error converting timestamp to EST for {ticker}: {e}"
                        )

                return {
                    "bp": latest_quote.get("bp"),  # Bid price
                    "ap": latest_quote.get("ap"),  # Ask price
                    "bs": latest_quote.get("bs"),  # Bid size
                    "as": latest_quote.get("as"),  # Ask size
                    "t": latest_quote.get("t"),  # Original UTC timestamp (ISO format)
                    "t_utc": utc_timestamp,  # Parsed UTC datetime object
                    "t_est": est_timestamp,  # EST datetime object
                    "t_est_str": (
                        est_timestamp.strftime("%Y-%m-%d %H:%M:%S.%f %Z%z")
                        .replace("+0000", "")
                        .strip()
                        if est_timestamp
                        else None
                    ),  # EST as formatted string (e.g., "2025-12-01 15:04:38.011885 EST")
                }

        except asyncio.TimeoutError:
            logger.debug(f"Timeout fetching real-time Alpaca quote for {ticker}")
            return None
        except Exception as e:
            logger.debug(f"Error fetching real-time Alpaca quote for {ticker}: {e}")
            return None

    @classmethod
    async def get_entry_price_quote(
        cls,
        ticker: str,
        action: str,
        current_price_hint: Optional[float] = None,
        penny_stock_threshold: float = PENNY_STOCK_PRICE_THRESHOLD,
    ) -> Tuple[Optional[float], str]:
        """
        Get entry price quote using real-time Alpaca API for penny stocks,
        falling back to MCPClient for others or if real-time fails.

        For penny stocks (< threshold), this uses real-time quotes to capture
        fast-moving opportunities.

        Args:
            ticker: Stock ticker symbol
            action: "buy_to_open" (use ask) or "sell_to_open" (use bid)
            current_price_hint: Optional current price hint to determine if penny stock
            penny_stock_threshold: Price threshold for penny stock treatment (default: 5.0)

        Returns:
            Tuple of (enter_price: Optional[float], quote_source: str)
        """
        is_long = action == "buy_to_open"
        is_penny_stock = False

        # Determine if this is a penny stock
        if current_price_hint and current_price_hint < penny_stock_threshold:
            is_penny_stock = True

        # Try real-time Alpaca quotes first for penny stocks (fast-moving opportunities)
        if is_penny_stock:
            realtime_quote = await cls.get_realtime_alpaca_quote(ticker)
            if realtime_quote:
                bp = realtime_quote.get("bp")
                ap = realtime_quote.get("ap")

                if is_long:
                    enter_price = ap if ap and ap > 0 else None
                else:
                    enter_price = bp if bp and bp > 0 else None

                if enter_price:
                    est_time_str = realtime_quote.get("t_est_str", "")
                    time_info = f" @ {est_time_str}" if est_time_str else ""
                    logger.info(
                        f"✅ Real-time quote for {ticker}: ${enter_price:.4f} "
                        f"({'ASK' if is_long else 'BID'}){time_info} - fast entry for penny stock"
                    )
                    return enter_price, "realtime_alpaca"

        # Fallback to MCPClient.get_quote() (may have latency but more reliable)
        quote_response = await MCPClient.get_quote(ticker)
        if quote_response:
            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})

            if is_long:
                enter_price = ticker_quote.get("ap", 0.0)
            else:
                enter_price = ticker_quote.get("bp", 0.0)

            if enter_price > 0:
                quote_source = "mcp_client" + (" (fallback)" if is_penny_stock else "")
                return enter_price, quote_source

        return None, "none"

    @classmethod
    async def get_exit_price_quote(
        cls,
        ticker: str,
        original_action: str,
        enter_price: float,
        penny_stock_threshold: float = PENNY_STOCK_PRICE_THRESHOLD,
    ) -> Tuple[Optional[float], str]:
        """
        Get exit price quote using real-time Alpaca API for penny stocks,
        falling back to MCPClient for others or if real-time fails.

        For penny stocks (< threshold), this uses real-time quotes for fast exits
        to capture rapid price movements.

        Args:
            ticker: Stock ticker symbol
            original_action: "buy_to_open" (long - use bid) or "sell_to_open" (short - use ask)
            enter_price: Entry price to determine if penny stock
            penny_stock_threshold: Price threshold for penny stock treatment (default: 5.0)

        Returns:
            Tuple of (exit_price: Optional[float], quote_source: str)
        """
        is_long = original_action == "buy_to_open"
        is_penny_stock = enter_price < penny_stock_threshold

        # Try real-time Alpaca quotes first for penny stocks (fast exits)
        if is_penny_stock:
            realtime_quote = await cls.get_realtime_alpaca_quote(ticker)
            if realtime_quote:
                bp = realtime_quote.get("bp")
                ap = realtime_quote.get("ap")

                if is_long:
                    # Long exit: use bid price (selling)
                    exit_price = bp if bp and bp > 0 else None
                else:
                    # Short exit: use ask price (buying to cover)
                    exit_price = ap if ap and ap > 0 else None

                if exit_price:
                    est_time_str = realtime_quote.get("t_est_str", "")
                    time_info = f" @ {est_time_str}" if est_time_str else ""
                    logger.info(
                        f"✅ Real-time exit quote for {ticker}: ${exit_price:.4f} "
                        f"({'BID' if is_long else 'ASK'}){time_info} - fast exit for penny stock"
                    )
                    return exit_price, "realtime_alpaca"

        # Fallback to MCPClient.get_quote() (may have latency but more reliable)
        quote_response = await MCPClient.get_quote(ticker)
        if quote_response:
            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})

            if is_long:
                exit_price = ticker_quote.get("bp", 0.0)  # Bid price for long exit
            else:
                exit_price = ticker_quote.get("ap", 0.0)  # Ask price for short exit

            if exit_price > 0:
                quote_source = "mcp_client" + (" (fallback)" if is_penny_stock else "")
                return exit_price, quote_source

        return None, "none"

    @classmethod
    async def get_realtime_quotes_for_momentum(
        cls, ticker: str, limit: int = 200
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get real-time quotes from Alpaca API for momentum calculations.
        Fetches multiple quotes (default 200) and converts them to datetime_price format
        with EST timestamps.

        Args:
            ticker: Stock ticker symbol
            limit: Number of quotes to fetch (default: 200)

        Returns:
            List of price data in datetime_price format:
            [{"timestamp": datetime, "price": float, "t_est_str": str}, ...]
            or None if unavailable
        """
        if not cls._alpaca_api_key or not cls._alpaca_api_secret:
            return None

        try:
            # Use shared session for efficiency
            if cls._alpaca_session is None or cls._alpaca_session.closed:
                cls._alpaca_session = aiohttp.ClientSession()

            url = cls._alpaca_quotes_url
            params = {
                "symbols": ticker,
                "limit": limit,
                "feed": "sip",
                "sort": "desc",  # Most recent first
            }
            headers = {
                "accept": "application/json",
                "APCA-API-KEY-ID": cls._alpaca_api_key,
                "APCA-API-SECRET-KEY": cls._alpaca_api_secret,
            }

            async with cls._alpaca_session.get(
                url,
                params={k: str(v) for k, v in params.items()},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    logger.debug(
                        f"Alpaca quotes API returned status {response.status} for {ticker}"
                    )
                    return None

                data = await response.json()
                quotes_dict = data.get("quotes", {})
                ticker_quotes = quotes_dict.get(ticker, [])

                if not ticker_quotes or len(ticker_quotes) == 0:
                    return None

                # Convert quotes to datetime_price format with EST timestamps
                est_tz = pytz.timezone("America/New_York")
                price_data = []

                # Process quotes from oldest to newest (reverse order for chronological)
                for quote in reversed(ticker_quotes):
                    try:
                        bp = quote.get("bp")  # Bid price
                        ap = quote.get("ap")  # Ask price

                        # Use mid price (average of bid and ask) for momentum calculation
                        if bp is not None and ap is not None:
                            mid_price = (bp + ap) / 2.0
                        elif ap is not None:
                            mid_price = ap
                        elif bp is not None:
                            mid_price = bp
                        else:
                            continue  # Skip quotes without valid prices

                        if mid_price <= 0:
                            continue

                        # Parse and convert UTC timestamp to EST
                        utc_timestamp_str = quote.get("t")
                        if not utc_timestamp_str:
                            continue

                        try:
                            # Parse UTC timestamp
                            utc_timestamp_str_clean = utc_timestamp_str.replace(
                                "Z", "+00:00"
                            )
                            utc_timestamp = datetime.fromisoformat(
                                utc_timestamp_str_clean
                            )

                            # Ensure UTC timezone
                            if utc_timestamp.tzinfo is None:
                                utc_timestamp = utc_timestamp.replace(
                                    tzinfo=timezone.utc
                                )

                            # Convert to EST
                            est_timestamp = utc_timestamp.astimezone(est_tz)
                            est_timestamp_str = est_timestamp.strftime(
                                "%Y-%m-%d %H:%M:%S.%f"
                            )

                            # Add to price data
                            price_data.append(
                                {
                                    "timestamp": est_timestamp,  # EST datetime object
                                    "price": mid_price,
                                    "t_est_str": est_timestamp_str,
                                    "bp": bp,
                                    "ap": ap,
                                }
                            )
                        except (ValueError, AttributeError) as e:
                            logger.debug(
                                f"Error parsing timestamp for {ticker} quote: {e}"
                            )
                            continue

                    except Exception as e:
                        logger.debug(f"Error processing quote for {ticker}: {e}")
                        continue

                if len(price_data) < 3:
                    logger.debug(
                        f"Insufficient quotes for momentum calculation: {len(price_data)} < 3 for {ticker}"
                    )
                    return None

                logger.debug(
                    f"✅ Fetched {len(price_data)} real-time quotes for {ticker} momentum calculation"
                )
                return price_data

        except asyncio.TimeoutError:
            logger.debug(f"Timeout fetching real-time quotes for momentum for {ticker}")
            return None
        except Exception as e:
            logger.debug(
                f"Error fetching real-time quotes for momentum for {ticker}: {e}"
            )
            return None

    @classmethod
    async def close_session(cls):
        """Close the shared Alpaca session if it exists"""
        if cls._alpaca_session and not cls._alpaca_session.closed:
            try:
                await cls._alpaca_session.close()
                logger.debug("Closed shared Alpaca session for real-time quotes")
            except Exception as e:
                logger.warning(f"Error closing Alpaca session: {e}")
