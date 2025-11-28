"""
Volatility Utilities for Trading Indicators

Provides volatility-aware calculations for stop losses, position sizing, and entry/exit decisions
"""

from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

from app.src.common.loguru_logger import logger


class VolatilityUtils:
    """Utility class for volatility-based trading calculations"""

    # Price thresholds for different stock categories
    PENNY_STOCK_THRESHOLD = 3.0  # Stocks below $3
    LOW_PRICE_THRESHOLD = 5.0  # Stocks below $5
    MID_PRICE_THRESHOLD = 10.0  # Stocks below $10

    # ATR-based trailing stop multipliers
    ATR_TRAILING_STOP_MULTIPLIER = 2.5  # Use 2.5x ATR for trailing stop

    # Minimum holding periods (seconds) before trailing stop activates
    PENNY_STOCK_MIN_HOLD_SECONDS = 180  # 3 minutes for penny stocks
    LOW_PRICE_MIN_HOLD_SECONDS = 120  # 2 minutes for low-price stocks
    DEFAULT_MIN_HOLD_SECONDS = 60  # 1 minute for normal stocks

    # Maximum ATR percentages for entry (volatility filter)
    PENNY_STOCK_MAX_ATR_PERCENT = 5.0
    LOW_PRICE_MAX_ATR_PERCENT = 4.0
    MID_PRICE_MAX_ATR_PERCENT = 3.0

    @classmethod
    def calculate_atr_percent(cls, atr: float, price: float) -> float:
        """Calculate ATR as a percentage of price"""
        if price <= 0 or atr <= 0:
            return 0.0
        return (atr / price) * 100

    @classmethod
    def calculate_volatility_adjusted_trailing_stop(
        cls,
        enter_price: float,
        current_price: float,
        atr: float,
        default_trailing_stop: float = 2.5,
    ) -> float:
        """
        Calculate trailing stop based on ATR instead of fixed percentage.

        For volatile stocks, use 2-3x ATR as trailing stop distance.
        This gives volatile stocks more room to breathe while keeping
        tighter stops on less volatile stocks.

        Args:
            enter_price: Original entry price
            current_price: Current market price
            atr: Average True Range value
            default_trailing_stop: Default trailing stop percentage

        Returns:
            Trailing stop percentage adjusted for volatility
        """
        if current_price <= 0 or atr <= 0:
            return default_trailing_stop

        # Calculate ATR as percentage of current price
        atr_percent = cls.calculate_atr_percent(atr, current_price)

        # Use 2.5x ATR for trailing stop
        trailing_stop = atr_percent * cls.ATR_TRAILING_STOP_MULTIPLIER

        # Apply bounds based on price category
        if enter_price < cls.PENNY_STOCK_THRESHOLD:
            # Penny stocks: wider bounds (3% to 8%)
            trailing_stop = max(3.0, min(8.0, trailing_stop))
        elif enter_price < cls.LOW_PRICE_THRESHOLD:
            # Low-price stocks: moderate bounds (2.5% to 6%)
            trailing_stop = max(2.5, min(6.0, trailing_stop))
        elif enter_price < cls.MID_PRICE_THRESHOLD:
            # Mid-price stocks: tighter bounds (2% to 5%)
            trailing_stop = max(2.0, min(5.0, trailing_stop))
        else:
            # Higher-price stocks: standard bounds (1.5% to 4%)
            trailing_stop = max(1.5, min(4.0, trailing_stop))

        logger.debug(
            f"Volatility-adjusted trailing stop: {trailing_stop:.2f}% "
            f"(ATR: {atr:.4f}, ATR%: {atr_percent:.2f}%, price: ${current_price:.2f})"
        )
        return trailing_stop

    @classmethod
    def calculate_volatility_adjusted_stop_loss(
        cls, enter_price: float, atr: float, default_stop_loss: float = -2.5
    ) -> float:
        """
        Calculate dynamic stop loss based on ATR.

        Args:
            enter_price: Entry price
            atr: Average True Range
            default_stop_loss: Default stop loss percentage (negative)

        Returns:
            Stop loss percentage (negative value)
        """
        if enter_price <= 0 or atr <= 0:
            return default_stop_loss

        atr_percent = cls.calculate_atr_percent(atr, enter_price)

        # Base stop loss on 3x ATR
        dynamic_stop = -(atr_percent * 3.0)

        # Apply bounds based on price category
        if enter_price < cls.PENNY_STOCK_THRESHOLD:
            # Penny stocks: wider stop loss (-3.5% to -8%)
            dynamic_stop = max(-8.0, min(-3.5, dynamic_stop))
        elif enter_price < cls.LOW_PRICE_THRESHOLD:
            # Low-price stocks: moderate stop loss (-3% to -6%)
            dynamic_stop = max(-6.0, min(-3.0, dynamic_stop))
        else:
            # Normal stocks: standard stop loss (-2% to -4%)
            dynamic_stop = max(-4.0, min(-2.0, dynamic_stop))

        logger.debug(
            f"Volatility-adjusted stop loss: {dynamic_stop:.2f}% "
            f"(ATR%: {atr_percent:.2f}%, price: ${enter_price:.2f})"
        )
        return dynamic_stop

    @classmethod
    def passes_volatility_filter(
        cls, enter_price: float, atr: float
    ) -> Tuple[bool, str]:
        """
        Check if volatility is within acceptable range for entry.
        Reject entries when volatility is too high (likely near reversal).

        Args:
            enter_price: Expected entry price
            atr: Average True Range

        Returns:
            Tuple of (passes_filter, reason)
        """
        if enter_price <= 0:
            return False, "Invalid entry price"

        if atr <= 0:
            return True, "No ATR data available"

        atr_percent = cls.calculate_atr_percent(atr, enter_price)

        # Check against thresholds based on price category
        if enter_price < cls.PENNY_STOCK_THRESHOLD:
            max_atr = cls.PENNY_STOCK_MAX_ATR_PERCENT
            if atr_percent > max_atr:
                return False, (
                    f"ATR too high for penny stock: {atr_percent:.2f}% > {max_atr}% "
                    f"(price: ${enter_price:.2f})"
                )
        elif enter_price < cls.LOW_PRICE_THRESHOLD:
            max_atr = cls.LOW_PRICE_MAX_ATR_PERCENT
            if atr_percent > max_atr:
                return False, (
                    f"ATR too high for low-price stock: {atr_percent:.2f}% > {max_atr}% "
                    f"(price: ${enter_price:.2f})"
                )
        elif enter_price < cls.MID_PRICE_THRESHOLD:
            max_atr = cls.MID_PRICE_MAX_ATR_PERCENT
            if atr_percent > max_atr:
                return False, (
                    f"ATR too high: {atr_percent:.2f}% > {max_atr}% "
                    f"(price: ${enter_price:.2f})"
                )

        return True, f"Volatility acceptable (ATR: {atr_percent:.2f}%)"

    @classmethod
    def should_apply_trailing_stop(
        cls, enter_price: float, created_at: Optional[str], profit_percent: float
    ) -> Tuple[bool, str]:
        """
        Determine if trailing stop should be active.
        For penny stocks, require minimum time elapsed before trailing stop activates.

        Args:
            enter_price: Entry price
            created_at: Trade creation timestamp (ISO format)
            profit_percent: Current profit percentage

        Returns:
            Tuple of (should_apply, reason)
        """
        if enter_price <= 0:
            return True, "Invalid entry price"

        # Determine minimum hold period based on price
        if enter_price < cls.PENNY_STOCK_THRESHOLD:
            min_hold_seconds = cls.PENNY_STOCK_MIN_HOLD_SECONDS
        elif enter_price < cls.LOW_PRICE_THRESHOLD:
            min_hold_seconds = cls.LOW_PRICE_MIN_HOLD_SECONDS
        else:
            min_hold_seconds = cls.DEFAULT_MIN_HOLD_SECONDS

        if not created_at:
            return True, "No creation timestamp"

        try:
            enter_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if enter_time.tzinfo is None:
                enter_time = enter_time.replace(tzinfo=timezone.utc)

            elapsed_seconds = (datetime.now(timezone.utc) - enter_time).total_seconds()

            if elapsed_seconds < min_hold_seconds:
                return False, (
                    f"Cooling period active: {elapsed_seconds:.0f}s < {min_hold_seconds}s "
                    f"(profit: {profit_percent:.2f}%)"
                )

            return True, f"Cooling period complete ({elapsed_seconds:.0f}s elapsed)"
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Error parsing created_at timestamp: {e}")
            return True, "Could not parse timestamp"

    @classmethod
    def calculate_position_size_multiplier(
        cls, enter_price: float, atr: float
    ) -> float:
        """
        Calculate position size multiplier based on volatility.
        More volatile stocks get smaller positions.

        Args:
            enter_price: Entry price
            atr: Average True Range

        Returns:
            Position size multiplier (0.25 to 1.0)
        """
        if enter_price <= 0:
            return 1.0

        if atr <= 0:
            # No ATR data - use price-based defaults
            if enter_price < cls.PENNY_STOCK_THRESHOLD:
                return 0.5  # Half size for penny stocks without ATR data
            return 1.0

        atr_percent = cls.calculate_atr_percent(atr, enter_price)

        # Scale position size inversely with volatility
        # Base case: 2% ATR = 1.0 multiplier
        if atr_percent <= 2.0:
            multiplier = 1.0
        elif atr_percent <= 3.0:
            multiplier = 0.75
        elif atr_percent <= 4.0:
            multiplier = 0.5
        elif atr_percent <= 5.0:
            multiplier = 0.35
        else:
            multiplier = 0.25  # Very small position for extremely volatile stocks

        # Additional reduction for penny stocks
        if enter_price < cls.PENNY_STOCK_THRESHOLD:
            multiplier *= 0.75  # 25% additional reduction

        logger.debug(
            f"Position size multiplier: {multiplier:.2f} "
            f"(ATR%: {atr_percent:.2f}%, price: ${enter_price:.2f})"
        )
        return multiplier

    @classmethod
    def is_likely_mean_reverting(
        cls,
        current_price: float,
        bollinger_upper: float,
        bollinger_lower: float,
        momentum_score: float,
    ) -> Tuple[bool, str]:
        """
        Check if the stock is likely to mean-revert soon based on Bollinger Bands.

        Args:
            current_price: Current market price
            bollinger_upper: Upper Bollinger Band
            bollinger_lower: Lower Bollinger Band
            momentum_score: Current momentum score (positive for long, negative for short)

        Returns:
            Tuple of (is_reverting, reason)
        """
        if bollinger_upper <= 0 or bollinger_lower <= 0 or current_price <= 0:
            return False, "No Bollinger data"

        band_width = bollinger_upper - bollinger_lower
        if band_width <= 0:
            return False, "Invalid Bollinger band width"

        # Calculate position within Bollinger Bands (0 = lower, 1 = upper)
        position_in_band = (current_price - bollinger_lower) / band_width

        # For LONG entries, reject if price is already at upper band (>90%)
        if momentum_score > 0 and position_in_band > 0.90:
            return True, (
                f"Price at upper Bollinger ({position_in_band:.0%}), "
                "likely to mean-revert down"
            )

        # For SHORT entries, reject if price is already at lower band (<10%)
        if momentum_score < 0 and position_in_band < 0.10:
            return True, (
                f"Price at lower Bollinger ({position_in_band:.0%}), "
                "likely to mean-revert up"
            )

        # Also check for extreme positions (>95% or <5%)
        if position_in_band > 0.95:
            return True, f"Price at extreme upper Bollinger ({position_in_band:.0%})"

        if position_in_band < 0.05:
            return True, f"Price at extreme lower Bollinger ({position_in_band:.0%})"

        return False, f"Price within normal Bollinger range ({position_in_band:.0%})"

    @classmethod
    def is_golden_ticker_for_penny_stock(
        cls,
        momentum_score: float,
        market_data: Dict[str, Any],
        exceptional_momentum_threshold: float = 5.0,
    ) -> Tuple[bool, str]:
        """
        More stringent golden ticker criteria for penny stocks.

        Args:
            momentum_score: Current momentum score
            market_data: Market data dictionary
            exceptional_momentum_threshold: Normal threshold for golden

        Returns:
            Tuple of (is_golden, reason)
        """
        technical_analysis = market_data.get("technical_analysis", {})
        current_price = technical_analysis.get("close_price", 0.0)

        # For penny stocks (< $3), require MUCH higher thresholds
        if current_price < cls.PENNY_STOCK_THRESHOLD:
            # Require exceptional momentum AND volume confirmation
            volume = technical_analysis.get("volume", 0)
            volume_sma = technical_analysis.get("volume_sma", 1)
            volume_ratio = volume / volume_sma if volume_sma > 0 else 0

            adx = technical_analysis.get("adx", 0)

            # Need 3x average volume AND >8% momentum for penny stock golden
            if abs(momentum_score) >= 8.0 and volume_ratio >= 3.0 and adx >= 30:
                return True, (
                    f"Penny stock golden: momentum={momentum_score:.2f}%, "
                    f"volume={volume_ratio:.1f}x, ADX={adx:.1f}"
                )

            # Explain why not golden
            reasons = []
            if abs(momentum_score) < 8.0:
                reasons.append(f"momentum {abs(momentum_score):.2f}% < 8%")
            if volume_ratio < 3.0:
                reasons.append(f"volume {volume_ratio:.1f}x < 3x")
            if adx < 30:
                reasons.append(f"ADX {adx:.1f} < 30")

            return False, f"Penny stock not golden: {', '.join(reasons)}"

        # For non-penny stocks, use standard threshold
        if abs(momentum_score) >= exceptional_momentum_threshold:
            return True, f"Exceptional momentum: {momentum_score:.2f}%"

        # Check for strong ADX + extreme RSI conditions
        adx = technical_analysis.get("adx", 0)
        rsi = technical_analysis.get("rsi", 50.0)

        if adx and adx > 40:
            is_long = momentum_score > 0
            is_short = momentum_score < 0

            if is_long and rsi < 25:  # Very oversold
                return (
                    True,
                    f"Strong trend (ADX={adx:.1f}) + very oversold (RSI={rsi:.1f})",
                )
            if is_short and rsi > 75:  # Very overbought
                return (
                    True,
                    f"Strong trend (ADX={adx:.1f}) + very overbought (RSI={rsi:.1f})",
                )

        return False, "Does not meet golden criteria"

    @classmethod
    def get_price_category(cls, price: float) -> str:
        """Get the price category for a stock"""
        if price < cls.PENNY_STOCK_THRESHOLD:
            return "penny_stock"
        elif price < cls.LOW_PRICE_THRESHOLD:
            return "low_price"
        elif price < cls.MID_PRICE_THRESHOLD:
            return "mid_price"
        else:
            return "normal"

    @classmethod
    def get_recommended_settings(cls, enter_price: float, atr: float) -> Dict[str, Any]:
        """
        Get recommended trading settings based on price and volatility.

        Args:
            enter_price: Entry price
            atr: Average True Range

        Returns:
            Dict with recommended settings
        """
        category = cls.get_price_category(enter_price)
        atr_percent = cls.calculate_atr_percent(atr, enter_price)

        return {
            "price_category": category,
            "atr_percent": atr_percent,
            "recommended_trailing_stop": cls.calculate_volatility_adjusted_trailing_stop(
                enter_price, enter_price, atr
            ),
            "recommended_stop_loss": cls.calculate_volatility_adjusted_stop_loss(
                enter_price, atr
            ),
            "position_size_multiplier": cls.calculate_position_size_multiplier(
                enter_price, atr
            ),
            "min_hold_seconds": (
                cls.PENNY_STOCK_MIN_HOLD_SECONDS
                if category == "penny_stock"
                else (
                    cls.LOW_PRICE_MIN_HOLD_SECONDS
                    if category == "low_price"
                    else cls.DEFAULT_MIN_HOLD_SECONDS
                )
            ),
        }
