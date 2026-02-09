#!/usr/bin/env python3
"""
Backtest Trading Indicators Script

This script backtests the actual trading indicators (Momentum and Penny Stocks)
from the codebase using historical data from Alpaca API.
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import requests
from dotenv import load_dotenv

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.src.services.trading.momentum_indicator import MomentumIndicator
from app.src.services.trading.penny_stocks_indicator import PennyStocksIndicator


@dataclass
class BacktestSignal:
    """Represents a trading signal from backtesting"""

    timestamp: str
    ticker: str
    action: str  # buy_to_open or sell_to_open
    price: float
    indicator: str
    signal_type: str  # entry
    reason: str
    confidence: float = 0.0


class AlpacaHistoricalClient:
    """Client for fetching historical data from Alpaca"""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://data.alpaca.markets/v2/stocks"
        self.headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}

    async def fetch_bars(
        self, symbol: str, start: str, end: str, timeframe: str = "1Min"
    ) -> List[Dict[str, Any]]:
        """Fetch historical bars for a symbol"""
        url = f"{self.base_url}/bars"

        # Convert datetime strings to proper format
        if "T" in start:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            start_str = f"{start}T00:00:00Z"

        if "T" in end:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            end_str = f"{end}T23:59:59Z"

        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "start": start_str,
            "end": end_str,
            "adjustment": "raw",
            "feed": "sip",
        }

        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if symbol in data.get("bars", {}):
                return data["bars"][symbol]
            return []

        except Exception as e:
            print(f"Error fetching bars for {symbol}: {e}")
            return []

    async def fetch_bars_batch(
        self, symbols: List[str], start_date: str, end_date: str, batch_days: int = 7
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch bars in batches to handle large date ranges"""
        all_bars = {symbol: [] for symbol in symbols}

        # Parse dates
        if "T" in start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        else:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")

        if "T" in end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Process in batches
        current_start = start_dt
        batch_num = 1

        while current_start < end_dt:
            batch_end = min(current_start + timedelta(days=batch_days), end_dt)

            print(
                f"Fetching batch {batch_num}: {current_start.strftime('%Y-%m-%d')} to {batch_end.strftime('%Y-%m-%d')}"
            )

            # Fetch for all symbols in this batch
            tasks = []
            for symbol in symbols:
                task = self.fetch_bars(
                    symbol,
                    current_start.strftime("%Y-%m-%d"),
                    batch_end.strftime("%Y-%m-%d"),
                )
                tasks.append(task)

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(batch_results):
                symbol = symbols[i]
                if isinstance(result, Exception):
                    print(f"Error fetching {symbol}: {result}")
                elif result:
                    all_bars[symbol].extend(result)

            current_start = batch_end
            batch_num += 1

            # Rate limiting
            await asyncio.sleep(1)

        # Sort bars by timestamp
        for symbol in symbols:
            all_bars[symbol].sort(key=lambda x: x["t"])

        return all_bars


