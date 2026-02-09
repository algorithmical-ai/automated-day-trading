#!/usr/bin/env python3
"""
Profit-Optimized Backtest Trading Indicators Script

This script focuses on PROFITABLE trades - optimized holding periods and exit strategies.
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


class ProfitOptimizedBacktestEngine:
    """Profit-optimized backtesting engine - focuses on profitable trades"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # High-quality stocks with good volatility and liquidity
    PROFIT_STOCKS = [
        "AAPL",  # Apple - stable but good moves
        "TSLA",  # Tesla - high volatility, good for momentum
        "NVDA",  # NVIDIA - strong trends
        "AMD",   # AMD - good momentum
        "META",  # Meta - volatile
        "NFLX",  # Netflix - good trends
        "AMZN",  # Amazon - large cap but moves
        "GOOGL", # Google - stable
        "MSFT",  # Microsoft - tech leader
        "SPY",   # SPY ETF - market proxy
    ]

    def simulate_profit_momentum_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Profit-optimized MomentumIndicator - focuses on profitable setups"""
        signals = []

        if len(bars) < 25:
            return signals

        print(f"Simulating Profit Momentum for {ticker} with {len(bars)} bars")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]

        # Track entries per day (max 2 trades per day for quality)
        entries_by_date = {}

        for i in range(25, len(bars)):
            current_bar = bars[i]
            timestamp = current_bar.get("t", "")
            price = float(current_bar.get("c", 0))
            
            # Extract date from timestamp
            if "T" in timestamp:
                date_str = timestamp.split("T")[0]
            else:
                date_str = timestamp[:10]

            # Skip if already have 2 trades today
            if entries_by_date.get(date_str, 0) >= 2:
                continue

            # Profit-focused momentum calculation
            momentum_score = self._calculate_profit_momentum(prices, volumes, highs, lows, i)
            
            # Optimized threshold for profitability
            if abs(momentum_score) >= 0.8:  # 0.8% minimum momentum
                # Volume confirmation
                volume_analysis = self._analyze_volume_quality(volumes, i)
                
                if volume_analysis["volume_ratio"] >= 1.5:  # 1.5x average volume
                    # Technical analysis
                    tech_analysis = self._profit_technical_analysis(prices, highs, lows, i)
                    
                    # Profit-focused entry conditions
                    if momentum_score > 0:  # Long entry
                        if (tech_analysis["rsi"] >= 40.0 and tech_analysis["rsi"] <= 75.0 and  # Reasonable RSI
                            tech_analysis["trend_strength"] >= 0.3 and  # Moderate uptrend
                            tech_analysis["price_position"] >= 0.4 and  # Above lower half
                            tech_analysis["volatility"] >= 0.01):  # Minimum volatility
                            
                            # Profit quality filters
                            if self._profit_quality_filters(prices, volumes, i, is_long=True):
                                action = "buy_to_open"
                                reason = f"PROFIT Momentum long: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x"
                                confidence = min(abs(momentum_score) / 3.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Profit Momentum",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": tech_analysis["rsi"],
                                        "trend_strength": tech_analysis["trend_strength"],
                                        "volume_ratio": volume_analysis["volume_ratio"],
                                        "price_position": tech_analysis["price_position"],
                                        "volatility": tech_analysis["volatility"],
                                    }
                                )
                                signals.append(signal)
                                entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1

                    elif momentum_score < 0:  # Short entry
                        if (tech_analysis["rsi"] >= 55.0 and tech_analysis["rsi"] <= 80.0 and  # Near overbought
                            tech_analysis["trend_strength"] <= -0.3 and  # Moderate downtrend
                            tech_analysis["price_position"] <= 0.6 and  # Below upper half
                            tech_analysis["volatility"] >= 0.01):  # Minimum volatility
                            
                            # Profit quality filters
                            if self._profit_quality_filters(prices, volumes, i, is_long=False):
                                action = "sell_to_open"
                                reason = f"PROFIT Momentum short: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x"
                                confidence = min(abs(momentum_score) / 3.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Profit Momentum",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": tech_analysis["rsi"],
                                        "trend_strength": tech_analysis["trend_strength"],
                                        "volume_ratio": volume_analysis["volume_ratio"],
                                        "price_position": tech_analysis["price_position"],
                                        "volatility": tech_analysis["volatility"],
                                    }
                                )
                                signals.append(signal)
                                entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1

        return signals

    def _calculate_profit_momentum(
        self, 
        prices: List[float], 
        volumes: List[float], 
        highs: List[float], 
        lows: List[float], 
        i: int
    ) -> float:
        """Profit-focused momentum calculation"""
        if i < 20:
            return 0.0

        # Multiple timeframe momentum with profit focus
        momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        momentum_20 = (prices[i] - prices[i-20]) / prices[i-20] * 100 if i >= 20 else 0
        
        # Weight recent momentum more heavily for quick profits
        momentum_score = (momentum_2 * 0.4 + momentum_5 * 0.3 + momentum_10 * 0.2 + momentum_20 * 0.1)
        
        # Volume-weighted momentum (important for profitability)
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
        volume_weight = min(recent_volume / avg_volume, 2.0) if avg_volume > 0 else 1.0
        
        # Price range momentum (breakout potential)
        recent_high = max(highs[max(0, i-5):i])
        recent_low = min(lows[max(0, i-5):i])
        range_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        # Volatility boost (higher volatility = more profit potential)
        recent_volatility = (max(prices[max(0, i-5):i+1]) - min(prices[max(0, i-5):i+1])) / prices[i]
        volatility_boost = 1.0 + min(recent_volatility * 10, 1.0)  # Max 2x boost
        
        # Final momentum score with profit factors
        final_momentum = momentum_score * volume_weight * (0.7 + range_position * 0.3) * volatility_boost
        
        return final_momentum

    def _analyze_volume_quality(self, volumes: List[float], i: int) -> Dict[str, float]:
        """Analyze volume quality for profitability"""
        # Recent volume analysis
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume_5 = sum(volumes[max(0, i-8):i-3]) / 5 if i > 8 else recent_volume
        avg_volume_20 = sum(volumes[max(0, i-20):i-5]) / 15 if i > 20 else recent_volume
        
        volume_ratio_5 = recent_volume / avg_volume_5 if avg_volume_5 > 0 else 1.0
        volume_ratio_20 = recent_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
        
        # Volume trend (increasing volume is good for profits)
        volume_trend = (volumes[i] - volumes[max(0, i-5)]) / volumes[max(0, i-5)] if i > 5 and volumes[max(0, i-5)] > 0 else 0
        
        return {
            "volume_ratio": max(volume_ratio_5, volume_ratio_20),
            "volume_trend": volume_trend,
            "recent_volume": recent_volume,
        }

    def _profit_technical_analysis(self, prices: List[float], highs: List[float], lows: List[float], i: int) -> Dict[str, float]:
        """Profit-focused technical analysis"""
        if i < 20:
            return {"rsi": 50.0, "trend_strength": 0.0, "price_position": 0.5, "volatility": 0.01}
        
        # RSI calculation
        rsi = self._profit_rsi(prices[max(0, i-14):i+1])
        
        # Trend strength calculation (profit-focused)
        short_trend = (prices[i] - prices[i-3]) / prices[i-3] if i >= 3 else 0
        medium_trend = (prices[i] - prices[i-8]) / prices[i-8] if i >= 8 else 0
        long_trend = (prices[i] - prices[i-15]) / prices[i-15] if i >= 15 else 0
        
        # Weighted trend strength
        trend_strength = (short_trend * 0.5 + medium_trend * 0.3 + long_trend * 0.2) / 3.0
        trend_strength = max(-1.0, min(1.0, trend_strength))
        
        # Price position in recent range
        recent_high = max(highs[max(0, i-8):i])
        recent_low = min(lows[max(0, i-8):i])
        price_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        # Volatility (important for profit potential)
        recent_prices = prices[max(0, i-10):i+1]
        volatility = (max(recent_prices) - min(recent_prices)) / sum(recent_prices) * len(recent_prices) if recent_prices else 0.01
        
        return {
            "rsi": rsi,
            "trend_strength": trend_strength,
            "price_position": price_position,
            "volatility": volatility,
        }

    def _profit_rsi(self, prices: List[float], period: int = 14) -> float:
        """Profit-focused RSI calculation"""
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

    def _profit_quality_filters(self, prices: List[float], volumes: List[float], i: int, is_long: bool) -> bool:
        """Profit-focused quality filters"""
        if i < 10:
            return False
        
        # Price stability check (avoid erratic stocks)
        recent_prices = prices[max(0, i-8):i+1]
        price_volatility = max(recent_prices) - min(recent_prices)
        avg_price = sum(recent_prices) / len(recent_prices)
        volatility_ratio = price_volatility / avg_price if avg_price > 0 else 1.0
        
        # Allow moderate volatility (good for profits)
        if volatility_ratio < 0.005 or volatility_ratio > 0.15:  # Too stable or too volatile
            return False
        
        # Volume consistency check
        recent_volumes = volumes[max(0, i-3):i+1]
        volume_consistency = min(recent_volumes) / max(recent_volumes) if max(recent_volumes) > 0 else 0
        
        if volume_consistency < 0.2:  # Volume varies too much
            return False
        
        # Price momentum consistency (important for profits)
        if is_long:
            # For long: recent momentum should be positive
            momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
            momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
            return momentum_2 > 0 and momentum_5 > 0
        else:
            # For short: recent momentum should be negative
            momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
            momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
            return momentum_2 < 0 and momentum_5 < 0
        
        return True

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[BacktestSignal]:
        """Run profit-optimized backtest"""
        print(f"Starting PROFIT-OPTIMIZED backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")
        print("💰 FOCUS: Profitable trades with optimized holding periods")

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
                momentum_signals = self.simulate_profit_momentum_indicator(ticker, bars)
                print(f"  Profit Momentum: {len(momentum_signals)} signals")
                all_signals.extend(momentum_signals)

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
                "trend_strength",
                "volume_ratio",
                "price_position",
                "volatility",
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
                    "trend_strength": indicators.get("trend_strength", ""),
                    "volume_ratio": indicators.get("volume_ratio", ""),
                    "price_position": indicators.get("price_position", ""),
                    "volatility": indicators.get("volatility", ""),
                }
                writer.writerow(row)

        print(f"Saved {len(signals)} PROFIT signals to {filename}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Profit-optimized backtest")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help="Ticker symbols (if empty, uses profit stocks)",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=["Momentum"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output",
        default="profit_trading_backtest.csv",
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

    # Use profit stocks if no tickers provided
    if not args.tickers:
        engine = ProfitOptimizedBacktestEngine(api_key, secret_key)
        tickers = engine.PROFIT_STOCKS
        print(f"Using profit stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = ProfitOptimizedBacktestEngine(api_key, secret_key)
    signals = await engine.backtest_indicators(
        tickers, args.start_date, args.end_date, args.indicators
    )

    # Save results
    engine.save_to_csv(signals, args.output)

    # Print summary
    print("\n💰 PROFIT-OPTIMIZED BACKTEST COMPLETED!")
    print(f"Total signals generated: {len(signals)}")
    print("🎯 Goal: Profitable trades with optimized holding periods")

    if signals:
        # Count by indicator
        indicator_counts = {}
        ticker_counts = {}
        for signal in signals:
            indicator_counts[signal.indicator] = indicator_counts.get(signal.indicator, 0) + 1
            ticker_counts[signal.ticker] = ticker_counts.get(signal.ticker, 0) + 1

        print("\n📊 Profit Signals by indicator:")
        for indicator, count in sorted(indicator_counts.items()):
            print(f"  {indicator}: {count}")

        print("\n📈 Profit Signals by ticker:")
        for ticker, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {ticker}: {count}")
    else:
        print("\n⚠️  No profit signals generated - try different parameters")


if __name__ == "__main__":
    asyncio.run(main())
