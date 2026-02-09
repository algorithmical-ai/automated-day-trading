#!/usr/bin/env python3
"""
Simplified Backtest Trading Indicators Script

This script backtests trading indicators with lower thresholds to generate more signals for testing.
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
    technical_indicators: Dict[str, Any] = None


class AlpacaHistoricalClient:
    """Client for fetching historical data from Alpaca"""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://data.alpaca.markets/v2/stocks"
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }

    async def fetch_bars(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1Min",
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
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if symbol in data.get("bars", {}):
                return data["bars"][symbol]
            return []

        except Exception as e:
            print(f"Error fetching bars for {symbol}: {e}")
            return []

    async def fetch_bars_batch(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        batch_days: int = 7,
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


class SimplifiedBacktestEngine:
    """Simplified backtesting engine with lower thresholds"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # Real penny stocks that were under $5 in 2024
    PENNY_STOCKS = [
        "AMC",  # AMC Entertainment
        "GME",  # GameStop  
        "BB",   # BlackBerry
        "NOK",  # Nokia
        "SNDL", # Sundial Growers
        "BNGO", # Golden Entertainment
        "MVIS", # MicroVision
        "SPCE", # Virgin Galactic
        "BITF", # Bitfarms
        "RIOT", # Riot Blockchain
        "MARA", # Marathon Digital
        "HUT",  # Hut 8 Mining
    ]

    def simulate_momentum_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Simplified MomentumIndicator simulation with lower thresholds"""
        signals = []

        if len(bars) < 20:
            return signals

        print(f"Simulating Momentum for {ticker} with {len(bars)} bars")

        # Extract price data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]

        # Simulate momentum entry logic with very low thresholds for testing
        for i in range(20, len(bars)):
            current_bar = bars[i]
            timestamp = current_bar.get("t", "")
            price = float(current_bar.get("c", 0))

            # Simple momentum calculation
            if i >= 5:
                momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100
                momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
                momentum_20 = (prices[i] - prices[i-20]) / prices[i-20] * 100
                
                # Weighted momentum score
                momentum_score = (momentum_5 * 0.5 + momentum_10 * 0.3 + momentum_20 * 0.2)
                
                # Very low threshold for testing
                if abs(momentum_score) >= 0.5:  # Much lower than 1.5%
                    # Volume check
                    recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
                    avg_volume = sum(volumes[max(0, i-15):i-3]) / 12 if i > 15 else recent_volume
                    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
                    
                    # Lower volume requirement
                    if volume_ratio >= 1.2:  # Lower than 1.5
                        # Simple RSI approximation
                        rsi = self._simple_rsi(prices[max(0, i-14):i+1])
                        
                        if momentum_score > 0:  # Long entry
                            if 30.0 <= rsi <= 80.0:  # Wider RSI range
                                action = "buy_to_open"
                                reason = f"Momentum long: score={momentum_score:.2f}, rsi={rsi:.1f}, vol_ratio={volume_ratio:.1f}"
                                confidence = min(abs(momentum_score) / 3.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Momentum",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": rsi,
                                        "volume_ratio": volume_ratio,
                                    }
                                )
                                signals.append(signal)

                        elif momentum_score < 0:  # Short entry
                            if 20.0 <= rsi <= 70.0:  # Wider RSI range
                                action = "sell_to_open"
                                reason = f"Momentum short: score={momentum_score:.2f}, rsi={rsi:.1f}, vol_ratio={volume_ratio:.1f}"
                                confidence = min(abs(momentum_score) / 3.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Momentum",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": rsi,
                                        "volume_ratio": volume_ratio,
                                    }
                                )
                                signals.append(signal)

        return signals

    def simulate_penny_stocks_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Simplified PennyStocksIndicator simulation with lower thresholds"""
        signals = []

        if len(bars) < 15:
            return signals

        # Check if this is actually a penny stock
        current_price = float(bars[-1].get("c", 0))
        if not (0.10 <= current_price <= 10.0):  # Wider range for more candidates
            print(f"{ticker} price ${current_price:.2f} - not in penny stock range")
            return signals

        print(f"{ticker} price ${current_price:.2f} - penny stock candidate")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]

        # Track entries per day (one entry per ticker per day rule)
        entries_by_date = {}

        for i in range(15, len(bars)):
            current_bar = bars[i]
            timestamp = current_bar.get("t", "")
            price = float(current_bar.get("c", 0))
            
            # Extract date from timestamp
            if "T" in timestamp:
                date_str = timestamp.split("T")[0]
            else:
                date_str = timestamp[:10]

            # Skip if already entered today
            if date_str in entries_by_date:
                continue

            # Simplified penny stocks momentum calculation
            if i >= 5:
                momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100
                momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
                momentum_15 = (prices[i] - prices[i-15]) / prices[i-15] * 100 if i >= 15 else 0
                
                # Penny stocks momentum score
                momentum_score = (momentum_5 * 0.4 + momentum_10 * 0.4 + momentum_15 * 0.2)
                
                # Much lower threshold for penny stocks
                if abs(momentum_score) >= 1.0:  # Lower than 5%
                    # Volume filter
                    recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
                    avg_volume = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
                    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
                    
                    # Lower volume requirement for testing
                    if volume_ratio >= 1.5:  # Lower than 2.0
                        # Simple trend confirmation
                        if momentum_score > 0:
                            # Check if recent trend is upward
                            recent_trend = sum(prices[max(0, i-3):i]) - sum(prices[max(0, i-6):i-3])
                            trend_ok = recent_trend > 0
                        else:
                            # Check if recent trend is downward
                            recent_trend = sum(prices[max(0, i-3):i]) - sum(prices[max(0, i-6):i-3])
                            trend_ok = recent_trend < 0
                        
                        if trend_ok:
                            # Simple RSI
                            rsi = self._simple_rsi(prices[max(0, i-14):i+1])
                            
                            # Penny stocks typically only go long
                            if momentum_score > 0 and 20.0 <= rsi <= 80.0:  # Wide RSI range
                                action = "buy_to_open"
                                reason = f"Penny stock long: score={momentum_score:.2f}, rsi={rsi:.1f}, vol_ratio={volume_ratio:.1f}"
                                confidence = min(abs(momentum_score) / 5.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Penny Stocks",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": rsi,
                                        "volume_ratio": volume_ratio,
                                        "price": price,
                                    }
                                )
                                signals.append(signal)
                                
                                # Mark this date as having an entry
                                entries_by_date[date_str] = True

        return signals

    def _simple_rsi(self, prices: List[float], period: int = 14) -> float:
        """Simple RSI calculation"""
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
        else:
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0
        else:
            rs = avg_gain / avg_loss
            return 100.0 - (100.0 / (1.0 + rs))

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[BacktestSignal]:
        """Run backtest for specified indicators"""
        print(f"Starting simplified backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")

        # Fetch historical data
        all_bars = await self.alpaca_client.fetch_bars_batch(
            symbols=tickers, start_date=start_date, end_date=end_date
        )

        all_signals = []

        for ticker in tickers:
            bars = all_bars.get(ticker, [])
            if not bars:
                print(f"No data found for {ticker}")
                continue

            print(f"Backtesting {ticker} with {len(bars)} bars...")

            if "Momentum" in indicators:
                momentum_signals = self.simulate_momentum_indicator(ticker, bars)
                print(f"  Momentum: {len(momentum_signals)} signals")
                all_signals.extend(momentum_signals)

            if "Penny Stocks" in indicators:
                penny_signals = self.simulate_penny_stocks_indicator(ticker, bars)
                print(f"  Penny Stocks: {len(penny_signals)} signals")
                all_signals.extend(penny_signals)

        return all_signals

    def save_to_csv(self, signals: List[BacktestSignal], filename: str):
        """Save signals to CSV file"""
        import csv

        with open(filename, "w", newline="") as csvfile:
            fieldnames = [
                "timestamp",
                "ticker",
                "action",
                "price",
                "indicator",
                "signal_type",
                "reason",
                "confidence",
                "momentum_score",
                "rsi",
                "volume_ratio",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for signal in signals:
                indicators = signal.technical_indicators or {}
                
                row = {
                    "timestamp": signal.timestamp,
                    "ticker": signal.ticker,
                    "action": signal.action,
                    "price": signal.price,
                    "indicator": signal.indicator,
                    "signal_type": signal.signal_type,
                    "reason": signal.reason,
                    "confidence": signal.confidence,
                    "momentum_score": indicators.get("momentum_score", ""),
                    "rsi": indicators.get("rsi", ""),
                    "volume_ratio": indicators.get("volume_ratio", ""),
                }
                writer.writerow(row)

        print(f"Saved {len(signals)} signals to {filename}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Backtest trading indicators")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help="Ticker symbols (if empty, uses default penny stocks)",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=["Momentum", "Penny Stocks"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output",
        default="simplified_trading_backtest.csv",
        help="Output CSV filename",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        print("Error: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        return

    # Use default penny stocks if no tickers provided
    if not args.tickers:
        engine = SimplifiedBacktestEngine(api_key, secret_key)
        tickers = engine.PENNY_STOCKS
        print(f"Using default penny stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = SimplifiedBacktestEngine(api_key, secret_key)
    signals = await engine.backtest_indicators(
        tickers, args.start_date, args.end_date, args.indicators
    )

    # Save results
    engine.save_to_csv(signals, args.output)

    # Print summary
    print("\nBacktest completed!")
    print(f"Total signals generated: {len(signals)}")

    if signals:
        # Count by indicator
        indicator_counts = {}
        ticker_counts = {}
        for signal in signals:
            indicator_counts[signal.indicator] = indicator_counts.get(signal.indicator, 0) + 1
            ticker_counts[signal.ticker] = ticker_counts.get(signal.ticker, 0) + 1

        print("\nSignals by indicator:")
        for indicator, count in sorted(indicator_counts.items()):
            print(f"  {indicator}: {count}")

        print("\nSignals by ticker:")
        for ticker, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {ticker}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
