"""
Market Data Service
Provides entry and exit analysis for trading signals
"""

import asyncio
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional

import aiohttp
import pytz

from app.src.common.loguru_logger import logger
from app.src.models.technical_indicators import TechnicalIndicators
from app.src.services.mcp.mcp_client import MCPClient
from app.src.common.utils import dict_to_technical_indicators


class MarketDataService:
    """Service for analyzing market data for entry and exit signals"""

    # Entry score thresholds (similar to BuyToOpenService and SellToOpenService)
    # Loosened thresholds to allow more trades
    _base_normal_entry_threshold = 0.65  # Lowered from 0.75
    _base_golden_entry_threshold = 0.60  # Lowered from 0.70
    _min_adx_normal = 20.0  # Lowered from 25.0
    _min_adx_golden = 25.0  # Lowered from 32.0
    _min_volume_ratio_normal = 1.0  # Lowered from 1.2 (allow at least average volume)
    _min_volume_ratio_golden = 1.5  # Lowered from 2.5
    _min_ema_crossover_pct = 0.05  # Lowered from 0.1 (allow smaller crossovers)
    _max_vwap_deviation_normal = 2.5  # Increased from 2.0 (allow more deviation)
    _max_vwap_deviation_golden = 4.0  # Increased from 3.5
    _max_vwap_premium_normal = 0.50  # Increased from 0.35 (allow higher premium)
    _max_vwap_premium_golden = 1.0  # Increased from 0.75

    # Exit monitoring parameters (similar to ExitMonitoringService)
    _minimum_hold_seconds = 60
    _reversal_confirmation_required = 2
    _low_volume_threshold_avg = 0.6
    _low_volume_threshold_single = 0.45

    # Rate limiting for Alpaca API shortability checks
    _shortability_cache: Dict[str, Tuple[bool, str, datetime]] = {}
    _shortability_cache_ttl_seconds = 300  # 5 minutes cache
    _last_shortability_check_time: Optional[datetime] = None
    _min_seconds_between_checks = 0.1  # 100ms between API calls to respect rate limits

    # Local in-memory cache for is_shortable (ticker -> is_shortable)
    _is_shortable_local_cache: Dict[str, bool] = {}

    @classmethod
    async def _check_ticker_shortable(
        cls, ticker: str, indicator: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Check if a ticker is shortable.
        Checks in order: local cache -> DynamoDB -> Alpaca API.
        Includes rate limiting, caching, and retry logic for 429 errors.

        Args:
            ticker: Stock ticker symbol
            indicator: Optional indicator name for DynamoDB lookup

        Returns:
            Tuple of (is_shortable: bool, reason: str)
        """
        # Check local in-memory cache first (fastest)
        if ticker in cls._is_shortable_local_cache:
            is_shortable = cls._is_shortable_local_cache[ticker]
            logger.debug(f"Using local cache for {ticker} shortability: {is_shortable}")
            return (
                is_shortable,
                f"{ticker} is {'shortable' if is_shortable else 'not shortable'} (from local cache)",
            )

        # Check DynamoDB cache (if indicator provided)
        if indicator:
            from app.src.db.dynamodb_client import DynamoDBClient

            db_shortable = await DynamoDBClient.get_ticker_shortability_from_db(
                ticker, indicator
            )
            if db_shortable is not None:
                # Store in local cache for future use
                cls._is_shortable_local_cache[ticker] = db_shortable
                logger.debug(
                    f"Using DynamoDB cache for {ticker} shortability: {db_shortable}"
                )
                return (
                    db_shortable,
                    f"{ticker} is {'shortable' if db_shortable else 'not shortable'} (from DynamoDB)",
                )

        # Check API cache (with TTL)
        now = datetime.now(timezone.utc)
        if ticker in cls._shortability_cache:
            cached_result, cached_reason, cached_time = cls._shortability_cache[ticker]
            age_seconds = (now - cached_time).total_seconds()
            if age_seconds < cls._shortability_cache_ttl_seconds:
                # Also store in local cache
                cls._is_shortable_local_cache[ticker] = cached_result
                logger.debug(
                    f"Using API cache for {ticker} shortability: {cached_result}"
                )
                return cached_result, cached_reason

        api_key = os.environ.get("REAL_TRADE_API_KEY", "")
        api_secret = os.environ.get("REAL_TRADE_SECRET_KEY", "")

        if not api_key or not api_secret:
            logger.warning(
                f"No Alpaca API credentials available, assuming {ticker} is shortable"
            )
            result = (True, "No API credentials, assuming shortable")
            cls._shortability_cache[ticker] = (*result, now)
            cls._is_shortable_local_cache[ticker] = True
            return result

        # Rate limiting: ensure minimum time between API calls
        if cls._last_shortability_check_time:
            time_since_last = (now - cls._last_shortability_check_time).total_seconds()
            if time_since_last < cls._min_seconds_between_checks:
                await asyncio.sleep(cls._min_seconds_between_checks - time_since_last)

        url = f"https://api.alpaca.markets/v2/assets/{ticker}"
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }

        # Retry logic for 429 errors with exponential backoff
        max_retries = 3
        base_delay = 1.0  # Start with 1 second delay

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        cls._last_shortability_check_time = datetime.now(timezone.utc)

                        if response.status == 200:
                            data = await response.json()
                            shortable = data.get("shortable", False)
                            easy_to_borrow = data.get("easy_to_borrow", False)
                            tradable = data.get("tradable", False)

                            if not tradable:
                                result = (False, f"{ticker} is not tradable")
                                cls._shortability_cache[ticker] = (*result, now)
                                cls._is_shortable_local_cache[ticker] = False
                                # Store in DynamoDB if indicator provided
                                if indicator:
                                    from app.src.db.dynamodb_client import (
                                        DynamoDBClient,
                                    )

                                    await DynamoDBClient.log_inactive_ticker_reason(
                                        ticker=ticker,
                                        indicator=indicator,
                                        is_shortable=False,
                                    )
                                return result
                            if not shortable:
                                result = (False, f"{ticker} is not shortable")
                                cls._shortability_cache[ticker] = (*result, now)
                                cls._is_shortable_local_cache[ticker] = False
                                # Store in DynamoDB if indicator provided
                                if indicator:
                                    from app.src.db.dynamodb_client import (
                                        DynamoDBClient,
                                    )

                                    await DynamoDBClient.log_inactive_ticker_reason(
                                        ticker=ticker,
                                        indicator=indicator,
                                        is_shortable=False,
                                    )
                                return result
                            if not easy_to_borrow:
                                logger.warning(
                                    f"{ticker} is shortable but not easy to borrow"
                                )
                                # Still allow it, but log a warning

                            result = (True, f"{ticker} is shortable")
                            cls._shortability_cache[ticker] = (*result, now)
                            cls._is_shortable_local_cache[ticker] = True
                            # Store in DynamoDB if indicator provided
                            if indicator:
                                from app.src.db.dynamodb_client import DynamoDBClient

                                await DynamoDBClient.log_inactive_ticker_reason(
                                    ticker=ticker,
                                    indicator=indicator,
                                    is_shortable=True,
                                )
                            return result
                        elif response.status == 404:
                            result = (False, f"{ticker} not found in Alpaca assets")
                            cls._shortability_cache[ticker] = (*result, now)
                            cls._is_shortable_local_cache[ticker] = False
                            # Store in DynamoDB if indicator provided
                            if indicator:
                                from app.src.db.dynamodb_client import DynamoDBClient

                                await DynamoDBClient.log_inactive_ticker_reason(
                                    ticker=ticker,
                                    indicator=indicator,
                                    is_shortable=False,
                                )
                            return result
                        elif response.status == 429:
                            # Rate limited - retry with exponential backoff
                            if attempt < max_retries - 1:
                                delay = base_delay * (2**attempt)  # Exponential backoff
                                logger.warning(
                                    f"Rate limited (429) for {ticker}, retrying in {delay:.1f}s "
                                    f"(attempt {attempt + 1}/{max_retries})"
                                )
                                await asyncio.sleep(delay)
                                continue
                            else:
                                logger.warning(
                                    f"Rate limited (429) for {ticker} after {max_retries} attempts, assuming shortable"
                                )
                                # Fail open after max retries
                                result = (
                                    True,
                                    f"Rate limited after {max_retries} attempts, assuming shortable",
                                )
                                cls._shortability_cache[ticker] = (*result, now)
                                cls._is_shortable_local_cache[ticker] = True
                                return result
                        else:
                            logger.warning(
                                f"Alpaca API returned status {response.status} for {ticker} asset check"
                            )
                            # Assume shortable if API call fails (fail open)
                            result = (
                                True,
                                f"API error (status {response.status}), assuming shortable",
                            )
                            cls._shortability_cache[ticker] = (*result, now)
                            cls._is_shortable_local_cache[ticker] = True
                            return result
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Error checking if {ticker} is shortable (attempt {attempt + 1}/{max_retries}): {str(e)}, retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.warning(
                        f"Error checking if {ticker} is shortable after {max_retries} attempts: {str(e)}, assuming shortable"
                    )
                    # Fail open - assume shortable if check fails
                    result = (
                        True,
                        f"Error checking shortability after {max_retries} attempts: {str(e)}, assuming shortable",
                    )
                    cls._shortability_cache[ticker] = (*result, now)
                    cls._is_shortable_local_cache[ticker] = True
                    return result

        # Should not reach here, but fail open just in case
        result = (True, "Max retries exceeded, assuming shortable")
        cls._shortability_cache[ticker] = (*result, now)
        cls._is_shortable_local_cache[ticker] = True
        return result

    @classmethod
    async def enter_trade(
        cls,
        ticker: str,
        action: str,
        market_data: Optional[Dict[str, Any]] = None,
        indicator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a ticker for entry signal (buy-to-open or sell-to-open).

        Args:
            ticker: Stock ticker symbol
            action: "buy_to_open" (for long) or "sell_to_open" (for short)
            market_data: Optional pre-fetched market data
            indicator: Optional indicator name for DynamoDB shortability lookup

        Returns:
            Dict containing entry signal details or analysis
        """
        ticker = ticker.upper().strip()
        action = action.lower().strip()

        # Check if ticker is shortable for sell_to_open actions
        if action == "sell_to_open":
            is_shortable, shortable_reason = await cls._check_ticker_shortable(
                ticker, indicator=indicator
            )
            if not is_shortable:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {},
                    "message": f"Cannot proceed with short: {shortable_reason}",
                }
            logger.debug(f"Shortability check passed for {ticker}: {shortable_reason}")

        if market_data is None:  # noqa: C0301
            market_data = await MCPClient.get_market_data(ticker)
            if market_data is None:
                raise ValueError(f"No market data available for {ticker}")

        indicators = dict_to_technical_indicators(market_data)
        if indicators is None:
            raise ValueError(f"Failed to convert technical indicators for {ticker}")

        # Calculate entry score
        entry_score = cls._calculate_entry_score(indicators, action)

        # Check if golden entry
        is_golden, golden_reason = cls._is_golden_entry(indicators, entry_score, action)

        # Check trend direction
        trend_check = cls._is_upward_or_downward_trend(indicators, action)

        # Validate entry conditions based on action
        if action == "buy_to_open":
            # Validate long entry conditions
            if not trend_check:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "golden_reason": golden_reason if is_golden else "",
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"{ticker} is not in an upward trend",
                }

            # Check EMA crossover strength
            if indicators.ema_slow > 0:
                ema_diff_pct = (
                    abs(
                        (indicators.ema_fast - indicators.ema_slow)
                        / indicators.ema_slow
                    )
                    * 100
                )
                if ema_diff_pct < cls._min_ema_crossover_pct:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"EMA crossover too weak: {ema_diff_pct:.3f}% (minimum {cls._min_ema_crossover_pct:.1f}% required)",
                    }

            # Check RSI for long entries
            if indicators.rsi < 40:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"RSI {indicators.rsi:.1f} too low for long entry (minimum 40)",
                }
            if indicators.rsi > 65:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"RSI {indicators.rsi:.1f} too high for long entry (maximum 65)",
                }

            # Check ADX
            min_adx = cls._min_adx_golden if is_golden else cls._min_adx_normal
            if indicators.adx < min_adx:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"ADX {indicators.adx:.2f} below minimum {min_adx:.2f} required",
                }

            # Check volume
            if indicators.volume > 0 and indicators.volume_sma > 0:
                volume_ratio = indicators.volume / indicators.volume_sma
                min_volume = (
                    cls._min_volume_ratio_golden
                    if is_golden
                    else cls._min_volume_ratio_normal
                )
                if volume_ratio < min_volume:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"Volume ratio {volume_ratio:.2f}x below minimum {min_volume:.2f}x",
                    }

            # Check VWAP deviation
            if indicators.close_price > 0 and indicators.vwap > 0:
                vwap_diff_pct = (
                    (indicators.close_price - indicators.vwap) / indicators.vwap
                ) * 100
                max_deviation = (
                    cls._max_vwap_deviation_golden
                    if is_golden
                    else cls._max_vwap_deviation_normal
                )
                if abs(vwap_diff_pct) > max_deviation:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"Price deviation from VWAP is {abs(vwap_diff_pct):.2f}% which exceeds {max_deviation:.2f}%",
                    }
                if indicators.ema_fast < indicators.vwap:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"Fast EMA {indicators.ema_fast:.2f} below VWAP {indicators.vwap:.2f}",
                    }
                if vwap_diff_pct > 0:
                    max_premium = (
                        cls._max_vwap_premium_golden
                        if is_golden
                        else cls._max_vwap_premium_normal
                    )
                    if vwap_diff_pct > max_premium:
                        return {
                            "ticker": ticker,
                            "action": action,
                            "signal": None,
                            "enter": False,
                            "analysis": {
                                "entry_score": entry_score,
                                "is_golden": is_golden,
                                "trend_check": trend_check,
                                "indicators": indicators,
                            },
                            "message": f"Price is {vwap_diff_pct:.2f}% above VWAP which exceeds allowed premium of {max_premium:.2f}%",
                        }

        else:  # sell_to_open
            # Validate short entry conditions
            if not trend_check:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "golden_reason": golden_reason if is_golden else "",
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"{ticker} is not in a downward trend",
                }

            # Check EMA crossover strength
            if indicators.ema_slow > 0:
                ema_diff_pct = (
                    abs(
                        (indicators.ema_slow - indicators.ema_fast)
                        / indicators.ema_slow
                    )
                    * 100
                )
                if ema_diff_pct < cls._min_ema_crossover_pct:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"EMA crossover too weak: {ema_diff_pct:.3f}% (minimum {cls._min_ema_crossover_pct:.1f}% required)",
                    }

            # Check RSI for short entries
            if indicators.rsi > 60:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"RSI {indicators.rsi:.1f} too high for short entry (maximum 60)",
                }
            if indicators.rsi < 35:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"RSI {indicators.rsi:.1f} too low for short entry (minimum 35)",
                }

            # Check ADX
            min_adx = cls._min_adx_golden if is_golden else cls._min_adx_normal
            if indicators.adx < min_adx:
                return {
                    "ticker": ticker,
                    "action": action,
                    "signal": None,
                    "enter": False,
                    "analysis": {
                        "entry_score": entry_score,
                        "is_golden": is_golden,
                        "trend_check": trend_check,
                        "indicators": indicators,
                    },
                    "message": f"ADX {indicators.adx:.2f} below minimum {min_adx:.2f} required",
                }

            # Check volume
            if indicators.volume > 0 and indicators.volume_sma > 0:
                volume_ratio = indicators.volume / indicators.volume_sma
                min_volume = (
                    cls._min_volume_ratio_golden
                    if is_golden
                    else cls._min_volume_ratio_normal
                )
                if volume_ratio < min_volume:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"Volume ratio {volume_ratio:.2f}x below minimum {min_volume:.2f}x",
                    }

            # Check VWAP deviation
            if indicators.close_price > 0 and indicators.vwap > 0:
                vwap_diff_pct = (
                    (indicators.close_price - indicators.vwap) / indicators.vwap
                ) * 100
                max_deviation = (
                    cls._max_vwap_deviation_golden
                    if is_golden
                    else cls._max_vwap_deviation_normal
                )
                if abs(vwap_diff_pct) > max_deviation:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"Price deviation from VWAP is {abs(vwap_diff_pct):.2f}% which exceeds {max_deviation:.2f}%",
                    }
                if vwap_diff_pct < -max_deviation:
                    return {
                        "ticker": ticker,
                        "action": action,
                        "signal": None,
                        "enter": False,
                        "analysis": {
                            "entry_score": entry_score,
                            "is_golden": is_golden,
                            "trend_check": trend_check,
                            "indicators": indicators,
                        },
                        "message": f"Price is {vwap_diff_pct:.2f}% below VWAP which exceeds allowed deviation",
                    }

        # Check entry score threshold
        threshold = (
            cls._base_golden_entry_threshold
            if is_golden
            else cls._base_normal_entry_threshold
        )
        if entry_score < threshold:
            return {
                "ticker": ticker,
                "action": action,
                "signal": None,
                "enter": False,
                "analysis": {
                    "entry_score": entry_score,
                    "is_golden": is_golden,
                    "golden_reason": golden_reason if is_golden else "",
                    "trend_check": trend_check,
                    "indicators": indicators,
                },
                "message": f"Entry score {entry_score:.2f} below threshold {threshold:.2f}",
            }

        # Calculate portfolio allocation
        portfolio_allocation = cls._calculate_portfolio_allocation(
            entry_score, indicators, is_golden
        )

        # Return successful entry signal
        return {
            "ticker": ticker,
            "action": action,
            "signal": {
                "ticker": ticker,
                "entry_score": entry_score,
                "portfolio_allocation": portfolio_allocation,
                "indicators": indicators,
                "is_golden": is_golden,
                "golden_reason": golden_reason if is_golden else "",
            },
            "enter": True,
        }

    @classmethod
    def _calculate_entry_score(
        cls, indicators: TechnicalIndicators, action: str
    ) -> float:
        """
        Calculate entry score for a ticker based on technical indicators.

        Args:
            indicators: TechnicalIndicators object
            action: "buy_to_open" (long) or "sell_to_open" (short)

        Returns:
            Score between 0 and 1.0 (higher = better entry signal)
        """
        if action == "buy_to_open":
            return cls._calculate_long_entry_score(indicators)
        else:  # sell_to_open
            return cls._calculate_short_entry_score(indicators)

    @classmethod
    def _calculate_long_entry_score(cls, indicators: TechnicalIndicators) -> float:
        """Calculate entry score for long position (buy_to_open)"""
        score = 0.0
        max_score = 0.0

        # 1. Trend direction (EMA crossover) - Weight: 25%
        max_score += 0.25
        if indicators.ema_fast > indicators.ema_slow and indicators.ema_slow > 0:
            ema_diff_pct = (
                (indicators.ema_fast - indicators.ema_slow) / indicators.ema_slow
            ) * 100
            if ema_diff_pct < 0.1:
                ema_score = 0.10 + (ema_diff_pct / 0.1) * 0.08
            elif ema_diff_pct < 0.5:
                ema_score = 0.18 + ((ema_diff_pct - 0.1) / 0.4) * 0.03
            elif ema_diff_pct < 1.0:
                ema_score = 0.21 + ((ema_diff_pct - 0.5) / 0.5) * 0.03
            else:
                ema_score = min(0.25, 0.24 + (ema_diff_pct - 1.0) / 10.0)
            score += ema_score

        # 2. MACD momentum - Weight: 25%
        max_score += 0.25
        macd, signal, hist = indicators.macd
        if hist > 0:
            hist_strength = min(abs(hist) / (abs(macd) + 0.001), 1.0)
            score += 0.25 * hist_strength
        elif macd > signal:
            score += 0.15

        # 3. RSI position - Weight: 15%
        max_score += 0.15
        if 30 < indicators.rsi < 70:
            if 40 <= indicators.rsi <= 60:
                score += 0.15
            elif 30 < indicators.rsi < 40:
                score += 0.10
            elif 60 < indicators.rsi < 65:
                score += 0.08
            elif 65 <= indicators.rsi < 70:
                score += 0.05
        elif indicators.rsi < 30:
            score += 0.08

        # 4. Trend strength (ADX) - Weight: 15%
        max_score += 0.15
        if indicators.adx > 30:
            adx_score = min(1.0, indicators.adx / 50.0)
            score += 0.15 * adx_score
        elif indicators.adx > 25:
            adx_score = min(1.0, indicators.adx / 40.0)
            score += 0.12 * adx_score
        elif indicators.adx > 20:
            score += 0.08

        # 5. Price vs VWAP - Weight: 10%
        max_score += 0.10
        if indicators.close_price > 0 and indicators.vwap > 0:
            vwap_diff_pct = (
                (indicators.close_price - indicators.vwap) / indicators.vwap
            ) * 100
            if vwap_diff_pct > 0:
                score += 0.10 * min(1.0, vwap_diff_pct / 2.0)
            elif vwap_diff_pct > -1.0:
                score += 0.05

        # 6. Volume confirmation - Weight: 10%
        max_score += 0.10
        if indicators.volume > 0 and indicators.volume_sma > 0:
            volume_ratio = indicators.volume / indicators.volume_sma
            if volume_ratio > 2.0:
                score += 0.10 * min(1.0, volume_ratio / 3.0)
            elif volume_ratio > 1.5:
                score += 0.08
            elif volume_ratio > 1.2:
                score += 0.05

        # Normalize score to 0-1 range
        if max_score > 0:
            score = score / max_score

        return score

    @classmethod
    def _calculate_short_entry_score(cls, indicators: TechnicalIndicators) -> float:
        """Calculate entry score for short position (sell_to_open)"""
        score = 0.0
        max_score = 0.0

        # 1. Trend direction (EMA crossover) - Weight: 25%
        max_score += 0.25
        if indicators.ema_fast < indicators.ema_slow and indicators.ema_slow > 0:
            ema_diff_pct = (
                (indicators.ema_slow - indicators.ema_fast) / indicators.ema_slow
            ) * 100
            if ema_diff_pct < 0.1:
                ema_score = 0.10 + (ema_diff_pct / 0.1) * 0.08
            elif ema_diff_pct < 0.5:
                ema_score = 0.18 + ((ema_diff_pct - 0.1) / 0.4) * 0.03
            elif ema_diff_pct < 1.0:
                ema_score = 0.21 + ((ema_diff_pct - 0.5) / 0.5) * 0.03
            else:
                ema_score = min(0.25, 0.24 + (ema_diff_pct - 1.0) / 10.0)
            score += ema_score

        # 2. MACD momentum - Weight: 25%
        max_score += 0.25
        macd, signal, hist = indicators.macd
        if hist < 0:
            hist_strength = min(abs(hist) / (abs(macd) + 0.001), 1.0)
            score += 0.25 * hist_strength
        elif macd < signal:
            score += 0.15

        # 3. RSI position - Weight: 15%
        max_score += 0.15
        if 30 < indicators.rsi < 70:
            if 40 <= indicators.rsi <= 60:
                score += 0.10  # Neutral RSI less favorable for shorts
            elif 60 < indicators.rsi < 70:
                score += 0.15  # Overbought is good for shorts
            elif 50 < indicators.rsi < 60:
                score += 0.08
            elif 30 < indicators.rsi < 40:
                score += 0.05
        elif indicators.rsi > 70:
            score += 0.12  # Very overbought

        # 4. Trend strength (ADX) - Weight: 15%
        max_score += 0.15
        if indicators.adx > 30:
            adx_score = min(1.0, indicators.adx / 50.0)
            score += 0.15 * adx_score
        elif indicators.adx > 25:
            adx_score = min(1.0, indicators.adx / 40.0)
            score += 0.12 * adx_score
        elif indicators.adx > 20:
            score += 0.08

        # 5. Price vs VWAP - Weight: 10%
        max_score += 0.10
        if indicators.close_price > 0 and indicators.vwap > 0:
            vwap_diff_pct = (
                (indicators.close_price - indicators.vwap) / indicators.vwap
            ) * 100
            if vwap_diff_pct < 0:
                score += 0.10 * min(1.0, abs(vwap_diff_pct) / 2.0)
            elif vwap_diff_pct < 1.0:
                score += 0.05

        # 6. Volume confirmation - Weight: 10%
        max_score += 0.10
        if indicators.volume > 0 and indicators.volume_sma > 0:
            volume_ratio = indicators.volume / indicators.volume_sma
            if volume_ratio > 2.0:
                score += 0.10 * min(1.0, volume_ratio / 3.0)
            elif volume_ratio > 1.5:
                score += 0.08
            elif volume_ratio > 1.2:
                score += 0.05

        # Normalize score to 0-1 range
        if max_score > 0:
            score = score / max_score

        return score

    @classmethod
    def _is_golden_entry(
        cls, indicators: TechnicalIndicators, entry_score: float, action: str
    ) -> Tuple[bool, str]:
        """
        Check if ticker qualifies as GOLDEN entry.

        Args:
            indicators: TechnicalIndicators object
            entry_score: Calculated entry score
            action: "buy_to_open" or "sell_to_open"

        Returns:
            Tuple of (is_golden: bool, reason: str)
        """
        golden_reasons = []

        if action == "buy_to_open":
            # Long golden entry conditions
            if indicators.ema_slow > 0:
                ema_diff_pct = (
                    (indicators.ema_fast - indicators.ema_slow) / indicators.ema_slow
                ) * 100
                if ema_diff_pct > 3.0:
                    golden_reasons.append(
                        f"Strong EMA divergence ({ema_diff_pct:.2f}%)"
                    )

            macd, _signal, hist = indicators.macd
            if hist > 0 and abs(hist) > abs(macd) * 0.8:
                golden_reasons.append(f"Very strong MACD momentum (hist={hist:.4f})")

            if indicators.adx > 35:
                golden_reasons.append(f"Very strong trend (ADX={indicators.adx:.1f})")

            if indicators.close_price > 0 and indicators.vwap > 0:
                vwap_diff_pct = (
                    (indicators.close_price - indicators.vwap) / indicators.vwap
                ) * 100
                if vwap_diff_pct > 2.0:
                    golden_reasons.append(
                        f"Price well above VWAP ({vwap_diff_pct:.2f}%)"
                    )

            if indicators.volume > 0 and indicators.volume_sma > 0:
                volume_ratio = indicators.volume / indicators.volume_sma
                if volume_ratio > 2.0:
                    golden_reasons.append(
                        f"High volume confirmation ({volume_ratio:.2f}x average)"
                    )

            if 40 <= indicators.rsi <= 60:
                golden_reasons.append(f"Optimal RSI ({indicators.rsi:.1f})")

        else:  # sell_to_open
            # Short golden entry conditions
            if indicators.ema_slow > 0:
                ema_diff_pct = (
                    (indicators.ema_slow - indicators.ema_fast) / indicators.ema_slow
                ) * 100
                if ema_diff_pct > 3.0:
                    golden_reasons.append(
                        f"Strong EMA divergence ({ema_diff_pct:.2f}%)"
                    )

            macd, _signal, hist = indicators.macd
            if hist < 0 and abs(hist) > abs(macd) * 0.8:
                golden_reasons.append(f"Very strong MACD momentum (hist={hist:.4f})")

            if indicators.adx > 35:
                golden_reasons.append(f"Very strong trend (ADX={indicators.adx:.1f})")

            if indicators.close_price > 0 and indicators.vwap > 0:
                vwap_diff_pct = (
                    (indicators.close_price - indicators.vwap) / indicators.vwap
                ) * 100
                if vwap_diff_pct < -2.0:
                    golden_reasons.append(
                        f"Price well below VWAP ({vwap_diff_pct:.2f}%)"
                    )

            if indicators.volume > 0 and indicators.volume_sma > 0:
                volume_ratio = indicators.volume / indicators.volume_sma
                if volume_ratio > 2.0:
                    golden_reasons.append(
                        f"High volume confirmation ({volume_ratio:.2f}x average)"
                    )

            if 50 <= indicators.rsi <= 70:
                golden_reasons.append(f"Optimal RSI for short ({indicators.rsi:.1f})")

        # Require at least 5 golden signals
        if len(golden_reasons) >= 5 or entry_score >= 0.9:
            if entry_score >= 0.9:
                golden_reasons.append(f"Exceptional entry score ({entry_score:.2f})")
            reason = "GOLDEN: " + "; ".join(golden_reasons)
            return True, reason

        return False, ""

    @classmethod
    def _is_upward_or_downward_trend(
        cls, indicators: TechnicalIndicators, action: str
    ) -> bool:
        """
        Check if the trend is upward (for buy_to_open) or downward (for sell_to_open).

        Args:
            indicators: TechnicalIndicators object
            action: "buy_to_open" (check upward) or "sell_to_open" (check downward)

        Returns:
            True if trend matches action direction
        """
        if action == "buy_to_open":
            return cls._is_upward_trend(indicators)
        else:  # sell_to_open
            return cls._is_downward_trend(indicators)

    @classmethod
    def _check_price_trend_upward(cls, datetime_price: Tuple) -> bool:
        """
        Check if price trend is upward by analyzing datetime_price time-series data.
        Data is sorted by timestamp in ascending order (oldest to newest).

        Args:
            datetime_price: Tuple/list of price data entries, each containing [timestamp, price] or dict

        Returns:
            True if price shows upward trend
        """
        if not datetime_price or len(datetime_price) < 3:
            return False

        try:
            # Parse and extract (timestamp, price) pairs
            price_points = []
            for entry in datetime_price:
                try:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        # Format: [timestamp, price] or [datetime_str, price]
                        timestamp_str = str(entry[0])
                        price = float(entry[1])
                        price_points.append((timestamp_str, price))
                    elif isinstance(entry, dict):
                        # Format: {"datetime": ..., "price": ...} or {"datetime": ..., "close": ...}
                        timestamp_str = str(
                            entry.get("datetime") or entry.get("timestamp") or ""
                        )
                        price = float(
                            entry.get("price")
                            or entry.get("close")
                            or entry.get("close_price")
                            or 0.0
                        )
                        if price > 0:
                            price_points.append((timestamp_str, price))
                except (ValueError, TypeError, KeyError, IndexError):
                    continue

            if len(price_points) < 3:
                return False

            # Sort by timestamp in ascending order (oldest to newest)
            # Handle EST timestamps - parse and sort properly
            est_tz = pytz.timezone("America/New_York")

            def parse_timestamp(ts_str: str) -> datetime:
                """Parse timestamp string, handling various formats"""
                ts_str = str(ts_str).strip()
                # Try ISO format first
                try:
                    if "T" in ts_str or "+" in ts_str or ts_str.endswith("Z"):
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        # Try common formats
                        for fmt in [
                            "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d %H:%M:%S.%f",
                            "%Y-%m-%d",
                        ]:
                            try:
                                dt = datetime.strptime(ts_str, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            # Fallback: try ISO without timezone
                            dt = datetime.fromisoformat(ts_str)

                    # Ensure timezone-aware (assume EST if not specified)
                    if dt.tzinfo is None:
                        dt = est_tz.localize(dt)
                    else:
                        dt = dt.astimezone(est_tz)

                    return dt
                except Exception:
                    # If parsing fails, return a default datetime
                    return datetime.now(est_tz)

            # Sort by timestamp (ascending - oldest to newest)
            try:
                price_points_sorted = sorted(
                    price_points, key=lambda x: parse_timestamp(x[0])
                )
            except Exception:
                # If sorting fails, use original order
                price_points_sorted = price_points

            # Extract prices in chronological order
            prices = [float(price) for _, price in price_points_sorted]

            if len(prices) < 3:
                return False

            # Analyze trend: compare early vs recent prices
            # Use first 1/3 and last 1/3 of data points
            n = len(prices)
            early_count = max(1, n // 3)
            recent_count = max(1, n // 3)

            early_prices = prices[:early_count]
            recent_prices = prices[-recent_count:]

            early_avg = sum(early_prices) / len(early_prices)
            recent_avg = sum(recent_prices) / len(recent_prices)

            # Check if recent average is higher than early average
            if recent_avg <= early_avg:
                return False

            # Calculate percentage change
            change_pct = ((recent_avg - early_avg) / early_avg) * 100

            # Also check recent momentum (last few points)
            if len(recent_prices) >= 2:
                recent_momentum = sum(
                    (recent_prices[i] - recent_prices[i - 1])
                    for i in range(1, len(recent_prices))
                ) / max(1, len(recent_prices) - 1)

                # Both overall trend and recent momentum should be positive
                return change_pct > 0.1 and recent_momentum > 0

            return change_pct > 0.1

        except Exception as e:
            logger.debug(f"Error checking upward price trend: {str(e)}")
            return False

    @classmethod
    def _check_price_trend_downward(cls, datetime_price: Tuple) -> bool:
        """
        Check if price trend is downward by analyzing datetime_price time-series data.
        Data is sorted by timestamp in ascending order (oldest to newest).

        Args:
            datetime_price: Tuple/list of price data entries, each containing [timestamp, price] or dict

        Returns:
            True if price shows downward trend
        """
        if not datetime_price or len(datetime_price) < 3:
            return False

        try:
            # Parse and extract (timestamp, price) pairs
            price_points = []
            for entry in datetime_price:
                try:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        timestamp_str = str(entry[0])
                        price = float(entry[1])
                        price_points.append((timestamp_str, price))
                    elif isinstance(entry, dict):
                        timestamp_str = str(
                            entry.get("datetime") or entry.get("timestamp") or ""
                        )
                        price = float(
                            entry.get("price")
                            or entry.get("close")
                            or entry.get("close_price")
                            or 0.0
                        )
                        if price > 0:
                            price_points.append((timestamp_str, price))
                except (ValueError, TypeError, KeyError, IndexError):
                    continue

            if len(price_points) < 3:
                return False

            # Sort by timestamp in ascending order (oldest to newest)
            est_tz = pytz.timezone("America/New_York")

            def parse_timestamp(ts_str: str) -> datetime:
                """Parse timestamp string, handling various formats"""
                ts_str = str(ts_str).strip()
                try:
                    if "T" in ts_str or "+" in ts_str or ts_str.endswith("Z"):
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        for fmt in [
                            "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d %H:%M:%S.%f",
                            "%Y-%m-%d",
                        ]:
                            try:
                                dt = datetime.strptime(ts_str, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            dt = datetime.fromisoformat(ts_str)

                    if dt.tzinfo is None:
                        dt = est_tz.localize(dt)
                    else:
                        dt = dt.astimezone(est_tz)

                    return dt
                except Exception:
                    return datetime.now(est_tz)

            try:
                price_points_sorted = sorted(
                    price_points, key=lambda x: parse_timestamp(x[0])
                )
            except Exception:
                price_points_sorted = price_points

            # Extract prices in chronological order
            prices = [float(price) for _, price in price_points_sorted]

            if len(prices) < 3:
                return False

            # Analyze trend: compare early vs recent prices
            n = len(prices)
            early_count = max(1, n // 3)
            recent_count = max(1, n // 3)

            early_prices = prices[:early_count]
            recent_prices = prices[-recent_count:]

            early_avg = sum(early_prices) / len(early_prices)
            recent_avg = sum(recent_prices) / len(recent_prices)

            # Check if recent average is lower than early average
            if recent_avg >= early_avg:
                return False

            # Calculate percentage change
            change_pct = ((recent_avg - early_avg) / early_avg) * 100

            # Also check recent momentum (last few points)
            if len(recent_prices) >= 2:
                recent_momentum = sum(
                    (recent_prices[i] - recent_prices[i - 1])
                    for i in range(1, len(recent_prices))
                ) / max(1, len(recent_prices) - 1)

                # Both overall trend and recent momentum should be negative
                return change_pct < -0.1 and recent_momentum < 0

            return change_pct < -0.1

        except Exception as e:
            logger.debug(f"Error checking downward price trend: {str(e)}")
            return False

    @classmethod
    def _is_upward_trend(cls, indicators: TechnicalIndicators) -> bool:
        """Determine if ticker is in upward trend using time-series price data and indicators"""
        trend_confirmations = 0

        # First, verify trend using actual price data from datetime_price (if available)
        price_trend_confirmed = False
        if indicators.datetime_price and len(indicators.datetime_price) >= 3:
            price_trend_confirmed = cls._check_price_trend_upward(
                indicators.datetime_price
            )
            if price_trend_confirmed:
                trend_confirmations += 1
            # If price data shows downward trend, reject immediately
            elif cls._check_price_trend_downward(indicators.datetime_price):
                return False

        # 1. EMA fast > EMA slow
        if indicators.ema_fast > indicators.ema_slow:
            trend_confirmations += 1

        # 2. MACD histogram positive
        _macd, _signal, hist = indicators.macd
        if hist > 0:
            trend_confirmations += 1

        # 3. Price above VWAP
        if indicators.close_price > 0 and indicators.vwap > 0:
            if indicators.close_price > indicators.vwap:
                trend_confirmations += 1

        # 4. RSI not overbought
        if indicators.rsi < 70:
            trend_confirmations += 1

        # 5. ADX indicates strong trend
        if indicators.adx > 25:
            trend_confirmations += 1

        # Require at least 3 confirmations, and if price data is available, it must confirm
        if price_trend_confirmed:
            return trend_confirmations >= 3
        else:
            # If no price data, require 4 confirmations for safety
            return trend_confirmations >= 4

    @classmethod
    def _is_downward_trend(cls, indicators: TechnicalIndicators) -> bool:
        """Determine if ticker is in downward trend using time-series price data and indicators"""
        trend_confirmations = 0

        # First, verify trend using actual price data from datetime_price (if available)
        price_trend_confirmed = False
        if indicators.datetime_price and len(indicators.datetime_price) >= 3:
            price_trend_confirmed = cls._check_price_trend_downward(
                indicators.datetime_price
            )
            if price_trend_confirmed:
                trend_confirmations += 1
            # If price data shows upward trend, reject immediately
            elif cls._check_price_trend_upward(indicators.datetime_price):
                return False

        # 1. EMA fast < EMA slow
        if indicators.ema_fast < indicators.ema_slow:
            trend_confirmations += 1

        # 2. MACD histogram negative
        _macd, _signal, hist = indicators.macd
        if hist < 0:
            trend_confirmations += 1

        # 3. Price below VWAP
        if indicators.close_price > 0 and indicators.vwap > 0:
            if indicators.close_price < indicators.vwap:
                trend_confirmations += 1

        # 4. RSI not oversold (for shorts, we want RSI high but not too high)
        if indicators.rsi > 30:
            trend_confirmations += 1

        # 5. ADX indicates strong trend
        if indicators.adx > 25:
            trend_confirmations += 1

        # Require at least 3 confirmations, and if price data is available, it must confirm
        if price_trend_confirmed:
            return trend_confirmations >= 3
        else:
            # If no price data, require 4 confirmations for safety
            return trend_confirmations >= 4

    @classmethod
    def _calculate_portfolio_allocation(
        cls, entry_score: float, indicators: TechnicalIndicators, is_golden: bool
    ) -> float:
        """
        Calculate portfolio allocation percentage based on entry score and indicators.

        Args:
            entry_score: Entry score (0-1)
            indicators: TechnicalIndicators object
            is_golden: Whether this is a golden entry

        Returns:
            Portfolio allocation percentage (0.0 to 1.0)
        """
        # Base allocation from entry score (0-5% max)
        base_allocation = entry_score * 0.05

        # Adjust based on additional factors
        adjustments = 0.0

        # Strong ADX (>30) increases confidence
        if indicators.adx > 30:
            adjustments += 0.01

        # High volume increases confidence
        if indicators.volume > 0 and indicators.volume_sma > 0:
            if indicators.volume > indicators.volume_sma * 1.5:
                adjustments += 0.01

        # RSI in sweet spot increases confidence
        if 40 <= indicators.rsi <= 60:
            adjustments += 0.005

        # MACD histogram strongly positive/negative
        macd, _signal, hist = indicators.macd
        if abs(hist) > abs(macd) * 0.5:
            adjustments += 0.005

        # Calculate final allocation (cap at 10% max per position, 15% for GOLDEN)
        final_allocation = min(0.10, base_allocation + adjustments)

        if is_golden and final_allocation > 0:
            final_allocation = min(0.15, final_allocation * 1.2)

        return final_allocation

    @classmethod
    async def exit_trade(
        cls, ticker: str, enter_price: float, action: str
    ) -> Dict[str, Any]:
        """
        Analyze if it's the right time to exit a trade.

        Args:
            ticker: Stock ticker symbol
            enter_price: Entry price of the trade
            action: Exit action - "BUY_TO_CLOSE" (for short) or "SELL_TO_CLOSE" (for long)

        Returns:
            Dict containing exit decision, reason, profit_pct, and other details
        """
        ticker = ticker.upper()
        action = action.upper().strip()

        # Convert exit action to original entry action
        if action == "BUY_TO_CLOSE":
            entry_action = "SELL_TO_OPEN"  # Short position
        elif action == "SELL_TO_CLOSE":
            entry_action = "BUY_TO_OPEN"  # Long position
        else:
            return {
                "exit_decision": False,
                "reason": f"Invalid exit_action: {action}. Must be BUY_TO_CLOSE or SELL_TO_CLOSE",
                "error": True,
            }

        # Validate enter_price
        if not isinstance(enter_price, (int, float)) or enter_price <= 0:
            return {
                "exit_decision": False,
                "reason": f"Invalid enter_price: {enter_price}. Must be a positive number",
                "error": True,
            }

        try:
            # Get current market data
            market_data = await MCPClient.get_market_data(ticker)
            if market_data is None:
                return {
                    "exit_decision": False,
                    "reason": f"No market data available for {ticker}",
                    "error": True,
                }

            technical_analysis = market_data.get("technical_analysis", {})
            if not technical_analysis:
                return {
                    "exit_decision": False,
                    "reason": f"No technical analysis available for {ticker}",
                    "error": True,
                }

            # Convert to TechnicalIndicators object
            indicators = dict_to_technical_indicators(technical_analysis)
            if indicators is None:
                return {
                    "exit_decision": False,
                    "reason": f"Failed to convert technical indicators for {ticker}",
                    "error": True,
                }

            current_price = indicators.close_price
            if not cls._is_valid_price(current_price):
                return {
                    "exit_decision": False,
                    "reason": f"Invalid current_price: {current_price}",
                    "error": True,
                }

            # Calculate profit/loss
            if entry_action == "BUY_TO_OPEN":
                profit_or_loss = current_price - enter_price
                profit_pct = (
                    ((current_price - enter_price) / enter_price) * 100
                    if enter_price > 0
                    else 0
                )
            else:  # SELL_TO_OPEN
                profit_or_loss = enter_price - current_price
                profit_pct = (
                    ((enter_price - current_price) / enter_price) * 100
                    if enter_price > 0
                    else 0
                )

            # Check exit conditions (simplified version - full implementation would track hold time, peak prices, etc.)
            should_exit, exit_reason = cls._should_exit_on_indicators(
                indicators, entry_action, enter_price, current_price, profit_pct
            )

            # Calculate stop loss (simplified)
            stop_loss_pct = 0.02  # 2% default
            if entry_action == "BUY_TO_OPEN":
                stop_loss_price = current_price * (1 - stop_loss_pct)
            else:
                stop_loss_price = current_price * (1 + stop_loss_pct)

            return {
                "exit_decision": should_exit,
                "reason": exit_reason,
                "profit_pct": round(profit_pct, 2),
                "profit_or_loss": round(profit_or_loss, 2),
                "current_price": round(current_price, 2),
                "enter_price": round(enter_price, 2),
                "stop_loss_price": round(stop_loss_price, 2),
                "stop_loss_pct": round(stop_loss_pct * 100, 1),
                "indicators": {
                    "rsi": round(indicators.rsi, 2),
                    "adx": round(indicators.adx, 2),
                    "macd_histogram": round(indicators.macd[2], 4),
                    "ema_fast": round(indicators.ema_fast, 2),
                    "ema_slow": round(indicators.ema_slow, 2),
                },
                "error": False,
            }

        except Exception as e:  # noqa: BLE001
            # Catch all exceptions to return proper error response
            logger.error(f"Error analyzing exit for {ticker}: {str(e)}", exc_info=True)
            return {
                "exit_decision": False,
                "reason": f"Error analyzing exit: {str(e)}",
                "error": True,
            }

    @classmethod
    def _is_valid_price(cls, price: float) -> bool:
        """Check if price is valid (positive, finite, not NaN)"""
        return price is not None and price > 0 and math.isfinite(price)

    @classmethod
    def _should_exit_on_indicators(
        cls,
        indicators: TechnicalIndicators,
        entry_action: str,
        enter_price: float,  # noqa: ARG002, F841
        current_price: float,  # noqa: ARG002, F841
        profit_pct: float,
    ) -> Tuple[bool, str]:
        """
        Check if technical indicators suggest exit.

        Args:
            indicators: Current technical indicators
            entry_action: BUY_TO_OPEN (long) or SELL_TO_OPEN (short)
            enter_price: Entry price
            current_price: Current price
            profit_pct: Current profit percentage

        Returns:
            Tuple of (should_exit: bool, reason: str)
        """
        exit_reasons = []
        _macd, _signal, hist = indicators.macd

        # Check stop loss (simplified - 2% for regular, 1.5% for penny stocks)
        is_penny = current_price < 5.0
        stop_loss_pct = 0.015 if is_penny else 0.02

        if entry_action == "BUY_TO_OPEN":
            # Long position exit conditions
            if profit_pct < -stop_loss_pct * 100:
                exit_reasons.append(f"Stop loss triggered: {profit_pct:.2f}% loss")

            # MACD reversal
            if hist < 0 and indicators.ema_fast < indicators.ema_slow:
                exit_reasons.append("MACD negative + EMA crossover reversed")

            # RSI overbought
            if indicators.rsi > 80:
                exit_reasons.append(f"RSI very overbought ({indicators.rsi:.1f})")
            elif indicators.rsi > 75 and hist < 0:
                exit_reasons.append(
                    f"RSI overbought ({indicators.rsi:.1f}) + MACD momentum loss"
                )

            # Price vs VWAP
            if indicators.close_price > 0 and indicators.vwap > 0:
                vwap_diff_pct = (
                    (indicators.close_price - indicators.vwap) / indicators.vwap
                ) * 100
                if vwap_diff_pct < -2.0:
                    exit_reasons.append(f"Price below VWAP ({vwap_diff_pct:.1f}%)")

            # ADX weak trend
            if indicators.adx < 15:
                exit_reasons.append(f"ADX weak trend ({indicators.adx:.1f})")

            # Profit targets
            if profit_pct >= 3.0:
                exit_reasons.append(f"Profit target reached ({profit_pct:.1f}%)")
            elif profit_pct >= 2.0 and indicators.adx < 20:
                exit_reasons.append(
                    f"Secured profit after trend weakening ({profit_pct:.1f}%)"
                )

        else:  # SELL_TO_OPEN
            # Short position exit conditions
            if profit_pct < -stop_loss_pct * 100:
                exit_reasons.append(f"Stop loss triggered: {profit_pct:.2f}% loss")

            # MACD reversal
            if hist > 0 and indicators.ema_fast > indicators.ema_slow:
                exit_reasons.append("MACD positive + EMA crossover reversed")

            # RSI oversold
            if indicators.rsi < 20:
                exit_reasons.append(f"RSI very oversold ({indicators.rsi:.1f})")
            elif indicators.rsi < 25 and hist > 0:
                exit_reasons.append(
                    f"RSI oversold ({indicators.rsi:.1f}) + MACD momentum loss"
                )

            # Price vs VWAP
            if indicators.close_price > 0 and indicators.vwap > 0:
                vwap_diff_pct = (
                    (indicators.close_price - indicators.vwap) / indicators.vwap
                ) * 100
                if vwap_diff_pct > 3.0:
                    exit_reasons.append(f"Price above VWAP ({vwap_diff_pct:.1f}%)")

            # ADX weak trend
            if indicators.adx < 15:
                exit_reasons.append(f"ADX weak trend ({indicators.adx:.1f})")

            # Profit targets
            if profit_pct >= 3.0:
                exit_reasons.append(f"Profit target reached ({profit_pct:.1f}%)")
            elif profit_pct >= 2.0 and indicators.adx < 20:
                exit_reasons.append(
                    f"Secured profit after trend weakening ({profit_pct:.1f}%)"
                )

        if exit_reasons:
            return True, "; ".join(exit_reasons)

        return False, "No exit conditions met"
