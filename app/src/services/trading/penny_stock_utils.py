"""
Penny Stock Algorithm Utilities

This module contains utility classes for the improved penny stock trading algorithm:
- SpreadCalculator: Calculates bid-ask spread and breakeven prices
- ATRCalculator: Calculates Average True Range for volatility-based stops
- TieredTrailingStop: Manages tiered trailing stop logic
- MomentumConfirmation: Validates entry momentum
- ExitDecisionEngine: Centralized exit decision logic
- DailyPerformanceMetrics: Tracks daily trading performance
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime


class SpreadCalculator:
    """Calculates bid-ask spread and breakeven price accounting for spread."""
    
    @staticmethod
    def calculate_spread_percent(bid: float, ask: float) -> float:
        """
        Calculate bid-ask spread as percentage of mid price.
        
        Args:
            bid: Bid price
            ask: Ask price
            
        Returns:
            Spread as percentage of mid price, or infinity if invalid prices
        """
        if bid <= 0 or ask <= 0:
            return float('inf')
        mid = (bid + ask) / 2
        return ((ask - bid) / mid) * 100
    
    @staticmethod
    def calculate_breakeven_price(entry_price: float, spread_percent: float, is_long: bool) -> float:
        """
        Calculate breakeven price accounting for spread.
        
        For longs: need price to rise by spread to break even (buy at ask, sell at bid)
        For shorts: need price to fall by spread to break even (sell at bid, buy at ask)
        
        Args:
            entry_price: The entry price of the trade
            spread_percent: The bid-ask spread as a percentage
            is_long: True for long positions, False for short positions
            
        Returns:
            The breakeven price accounting for spread
        """
        spread_buffer = entry_price * (spread_percent / 100)
        if is_long:
            return entry_price + spread_buffer
        else:
            return entry_price - spread_buffer


class ATRCalculator:
    """Calculates Average True Range for volatility-based stop losses."""
    
    DEFAULT_STOP_LOSS_PERCENT = -2.0
    
    @staticmethod
    def calculate_atr(bars: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
        """
        Calculate ATR from price bars.
        
        Args:
            bars: List of price bars with 'h' (high), 'l' (low), 'c' (close) keys
            period: Number of periods for ATR calculation (default 14)
            
        Returns:
            ATR value, or None if insufficient data
        """
        if len(bars) < period + 1:
            return None
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i].get('h', 0)
            low = bars[i].get('l', 0)
            prev_close = bars[i-1].get('c', 0)
            
            if high <= 0 or low <= 0 or prev_close <= 0:
                continue
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return None
        
        # Use last 'period' true ranges
        recent_tr = true_ranges[-period:]
        return sum(recent_tr) / len(recent_tr)
    
    @classmethod
    def calculate_stop_loss_percent(
        cls,
        atr: Optional[float],
        current_price: float,
        multiplier: float = 1.5,
        min_stop: float = -1.5,
        max_stop: float = -4.0
    ) -> float:
        """
        Calculate stop loss as percentage based on ATR.
        
        Args:
            atr: Average True Range value (None to use default)
            current_price: Current stock price
            multiplier: ATR multiplier (default 1.5)
            min_stop: Minimum stop loss percentage (closest to 0, default -1.5%)
            max_stop: Maximum stop loss percentage (furthest from 0, default -4.0%)
            
        Returns:
            Stop loss as negative percentage (e.g., -2.5 for 2.5% stop)
        """
        if atr is None or current_price <= 0:
            return cls.DEFAULT_STOP_LOSS_PERCENT
        
        atr_percent = (atr / current_price) * 100 * multiplier
        stop_percent = -atr_percent
        
        # Clamp to bounds (max_stop is more negative, min_stop is less negative)
        return max(max_stop, min(min_stop, stop_percent))


@dataclass
class TrailingStopConfig:
    """Configuration for a trailing stop tier."""
    profit_threshold: float  # Profit % to activate this tier
    trail_percent: float     # Trail distance below peak as percentage
    min_locked_profit: float # Minimum profit to lock (0 if not applicable)


class TieredTrailingStop:
    """Manages tiered trailing stop logic that tightens as profit grows."""
    
    # Tiers ordered from highest to lowest profit threshold
    # This ensures we check the most profitable tier first
    TIERS = [
        TrailingStopConfig(profit_threshold=3.0, trail_percent=1.5, min_locked_profit=1.5),
        TrailingStopConfig(profit_threshold=2.0, trail_percent=0.3, min_locked_profit=0.0),
        TrailingStopConfig(profit_threshold=1.0, trail_percent=0.5, min_locked_profit=0.0),
    ]
    
    @classmethod
    def get_trailing_stop_price(
        cls,
        peak_price: float,
        current_profit_percent: float,
        entry_price: float,
        is_long: bool
    ) -> Optional[float]:
        """
        Calculate trailing stop price based on current profit tier.
        
        Args:
            peak_price: The highest (for long) or lowest (for short) price since entry
            current_profit_percent: Current profit as percentage
            entry_price: Original entry price (or breakeven price)
            is_long: True for long positions, False for short positions
            
        Returns:
            Trailing stop price, or None if no trailing stop should be active
        """
        for tier in cls.TIERS:
            if current_profit_percent >= tier.profit_threshold:
                trail_amount = peak_price * (tier.trail_percent / 100)
                
                if is_long:
                    stop_price = peak_price - trail_amount
                    # Ensure minimum locked profit
                    if tier.min_locked_profit > 0:
                        min_stop = entry_price * (1 + tier.min_locked_profit / 100)
                        stop_price = max(stop_price, min_stop)
                else:
                    stop_price = peak_price + trail_amount
                    if tier.min_locked_profit > 0:
                        min_stop = entry_price * (1 - tier.min_locked_profit / 100)
                        stop_price = min(stop_price, min_stop)
                
                return stop_price
        
        return None  # No trailing stop active yet


class MomentumConfirmation:
    """Validates entry momentum by checking recent bar direction."""
    
    MIN_BARS_IN_TREND = 3
    TOTAL_BARS_TO_CHECK = 5
    
    @classmethod
    def is_momentum_confirmed(
        cls,
        bars: List[Dict[str, Any]],
        is_long: bool
    ) -> Tuple[bool, str]:
        """
        Check if momentum is confirmed for entry.
        
        Requires at least 3 of the last 5 bars to move in the trend direction,
        AND the most recent bar must confirm the trend.
        
        Args:
            bars: List of price bars with 'c' (close) key
            is_long: True for long (upward) momentum, False for short (downward)
            
        Returns:
            Tuple of (is_confirmed, reason)
        """
        if len(bars) < cls.TOTAL_BARS_TO_CHECK:
            return False, f"Insufficient bars: {len(bars)} < {cls.TOTAL_BARS_TO_CHECK}"
        
        recent_bars = bars[-cls.TOTAL_BARS_TO_CHECK:]
        
        # Count bars moving in trend direction
        bars_in_trend = 0
        for i in range(1, len(recent_bars)):
            prev_close = recent_bars[i-1].get('c', 0)
            curr_close = recent_bars[i].get('c', 0)
            
            if prev_close <= 0 or curr_close <= 0:
                continue
            
            if is_long and curr_close > prev_close:
                bars_in_trend += 1
            elif not is_long and curr_close < prev_close:
                bars_in_trend += 1
        
        # Check if last bar is with trend
        last_bar_close = recent_bars[-1].get('c', 0)
        second_last_close = recent_bars[-2].get('c', 0)
        
        if last_bar_close <= 0 or second_last_close <= 0:
            return False, "Invalid price data in recent bars"
        
        last_bar_with_trend = (
            (is_long and last_bar_close > second_last_close) or
            (not is_long and last_bar_close < second_last_close)
        )
        
        if bars_in_trend < cls.MIN_BARS_IN_TREND:
            return False, f"Only {bars_in_trend}/{cls.MIN_BARS_IN_TREND} bars in trend direction"
        
        if not last_bar_with_trend:
            return False, "Last bar moves against trend"
        
        return True, f"Confirmed: {bars_in_trend}/{cls.TOTAL_BARS_TO_CHECK - 1} bars in trend, last bar confirms"


@dataclass
class ExitDecision:
    """Result of exit evaluation."""
    should_exit: bool
    reason: str
    exit_type: str  # 'emergency', 'stop_loss', 'trailing_stop', 'none'
    is_spread_induced: bool = False


class ExitDecisionEngine:
    """Centralized exit decision logic with priority-based evaluation."""
    
    MIN_HOLDING_SECONDS = 60
    EMERGENCY_STOP_PERCENT = -3.0
    CONSECUTIVE_CHECKS_REQUIRED = 2
    
    def __init__(self):
        self.consecutive_loss_checks: Dict[str, int] = {}
    
    def evaluate_exit(
        self,
        ticker: str,
        entry_price: float,
        breakeven_price: float,
        current_price: float,
        peak_price: float,
        atr_stop_percent: float,
        holding_seconds: float,
        is_long: bool,
        spread_percent: float
    ) -> ExitDecision:
        """
        Evaluate whether trade should exit and why.
        
        Priority order:
        1. Emergency exit on significant loss (always active, even during holding period)
        2. Block non-emergency exits during minimum holding period
        3. Trailing stop for profitable trades
        4. ATR-based stop loss with consecutive check requirement
        
        Args:
            ticker: Stock ticker symbol
            entry_price: Original entry price
            breakeven_price: Breakeven price accounting for spread
            current_price: Current market price
            peak_price: Peak price since entry (highest for long, lowest for short)
            atr_stop_percent: ATR-based stop loss percentage (negative)
            holding_seconds: Seconds since trade entry
            is_long: True for long positions
            spread_percent: Bid-ask spread at entry as percentage
            
        Returns:
            ExitDecision with should_exit, reason, exit_type, and is_spread_induced
        """
        profit_vs_entry = self._calc_profit(entry_price, current_price, is_long)
        profit_vs_breakeven = self._calc_profit(breakeven_price, current_price, is_long)
        
        # PRIORITY 1: Emergency exit on significant loss (always active)
        if profit_vs_entry <= self.EMERGENCY_STOP_PERCENT:
            is_spread_induced = abs(profit_vs_entry) <= spread_percent * 1.5
            return ExitDecision(
                should_exit=True,
                reason=f"Emergency stop: {profit_vs_entry:.2f}% loss",
                exit_type='emergency',
                is_spread_induced=is_spread_induced
            )
        
        # Within minimum holding period - only emergency exits allowed
        if holding_seconds < self.MIN_HOLDING_SECONDS:
            return ExitDecision(
                should_exit=False,
                reason=f"Within holding period ({holding_seconds:.0f}s < {self.MIN_HOLDING_SECONDS}s)",
                exit_type='none'
            )
        
        # PRIORITY 2: Trailing stop (if in profit vs breakeven)
        if profit_vs_breakeven >= 1.0:
            trailing_stop_price = TieredTrailingStop.get_trailing_stop_price(
                peak_price, profit_vs_breakeven, breakeven_price, is_long
            )
            if trailing_stop_price:
                triggered = (current_price <= trailing_stop_price) if is_long else (current_price >= trailing_stop_price)
                if triggered:
                    return ExitDecision(
                        should_exit=True,
                        reason=f"Trailing stop triggered at ${trailing_stop_price:.4f}",
                        exit_type='trailing_stop'
                    )
        
        # PRIORITY 3: ATR-based stop loss (requires consecutive checks)
        if profit_vs_breakeven <= atr_stop_percent:
            self.consecutive_loss_checks[ticker] = self.consecutive_loss_checks.get(ticker, 0) + 1
            
            if self.consecutive_loss_checks[ticker] >= self.CONSECUTIVE_CHECKS_REQUIRED:
                is_spread_induced = abs(profit_vs_entry) <= spread_percent * 1.5
                self.consecutive_loss_checks[ticker] = 0
                return ExitDecision(
                    should_exit=True,
                    reason=f"ATR stop loss: {profit_vs_breakeven:.2f}% (threshold: {atr_stop_percent:.2f}%)",
                    exit_type='stop_loss',
                    is_spread_induced=is_spread_induced
                )
            else:
                return ExitDecision(
                    should_exit=False,
                    reason=f"Loss warning {self.consecutive_loss_checks[ticker]}/{self.CONSECUTIVE_CHECKS_REQUIRED}",
                    exit_type='none'
                )
        else:
            # Reset consecutive loss counter if not in loss
            self.consecutive_loss_checks[ticker] = 0
        
        return ExitDecision(
            should_exit=False,
            reason=f"Holding: profit {profit_vs_breakeven:.2f}%",
            exit_type='none'
        )
    
    def reset_ticker(self, ticker: str) -> None:
        """Reset consecutive loss counter for a ticker (call after exit)."""
        if ticker in self.consecutive_loss_checks:
            del self.consecutive_loss_checks[ticker]
    
    def _calc_profit(self, base_price: float, current_price: float, is_long: bool) -> float:
        """Calculate profit percentage."""
        if base_price <= 0:
            return 0.0
        if is_long:
            return ((current_price - base_price) / base_price) * 100
        else:
            return ((base_price - current_price) / base_price) * 100


@dataclass
class DailyPerformanceMetrics:
    """Tracks daily trading performance metrics."""
    
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    spread_induced_losses: int = 0
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate as percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def average_win(self) -> float:
        """Calculate average winning trade profit."""
        if self.winning_trades == 0:
            return 0.0
        return self.total_profit / self.winning_trades
    
    @property
    def average_loss(self) -> float:
        """Calculate average losing trade loss (returns positive number)."""
        if self.losing_trades == 0:
            return 0.0
        return abs(self.total_loss) / self.losing_trades
    
    @property
    def profit_factor(self) -> float:
        """Calculate profit factor (total profit / total loss)."""
        if self.total_loss == 0:
            return float('inf') if self.total_profit > 0 else 0.0
        return abs(self.total_profit / self.total_loss)
    
    def record_trade(self, profit_percent: float, is_spread_induced: bool = False) -> None:
        """Record a completed trade."""
        self.total_trades += 1
        if profit_percent >= 0:
            self.winning_trades += 1
            self.total_profit += profit_percent
        else:
            self.losing_trades += 1
            self.total_loss += profit_percent  # Will be negative
            if is_spread_induced:
                self.spread_induced_losses += 1
    
    def reset(self) -> None:
        """Reset all metrics for a new day."""
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.spread_induced_losses = 0
        self.date = datetime.now().strftime("%Y-%m-%d")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging."""
        return {
            "date": self.date,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": f"{self.win_rate:.1f}%",
            "total_profit": f"{self.total_profit:.2f}%",
            "total_loss": f"{self.total_loss:.2f}%",
            "average_win": f"{self.average_win:.2f}%",
            "average_loss": f"{self.average_loss:.2f}%",
            "profit_factor": f"{self.profit_factor:.2f}",
            "spread_induced_losses": self.spread_induced_losses,
        }
