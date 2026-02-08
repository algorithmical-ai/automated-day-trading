"""
Historical Data Fetcher for Backtesting.

Fetches 1-minute bars from Alpaca Markets API and caches to disk.
Uses synchronous requests (not async) for simplicity.
"""

import os
import time
import gzip
import pickle
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from backtesting.config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ALPACA_BASE_URL,
    CACHE_DIR,
    REQUEST_DELAY_SECONDS,
    BARS_TIMEFRAME,
    START_DATE,
    END_DATE,
)


def _get_trading_days(start_date: str, end_date: str) -> List[str]:
    """Generate list of weekday dates between start and end (inclusive).

    We fetch day-by-day to stay within API limits and handle pagination per day.
    Non-trading days (holidays) will simply return no bars.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    days = []
    current = start
    while current <= end:
        # Only weekdays (Mon=0, Fri=4)
        if current.weekday() < 5:
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return days


def _fetch_bars_for_day(
    ticker: str,
    date: str,
    session: requests.Session,
) -> List[Dict[str, Any]]:
    """Fetch all 1-min bars for a ticker on a single trading day.

    Handles pagination via next_page_token.

    Args:
        ticker: Stock symbol
        date: Date string YYYY-MM-DD
        session: requests.Session with auth headers

    Returns:
        List of bar dicts with keys: t, o, h, l, c, v, n, vw
    """
    all_bars = []
    next_page_token = None

    start = f"{date}T09:30:00-04:00"  # Market open ET (approximate; DST handled by Alpaca)
    end = f"{date}T16:00:00-04:00"    # Market close ET

    while True:
        params = {
            "timeframe": BARS_TIMEFRAME,
            "start": start,
            "end": end,
            "limit": 10000,
            "adjustment": "raw",
            "feed": "sip",
        }
        if next_page_token:
            params["page_token"] = next_page_token

        url = f"{ALPACA_BASE_URL}/stocks/{ticker}/bars"

        try:
            resp = session.get(url, params=params)

            if resp.status_code == 429:
                # Rate limited - wait and retry
                print(f"  Rate limited for {ticker} on {date}, waiting 5s...")
                time.sleep(5)
                continue

            if resp.status_code == 422:
                # Invalid ticker or no data
                return []

            resp.raise_for_status()
            data = resp.json()

            bars = data.get("bars", [])
            if bars:
                all_bars.extend(bars)

            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break

            time.sleep(REQUEST_DELAY_SECONDS)

        except requests.exceptions.RequestException as e:
            print(f"  Error fetching {ticker} on {date}: {e}")
            break

    return all_bars


def fetch_ticker_data(
    ticker: str,
    start_date: str = START_DATE,
    end_date: str = END_DATE,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """Fetch all 1-min bars for a ticker over the date range.

    Checks disk cache first. If cached data exists and force_refresh is False,
    loads from cache. Otherwise fetches from Alpaca API day-by-day.

    Args:
        ticker: Stock symbol
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        force_refresh: If True, skip cache and refetch

    Returns:
        List of bar dicts sorted by timestamp, with keys:
        t (timestamp), o (open), h (high), l (low), c (close), v (volume)
    """
    # Check cache
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{ticker}_{start_date}_{end_date}_1min.pkl.gz")

    if not force_refresh and os.path.exists(cache_file):
        try:
            with gzip.open(cache_file, "rb") as f:
                cached_bars = pickle.load(f)
            print(f"  Loaded {len(cached_bars):,} bars for {ticker} from cache")
            return cached_bars
        except Exception as e:
            print(f"  Cache load failed for {ticker}: {e}, refetching...")

    # Fetch from API
    session = requests.Session()
    session.headers.update({
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    })

    trading_days = _get_trading_days(start_date, end_date)
    all_bars = []

    print(f"  Fetching {ticker}: {len(trading_days)} trading days...")

    for i, day in enumerate(trading_days):
        bars = _fetch_bars_for_day(ticker, day, session)
        if bars:
            all_bars.extend(bars)

        # Progress update every 50 days
        if (i + 1) % 50 == 0:
            print(f"    {ticker}: {i+1}/{len(trading_days)} days, {len(all_bars):,} bars so far")

        # Rate limit
        time.sleep(REQUEST_DELAY_SECONDS)

    # Sort by timestamp
    all_bars.sort(key=lambda b: b.get("t", ""))

    print(f"  Fetched {len(all_bars):,} bars for {ticker}")

    # Save to cache
    if all_bars:
        try:
            with gzip.open(cache_file, "wb") as f:
                pickle.dump(all_bars, f)
            print(f"  Cached {ticker} to disk")
        except Exception as e:
            print(f"  Failed to cache {ticker}: {e}")

    session.close()
    return all_bars


def fetch_all_tickers(
    tickers: List[str],
    start_date: str = START_DATE,
    end_date: str = END_DATE,
    force_refresh: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch data for all tickers.

    Args:
        tickers: List of ticker symbols
        start_date: Start date
        end_date: End date
        force_refresh: If True, skip cache

    Returns:
        Dict mapping ticker -> list of bars
    """
    result = {}

    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Processing {ticker}...")
        bars = fetch_ticker_data(ticker, start_date, end_date, force_refresh)

        if bars:
            result[ticker] = bars
        else:
            print(f"  WARNING: No data for {ticker}, skipping")

    return result


def group_bars_by_day(bars: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group bars by trading date.

    Args:
        bars: List of bar dicts with 't' (timestamp) key

    Returns:
        Dict mapping date string (YYYY-MM-DD) -> list of bars for that day
    """
    days = {}

    for bar in bars:
        ts = bar.get("t", "")
        if not ts:
            continue

        # Extract date from ISO timestamp
        # Timestamps look like "2024-01-15T09:30:00Z" or "2024-01-15T09:30:00-05:00"
        date_str = ts[:10]

        if date_str not in days:
            days[date_str] = []
        days[date_str].append(bar)

    # Sort bars within each day by timestamp
    for date_str in days:
        days[date_str].sort(key=lambda b: b.get("t", ""))

    return days
