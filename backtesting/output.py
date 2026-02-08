"""
Output module for backtesting results.

Writes trade records to CSV files and generates summary statistics.
"""

import csv
import os
from typing import List
from datetime import datetime

from backtesting.models import TradeRecord, SimulationResult
from backtesting.config import OUTPUT_DIR


def write_trades_csv(trades: List[TradeRecord], filename: str) -> str:
    """Write trade records to a CSV file.

    Args:
        trades: List of TradeRecord objects
        filename: Output filename (without directory)

    Returns:
        Full path to written file
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)

    headers = [
        "date",
        "entry_time",
        "exit_time",
        "ticker",
        "action",
        "close_action",
        "direction",
        "entry_price",
        "exit_price",
        "shares",
        "position_value",
        "profit_loss_pct",
        "profit_loss_dollars",
        "exit_reason",
        "hold_duration_seconds",
        "indicator_name",
        "entry_spread_pct",
        "atr_at_entry",
        "momentum_at_entry",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for trade in trades:
            writer.writerow([
                trade.date,
                trade.entry_time,
                trade.exit_time,
                trade.ticker,
                trade.action,
                trade.close_action,
                trade.direction,
                f"{trade.entry_price:.4f}",
                f"{trade.exit_price:.4f}",
                f"{trade.shares:.4f}",
                f"{trade.position_value:.2f}",
                f"{trade.profit_loss_pct:.4f}",
                f"{trade.profit_loss_dollars:.2f}",
                trade.exit_reason,
                f"{trade.hold_duration_seconds:.1f}",
                trade.indicator_name,
                f"{trade.entry_spread_pct:.4f}",
                f"{trade.atr_at_entry:.4f}",
                f"{trade.momentum_at_entry:.4f}",
            ])

    print(f"Wrote {len(trades)} trades to {filepath}")
    return filepath


def write_summary(result: SimulationResult, filename: str) -> str:
    """Write summary statistics to a text file.

    Args:
        result: SimulationResult with computed statistics
        filename: Output filename (without directory)

    Returns:
        Full path to written file
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w") as f:
        f.write("=" * 70 + "\n")
        f.write(f"BACKTESTING SUMMARY: {result.indicator_name}\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Date Range:    {result.start_date} to {result.end_date}\n")
        f.write(f"Tickers:       {', '.join(result.tickers)}\n")
        f.write(f"Generated:     {datetime.now().isoformat()}\n\n")

        f.write("-" * 40 + "\n")
        f.write("OVERALL STATISTICS\n")
        f.write("-" * 40 + "\n")
        f.write(f"Total Trades:           {result.total_trades}\n")
        f.write(f"Winning Trades:         {result.winning_trades}\n")
        f.write(f"Losing Trades:          {result.losing_trades}\n")
        f.write(f"Win Rate:               {result.win_rate:.1f}%\n")
        f.write(f"Total Profit (winners): {result.total_profit_pct:.2f}%\n")
        f.write(f"Total Loss (losers):    {result.total_loss_pct:.2f}%\n")
        f.write(f"Net P&L ($):            ${result.total_pnl_dollars:,.2f}\n")
        f.write(f"Profit Factor:          {result.profit_factor:.2f}\n")
        f.write(f"Max Drawdown:           {result.max_drawdown_pct:.2f}%\n")
        f.write(f"Sharpe Ratio:           {result.sharpe_ratio:.2f}\n")
        f.write(f"Avg Hold Duration:      {result.avg_hold_duration_seconds:.0f}s "
                f"({result.avg_hold_duration_seconds/60:.1f} min)\n")
        f.write(f"Avg Profit/Winner:      {result.avg_profit_per_winner:.2f}%\n")
        f.write(f"Avg Loss/Loser:         {result.avg_loss_per_loser:.2f}%\n\n")

        # Exit reason breakdown
        exit_reasons = {}
        for trade in result.trades:
            reason_key = trade.exit_reason.split("_")[0] if "_" in trade.exit_reason else trade.exit_reason
            # Normalize reason keys
            if "emergency" in trade.exit_reason:
                reason_key = "emergency_stop"
            elif "trailing" in trade.exit_reason:
                reason_key = "trailing_stop"
            elif "profit_target" in trade.exit_reason:
                reason_key = "profit_target"
            elif "force_close" in trade.exit_reason:
                reason_key = "force_close_eod"
            elif "ATR" in trade.exit_reason or "atr" in trade.exit_reason.lower():
                reason_key = "atr_stop_loss"
            elif "max_hold" in trade.exit_reason:
                reason_key = "max_hold_time"
            elif "early_exit" in trade.exit_reason.lower():
                reason_key = "early_exit"
            elif "initial" in trade.exit_reason.lower():
                reason_key = "initial_stop"
            elif "trend_reversal" in trade.exit_reason.lower():
                reason_key = "trend_reversal"
            elif "flat" in trade.exit_reason.lower():
                reason_key = "flat_trailing_stop"
            else:
                reason_key = trade.exit_reason[:30]

            if reason_key not in exit_reasons:
                exit_reasons[reason_key] = {"count": 0, "avg_pnl": 0.0, "total_pnl": 0.0}
            exit_reasons[reason_key]["count"] += 1
            exit_reasons[reason_key]["total_pnl"] += trade.profit_loss_pct

        f.write("-" * 40 + "\n")
        f.write("EXIT REASON BREAKDOWN\n")
        f.write("-" * 40 + "\n")
        f.write(f"{'Reason':<25} {'Count':>6} {'Avg P&L':>10} {'Total P&L':>10}\n")
        for reason, data in sorted(exit_reasons.items(), key=lambda x: -x[1]["count"]):
            avg = data["total_pnl"] / data["count"] if data["count"] > 0 else 0
            f.write(f"{reason:<25} {data['count']:>6} {avg:>9.2f}% {data['total_pnl']:>9.2f}%\n")
        f.write("\n")

        # Per-ticker breakdown
        f.write("-" * 40 + "\n")
        f.write("PER-TICKER BREAKDOWN\n")
        f.write("-" * 40 + "\n")
        f.write(f"{'Ticker':<8} {'Trades':>6} {'Wins':>5} {'Losses':>6} "
                f"{'Win%':>6} {'P&L%':>8} {'P&L$':>10} {'AvgHold':>8}\n")

        for ticker in sorted(result.per_ticker_stats.keys()):
            stats = result.per_ticker_stats[ticker]
            hold_min = stats["avg_hold_seconds"] / 60
            f.write(
                f"{ticker:<8} {stats['total_trades']:>6} {stats['winning_trades']:>5} "
                f"{stats['losing_trades']:>6} {stats['win_rate']:>5.1f}% "
                f"{stats['total_pnl_pct']:>7.2f}% "
                f"${stats['total_pnl_dollars']:>9.2f} "
                f"{hold_min:>6.1f}m\n"
            )

        f.write("\n" + "=" * 70 + "\n")

    print(f"Wrote summary to {filepath}")
    return filepath


def print_summary(result: SimulationResult):
    """Print summary statistics to console."""
    print("\n" + "=" * 70)
    print(f"  BACKTESTING RESULTS: {result.indicator_name}")
    print("=" * 70)
    print(f"  Date Range:    {result.start_date} to {result.end_date}")
    print(f"  Tickers:       {len(result.tickers)}")
    print(f"  Total Trades:  {result.total_trades}")
    print(f"  Win Rate:      {result.win_rate:.1f}%")
    print(f"  Profit Factor: {result.profit_factor:.2f}")
    print(f"  Net P&L:       ${result.total_pnl_dollars:,.2f}")
    print(f"  Max Drawdown:  {result.max_drawdown_pct:.2f}%")
    print(f"  Sharpe Ratio:  {result.sharpe_ratio:.2f}")
    print(f"  Avg Hold:      {result.avg_hold_duration_seconds/60:.1f} min")
    print(f"  Avg Win:       {result.avg_profit_per_winner:.2f}%")
    print(f"  Avg Loss:      {result.avg_loss_per_loser:.2f}%")
    print("=" * 70 + "\n")
