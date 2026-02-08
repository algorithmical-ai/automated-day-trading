"""
Penny Stocks Indicator Simulator for Backtesting.

Replicates the fast-scalping penny stock entry and exit logic from
PennyStocksIndicator without any async I/O dependencies.
"""

import sys
import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtesting.indicators.base_simulator import BaseIndicatorSimulator
from backtesting.models import ActivePosition
from backtesting.config import (
    PENNY_STOCK_POSITION_SIZE,
    PENNY_STOCK_MAX_POSITIONS,
    PENNY_STOCK_MAX_DAILY_TRADES,
    PENNY_STOCK_ENTRY_CUTOFF_HOUR,
    PENNY_STOCK_ENTRY_CUTOFF_MINUTE,
    FORCE_CLOSE_MINUTES_BEFORE,
)

# Import shared utility classes
from app.src.services.trading.penny_stock_utils import (
    SpreadCalculator,
    ATRCalculator,
    TieredTrailingStop,
    EnhancedExitDecisionEngine,
    MomentumConfirmation,
)
from app.src.services.trading.validation.trend_analyzer import TrendAnalyzer
from app.src.services.trading.peak_detection_config import PeakDetectionConfig


class PennyStocksSimulator(BaseIndicatorSimulator):
    """Simulates the Penny Stocks indicator with fast-scalping settings."""

    # Entry thresholds (matching PennyStocksIndicator scalping config)
    MIN_PRICE = 0.75
    MAX_PRICE = 5.00
    MIN_MOMENTUM = 3.0          # Minimum trend momentum %
    MAX_MOMENTUM = 25.0         # Maximum momentum %
    MIN_CONTINUATION = 0.5      # Minimum continuation score
    MIN_VOLUME = 5000           # Minimum bar volume
    MAX_SPREAD_PCT = 0.75       # Maximum spread %
    IMMEDIATE_MOMENTUM_THRESHOLD = 0.1  # Immediate bar momentum check

    # Exit thresholds
    PROFIT_TARGET = 1.5         # Take profit at 1.5%
    EMERGENCY_STOP = -5.0       # Emergency stop at -5%
    EARLY_EXIT_LOSS = -1.5      # Early exit loss threshold
    EARLY_EXIT_TIME = 30        # Early exit time window (seconds)
    INITIAL_STOP_LOSS = -2.0    # Initial period stop loss
    INITIAL_PERIOD = 60         # Initial period seconds
    TRAILING_STOP_FLAT = 1.0    # Flat trailing stop 1%
    MIN_HOLDING_SECONDS = 15    # Minimum holding time
    MAX_HOLDING_MINUTES = 15    # Maximum holding time

    # Cooldown
    TICKER_COOLDOWN_MINUTES = 5

    def __init__(self):
        self._config = PeakDetectionConfig()
        self._exit_engine = EnhancedExitDecisionEngine(config=self._config)
        self._ticker_last_exit: Dict[str, datetime] = {}
        self._current_day = ""

    def indicator_name(self) -> str:
        return "Penny Stocks"

    def _reset_daily_state(self, date_str: str):
        """Reset daily tracking."""
        if date_str != self._current_day:
            self._ticker_last_exit = {}
            self._current_day = date_str
            self._exit_engine = EnhancedExitDecisionEngine(config=self._config)

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
        """Evaluate penny stock entry conditions.

        Only longs (shorts disabled for penny stocks).
        """
        date_str = current_time.strftime("%Y-%m-%d")
        self._reset_daily_state(date_str)

        # Position limits
        my_positions = {k: v for k, v in active_positions.items()
                       if v.indicator_name == self.indicator_name()}
        if len(my_positions) >= PENNY_STOCK_MAX_POSITIONS:
            return None

        if daily_trade_count >= PENNY_STOCK_MAX_DAILY_TRADES:
            return None

        if ticker in active_positions:
            return None

        # Time cutoff
        if (current_time.hour > PENNY_STOCK_ENTRY_CUTOFF_HOUR or
            (current_time.hour == PENNY_STOCK_ENTRY_CUTOFF_HOUR and
             current_time.minute > PENNY_STOCK_ENTRY_CUTOFF_MINUTE)):
            return None

        # Cooldown check
        if ticker in self._ticker_last_exit:
            cooldown_end = self._ticker_last_exit[ticker] + timedelta(minutes=self.TICKER_COOLDOWN_MINUTES)
            if current_time < cooldown_end:
                return None

        # Price filter
        current_price = float(bar.get("c", 0))
        if current_price < self.MIN_PRICE or current_price > self.MAX_PRICE:
            return None

        # Spread check
        spread_pct = self.estimate_spread(bar)
        if spread_pct > self.MAX_SPREAD_PCT:
            return None

        # Volume check
        volume = float(bar.get("v", 0))
        if volume < self.MIN_VOLUME:
            return None

        # Need enough bars for trend analysis
        if len(bars_window) < 5:
            return None

        # Trend analysis using TrendAnalyzer (direct import, pure function)
        trend_metrics = TrendAnalyzer.calculate_trend_metrics(bars_window[-10:])

        momentum = trend_metrics.momentum_score
        continuation = trend_metrics.continuation_score

        # Momentum bounds
        abs_momentum = abs(momentum)
        if abs_momentum < self.MIN_MOMENTUM or abs_momentum > self.MAX_MOMENTUM:
            return None

        # Only longs
        if momentum <= 0:
            return None

        # Continuation check
        if continuation < self.MIN_CONTINUATION:
            return None

        # Immediate momentum check (last bar must show movement)
        if len(bars_window) >= 2:
            prev_close = float(bars_window[-2].get("c", 0))
            if prev_close > 0:
                immediate_change = ((current_price - prev_close) / prev_close) * 100
                if immediate_change < self.IMMEDIATE_MOMENTUM_THRESHOLD:
                    return None

        # Peak validation - check we're not buying at the peak
        peak_price = trend_metrics.peak_price
        if peak_price > 0 and current_price > 0:
            pct_below_peak = ((current_price - peak_price) / peak_price) * 100
            # Reject if too close to peak (within -0.2% of peak means we're AT the peak)
            if pct_below_peak > -0.2:
                # Check peak proximity
                if peak_price > current_price:
                    proximity = current_price / peak_price
                    if proximity > self._config.peak_proximity_threshold:
                        return None

        # Momentum confirmation using recent bars
        is_confirmed, _reason = MomentumConfirmation.is_momentum_confirmed(
            bars_window[-5:] if len(bars_window) >= 5 else bars_window,
            is_long=True
        )
        if not is_confirmed:
            return None

        # Calculate entry price and stops
        entry_price = self.estimate_entry_price(bar, "long")

        # ATR-based stop loss
        atr = ATRCalculator.calculate_atr(bars_window, period=14)
        atr_stop = ATRCalculator.calculate_stop_loss_percent(
            atr, current_price,
            multiplier=2.5,
            min_stop=-3.0,
            max_stop=-5.0,
        )

        position_size = PENNY_STOCK_POSITION_SIZE

        return ("long", entry_price, position_size, atr_stop, spread_pct)

    def should_exit(
        self,
        position: ActivePosition,
        bar: Dict[str, Any],
        bars_window: List[Dict[str, Any]],
        indicators: Dict[str, Any],
        current_time: datetime,
    ) -> Optional[Tuple[str, float]]:
        """Evaluate exit conditions with 5-priority scalping exit logic.

        Priority order:
        1. Emergency stop (-5%)
        2. Profit target (1.5%)
        3. Min holding period gate
        4. EnhancedExitDecisionEngine
        5. Flat trailing stop (1.0%)
        """
        current_price = float(bar.get("c", 0))
        if current_price <= 0:
            return None

        holding_secs = position.holding_seconds(current_time)
        profit_pct = position.profit_percent(current_price)

        # Update peak
        position.update_peak(current_price)

        # Force close near EOD
        if current_time.hour == 15 and current_time.minute >= (60 - FORCE_CLOSE_MINUTES_BEFORE):
            exit_price = self.estimate_exit_price(bar, position.direction)
            self._record_exit(position.ticker, current_time)
            return "force_close_eod", exit_price
        if current_time.hour >= 16:
            exit_price = self.estimate_exit_price(bar, position.direction)
            self._record_exit(position.ticker, current_time)
            return "force_close_eod", exit_price

        # Max holding time
        if holding_secs > self.MAX_HOLDING_MINUTES * 60:
            exit_price = self.estimate_exit_price(bar, position.direction)
            self._record_exit(position.ticker, current_time)
            return f"max_hold_{self.MAX_HOLDING_MINUTES}min", exit_price

        # PRIORITY 1: Emergency stop (always active)
        if profit_pct <= self.EMERGENCY_STOP:
            exit_price = self.estimate_exit_price(bar, position.direction)
            self._record_exit(position.ticker, current_time)
            return f"emergency_stop_{profit_pct:.1f}%", exit_price

        # PRIORITY 2: Profit target
        if profit_pct >= self.PROFIT_TARGET:
            exit_price = self.estimate_exit_price(bar, position.direction)
            self._record_exit(position.ticker, current_time)
            return f"profit_target_{profit_pct:.1f}%", exit_price

        # PRIORITY 3: Min holding period (block non-emergency/profit exits)
        if holding_secs < self.MIN_HOLDING_SECONDS:
            return None

        # PRIORITY 4: Enhanced exit engine
        is_long = position.direction == "long"
        breakeven = position.breakeven_price

        recent_bars = bars_window[-3:] if len(bars_window) >= 3 else bars_window

        exit_decision = self._exit_engine.evaluate_exit(
            ticker=position.ticker,
            entry_price=position.entry_price,
            breakeven_price=breakeven,
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
            self._record_exit(position.ticker, current_time)
            return exit_decision.reason, exit_price

        # PRIORITY 5: Flat trailing stop (1.0%)
        if profit_pct > 0.3:  # Activate after small profit
            peak_profit = position.profit_percent(position.peak_price)
            drop_from_peak = peak_profit - profit_pct
            if drop_from_peak >= self.TRAILING_STOP_FLAT:
                exit_price = self.estimate_exit_price(bar, position.direction)
                self._record_exit(position.ticker, current_time)
                return f"flat_trailing_stop_{self.TRAILING_STOP_FLAT}%", exit_price

        return None

    def _record_exit(self, ticker: str, exit_time: datetime):
        """Record exit time for cooldown tracking."""
        self._ticker_last_exit[ticker] = exit_time
        self._exit_engine.reset_ticker(ticker)
