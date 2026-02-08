"""
Base class for indicator simulators.

Defines the interface that momentum and penny stock simulators must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from backtesting.models import ActivePosition


class BaseIndicatorSimulator(ABC):
    """Abstract base class for backtesting indicator simulators."""

    @abstractmethod
    def indicator_name(self) -> str:
        """Return the name of this indicator."""
        pass

    @abstractmethod
    def should_enter(
        self,
        ticker: str,
        bar: Dict[str, Any],
        bars_window: List[Dict[str, Any]],
        indicators: Dict[str, Any],
        current_time: datetime,
        active_positions: Dict[str, ActivePosition],
        daily_trade_count: int,
    ) -> Optional[Tuple[str, float, float, float, float]]:
        """Evaluate whether to enter a trade.

        Args:
            ticker: Stock symbol
            bar: Current bar dict (o, h, l, c, v, t)
            bars_window: Rolling window of recent bars (for TA)
            indicators: Technical indicators dict from calculate_indicators()
            current_time: Current bar timestamp
            active_positions: Dict of currently active positions (ticker -> ActivePosition)
            daily_trade_count: Number of trades already made today

        Returns:
            None if no entry, or tuple of:
            (direction, entry_price, position_size_dollars, atr_stop_percent, spread_percent)
        """
        pass

    @abstractmethod
    def should_exit(
        self,
        position: ActivePosition,
        bar: Dict[str, Any],
        bars_window: List[Dict[str, Any]],
        indicators: Dict[str, Any],
        current_time: datetime,
    ) -> Optional[Tuple[str, float]]:
        """Evaluate whether to exit an existing position.

        Args:
            position: The active position
            bar: Current bar dict
            bars_window: Rolling window of recent bars
            indicators: Technical indicators
            current_time: Current bar timestamp

        Returns:
            None if no exit, or tuple of (exit_reason, exit_price)
        """
        pass

    def estimate_spread(self, bar: Dict[str, Any]) -> float:
        """Estimate bid-ask spread from bar OHLC data.

        Uses: spread ≈ (high - low) * 0.20 as a rough estimate.
        Returns spread as a percentage of mid price.
        """
        high = float(bar.get("h", 0))
        low = float(bar.get("l", 0))
        close = float(bar.get("c", 0))

        if close <= 0 or high <= 0 or low <= 0:
            return 1.0  # Default 1% spread

        # Estimate spread from bar range
        spread_est = (high - low) * 0.20
        spread_pct = (spread_est / close) * 100

        # Clamp to reasonable range
        return max(0.01, min(spread_pct, 5.0))

    def estimate_entry_price(self, bar: Dict[str, Any], direction: str) -> float:
        """Estimate entry price accounting for spread.

        For longs: entry at ask (slightly above close)
        For shorts: entry at bid (slightly below close)
        """
        close = float(bar.get("c", 0))
        high = float(bar.get("h", 0))
        low = float(bar.get("l", 0))

        if close <= 0:
            return 0.0

        # Estimate half-spread
        half_spread = (high - low) * 0.10  # Half of estimated spread

        if direction == "long":
            return close + half_spread  # Buy at ask
        else:
            return close - half_spread  # Sell at bid

    def estimate_exit_price(self, bar: Dict[str, Any], direction: str) -> float:
        """Estimate exit price accounting for spread.

        For longs: exit at bid (slightly below close)
        For shorts: exit at ask (slightly above close)
        """
        close = float(bar.get("c", 0))
        high = float(bar.get("h", 0))
        low = float(bar.get("l", 0))

        if close <= 0:
            return 0.0

        half_spread = (high - low) * 0.10

        if direction == "long":
            return close - half_spread  # Sell at bid
        else:
            return close + half_spread  # Buy at ask
