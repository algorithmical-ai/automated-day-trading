"""
Backtesting CLI Entry Point.

Usage:
    python -m backtesting.backtest --indicator momentum
    python -m backtesting.backtest --indicator penny
    python -m backtesting.backtest --indicator both
    python -m backtesting.backtest --indicator momentum --tickers AAPL,MSFT --days 30
    python -m backtesting.backtest --indicator penny --start 2024-01-01 --end 2024-06-30
"""

import argparse
import sys
import os
from datetime import datetime, timedelta

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backtesting.config import (
    MOMENTUM_TICKERS,
    PENNY_STOCK_TICKERS,
    START_DATE,
    END_DATE,
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
)
from backtesting.data_fetcher import fetch_all_tickers
from backtesting.trade_engine import run_simulation
from backtesting.output import write_trades_csv, write_summary, print_summary
from backtesting.indicators.momentum_sim import MomentumSimulator
from backtesting.indicators.penny_stocks_sim import PennyStocksSimulator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backtest Momentum and Penny Stock trading indicators"
    )
    parser.add_argument(
        "--indicator",
        choices=["momentum", "penny", "both"],
        required=True,
        help="Which indicator to backtest"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Comma-separated ticker list (overrides defaults)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help="Number of days to backtest (overrides --start)"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="",
        help="Start date YYYY-MM-DD (default: 1 year ago)"
    )
    parser.add_argument(
        "--end",
        type=str,
        default="",
        help="End date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force re-download of cached data"
    )
    return parser.parse_args()


def run_backtest(
    indicator_type: str,
    tickers: list,
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
):
    """Run backtest for a specific indicator.

    Args:
        indicator_type: "momentum" or "penny"
        tickers: List of ticker symbols
        start_date: Start date string
        end_date: End date string
        force_refresh: Force re-download data
    """
    # Create simulator
    if indicator_type == "momentum":
        simulator = MomentumSimulator()
    else:
        simulator = PennyStocksSimulator()

    print(f"\n{'='*70}")
    print(f"  BACKTESTING: {simulator.indicator_name()}")
    print(f"  Period: {start_date} to {end_date}")
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"{'='*70}\n")

    # Step 1: Fetch data
    print("Step 1: Fetching historical data...")
    ticker_data = fetch_all_tickers(tickers, start_date, end_date, force_refresh)

    if not ticker_data:
        print("ERROR: No data fetched for any ticker. Check API keys and ticker symbols.")
        return None

    total_bars = sum(len(bars) for bars in ticker_data.values())
    print(f"\nData fetched: {len(ticker_data)} tickers, {total_bars:,} total bars\n")

    # Step 2: Run simulation
    print("Step 2: Running simulation...")
    result = run_simulation(ticker_data, simulator, start_date, end_date)

    # Step 3: Output results
    print("\nStep 3: Writing results...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Write trades CSV
    csv_filename = f"{indicator_type}_trades_{timestamp}.csv"
    write_trades_csv(result.trades, csv_filename)

    # Write summary
    summary_filename = f"{indicator_type}_summary_{timestamp}.txt"
    write_summary(result, summary_filename)

    # Print to console
    print_summary(result)

    return result


def main():
    args = parse_args()

    # Validate API keys
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("ERROR: Alpaca API keys not found.")
        print("Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
        print("")
        print("Example:")
        print("  export ALPACA_API_KEY=your_key_here")
        print("  export ALPACA_SECRET_KEY=your_secret_here")
        sys.exit(1)

    # Determine dates
    end_date = args.end if args.end else END_DATE
    if args.days > 0:
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    else:
        start_date = args.start if args.start else START_DATE

    # Run momentum backtest
    if args.indicator in ("momentum", "both"):
        tickers = args.tickers.split(",") if args.tickers else MOMENTUM_TICKERS
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        run_backtest("momentum", tickers, start_date, end_date, args.force_refresh)

    # Run penny stocks backtest
    if args.indicator in ("penny", "both"):
        tickers = args.tickers.split(",") if args.tickers else PENNY_STOCK_TICKERS
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        run_backtest("penny", tickers, start_date, end_date, args.force_refresh)

    print("\nBacktesting complete!")


if __name__ == "__main__":
    main()
