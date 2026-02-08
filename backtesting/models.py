"""
Data models for the backtesting framework.

Defines dataclasses for trade records, active positions, and simulation results.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class TradeRecord:
    """A single completed trade (entry + exit pair)."""
    date: str                     # Trading date YYYY-MM-DD
    entry_time: str               # Entry timestamp ISO format
    exit_time: str                # Exit timestamp ISO format
    ticker: str
    action: str                   # buy_to_open, sell_to_open
    close_action: str             # sell_to_close, buy_to_close
    direction: str                # long or short
    entry_price: float
    exit_price: float
    shares: float
    position_value: float         # entry_price * shares
    profit_loss_pct: float        # % P&L
    profit_loss_dollars: float    # $ P&L
    exit_reason: str
    hold_duration_seconds: float
    indicator_name: str
    # Extra metadata
    entry_spread_pct: float = 0.0
    atr_at_entry: float = 0.0
    momentum_at_entry: float = 0.0
    confidence_at_entry: float = 0.0


@dataclass
class ActivePosition:
    """An active (open) position being tracked during simulation."""
    ticker: str
    direction: str              # "long" or "short"
    entry_price: float
    breakeven_price: float      # entry_price adjusted for spread
    shares: float
    position_value: float
    entry_time: datetime
    entry_bar_index: int        # Index in the day's bar list
    peak_price: float           # Highest price since entry (for longs), lowest for shorts
    atr_stop_percent: float     # ATR-based stop loss %
    spread_percent: float       # Spread at entry
    indicator_name: str
    momentum_at_entry: float = 0.0
    confidence_at_entry: float = 0.0
    consecutive_loss_checks: int = 0  # For ATR stop with consecutive check requirement

    def update_peak(self, current_price: float):
        """Update peak price tracking."""
        if self.direction == "long":
            self.peak_price = max(self.peak_price, current_price)
        else:
            self.peak_price = min(self.peak_price, current_price)

    def holding_seconds(self, current_time: datetime) -> float:
        """Calculate seconds since entry."""
        return (current_time - self.entry_time).total_seconds()

    def profit_percent(self, current_price: float) -> float:
        """Calculate current profit percentage."""
        if self.entry_price <= 0:
            return 0.0
        if self.direction == "long":
            return ((current_price - self.entry_price) / self.entry_price) * 100
        else:
            return ((self.entry_price - current_price) / self.entry_price) * 100


@dataclass
class SimulationResult:
    """Results from a complete simulation run."""
    indicator_name: str
    tickers: List[str]
    start_date: str
    end_date: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit_pct: float = 0.0
    total_loss_pct: float = 0.0
    total_pnl_dollars: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_duration_seconds: float = 0.0
    avg_profit_per_winner: float = 0.0
    avg_loss_per_loser: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)
    per_ticker_stats: dict = field(default_factory=dict)

    def calculate_statistics(self):
        """Calculate summary statistics from trade list."""
        if not self.trades:
            return

        self.total_trades = len(self.trades)
        winners = [t for t in self.trades if t.profit_loss_pct >= 0]
        losers = [t for t in self.trades if t.profit_loss_pct < 0]

        self.winning_trades = len(winners)
        self.losing_trades = len(losers)

        self.total_profit_pct = sum(t.profit_loss_pct for t in winners)
        self.total_loss_pct = sum(t.profit_loss_pct for t in losers)
        self.total_pnl_dollars = sum(t.profit_loss_dollars for t in self.trades)

        self.win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0

        self.avg_profit_per_winner = (self.total_profit_pct / self.winning_trades) if self.winning_trades > 0 else 0.0
        self.avg_loss_per_loser = (self.total_loss_pct / self.losing_trades) if self.losing_trades > 0 else 0.0

        self.profit_factor = (self.total_profit_pct / abs(self.total_loss_pct)) if self.total_loss_pct != 0 else float('inf')

        self.avg_hold_duration_seconds = (
            sum(t.hold_duration_seconds for t in self.trades) / self.total_trades
        ) if self.total_trades > 0 else 0.0

        # Calculate max drawdown
        cumulative_pnl = 0.0
        peak_pnl = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative_pnl += t.profit_loss_pct
            peak_pnl = max(peak_pnl, cumulative_pnl)
            dd = peak_pnl - cumulative_pnl
            max_dd = max(max_dd, dd)
        self.max_drawdown_pct = max_dd

        # Sharpe ratio (annualized, using daily returns)
        import numpy as np
        if len(self.trades) > 1:
            returns = [t.profit_loss_pct for t in self.trades]
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            if std_return > 0:
                # Approximate annualization: assume ~252 trading days
                self.sharpe_ratio = (mean_return / std_return) * np.sqrt(252)
            else:
                self.sharpe_ratio = 0.0

        # Per-ticker stats
        ticker_trades = {}
        for t in self.trades:
            if t.ticker not in ticker_trades:
                ticker_trades[t.ticker] = []
            ticker_trades[t.ticker].append(t)

        for ticker, ttrades in ticker_trades.items():
            wins = [t for t in ttrades if t.profit_loss_pct >= 0]
            losses = [t for t in ttrades if t.profit_loss_pct < 0]
            self.per_ticker_stats[ticker] = {
                "total_trades": len(ttrades),
                "winning_trades": len(wins),
                "losing_trades": len(losses),
                "win_rate": (len(wins) / len(ttrades) * 100) if ttrades else 0.0,
                "total_pnl_pct": sum(t.profit_loss_pct for t in ttrades),
                "total_pnl_dollars": sum(t.profit_loss_dollars for t in ttrades),
                "avg_hold_seconds": sum(t.hold_duration_seconds for t in ttrades) / len(ttrades),
            }