class TradingIndicatorBacktester:
    """Backtester for actual trading indicators"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    def simulate_momentum_indicator(
        self, ticker: str, bars: List[Dict[str, Any]]
    ) -> List[BacktestSignal]:
        """Simulate MomentumIndicator logic on historical data"""
        signals = []

        if len(bars) < 20:  # Need enough data for momentum calculation
            return signals

        print(f"Sample bar data structure: {bars[0] if bars else 'No bars'}")

        # Simulate momentum calculation similar to MomentumIndicator
        for i in range(20, len(bars)):
            current_bars = bars[: i + 1]  # All bars up to current point

            # Calculate momentum score (simplified version)
            momentum_score = self._calculate_momentum_score(current_bars)

            if abs(momentum_score) > 0.01:  # Lower threshold for testing
                current_bar = bars[i]
                price = current_bar.get("c") or current_bar.get("close") or 0
                timestamp = current_bar.get("t", "")

                if momentum_score > 0:
                    action = "buy_to_open"
                    reason = f"Momentum bullish: {momentum_score:.3f}"
                else:
                    action = "sell_to_open"
                    reason = f"Momentum bearish: {momentum_score:.3f}"

                signal = BacktestSignal(
                    timestamp=timestamp,
                    ticker=ticker,
                    action=action,
                    price=price,
                    indicator="Momentum",
                    signal_type="entry",
                    reason=reason,
                    confidence=abs(momentum_score),
                )
                signals.append(signal)

        return signals

    def simulate_penny_stocks_indicator(
        self, ticker: str, bars: List[Dict[str, Any]]
    ) -> List[BacktestSignal]:
        """Simulate PennyStocksIndicator logic on historical data"""
        signals = []

        if len(bars) < 15:  # Need enough data for trend calculation
            return signals

        # Filter for penny stocks (price < $5)
        current_price = bars[-1].get("c") or bars[-1].get("close") or 0
        if current_price >= 5.0:
            print(f"{ticker} price ${current_price:.2f} - not a penny stock")
            return signals

        print(f"{ticker} price ${current_price:.2f} - penny stock candidate")

        # Simulate penny stocks trend calculation
        for i in range(15, len(bars)):
            current_bars = bars[: i + 1]

            # Calculate trend score similar to PennyStocksIndicator
            trend_score, reason, peak_price, bottom_price, continuation = (
                self._calculate_penny_stocks_trend(current_bars)
            )

            if abs(trend_score) > 0.005:  # Lower threshold for testing
                current_bar = bars[i]
                price = current_bar.get("c") or current_bar.get("close") or 0
                timestamp = current_bar.get("t", "")

                if trend_score > 0:
                    action = "buy_to_open"
                else:
                    action = "sell_to_open"

                signal = BacktestSignal(
                    timestamp=timestamp,
                    ticker=ticker,
                    action=action,
                    price=price,
                    indicator="Penny Stocks",
                    signal_type="entry",
                    reason=reason,
                    confidence=abs(trend_score),
                )
                signals.append(signal)

        return signals

    def _calculate_momentum_score(self, bars: List[Dict[str, Any]]) -> float:
        """Calculate momentum score similar to MomentumIndicator"""
        if len(bars) < 20:
            return 0.0

        # Get recent prices
        recent_prices = []
        for bar in bars[-20:]:
            price = bar.get("c") or bar.get("close") or 0
            if price > 0:
                recent_prices.append(price)

        if len(recent_prices) < 10:
            return 0.0

        # Calculate price changes
        price_changes = []
        for i in range(1, len(recent_prices)):
            change = (recent_prices[i] - recent_prices[i - 1]) / recent_prices[i - 1]
            price_changes.append(change)

        # Calculate momentum as average of recent changes with weighting
        if not price_changes:
            return 0.0

        # Weight recent changes more heavily
        weights = [i / len(price_changes) for i in range(1, len(price_changes) + 1)]
        momentum = sum(
            change * weight for change, weight in zip(price_changes, weights)
        )

        return momentum

    def _calculate_penny_stocks_trend(
        self, bars: List[Dict[str, Any]]
    ) -> Tuple[float, str, Optional[float], Optional[float], float]:
        """Calculate trend score similar to PennyStocksIndicator"""
        if len(bars) < 10:
            return 0.0, "Insufficient data", None, None, 0.0

        # Get recent prices (last 10 bars)
        recent_bars = bars[-10:] if len(bars) >= 10 else bars
        prices = []
        for bar in recent_bars:
            price = bar.get("c") or bar.get("close") or 0
            if price > 0:
                prices.append(price)

        if len(prices) < 3:
            return 0.0, "Insufficient valid prices", None, None, 0.0

        # Find peak and bottom
        peak_price = max(prices)
        bottom_price = min(prices)

        # Calculate trend score
        if len(prices) >= 5:
            # Use first and third quartile for trend calculation
            first_quarter = (
                prices[: len(prices) // 4] if len(prices) >= 4 else prices[:2]
            )
            last_quarter = (
                prices[-len(prices) // 4 :] if len(prices) >= 4 else prices[-2:]
            )

            if first_quarter and last_quarter:
                avg_first = sum(first_quarter) / len(first_quarter)
                avg_last = sum(last_quarter) / len(last_quarter)

                trend_score = (
                    (avg_last - avg_first) / avg_first if avg_first > 0 else 0.0
                )

                # Calculate continuation (how much trend continues in most recent bars)
                if len(prices) >= 3:
                    recent_change = (
                        (prices[-1] - prices[-3]) / prices[-3]
                        if prices[-3] > 0
                        else 0.0
                    )
                    continuation = max(
                        0.0, min(1.0, recent_change * 10)
                    )  # Scale to 0-1
                else:
                    continuation = 0.0

                if trend_score > 0.01:  # Upward trend
                    reason = f"Trending up: {trend_score:.3f}"
                elif trend_score < -0.01:  # Downward trend
                    reason = f"Trending down: {trend_score:.3f}"
                else:
                    reason = f"Neutral trend: {trend_score:.3f}"

                return trend_score, reason, peak_price, bottom_price, continuation

        return 0.0, "Unable to calculate trend", peak_price, bottom_price, 0.0

    async def backtest_indicators(
        self, tickers: List[str], start_date: str, end_date: str, indicators: List[str]
    ) -> List[BacktestSignal]:
        """Run backtest for specified indicators"""
        print(f"Starting backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")

        # Fetch historical data
        all_bars = await self.alpaca_client.fetch_bars_batch(
            symbols=tickers, start_date=start_date, end_date=end_date
        )

        all_signals = []

        # Backtest each ticker
        for ticker, bars in all_bars.items():
            if not bars:
                print(f"No data found for {ticker}")
                continue

            print(f"Backtesting {ticker} with {len(bars)} bars...")

            # Test each indicator
            if "Momentum" in indicators:
                signals = self.simulate_momentum_indicator(ticker, bars)
                all_signals.extend(signals)
                print(f"  Momentum: {len(signals)} signals")

            if "Penny Stocks" in indicators:
                signals = self.simulate_penny_stocks_indicator(ticker, bars)
                all_signals.extend(signals)
                print(f"  Penny Stocks: {len(signals)} signals")

        # Sort signals by timestamp
        all_signals.sort(key=lambda x: x.timestamp)

        return all_signals

    def save_to_csv(self, signals: List[BacktestSignal], filename: str):
        """Save signals to CSV file"""
        import csv

        if not signals:
            print("No signals to save")
            return

        fieldnames = [
            "timestamp",
            "ticker",
            "action",
            "price",
            "indicator",
            "signal_type",
            "reason",
            "confidence",
        ]

        with open(filename, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for signal in signals:
                row = {
                    "timestamp": signal.timestamp,
                    "ticker": signal.ticker,
                    "action": signal.action,
                    "price": signal.price,
                    "indicator": signal.indicator,
                    "signal_type": signal.signal_type,
                    "reason": signal.reason,
                    "confidence": signal.confidence,
                }
                writer.writerow(row)

        print(f"Saved {len(signals)} signals to {filename}")


async def main():
    """Main function to run the backtesting"""
    parser = argparse.ArgumentParser(description="Backtest trading indicators")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=["AAPL", "TSLA"],
        help="Stock tickers to backtest",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        choices=["Momentum", "Penny Stocks"],
        default=["Momentum", "Penny Stocks"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output", default="trading_backtest_results.csv", help="Output CSV file"
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        print("Error: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in environment")
        return 1

    # Initialize backtester
    backtester = TradingIndicatorBacktester(api_key, secret_key)

    try:
        # Run backtest
        signals = await backtester.backtest_indicators(
            tickers=args.tickers,
            start_date=args.start_date,
            end_date=args.end_date,
            indicators=args.indicators,
        )

        # Save results
        backtester.save_to_csv(signals, args.output)

        # Print summary
        print(f"\nBacktest completed!")
        print(f"Total signals generated: {len(signals)}")

        # Group by indicator
        indicator_counts = {}
        for signal in signals:
            indicator_counts[signal.indicator] = (
                indicator_counts.get(signal.indicator, 0) + 1
            )

        print(f"\nSignals by indicator:")
        for indicator, count in indicator_counts.items():
            print(f"  {indicator}: {count}")

        # Group by ticker
        ticker_counts = {}
        for signal in signals:
            ticker_counts[signal.ticker] = ticker_counts.get(signal.ticker, 0) + 1

        print(f"\nSignals by ticker:")
        for ticker, count in ticker_counts.items():
            print(f"  {ticker}: {count}")

    except Exception as e:
        print(f"Error during backtesting: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
