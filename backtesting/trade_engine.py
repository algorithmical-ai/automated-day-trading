"""
Bar-by-Bar Trade Simulation Engine.

Processes historical bars through indicator simulators, managing positions
and generating trade records.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime

from backtesting.models import ActivePosition, TradeRecord, SimulationResult
from backtesting.technical_analysis import calculate_indicators, MIN_BARS_FOR_TA
from backtesting.data_fetcher import group_bars_by_day
from backtesting.indicators.base_simulator import BaseIndicatorSimulator
from backtesting.config import FORCE_CLOSE_MINUTES_BEFORE


# Rolling window size for TA computation
TA_WINDOW_SIZE = 50


def _parse_bar_timestamp(bar: Dict[str, Any]) -> Optional[datetime]:
    """Parse timestamp from a bar dict.

    Handles formats like:
    - "2024-01-15T09:30:00Z"
    - "2024-01-15T09:30:00-05:00"
    - "2024-01-15T09:30:00+00:00"
    """
    ts = bar.get("t", "")
    if not ts:
        return None

    try:
        # Handle 'Z' suffix
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"

        dt = datetime.fromisoformat(ts)

        # Convert to naive datetime (we treat all times as ET for simplicity)
        # Alpaca returns UTC; market hours are 9:30-16:00 ET = 14:30-21:00 UTC
        # For simplicity, we'll subtract 5 hours (EST) or 4 hours (EDT)
        # This is approximate but sufficient for backtesting entry/exit timing
        if dt.tzinfo is not None:
            # Convert UTC to ET (approximate: assume EST = UTC-5)
            from datetime import timedelta, timezone
            utc_offset = dt.utcoffset()
            if utc_offset is not None:
                # If already in ET (offset -4 or -5), use as-is minus tzinfo
                offset_hours = utc_offset.total_seconds() / 3600
                if offset_hours == 0:
                    # UTC -> subtract 5 hours for EST (approximate)
                    dt = dt.replace(tzinfo=None) - timedelta(hours=5)
                else:
                    dt = dt.replace(tzinfo=None)
            else:
                dt = dt.replace(tzinfo=None)

        return dt
    except (ValueError, TypeError):
        return None


def simulate_ticker(
    ticker: str,
    bars: List[Dict[str, Any]],
    simulator: BaseIndicatorSimulator,
    start_date: str = "",
    end_date: str = "",
) -> List[TradeRecord]:
    """Run simulation for a single ticker across all its bars.

    Processes bars day-by-day. Within each day:
    1. Maintain a rolling TA_WINDOW_SIZE bar window
    2. Calculate indicators on the window
    3. Check exits first (if in position), then entries
    4. Force-close all positions at end of day

    Args:
        ticker: Stock symbol
        bars: All 1-min bars for this ticker (sorted by timestamp)
        simulator: The indicator simulator to use
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        List of TradeRecord for all completed trades
    """
    all_trades = []

    # Group by day
    days = group_bars_by_day(bars)

    # Sort days chronologically
    sorted_days = sorted(days.keys())

    # Filter by date range if specified
    if start_date:
        sorted_days = [d for d in sorted_days if d >= start_date]
    if end_date:
        sorted_days = [d for d in sorted_days if d <= end_date]

    print(f"    Simulating {ticker}: {len(sorted_days)} trading days")

    for day_idx, date_str in enumerate(sorted_days):
        day_bars = days[date_str]

        if len(day_bars) < 10:
            continue  # Skip thin trading days

        # Track state for this day
        active_positions: Dict[str, ActivePosition] = {}
        daily_trade_count = 0
        rolling_window: List[Dict[str, Any]] = []

        for bar_idx, bar in enumerate(day_bars):
            current_time = _parse_bar_timestamp(bar)
            if current_time is None:
                continue

            # Skip pre-market and after-hours (keep 9:30-16:00 ET)
            if current_time.hour < 9 or (current_time.hour == 9 and current_time.minute < 30):
                # Still add to rolling window for TA warmup
                rolling_window.append(bar)
                if len(rolling_window) > TA_WINDOW_SIZE:
                    rolling_window = rolling_window[-TA_WINDOW_SIZE:]
                continue

            if current_time.hour >= 16:
                continue

            # Update rolling window
            rolling_window.append(bar)
            if len(rolling_window) > TA_WINDOW_SIZE:
                rolling_window = rolling_window[-TA_WINDOW_SIZE:]

            # Calculate indicators (every bar for accuracy, or could optimize to every N bars)
            indicators = {}
            if len(rolling_window) >= MIN_BARS_FOR_TA:
                indicators = calculate_indicators(rolling_window)
            elif len(rolling_window) >= 5:
                indicators = calculate_indicators(rolling_window)

            # --- CHECK EXITS FIRST ---
            tickers_to_close = []
            for pos_ticker, position in active_positions.items():
                exit_result = simulator.should_exit(
                    position, bar, rolling_window, indicators, current_time
                )
                if exit_result:
                    exit_reason, exit_price = exit_result

                    # Create trade record
                    trade = _create_trade_record(
                        position, exit_price, exit_reason, current_time, simulator.indicator_name()
                    )
                    all_trades.append(trade)
                    daily_trade_count += 1
                    tickers_to_close.append(pos_ticker)

            # Remove closed positions
            for t in tickers_to_close:
                del active_positions[t]

            # --- CHECK ENTRIES ---
            if ticker not in active_positions:
                entry_result = simulator.should_enter(
                    ticker, bar, rolling_window, indicators,
                    current_time, active_positions, daily_trade_count
                )

                if entry_result:
                    direction, entry_price, position_size, atr_stop, spread_pct = entry_result

                    if entry_price > 0 and position_size > 0:
                        shares = position_size / entry_price

                        # Calculate breakeven accounting for spread
                        breakeven = SpreadCalculator.calculate_breakeven_price(
                            entry_price, spread_pct, is_long=(direction == "long")
                        ) if spread_pct > 0 else entry_price

                        position = ActivePosition(
                            ticker=ticker,
                            direction=direction,
                            entry_price=entry_price,
                            breakeven_price=breakeven,
                            shares=shares,
                            position_value=position_size,
                            entry_time=current_time,
                            entry_bar_index=bar_idx,
                            peak_price=entry_price,
                            atr_stop_percent=atr_stop,
                            spread_percent=spread_pct,
                            indicator_name=simulator.indicator_name(),
                        )
                        active_positions[ticker] = position

        # --- END OF DAY: Force close remaining positions ---
        for pos_ticker, position in list(active_positions.items()):
            # Use last bar of the day for exit
            last_bar = day_bars[-1]
            last_time = _parse_bar_timestamp(last_bar) or current_time
            exit_price = simulator.estimate_exit_price(last_bar, position.direction)

            trade = _create_trade_record(
                position, exit_price, "force_close_eod", last_time, simulator.indicator_name()
            )
            all_trades.append(trade)
            daily_trade_count += 1

        # Progress every 50 days
        if (day_idx + 1) % 50 == 0:
            print(f"      {ticker}: {day_idx+1}/{len(sorted_days)} days, {len(all_trades)} trades")

    print(f"    {ticker}: Completed - {len(all_trades)} total trades")
    return all_trades


# Need to import SpreadCalculator at module level for use in simulate_ticker
from app.src.services.trading.penny_stock_utils import SpreadCalculator


def _create_trade_record(
    position: ActivePosition,
    exit_price: float,
    exit_reason: str,
    exit_time: datetime,
    indicator_name: str,
) -> TradeRecord:
    """Create a TradeRecord from a position and exit info."""
    is_long = position.direction == "long"

    # Calculate P&L
    if is_long:
        pnl_pct = ((exit_price - position.entry_price) / position.entry_price) * 100
    else:
        pnl_pct = ((position.entry_price - exit_price) / position.entry_price) * 100

    pnl_dollars = pnl_pct / 100 * position.position_value

    hold_secs = (exit_time - position.entry_time).total_seconds()

    # Determine actions
    if is_long:
        action = "buy_to_open"
        close_action = "sell_to_close"
    else:
        action = "sell_to_open"
        close_action = "buy_to_close"

    return TradeRecord(
        date=position.entry_time.strftime("%Y-%m-%d"),
        entry_time=position.entry_time.isoformat(),
        exit_time=exit_time.isoformat(),
        ticker=position.ticker,
        action=action,
        close_action=close_action,
        direction=position.direction,
        entry_price=position.entry_price,
        exit_price=exit_price,
        shares=position.shares,
        position_value=position.position_value,
        profit_loss_pct=round(pnl_pct, 4),
        profit_loss_dollars=round(pnl_dollars, 2),
        exit_reason=exit_reason,
        hold_duration_seconds=round(hold_secs, 1),
        indicator_name=indicator_name,
        entry_spread_pct=round(position.spread_percent, 4),
        atr_at_entry=0.0,  # Could be added
        momentum_at_entry=position.momentum_at_entry,
        confidence_at_entry=position.confidence_at_entry,
    )


def run_simulation(
    ticker_data: Dict[str, List[Dict[str, Any]]],
    simulator: BaseIndicatorSimulator,
    start_date: str = "",
    end_date: str = "",
) -> SimulationResult:
    """Run full simulation across all tickers.

    Args:
        ticker_data: Dict mapping ticker -> list of bars
        simulator: Indicator simulator to use
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        SimulationResult with all trades and statistics
    """
    all_trades = []

    tickers = sorted(ticker_data.keys())
    print(f"\nRunning {simulator.indicator_name()} simulation for {len(tickers)} tickers...")

    for i, ticker in enumerate(tickers):
        bars = ticker_data[ticker]
        print(f"  [{i+1}/{len(tickers)}] {ticker} ({len(bars):,} bars)")

        trades = simulate_ticker(ticker, bars, simulator, start_date, end_date)
        all_trades.extend(trades)

    # Sort trades by entry time
    all_trades.sort(key=lambda t: t.entry_time)

    # Build result
    result = SimulationResult(
        indicator_name=simulator.indicator_name(),
        tickers=tickers,
        start_date=start_date or (all_trades[0].date if all_trades else ""),
        end_date=end_date or (all_trades[-1].date if all_trades else ""),
        trades=all_trades,
    )
    result.calculate_statistics()

    return result
