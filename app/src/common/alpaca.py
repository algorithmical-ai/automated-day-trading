"""
Alpaca API Client for direct market data access
"""

import asyncio
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta, date
import pytz  # type: ignore
import aiohttp
from app.src.common.loguru_logger import logger
from app.src.config.constants import DEBUG_DAY_TRADING


class AlpacaClient:
    """Client for interacting with Alpaca API directly"""

    # TODO: Move these to environment variables for security
    # Note: Environment variables use underscores, but Alpaca headers require hyphens
    API_KEY_ID = os.getenv("REAL_TRADE_API_KEY", "")
    API_SECRET_KEY = os.getenv("REAL_TRADE_SECRET_KEY", "")
    BASE_URL = "https://data.alpaca.markets/v2/stocks"

    # Cache variables for clock endpoint
    _clock_cache: Optional[Dict[str, Any]] = None
    _clock_cache_timestamp: Optional[datetime] = None
    _clock_cache_lock: asyncio.Lock = asyncio.Lock()
    _clock_cache_ttl_seconds: int = 600  # 10 minutes

    @classmethod
    def _is_clock_cache_valid(cls) -> bool:
        """
        Check if the cached clock response is still valid.

        Returns:
            True if cache exists and is less than TTL seconds old, False otherwise
        """
        if cls._clock_cache is None or cls._clock_cache_timestamp is None:
            return False

        current_time = datetime.now(timezone.utc)
        cache_age = (current_time - cls._clock_cache_timestamp).total_seconds()
        return cache_age < cls._clock_cache_ttl_seconds

    @classmethod
    async def quote(cls, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get latest quote for a ticker from Alpaca API.

        Retries up to 3 times with 2 second timeout per retry.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")

        Returns:
            Dict with transformed quote data matching expected format:
            {
                "quote": {
                    "quotes": {
                        ticker: {
                            "bp": bid_price,
                            "ap": ask_price,
                            ...
                        }
                    }
                }
            }
            or None if all retries fail
        """
        url = f"{cls.BASE_URL}/{ticker}/quotes/latest"
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": cls.API_KEY_ID,
            "APCA-API-SECRET-KEY": cls.API_SECRET_KEY,
        }

        max_retries = 5
        timeout_seconds = 3

        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()

                            # Transform Alpaca response to match expected format
                            # Alpaca returns: {"quote": {...}, "symbol": "AAPL"}
                            # Expected format: {"quote": {"quotes": {ticker: {...}}}}
                            alpaca_quote = data.get("quote", {})
                            symbol = data.get("symbol", ticker)

                            if not alpaca_quote:
                                logger.warning(
                                    f"No quote data in Alpaca response for {ticker}"
                                )
                                return None

                            # Transform to expected format
                            transformed_response = {
                                "quote": {"quotes": {symbol: alpaca_quote}}
                            }

                            logger.debug(
                                f"Successfully retrieved quote for {ticker} from Alpaca API"
                            )
                            return transformed_response
                        else:
                            error_text = await response.text()
                            logger.warning(
                                f"Alpaca API error for {ticker}: HTTP {response.status} - {error_text[:200]}"
                            )

                            # Retry on server errors (5xx)
                            if response.status >= 500 and attempt < max_retries - 1:
                                logger.info(
                                    f"Retrying Alpaca quote request for {ticker} "
                                    f"(attempt {attempt + 1}/{max_retries})"
                                )
                                await asyncio.sleep(timeout_seconds)
                                continue

                            # Don't retry on client errors (4xx)
                            return None

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    logger.debug(
                        f"Timeout getting quote for {ticker} from Alpaca API "
                        f"(attempt {attempt + 1}/{max_retries}), retrying..."
                    )
                    await asyncio.sleep(timeout_seconds)
                    continue
                logger.error(
                    f"Timeout getting quote for {ticker} from Alpaca API after {max_retries} attempts"
                )
                return None

            except aiohttp.ClientError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"HTTP client error getting quote for {ticker} from Alpaca API: {e} "
                        f"(attempt {attempt + 1}/{max_retries}), retrying..."
                    )
                    await asyncio.sleep(timeout_seconds)
                    continue
                logger.exception(
                    f"HTTP client error getting quote for {ticker} from Alpaca API after {max_retries} attempts"
                )
                return None

            except Exception as e:  # pylint: disable=broad-except
                logger.exception(
                    f"Unexpected error getting quote for {ticker} from Alpaca API: {e}"
                )
                # Don't retry on unexpected errors
                return None

        return None

    @classmethod
    async def get_market_data(
        cls, ticker: str, limit: int = 200
    ) -> Optional[Dict[str, Any]]:
        """
        Get historical bars for a ticker from Alpaca API.
        Fetches latest bars in descending order, then sorts in ascending order.
        Retries with previous day if empty bars are returned.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")
            limit: Number of bars to retrieve (default: 200)

        Returns:
            Dict with bars data:
            {
                "bars": {
                    ticker: [
                        {
                            "c": close_price,
                            "h": high_price,
                            "l": low_price,
                            "n": number_of_trades,
                            "o": open_price,
                            "t": "2025-11-24T09:00:00Z",  # GMT timestamp
                            "v": volume,
                            "vw": vwap
                        },
                        ... (sorted in ascending order by timestamp)
                    ]
                },
                "bars_est": {  # Converted to EST
                    ticker: [
                        {
                            ...same structure but "t" is in EST (sorted ascending)...
                        }
                    ]
                }
            }
            or None if all retries fail
        """
        url = f"{cls.BASE_URL}/bars"
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": cls.API_KEY_ID,
            "APCA-API-SECRET-KEY": cls.API_SECRET_KEY,
        }

        max_retries = 3
        timeout_seconds = 5
        est_tz = pytz.timezone("America/New_York")

        # Try today, then previous day, then day before that
        # If we don't get enough bars, extend to 5, 10, 15 days before
        today = date.today()
        initial_start_dates = [
            today,
            today - timedelta(days=1),
            today - timedelta(days=2),
        ]
        extended_start_dates = [
            today - timedelta(days=5),
            today - timedelta(days=10),
            today - timedelta(days=15),
            today - timedelta(days=30),
        ]
        all_bars: List[Dict[str, Any]] = []  # Accumulate bars from multiple days
        all_bars_est: List[Dict[str, Any]] = (
            []
        )  # Accumulate EST bars from multiple days
        seen_timestamps = set()  # Track timestamps to avoid duplicates

        # Helper function to get timestamp from bar
        def get_timestamp(bar):
            timestamp_str = bar.get("t", "")
            if timestamp_str:
                try:
                    if timestamp_str.endswith("Z"):
                        dt = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                    else:
                        dt = datetime.fromisoformat(timestamp_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    return datetime.min.replace(tzinfo=timezone.utc)
            return datetime.min.replace(tzinfo=timezone.utc)

        # First, try initial dates (today, yesterday, day before)
        start_dates = initial_start_dates.copy()
        tried_extended = False

        # Loop through dates - will extend to 5, 10, 15 days if needed
        while True:
            for day_offset, start_date in enumerate(start_dates):
                # Create start datetime at midnight UTC
                start_datetime = datetime.combine(start_date, datetime.min.time())
                start_datetime = start_datetime.replace(tzinfo=timezone.utc)
                start_iso = start_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")

                params = {
                    "symbols": ticker,
                    "timeframe": "1Min",
                    "start": start_iso,
                    "limit": str(limit),
                    "adjustment": "raw",
                    "feed": "sip",
                    "sort": "desc",  # Get latest bars first
                }

                for attempt in range(max_retries):
                    try:
                        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(
                                url, headers=headers, params=params
                            ) as response:
                                if response.status == 200:
                                    data = await response.json()

                                    bars_dict = data.get("bars", {})

                                    # Check if bars dict is empty
                                    if not bars_dict:
                                        logger.debug(
                                            f"Empty bars for {ticker} on {start_date.isoformat()}, "
                                            f"trying next day"
                                        )
                                        break  # Try next day

                                    ticker_bars = bars_dict.get(ticker, [])
                                    if not ticker_bars:
                                        logger.debug(
                                            f"Empty bars for {ticker} on {start_date.isoformat()}, "
                                            f"trying next day"
                                        )
                                        break  # Try next day

                                    # Sort bars in ascending order by timestamp
                                    ticker_bars.sort(key=get_timestamp)

                                    # Convert GMT timestamps to EST and accumulate bars
                                    for bar in ticker_bars:
                                        timestamp_str = bar.get("t", "")
                                        # Use timestamp as unique key to avoid duplicates
                                        if (
                                            timestamp_str
                                            and timestamp_str not in seen_timestamps
                                        ):
                                            seen_timestamps.add(timestamp_str)
                                            all_bars.append(bar)

                                            # Convert to EST
                                            bar_est = bar.copy()
                                            try:
                                                # Parse GMT timestamp (ends with Z)
                                                if timestamp_str.endswith("Z"):
                                                    dt_utc = datetime.fromisoformat(
                                                        timestamp_str.replace(
                                                            "Z", "+00:00"
                                                        )
                                                    )
                                                else:
                                                    dt_utc = datetime.fromisoformat(
                                                        timestamp_str
                                                    )
                                                    if dt_utc.tzinfo is None:
                                                        dt_utc = dt_utc.replace(
                                                            tzinfo=timezone.utc
                                                        )

                                                # Convert to EST
                                                dt_est = dt_utc.astimezone(est_tz)
                                                # Format back to ISO string in EST
                                                bar_est["t"] = dt_est.isoformat()
                                            except Exception as e:
                                                logger.debug(
                                                    f"Error converting timestamp {timestamp_str} to EST: {e}"
                                                )
                                                # Keep original timestamp if conversion fails
                                            all_bars_est.append(bar_est)

                                    logger.debug(
                                        f"Retrieved {len(ticker_bars)} bars for {ticker} "
                                        f"from Alpaca API (start date: {start_date.isoformat()}, "
                                        f"total accumulated: {len(all_bars)})"
                                    )

                                    # If we have enough bars, we can return early
                                    if len(all_bars) >= limit:
                                        # Break out of both loops
                                        break

                                    # Continue to next day to get more bars
                                    continue

                                # Handle non-200 responses
                                error_text = await response.text()
                                logger.warning(
                                    f"Alpaca API error for {ticker} bars: HTTP {response.status} - {error_text[:200]}"
                                )

                                # Retry on server errors (5xx)
                                if response.status >= 500 and attempt < max_retries - 1:
                                    logger.info(
                                        f"Retrying Alpaca bars request for {ticker} "
                                        f"(attempt {attempt + 1}/{max_retries})"
                                    )
                                    await asyncio.sleep(timeout_seconds)
                                    continue

                                # Don't retry on client errors (4xx)
                                if day_offset < len(start_dates) - 1:
                                    break  # Try next day
                                # If we have some bars, continue to extended dates if needed
                                if (
                                    not tried_extended
                                    and start_dates == initial_start_dates
                                    and len(all_bars) < limit
                                ):
                                    logger.info(
                                        f"Only {len(all_bars)} bars so far, trying extended dates (5, 10, 15, 30 days ago)"
                                    )
                                    start_dates = extended_start_dates.copy()
                                    tried_extended = True
                                    break  # Restart loop with extended dates
                                # If we already tried extended dates or have no bars, return
                                if len(all_bars) == 0:
                                    return None
                                break  # Return what we have

                    except asyncio.TimeoutError:
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Timeout getting bars for {ticker} from Alpaca API "
                                f"(attempt {attempt + 1}/{max_retries}), retrying..."
                            )
                            await asyncio.sleep(timeout_seconds)
                            continue
                        # If all retries failed for this day, try next day
                        if day_offset < len(start_dates) - 1:
                            logger.info(
                                f"Timeout getting bars for {ticker} on {start_date.isoformat()}, "
                                f"trying next day"
                            )
                            break
                        # Try extended dates if we haven't yet
                        if (
                            not tried_extended
                            and start_dates == initial_start_dates
                            and len(all_bars) < limit
                        ):
                            logger.info(
                                f"Only {len(all_bars)} bars so far, trying extended dates (5, 10, 15, 30 days ago) after timeout"
                            )
                            start_dates = extended_start_dates.copy()
                            tried_extended = True
                            break  # Restart loop with extended dates
                        logger.error(
                            f"Timeout getting bars for {ticker} from Alpaca API after {max_retries} attempts"
                        )
                        if len(all_bars) == 0:
                            return None
                        break  # Return what we have

                    except aiohttp.ClientError as e:
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"HTTP client error getting bars for {ticker} from Alpaca API: {e} "
                                f"(attempt {attempt + 1}/{max_retries}), retrying..."
                            )
                            await asyncio.sleep(timeout_seconds)
                            continue
                        # If all retries failed for this day, try next day
                        if day_offset < len(start_dates) - 1:
                            logger.info(
                                f"HTTP error getting bars for {ticker} on {start_date.isoformat()}, "
                                f"trying next day"
                            )
                            break
                        # Try extended dates if we haven't yet
                        if (
                            not tried_extended
                            and start_dates == initial_start_dates
                            and len(all_bars) < limit
                        ):
                            logger.info(
                                f"Only {len(all_bars)} bars so far, trying extended dates (5, 10, 15, 30 days ago) after HTTP error"
                            )
                            start_dates = extended_start_dates.copy()
                            tried_extended = True
                            break  # Restart loop with extended dates
                        logger.exception(
                            f"HTTP client error getting bars for {ticker} from Alpaca API after {max_retries} attempts"
                        )
                        if len(all_bars) == 0:
                            return None
                        break  # Return what we have

                    except Exception as e:  # pylint: disable=broad-except
                        logger.exception(
                            f"Unexpected error getting bars for {ticker} from Alpaca API: {e}"
                        )
                        # If error on this day, try next day
                        if day_offset < len(start_dates) - 1:
                            logger.info(
                                f"Error getting bars for {ticker} on {start_date.isoformat()}, "
                                f"trying next day"
                            )
                            break
                        # Try extended dates if we haven't yet
                        if (
                            not tried_extended
                            and start_dates == initial_start_dates
                            and len(all_bars) < limit
                        ):
                            logger.info(
                                f"Only {len(all_bars)} bars so far, trying extended dates (5, 10, 15, 30 days ago) after error"
                            )
                            start_dates = extended_start_dates.copy()
                            tried_extended = True
                            break  # Restart loop with extended dates
                        if len(all_bars) == 0:
                            return None
                        break  # Return what we have

            # If we finished all dates in current set and have enough bars, break outer loop
            if len(all_bars) >= limit:
                break
            # If we finished initial dates and don't have enough, try extended dates
            if (
                not tried_extended
                and start_dates == initial_start_dates
                and len(all_bars) < limit
            ):
                logger.debug(
                    f"Only {len(all_bars)} bars from initial dates (need {limit}), "
                    f"trying extended dates (5, 10, 15, 30 days ago)"
                )
                start_dates = extended_start_dates.copy()
                tried_extended = True
                continue  # Restart loop with extended dates
            # If we've tried both sets or have enough bars, exit
            break

        # After trying all dates, if we have bars, return them (up to limit)
        if all_bars:
            # Sort all accumulated bars by timestamp
            all_bars.sort(key=get_timestamp)
            all_bars_est.sort(
                key=lambda bar: (
                    get_timestamp(bar)
                    if bar.get("t")
                    else datetime.min.replace(tzinfo=timezone.utc)
                )
            )

            # Take only the most recent bars up to limit
            final_bars = all_bars[-limit:] if len(all_bars) > limit else all_bars
            final_bars_est = (
                all_bars_est[-limit:] if len(all_bars_est) > limit else all_bars_est
            )

            result = {
                "bars": {ticker: final_bars},
                "bars_est": {ticker: final_bars_est},
            }

            logger.debug(
                f"Successfully retrieved {len(final_bars)} bars for {ticker} "
                f"(accumulated from multiple days, limit: {limit})"
            )
            return result

        return None

    @classmethod
    async def clock(cls) -> Dict[str, Any]:
        """
        Get market clock status with retry logic for rate limits and caching

        Returns:
            Dict with market clock data (is_open, next_open, next_close, etc.)
        """
        if not cls.API_KEY_ID or not cls.API_SECRET_KEY:
            raise ValueError("Alpaca API credentials not configured")

        # Acquire lock to ensure thread-safe cache access
        async with cls._clock_cache_lock:
            # Check if we have a valid cached response
            if cls._is_clock_cache_valid():
                cache_age = (
                    datetime.now(timezone.utc) - cls._clock_cache_timestamp
                ).total_seconds()
                logger.debug(
                    f"Using cached clock response (age: {cache_age:.1f} seconds)"
                )
                return cls._clock_cache

            # Cache miss or expired - log and fetch from API
            if cls._clock_cache is None:
                logger.debug("Clock cache miss, fetching from API")
            else:
                cache_age = (
                    datetime.now(timezone.utc) - cls._clock_cache_timestamp
                ).total_seconds()
                logger.debug(
                    f"Clock cache expired (age: {cache_age:.1f} seconds), refreshing"
                )

            # Clock endpoint is on Trading API, not Data API
            # Use Trading API base URL for clock endpoint
            trading_base_url = "https://api.alpaca.markets/v2"
            url = f"{trading_base_url}/clock"

            headers = {
                "APCA-API-KEY-ID": cls.API_KEY_ID,
                "APCA-API-SECRET-KEY": cls.API_SECRET_KEY,
            }

            max_retries = 3
            retry_delay = 2  # seconds

            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                data = await response.json()
                                
                                # Update cache with new response
                                cls._clock_cache = data
                                cls._clock_cache_timestamp = datetime.now(timezone.utc)
                                
                                return data

                            error_text = await response.text()
                            
                            # Handle 429 rate limit with retry
                            if response.status == 429:
                                if attempt < max_retries - 1:
                                    logger.debug(
                                        f"Alpaca clock API rate limited (429). Retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})"
                                    )
                                    await asyncio.sleep(retry_delay)
                                    continue
                                else:
                                    logger.error(
                                        f"Alpaca clock API rate limited after {max_retries} attempts: {error_text}"
                                    )
                                    raise ValueError(f"Failed to fetch market clock after {max_retries} retries: rate limited")
                            
                            # For other errors, log and raise immediately
                            logger.warning(
                                f"Alpaca clock API returned {response.status}: {error_text}"
                            )
                            raise ValueError(f"Failed to fetch market clock: {response.status}")
                except aiohttp.ClientError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Network error fetching market clock. Retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"Error fetching market clock after {max_retries} attempts: {str(e)}", exc_info=True)
                        raise ValueError(f"Error fetching market clock: {str(e)}") from e

    @classmethod
    async def is_market_open(cls) -> bool:
        """
        Check if market is open

        Returns:
            True if market is open, False otherwise
        """
        if DEBUG_DAY_TRADING:
            return True
        clock = await cls.clock()
        if not clock:
            return False
        return clock.get("is_open", False)
