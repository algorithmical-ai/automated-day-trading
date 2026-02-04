"""
Market Direction Filter
Filters trading signals based on QQQ market trend to prevent losses
Uses HYBRID approach: 70% weight on 2-3 day trend + 30% on real-time trend
"""

from datetime import datetime, timezone
from typing import Tuple, Dict, Any

from app.src.common.loguru_logger import logger
from app.src.common.alpaca import AlpacaClient


class MarketDirectionFilter:
    """
    Filters trading signals based on QQQ market trend using HYBRID approach

    HYBRID STRATEGY:
    - Primary Filter (70% weight): 2-3 day historical trend using daily data
    - Secondary Filter (30% weight): Real-time intraday trend using recent bars
    - Blocks LONG positions when overall market is trending down
    - Blocks SHORT positions when overall market is trending up
    """

    # Cache trend data to avoid excessive API calls
    _daily_trend_cache: Dict[str, Tuple[str, datetime]] = {}
    _intraday_trend_cache: Dict[str, Tuple[str, datetime]] = {}
    _cache_ttl_minutes = 5  # Cache trend for 5 minutes

    # Hybrid decision weights
    _daily_trend_weight = 0.7  # 70% weight on 2-3 day trend
    _intraday_trend_weight = 0.3  # 30% weight on real-time trend

    @classmethod
    async def get_hybrid_qqq_trend(cls) -> Tuple[str, Dict[str, Any]]:
        """
        Get hybrid QQQ market trend combining daily and intraday analysis

        Returns:
            Tuple[str, Dict[str, Any]]: (final_trend_direction, trend_details)
            final_trend_direction: "UP", "DOWN", or "SIDEWAYS"
            trend_details: Dictionary with both daily and intraday trend metrics
        """
        try:
            # Get both trend analyses
            daily_trend, daily_details = await cls._get_daily_trend()
            intraday_trend, intraday_details = await cls._get_intraday_trend()

            # Combine trends using weighted decision
            final_trend = cls._combine_trends(daily_trend, intraday_trend)

            # Combine details for logging
            combined_details = {
                "final_trend": final_trend,
                "daily_trend": daily_trend,
                "intraday_trend": intraday_trend,
                "daily_weight": cls._daily_trend_weight,
                "intraday_weight": cls._intraday_trend_weight,
                "daily_details": daily_details,
                "intraday_details": intraday_details,
                "decision_logic": cls._get_decision_logic(
                    daily_trend, intraday_trend, final_trend
                ),
            }

            logger.info(
                f"Hybrid QQQ trend: {final_trend} (Daily: {daily_trend}, Intraday: {intraday_trend})"
            )
            return final_trend, combined_details

        except Exception as e:
            logger.error(f"Error calculating hybrid QQQ trend: {str(e)}")
            return "SIDEWAYS", {"error": str(e)}

    @classmethod
    async def _get_daily_trend(cls) -> Tuple[str, Dict[str, Any]]:
        """Get 2-3 day trend using daily closing prices"""
        cache_key = "daily_trend"
        now = datetime.now(timezone.utc)

        # Check cache
        if cache_key in cls._daily_trend_cache:
            cached_trend, cached_time = cls._daily_trend_cache[cache_key]
            age_minutes = (now - cached_time).total_seconds() / 60
            if age_minutes < cls._cache_ttl_minutes:
                logger.debug(f"Using cached daily trend: {cached_trend}")
                return cached_trend, {"cached": True, "age_minutes": age_minutes}

        try:
            # Fetch 3 days of daily data (1-day bars for 3 days)
            bars_data = await AlpacaClient.get_market_data("QQQ", limit=3)

            if not bars_data or "bars" not in bars_data:
                logger.warning("Failed to fetch QQQ daily data")
                return "SIDEWAYS", {"error": "Failed to fetch QQQ daily data"}

            bars = bars_data["bars"].get("QQQ", [])
            if len(bars) < 2:
                logger.warning(f"Insufficient QQQ daily bars: {len(bars)}")
                return "SIDEWAYS", {"error": f"Insufficient daily bars: {len(bars)}"}

            # Calculate daily trend
            trend = cls._calculate_daily_trend_from_bars(bars)

            # Cache result
            cls._daily_trend_cache[cache_key] = (trend, now)

            logger.debug(f"QQQ daily trend: {trend}")
            return trend, {"bars_analyzed": len(bars)}

        except Exception as e:
            logger.error(f"Error calculating daily trend: {str(e)}")
            return "SIDEWAYS", {"error": str(e)}

    @classmethod
    async def _get_intraday_trend(cls) -> Tuple[str, Dict[str, Any]]:
        """Get real-time intraday trend using recent bars"""
        cache_key = "intraday_trend"
        now = datetime.now(timezone.utc)

        # Check cache
        if cache_key in cls._intraday_trend_cache:
            cached_trend, cached_time = cls._intraday_trend_cache[cache_key]
            age_minutes = (now - cached_time).total_seconds() / 60
            if age_minutes < cls._cache_ttl_minutes:
                logger.debug(f"Using cached intraday trend: {cached_trend}")
                return cached_trend, {"cached": True, "age_minutes": age_minutes}

        try:
            # Fetch intraday data (last 50 bars)
            bars_data = await AlpacaClient.get_market_data("QQQ", limit=50)

            if not bars_data or "bars" not in bars_data:
                logger.warning("Failed to fetch QQQ intraday data")
                return "SIDEWAYS", {"error": "Failed to fetch QQQ intraday data"}

            bars = bars_data["bars"].get("QQQ", [])
            if len(bars) < 10:
                logger.warning(f"Insufficient QQQ intraday bars: {len(bars)}")
                return "SIDEWAYS", {"error": f"Insufficient intraday bars: {len(bars)}"}

            # Calculate intraday trend
            trend = cls._calculate_intraday_trend_from_bars(bars)

            # Cache result
            cls._intraday_trend_cache[cache_key] = (trend, now)

            logger.debug(f"QQQ intraday trend: {trend}")
            return trend, {"bars_analyzed": len(bars)}

        except Exception as e:
            logger.error(f"Error calculating intraday trend: {str(e)}")
            return "SIDEWAYS", {"error": str(e)}

    @classmethod
    def _calculate_daily_trend_from_bars(cls, bars: list) -> str:
        """
        Calculate 2-3 day trend from daily price bars

        Args:
            bars: List of daily price bars with close prices

        Returns:
            str: "UP", "DOWN", or "SIDEWAYS"
        """
        if len(bars) < 2:
            return "SIDEWAYS"

        # Extract close prices from daily bars
        closes = []
        for bar in bars:
            close_price = bar.get("c")
            if close_price is not None:
                closes.append(float(close_price))

        if len(closes) < 2:
            return "SIDEWAYS"

        # Calculate overall change from oldest to newest
        oldest_price = closes[0]
        newest_price = closes[-1]

        if oldest_price == 0:
            return "SIDEWAYS"

        percent_change = ((newest_price - oldest_price) / oldest_price) * 100

        # For daily trend, use more conservative thresholds
        if percent_change > 1.0:  # 1%+ upward move
            return "UP"
        elif percent_change < -1.0:  # 1%+ downward move
            return "DOWN"
        else:
            return "SIDEWAYS"

    @classmethod
    def _calculate_intraday_trend_from_bars(cls, bars: list) -> str:
        """
        Calculate intraday trend from recent price bars

        Args:
            bars: List of intraday price bars with close prices

        Returns:
            str: "UP", "DOWN", or "SIDEWAYS"
        """
        if len(bars) < 10:
            return "SIDEWAYS"

        # Extract close prices from intraday bars
        closes = []
        for bar in bars:
            close_price = bar.get("c")
            if close_price is not None:
                closes.append(float(close_price))

        if len(closes) < 10:
            return "SIDEWAYS"

        # Multiple timeframe analysis for intraday
        short_term_change = cls._calculate_percent_change(closes[-10:], closes[-5:])
        medium_term_change = (
            cls._calculate_percent_change(closes[-20:], closes[-10:])
            if len(closes) >= 20
            else 0
        )
        recent_momentum = (
            cls._calculate_percent_change(closes[-4:], closes[-1:])
            if len(closes) >= 4
            else 0
        )

        # Weighted score for intraday
        trend_score = (
            (recent_momentum * 0.5)
            + (short_term_change * 0.3)
            + (medium_term_change * 0.2)
        )

        # More sensitive thresholds for intraday
        if trend_score > 1.0:
            return "UP"
        elif trend_score < -1.0:
            return "DOWN"
        else:
            return "SIDEWAYS"

    @classmethod
    def _calculate_percent_change(
        cls, earlier_prices: list, later_prices: list
    ) -> float:
        """
        Calculate percentage change between two price periods

        Args:
            earlier_prices: List of earlier prices
            later_prices: List of later prices

        Returns:
            float: Percentage change (later - earlier) / earlier * 100
        """
        if not earlier_prices or not later_prices:
            return 0.0

        earlier_avg = sum(earlier_prices) / len(earlier_prices)
        later_avg = sum(later_prices) / len(later_prices)

        if earlier_avg == 0:
            return 0.0

        return ((later_avg - earlier_avg) / earlier_avg) * 100

    @classmethod
    def _combine_trends(cls, daily_trend: str, intraday_trend: str) -> str:
        """
        Combine daily and intraday trends using weighted decision

        Args:
            daily_trend: Daily trend ("UP", "DOWN", "SIDEWAYS")
            intraday_trend: Intraday trend ("UP", "DOWN", "SIDEWAYS")

        Returns:
            str: Final combined trend ("UP", "DOWN", "SIDEWAYS")
        """
        # Convert trends to numeric scores
        trend_scores = {"UP": 1, "SIDEWAYS": 0, "DOWN": -1}

        daily_score = trend_scores.get(daily_trend, 0)
        intraday_score = trend_scores.get(intraday_trend, 0)

        # Apply weights
        final_score = (daily_score * cls._daily_trend_weight) + (
            intraday_score * cls._intraday_trend_weight
        )

        # Convert back to trend
        if final_score > 0.3:  # Strong positive
            return "UP"
        elif final_score < -0.3:  # Strong negative
            return "DOWN"
        else:
            return "SIDEWAYS"

    @classmethod
    def _get_decision_logic(
        cls, daily_trend: str, intraday_trend: str, final_trend: str
    ) -> str:
        """
        Get explanation of the decision logic

        Args:
            daily_trend: Daily trend result
            intraday_trend: Intraday trend result
            final_trend: Final combined trend

        Returns:
            str: Explanation of the decision
        """
        if daily_trend == "DOWN" and intraday_trend == "DOWN":
            return "Both daily and intraday trends are DOWN - strong sell signal"
        elif daily_trend == "UP" and intraday_trend == "UP":
            return "Both daily and intraday trends are UP - strong buy signal"
        elif daily_trend == "DOWN" and final_trend == "DOWN":
            return "Daily trend DOWN outweighs intraday - net sell signal"
        elif daily_trend == "UP" and final_trend == "UP":
            return "Daily trend UP outweighs intraday - net buy signal"
        elif intraday_trend == "SIDEWAYS" and daily_trend != "SIDEWAYS":
            return f"Intraday neutral, following daily trend ({daily_trend})"
        elif daily_trend == "SIDEWAYS" and intraday_trend != "SIDEWAYS":
            return f"Daily neutral, following intraday trend ({intraday_trend})"
        else:
            return "Mixed signals, defaulting to SIDEWAYS"

    @classmethod
    async def should_allow_trade(
        cls, action: str, indicator_name: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if a trade should be allowed based on hybrid market direction

        Args:
            action: Trading action ("BUY_TO_OPEN" or "SELL_TO_OPEN")
            indicator_name: Name of the trading indicator

        Returns:
            Tuple[bool, str, Dict[str, Any]]: (should_allow, reason, trend_details)
        """
        # Get hybrid QQQ trend
        qqq_trend, trend_details = await cls.get_hybrid_qqq_trend()

        # Apply filtering logic
        if action == "BUY_TO_OPEN" and qqq_trend == "DOWN":
            reason = f"QQQ hybrid trend is DOWN ({qqq_trend}) - blocking LONG {indicator_name} trade to avoid losses"
            logger.warning(reason)
            return False, reason, trend_details

        elif action == "SELL_TO_OPEN" and qqq_trend == "UP":
            reason = f"QQQ hybrid trend is UP ({qqq_trend}) - blocking SHORT {indicator_name} trade to avoid losses"
            logger.warning(reason)
            return False, reason, trend_details

        # Trade is allowed
        reason = f"QQQ hybrid trend ({qqq_trend}) allows {action} for {indicator_name}"
        logger.info(reason)
        return True, reason, trend_details

    @classmethod
    def clear_cache(cls):
        """Clear both trend caches"""
        cls._daily_trend_cache.clear()
        cls._intraday_trend_cache.clear()
        logger.info("QQQ trend caches cleared")
