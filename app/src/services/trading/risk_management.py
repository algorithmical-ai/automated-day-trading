"""
Risk Management Utilities

Provides standardized risk management functions for all trading indicators:
- Stop loss calculation (2.0x ATR with bounds)
- Position sizing ($2000 base, adjusted for volatility/risk, min $500)
- Entry filtering (momentum, ADX, volume, price)
- Pricing logic (bid/ask selection for long/short entry/exit)

Requirements: 11.1, 11.2, 11.3, 18.1, 18.2, 18.3, 18.4, 18.5
"""

from typing import Dict, Any, Tuple, Optional

from app.src.common.loguru_logger import logger
from app.src.services.trading.trading_config import (
    ATR_STOP_LOSS_MULTIPLIER,
    PENNY_STOCK_STOP_LOSS_MIN,
    PENNY_STOCK_STOP_LOSS_MAX,
    STANDARD_STOCK_STOP_LOSS_MIN,
    STANDARD_STOCK_STOP_LOSS_MAX,
)


class RiskManagement:
    """Standardized risk management utilities for trading indicators"""

    # Price thresholds
    PENNY_STOCK_THRESHOLD = 5.0  # Stocks below $5 are penny stocks

    # Position sizing
    BASE_POSITION_SIZE = 2000.0  # Base position size in dollars
    MIN_POSITION_SIZE = 500.0  # Minimum position size in dollars

    # Entry filtering thresholds
    MIN_MOMENTUM_THRESHOLD = 1.5  # Minimum momentum percentage
    MAX_MOMENTUM_THRESHOLD = 15.0  # Maximum momentum percentage
    MIN_ADX = 20.0  # Minimum ADX for trend strength
    MIN_VOLUME_MULTIPLIER = 1.5  # Minimum volume vs SMA
    MIN_PRICE = 0.10  # Minimum stock price

    @classmethod
    def calculate_stop_loss(
        cls, entry_price: float, atr: float, is_penny_stock: Optional[bool] = None
    ) -> float:
        """
        Calculate dynamic stop loss based on 2.0x ATR with bounds.

        Property 43: For any ticker, the calculated dynamic stop loss should equal
        2.0x ATR, capped between -4% and -8% for penny stocks or -4% and -6% for
        standard stocks.

        Args:
            entry_price: Entry price of the trade
            atr: Average True Range value
            is_penny_stock: Whether the stock is a penny stock (< $5).
                          If None, determined from entry_price.

        Returns:
            Stop loss percentage (negative value, e.g., -5.0 for -5%)

        Validates: Requirements 11.1, 19.1, 19.3
        """
        if entry_price <= 0:
            logger.warning(f"Invalid entry price: {entry_price}")
            return -4.0  # Default to -4%

        if atr is None or atr <= 0:
            logger.warning(f"Invalid ATR: {atr}, using default stop loss")
            return -4.0  # Default to -4%

        # Determine if penny stock
        if is_penny_stock is None:
            is_penny_stock = entry_price < cls.PENNY_STOCK_THRESHOLD

        # Calculate ATR as percentage of entry price
        atr_percent = (atr / entry_price) * 100.0

        # Calculate stop loss as 2.0x ATR (from trading_config.py)
        stop_loss = -(atr_percent * ATR_STOP_LOSS_MULTIPLIER)

        # Apply bounds based on stock category
        if is_penny_stock:
            # Penny stocks: -8% to -4%
            stop_loss = max(PENNY_STOCK_STOP_LOSS_MIN, min(PENNY_STOCK_STOP_LOSS_MAX, stop_loss))
        else:
            # Standard stocks: -6% to -4%
            stop_loss = max(STANDARD_STOCK_STOP_LOSS_MIN, min(STANDARD_STOCK_STOP_LOSS_MAX, stop_loss))

        logger.debug(
            f"Stop loss calculated: {stop_loss:.2f}% "
            f"(entry: ${entry_price:.2f}, ATR: {atr:.4f}, "
            f"ATR%: {atr_percent:.2f}%, penny_stock: {is_penny_stock})"
        )

        return stop_loss

    @classmethod
    def calculate_position_size(
        cls,
        entry_price: float,
        atr: float,
        is_penny_stock: Optional[bool] = None,
    ) -> float:
        """
        Calculate position size starting at $2000 base, reduced for high volatility
        and high-risk penny stocks, with minimum of $500.

        Property 44: For any ticker, the calculated position size should start at
        $2000 and be reduced for high-volatility stocks and high-risk penny stocks,
        with a minimum of $500.

        Args:
            entry_price: Entry price of the trade
            atr: Average True Range value
            is_penny_stock: Whether the stock is a penny stock (< $5).
                          If None, determined from entry_price.

        Returns:
            Position size in dollars

        Validates: Requirements 11.2
        """
        if entry_price <= 0:
            logger.warning(f"Invalid entry price: {entry_price}")
            return cls.MIN_POSITION_SIZE

        # Determine if penny stock
        if is_penny_stock is None:
            is_penny_stock = entry_price < cls.PENNY_STOCK_THRESHOLD

        # Start with base position size
        position_size = cls.BASE_POSITION_SIZE

        # Reduce for high volatility
        if atr is not None and atr > 0:
            atr_percent = (atr / entry_price) * 100.0

            # Scale down position size based on volatility
            if atr_percent > 5.0:
                # Very high volatility: reduce to 25%
                position_size *= 0.25
            elif atr_percent > 4.0:
                # High volatility: reduce to 35%
                position_size *= 0.35
            elif atr_percent > 3.0:
                # Moderate-high volatility: reduce to 50%
                position_size *= 0.50
            elif atr_percent > 2.5:
                # Moderate volatility: reduce to 75%
                position_size *= 0.75
            # else: normal volatility, keep full size

        # Additional reduction for penny stocks (high risk)
        if is_penny_stock:
            position_size *= 0.75  # 25% additional reduction

        # Ensure minimum position size
        position_size = max(cls.MIN_POSITION_SIZE, position_size)

        atr_display = f"{atr:.4f}" if atr is not None else "N/A"
        logger.debug(
            f"Position size calculated: ${position_size:.2f} "
            f"(entry: ${entry_price:.2f}, ATR: {atr_display}, "
            f"penny_stock: {is_penny_stock})"
        )

        return position_size

    @classmethod
    def passes_entry_filters(
        cls,
        momentum: float,
        adx: float,
        volume: float,
        volume_sma: float,
        price: float,
    ) -> Tuple[bool, str]:
        """
        Check if ticker passes entry filtering criteria.

        Property 45: For any ticker evaluated for entry, the trading indicator
        should filter out tickers with momentum <1.5% or >15%, ADX <20,
        volume ≤1.5x SMA, or price <$0.10.

        Args:
            momentum: Momentum percentage (absolute value)
            adx: Average Directional Index
            volume: Current volume
            volume_sma: Volume simple moving average
            price: Current stock price

        Returns:
            Tuple of (passes, reason) where passes is True if all filters pass

        Validates: Requirements 11.3
        """
        # Check momentum bounds
        abs_momentum = abs(momentum)
        if abs_momentum < cls.MIN_MOMENTUM_THRESHOLD:
            return False, f"Momentum too low: {abs_momentum:.2f}% < {cls.MIN_MOMENTUM_THRESHOLD}%"

        if abs_momentum > cls.MAX_MOMENTUM_THRESHOLD:
            return False, f"Momentum too high: {abs_momentum:.2f}% > {cls.MAX_MOMENTUM_THRESHOLD}%"

        # Check ADX (trend strength)
        if adx < cls.MIN_ADX:
            return False, f"ADX too low: {adx:.2f} < {cls.MIN_ADX}"

        # Check volume
        if volume_sma > 0:
            volume_ratio = volume / volume_sma
            if volume_ratio <= cls.MIN_VOLUME_MULTIPLIER:
                return False, f"Volume too low: {volume_ratio:.2f}x ≤ {cls.MIN_VOLUME_MULTIPLIER}x SMA"
        else:
            # If no volume SMA, just check that volume is positive
            if volume <= 0:
                return False, "Volume is zero or negative"

        # Check minimum price
        if price < cls.MIN_PRICE:
            return False, f"Price too low: ${price:.2f} < ${cls.MIN_PRICE}"

        return True, "All entry filters passed"

    @classmethod
    def get_entry_price(cls, direction: str, bid: float, ask: float) -> float:
        """
        Get entry price based on position direction.

        Property 72: For any long position entered, the entry price should equal the ask price.
        Property 74: For any short position entered, the entry price should equal the bid price.

        Args:
            direction: "long" or "short"
            bid: Bid price
            ask: Ask price

        Returns:
            Entry price

        Validates: Requirements 18.1, 18.3
        """
        if direction.lower() == "long":
            # Long entry: use ask price (buying at ask)
            return ask
        else:
            # Short entry: use bid price (selling at bid)
            return bid

    @classmethod
    def get_exit_price(cls, direction: str, bid: float, ask: float) -> float:
        """
        Get exit price based on position direction.

        Property 73: For any long position exited, the exit price should equal the bid price.
        Property 75: For any short position exited, the exit price should equal the ask price.

        Args:
            direction: "long" or "short"
            bid: Bid price
            ask: Ask price

        Returns:
            Exit price

        Validates: Requirements 18.2, 18.4
        """
        if direction.lower() == "long":
            # Long exit: use bid price (selling at bid)
            return bid
        else:
            # Short exit: use ask price (buying at ask)
            return ask

    @classmethod
    def calculate_profit_loss(
        cls,
        direction: str,
        entry_price: float,
        exit_price: float,
    ) -> float:
        """
        Calculate profit or loss percentage for a trade.

        Property 76: For any trade, the profit or loss calculation should use the
        correct entry and exit prices based on position direction.

        Args:
            direction: "long" or "short"
            entry_price: Entry price
            exit_price: Exit price

        Returns:
            Profit/loss percentage (positive for profit, negative for loss)

        Validates: Requirements 18.5
        """
        if entry_price <= 0:
            logger.warning(f"Invalid entry price: {entry_price}")
            return 0.0

        if direction.lower() == "long":
            # Long: profit when exit > entry
            profit_loss = ((exit_price - entry_price) / entry_price) * 100.0
        else:
            # Short: profit when entry > exit
            profit_loss = ((entry_price - exit_price) / entry_price) * 100.0

        return profit_loss

    @classmethod
    def validate_prices(
        cls,
        bid: float,
        ask: float,
        current_price: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Validate bid/ask prices are reasonable.

        Args:
            bid: Bid price
            ask: Ask price
            current_price: Optional current price for additional validation

        Returns:
            Tuple of (is_valid, reason)
        """
        if bid <= 0:
            return False, f"Invalid bid price: {bid}"

        if ask <= 0:
            return False, f"Invalid ask price: {ask}"

        if bid > ask:
            return False, f"Bid ({bid}) > Ask ({ask})"

        # Check spread is reasonable (< 10%)
        spread_percent = ((ask - bid) / bid) * 100.0
        if spread_percent > 10.0:
            return False, f"Spread too wide: {spread_percent:.2f}%"

        # If current price provided, check it's between bid and ask
        if current_price is not None:
            if current_price < bid or current_price > ask:
                logger.warning(
                    f"Current price {current_price} outside bid-ask spread [{bid}, {ask}]"
                )

        return True, "Prices valid"
