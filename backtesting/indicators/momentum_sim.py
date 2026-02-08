"""
Momentum Indicator Simulator for Backtesting.

Replicates the entry and exit logic from MomentumIndicator without
any async I/O, DynamoDB, or webhook dependencies.
"""

import sys
import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Add project root to path so we can import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtesting.indicators.base_simulator import BaseIndicatorSimulator
from backtesting.models import ActivePosition
from backtesting.config import (
    MOMENTUM_BASE_POSITION_SIZE,
    MOMENTUM_MAX_POSITIONS,
    MOMENTUM_MAX_DAILY_TRADES,
    MOMENTUM_ENTRY_CUTOFF_HOUR,
    MOMENTUM_ENTRY_CUTOFF_MINUTE,
    FORCE_CLOSE_MINUTES_BEFORE,
)

# Import shared utility classes from the trading codebase
from app.src.services.trading.penny_stock_utils import (
    SpreadCalculator,
    TieredTrailingStop,
    ExitDecisionEngine,
    ATRCalculator,
)
from app.src.services.trading.trading_config import (
    ATR_STOP_LOSS_MULTIPLIER,
    PENNY_STOCK_STOP_LOSS_MIN,
    PENNY_STOCK_STOP_LOSS_MAX,
    STANDARD_STOCK_STOP_LOSS_MIN,
    STANDARD_STOCK_STOP_LOSS_MAX,
)
from app.src.services.trading.risk_management import RiskManagement


class MomentumSimulator(BaseIndicatorSimulator):
    """Simulates the Momentum Trading indicator for backtesting."""

    # Configuration matching MomentumIndicator class attributes
    MIN_MOMENTUM = 1.5          # Minimum momentum %
    MAX_MOMENTUM = 15.0         # Maximum momentum %
    MIN_ADX = 20.0
    RSI_MIN_LONG = 45.0
    RSI_MAX_LONG = 70.0
    RSI_MIN_SHORT = 50.0
    MFI_MIN_LONG = 20.0
    MFI_MAX_LONG = 80.0
    MFI_MIN_SHORT = 20.0
    MFI_MAX_SHORT = 80.0
    MIN_VOLUME_RATIO = 1.5
    MIN_STOCK_PRICE = 5.0       # Only stocks >= $5
    MAX_SPREAD_PCT = 3.0
    MAX_ATR_PCT = 5.0
    MIN_HOLDING_SECONDS = 60
    EMERGENCY_STOP_PCT = -5.0   # Matches ExitDecisionEngine
    PROFIT_TARGET = 1.5
    TRAILING_STOP_BASE = 2.0    # 2% flat trailing stop

    def __init__(self):
        self._exit_engine = ExitDecisionEngine()
        # Track tickers traded today to prevent re-entry
        self._traded_today = set()
        self._current_day = ""

    def indicator_name(self) -> str:
        return "Momentum Trading"

    def _reset_daily_state(self, date_str: str):
        """Reset daily tracking state."""
        if date_str != self._current_day:
            self._traded_today = set()
            self._current_day = date_str
            self._exit_engine = ExitDecisionEngine()

    def _calculate_momentum(self, datetime_price: Dict[str, float]) -> Tuple[float, str]:
        """Calculate momentum score from datetime_price dict.

        Replicates MomentumIndicator._calculate_momentum().

        Algorithm:
        1. Sort prices chronologically
        2. Split into early 1/3 and recent 1/3
        3. Calculate change_percent = (recent_avg - early_avg) / early_avg * 100
        4. Calculate trend from recent price changes
        5. momentum = 0.7 * change_percent + 0.3 * trend_percent
        """
        if not datetime_price or len(datetime_price) < 3:
            return 0.0, "Insufficient price data"

        # Sort by timestamp and extract prices
        sorted_items = sorted(datetime_price.items())
        prices = [float(p) for _, p in sorted_items if p and float(p) > 0]

        if len(prices) < 3:
            return 0.0, "Insufficient valid prices"

        n = len(prices)
        early_count = max(1, n // 3)
        recent_count = max(1, n // 3)

        early_prices = prices[:early_count]
        recent_prices = prices[-recent_count:]

        early_avg = sum(early_prices) / len(early_prices)
        recent_avg = sum(recent_prices) / len(recent_prices)

        if early_avg <= 0:
            return 0.0, "Invalid early average"

        change_percent = ((recent_avg - early_avg) / early_avg) * 100

        # Recent trend
        trend_sum = sum(
            recent_prices[i] - recent_prices[i-1]
            for i in range(1, len(recent_prices))
        )
        recent_trend = trend_sum / max(1, len(recent_prices) - 1)
        trend_percent = (recent_trend / early_avg) * 100

        momentum_score = 0.7 * change_percent + 0.3 * trend_percent

        reason = (f"Momentum: {change_percent:.2f}% change, "
                 f"{trend_percent:.2f}% trend (n={n})")
        return momentum_score, reason

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
        """Evaluate momentum entry conditions.

        Returns None or (direction, entry_price, position_size, atr_stop_pct, spread_pct)
        """
        date_str = current_time.strftime("%Y-%m-%d")
        self._reset_daily_state(date_str)

        # Check position limits
        my_positions = {k: v for k, v in active_positions.items()
                       if v.indicator_name == self.indicator_name()}
        if len(my_positions) >= MOMENTUM_MAX_POSITIONS:
            return None

        if daily_trade_count >= MOMENTUM_MAX_DAILY_TRADES:
            return None

        # Already in position for this ticker
        if ticker in active_positions:
            return None

        # Time cutoff
        if (current_time.hour > MOMENTUM_ENTRY_CUTOFF_HOUR or
            (current_time.hour == MOMENTUM_ENTRY_CUTOFF_HOUR and
             current_time.minute > MOMENTUM_ENTRY_CUTOFF_MINUTE)):
            return None

        # Price filter
        current_price = float(bar.get("c", 0))
        if current_price < self.MIN_STOCK_PRICE:
            return None

        # Spread check
        spread_pct = self.estimate_spread(bar)
        if spread_pct > self.MAX_SPREAD_PCT:
            return None

        # Calculate momentum from datetime_price
        datetime_price = indicators.get("datetime_price", {})
        momentum_score, _reason = self._calculate_momentum(datetime_price)

        abs_momentum = abs(momentum_score)
        if abs_momentum < self.MIN_MOMENTUM or abs_momentum > self.MAX_MOMENTUM:
            return None

        # Determine direction
        direction = "long" if momentum_score > 0 else "short"
        is_long = direction == "long"

        # ADX check
        adx = indicators.get("adx", 0.0)
        if adx is None or adx < self.MIN_ADX:
            return None

        # RSI check
        rsi = indicators.get("rsi", 50.0)
        if is_long and (rsi < self.RSI_MIN_LONG or rsi > self.RSI_MAX_LONG):
            return None
        if not is_long and rsi < self.RSI_MIN_SHORT:
            return None

        # MFI check
        mfi = indicators.get("mfi", 50.0)
        if is_long:
            if mfi < self.MFI_MIN_LONG or mfi > self.MFI_MAX_LONG:
                return None
        else:
            if mfi < self.MFI_MIN_SHORT or mfi > self.MFI_MAX_SHORT:
                return None

        # Volume check
        volume = indicators.get("volume", 0)
        volume_sma = indicators.get("volume_sma", 0)
        if volume_sma > 0:
            vol_ratio = volume / volume_sma
            if vol_ratio < self.MIN_VOLUME_RATIO:
                return None

        # Stochastic checks
        stoch = indicators.get("stoch", (50.0, 50.0))
        if isinstance(stoch, (list, tuple)) and len(stoch) >= 2:
            stoch_k, stoch_d = stoch[0], stoch[1]
        else:
            stoch_k, stoch_d = 50.0, 50.0

        if not is_long and stoch_k > stoch_d:
            return None  # Don't short with bullish stochastic
        if is_long and stoch_k > 80.0:
            return None  # Don't buy overbought
        if is_long and stoch_k < stoch_d and stoch_k < 30.0:
            return None  # Don't buy bearish

        # CCI check
        cci = indicators.get("cci", 0.0)
        if cci is not None:
            if is_long and cci > 200.0:
                return None
            if not is_long and cci < -200.0:
                return None
            if not is_long and cci > 100.0:
                return None

        # Bollinger band extreme check
        bollinger = indicators.get("bollinger", (0, 0, 0))
        if isinstance(bollinger, (list, tuple)) and len(bollinger) >= 3:
            bb_upper, bb_middle, bb_lower = bollinger[0], bollinger[1], bollinger[2]
            if bb_upper > 0 and bb_lower > 0:
                bb_width = bb_upper - bb_lower
                if bb_width > 0:
                    if is_long and current_price > bb_upper:
                        return None  # Above upper band
                    if not is_long and current_price < bb_lower:
                        return None  # Below lower band

        # EMA deviation check
        ema_fast = indicators.get("ema_fast", current_price)
        if ema_fast and ema_fast > 0:
            ema_dev = ((current_price - ema_fast) / ema_fast) * 100
            if not is_long and ema_dev > 10.0:
                return None  # Parabolic squeeze
            if is_long and ema_dev > 10.0:
                return None  # Too extended
            if is_long and ema_dev < -5.0:
                return None  # Falling knife

        # ATR volatility check
        atr = indicators.get("atr", current_price * 0.01)
        if atr and current_price > 0:
            atr_pct = (atr / current_price) * 100
            if atr_pct > self.MAX_ATR_PCT:
                return None

        # Calculate entry price, stop loss, and position size
        entry_price = self.estimate_entry_price(bar, direction)

        # ATR-based stop loss (using RiskManagement)
        is_penny = current_price < 5.0
        atr_stop = RiskManagement.calculate_stop_loss(entry_price, atr, is_penny)

        # Position size
        position_size = RiskManagement.calculate_position_size(entry_price, atr, is_penny)
        position_size = min(position_size, MOMENTUM_BASE_POSITION_SIZE)

        return (direction, entry_price, position_size, atr_stop, spread_pct)

    def should_exit(
        self,
        position: ActivePosition,
        bar: Dict[str, Any],
        bars_window: List[Dict[str, Any]],
        indicators: Dict[str, Any],
        current_time: datetime,
    ) -> Optional[Tuple[str, float]]:
        """Evaluate exit conditions using ExitDecisionEngine.

        Returns None or (exit_reason, exit_price)
        """
        current_price = float(bar.get("c", 0))
        if current_price <= 0:
            return None

        holding_secs = position.holding_seconds(current_time)
        is_long = position.direction == "long"
        profit_pct = position.profit_percent(current_price)

        # Update peak price
        position.update_peak(current_price)

        # Force close near market close
        if current_time.hour == 15 and current_time.minute >= (60 - FORCE_CLOSE_MINUTES_BEFORE):
            exit_price = self.estimate_exit_price(bar, position.direction)
            return "force_close_eod", exit_price
        if current_time.hour >= 16:
            exit_price = self.estimate_exit_price(bar, position.direction)
            return "force_close_eod", exit_price

        # Emergency stop
        if profit_pct <= self.EMERGENCY_STOP_PCT:
            exit_price = self.estimate_exit_price(bar, position.direction)
            return f"emergency_stop_{profit_pct:.1f}%", exit_price

        # Build recent bars for trend reversal detection
        recent_bars = bars_window[-3:] if len(bars_window) >= 3 else bars_window

        # Use ExitDecisionEngine
        exit_decision = self._exit_engine.evaluate_exit(
            ticker=position.ticker,
            entry_price=position.entry_price,
            breakeven_price=position.breakeven_price,
            current_price=current_price,
            peak_price=position.peak_price,
            atr_stop_percent=position.atr_stop_percent,
            holding_seconds=holding_secs,
            is_long=is_long,
            spread_percent=position.spread_percent,
            recent_bars=recent_bars,
        )

        if exit_decision.should_exit:
            exit_price = self.estimate_exit_price(bar, position.direction)
            return exit_decision.reason, exit_price

        # Flat trailing stop fallback (2% base, wider for shorts)
        if holding_secs >= self.MIN_HOLDING_SECONDS and profit_pct > 0.5:
            trail_pct = self.TRAILING_STOP_BASE
            if not is_long:
                trail_pct *= 1.5  # Wider for shorts

            peak_profit = position.profit_percent(position.peak_price)
            if peak_profit - profit_pct >= trail_pct:
                exit_price = self.estimate_exit_price(bar, position.direction)
                return f"trailing_stop_{trail_pct:.1f}%", exit_price

        # Max holding time for volatile stocks
        atr = indicators.get("atr", 0)
        close_price = indicators.get("close_price", position.entry_price)
        if atr and close_price > 0:
            atr_pct = (atr / close_price) * 100
            max_hold_minutes = 60 if atr_pct <= 3.0 else 30
            if holding_secs > max_hold_minutes * 60:
                exit_price = self.estimate_exit_price(bar, position.direction)
                return f"max_hold_{max_hold_minutes}min", exit_price

        return None
