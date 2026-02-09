#!/usr/bin/env python3
"""
Balanced Quality Backtest Trading Indicators Script

This script balances quality and quantity - generates selective but profitable trades.
Focuses on consistent profitability with reasonable signal frequency.
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


class BalancedBacktestEngine:
    """Balanced backtesting engine - quality trades with reasonable frequency"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # Mix of quality stocks including some larger cap for better signals
    BALANCED_STOCKS = [
        "AAPL",  # Apple - large cap, stable
        "TSLA",  # Tesla - volatile but liquid
        "NVDA",  # NVIDIA - growth stock
        "AMD",   # AMD - tech stock
        "AMC",   # AMC Entertainment - penny but popular
        "GME",   # GameStop - meme stock
        "BB",    # BlackBerry - penny stock
        "NOK",   # Nokia - penny stock
        "SNDL",  # Sundial Growers - penny stock
        "BNGO",  # Golden Entertainment - penny stock
        "MVIS",  # MicroVision - penny stock
        "SPCE",  # Virgin Galactic - penny stock
        "BITF",  # Bitfarms - crypto mining
        "RIOT",  # Riot Blockchain - crypto mining
        "MARA",  # Marathon Digital - crypto mining
    ]

    def simulate_momentum_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Balanced MomentumIndicator - quality trades with reasonable frequency"""
        signals = []

        if len(bars) < 30:
            return signals

        print(f"Simulating Balanced Momentum for {ticker} with {len(bars)} bars")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]

        # Track entries per day (max 3 trades per day)
        entries_by_date = {}

        for i in range(30, len(bars)):
            current_bar = bars[i]
            timestamp = current_bar.get("t", "")
            price = float(current_bar.get("c", 0))
            
            # Extract date from timestamp
            if "T" in timestamp:
                date_str = timestamp.split("T")[0]
            else:
                date_str = timestamp[:10]

            # Skip if already have 3 trades today
            if entries_by_date.get(date_str, 0) >= 3:
                continue

            # Balanced momentum calculation
            momentum_score = self._calculate_balanced_momentum(prices, volumes, highs, lows, i)
            
            # Moderate threshold - balance quality and quantity
            if abs(momentum_score) >= 1.5:  # 1.5% minimum momentum
                # Volume confirmation
                volume_analysis = self._analyze_volume_quality(volumes, i)
                
                if volume_analysis["volume_ratio"] >= 1.8:  # 1.8x average volume
                    # Technical analysis
                    tech_analysis = self._balanced_technical_analysis(prices, highs, lows, i)
                    
                    # Momentum entry conditions
                    if momentum_score > 0:  # Long entry
                        if (tech_analysis["rsi"] >= 35.0 and tech_analysis["rsi"] <= 70.0 and  # Reasonable RSI range
                            tech_analysis["trend_strength"] >= 0.4 and  # Moderate uptrend
                            tech_analysis["price_position"] >= 0.5):  # Above middle of range
                            
                            # Quality filters
                            if self._balanced_quality_filters(prices, volumes, i, is_long=True):
                                action = "buy_to_open"
                                reason = f"BALANCED Momentum long: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x"
                                confidence = min(abs(momentum_score) / 4.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Balanced Momentum",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": tech_analysis["rsi"],
                                        "trend_strength": tech_analysis["trend_strength"],
                                        "volume_ratio": volume_analysis["volume_ratio"],
                                        "price_position": tech_analysis["price_position"],
                                    }
                                )
                                signals.append(signal)
                                entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1

                    elif momentum_score < 0:  # Short entry
                        if (tech_analysis["rsi"] >= 50.0 and tech_analysis["rsi"] <= 75.0 and  # Near overbought
                            tech_analysis["trend_strength"] <= -0.4 and  # Moderate downtrend
                            tech_analysis["price_position"] <= 0.5):  # Below middle of range
                            
                            # Quality filters
                            if self._balanced_quality_filters(prices, volumes, i, is_long=False):
                                action = "sell_to_open"
                                reason = f"BALANCED Momentum short: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x"
                                confidence = min(abs(momentum_score) / 4.0, 1.0)
                                
                                signal = BacktestSignal(
                                    timestamp=timestamp,
                                    ticker=ticker,
                                    action=action,
                                    price=price,
                                    indicator="Balanced Momentum",
                                    signal_type="entry",
                                    reason=reason,
                                    confidence=confidence,
                                    technical_indicators={
                                        "momentum_score": momentum_score,
                                        "rsi": tech_analysis["rsi"],
                                        "trend_strength": tech_analysis["trend_strength"],
                                        "volume_ratio": volume_analysis["volume_ratio"],
                                        "price_position": tech_analysis["price_position"],
                                    }
                                )
                                signals.append(signal)
                                entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1

        return signals

    def simulate_penny_stocks_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Balanced PennyStocksIndicator - selective penny stock trades"""
        signals = []

        if len(bars) < 20:
            return signals

        # Check if this is actually a penny stock
        current_price = float(bars[-1].get("c", 0))
        if not (0.25 <= current_price <= 8.0):  # Wider range for more opportunities
            print(f"{ticker} price ${current_price:.2f} - not in penny stock range")
            return signals

        print(f"{ticker} price ${current_price:.2f} - penny stock candidate")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]

        # Track entries per day (max 2 penny stock trades per day)
        entries_by_date = {}

        for i in range(20, len(bars)):
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

            # Balanced penny stock momentum
            momentum_score = self._calculate_balanced_penny_momentum(prices, volumes, highs, lows, i)
            
            # Moderate threshold for penny stocks
            if momentum_score >= 2.5:  # 2.5% minimum for penny stocks
                # Volume confirmation
                volume_analysis = self._analyze_volume_quality(volumes, i)
                
                if volume_analysis["volume_ratio"] >= 2.5:  # 2.5x average volume
                    # Technical analysis
                    tech_analysis = self._balanced_technical_analysis(prices, highs, lows, i)
                    
                    # Penny stocks only go long
                    if (tech_analysis["rsi"] >= 30.0 and tech_analysis["rsi"] <= 65.0 and  # Conservative RSI
                        tech_analysis["trend_strength"] >= 0.5 and  # Moderate uptrend
                        tech_analysis["price_position"] >= 0.6):  # Near top of range
                        
                        # Penny stock quality filters
                        if self._balanced_penny_stock_filters(prices, volumes, highs, lows, i):
                            action = "buy_to_open"
                            reason = f"BALANCED Penny long: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x"
                            confidence = min(momentum_score / 6.0, 1.0)
                            
                            signal = BacktestSignal(
                                timestamp=timestamp,
                                ticker=ticker,
                                action=action,
                                price=price,
                                indicator="Balanced Penny Stocks",
                                signal_type="entry",
                                reason=reason,
                                confidence=confidence,
                                technical_indicators={
                                    "momentum_score": momentum_score,
                                    "rsi": tech_analysis["rsi"],
                                    "trend_strength": tech_analysis["trend_strength"],
                                    "volume_ratio": volume_analysis["volume_ratio"],
                                    "price_position": tech_analysis["price_position"],
                                    "price": price,
                                }
                            )
                            signals.append(signal)
                            
                            # Mark this date as having an entry
                            entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1

        return signals

    def _calculate_balanced_momentum(
        self, 
        prices: List[float], 
        volumes: List[float], 
        highs: List[float], 
        lows: List[float], 
        i: int
    ) -> float:
        """Balanced momentum calculation"""
        if i < 20:
            return 0.0

        # Multiple timeframe momentum
        momentum_3 = (prices[i] - prices[i-3]) / prices[i-3] * 100 if i >= 3 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        momentum_20 = (prices[i] - prices[i-20]) / prices[i-20] * 100 if i >= 20 else 0
        
        # Weighted momentum score
        momentum_score = (momentum_3 * 0.4 + momentum_5 * 0.3 + momentum_10 * 0.2 + momentum_20 * 0.1)
        
        # Volume-weighted momentum
        recent_volume = sum(volumes[max(0, i-5):i+1]) / 5
        avg_volume = sum(volumes[max(0, i-15):i-5]) / 10 if i > 15 else recent_volume
        volume_weight = min(recent_volume / avg_volume, 2.5) if avg_volume > 0 else 1.0
        
        # Price range momentum
        recent_high = max(highs[max(0, i-10):i])
        recent_low = min(lows[max(0, i-10):i])
        range_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        # Final momentum score
        final_momentum = momentum_score * volume_weight * (0.6 + range_position * 0.4)
        
        return final_momentum

    def _calculate_balanced_penny_momentum(
        self, 
        prices: List[float], 
        volumes: List[float], 
        highs: List[float], 
        lows: List[float], 
        i: int
    ) -> float:
        """Balanced penny stock momentum calculation"""
        if i < 15:
            return 0.0

        # Penny stock momentum
        momentum_3 = (prices[i] - prices[i-3]) / prices[i-3] * 100 if i >= 3 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        momentum_15 = (prices[i] - prices[i-15]) / prices[i-15] * 100 if i >= 15 else 0
        
        # Penny stocks need consistent momentum
        if not (momentum_3 > 0.5 and momentum_5 > 1.0 and momentum_10 > 1.5):
            return 0.0
        
        # Weighted momentum score
        momentum_score = (momentum_3 * 0.3 + momentum_5 * 0.3 + momentum_10 * 0.25 + momentum_15 * 0.15)
        
        # Volume requirement
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
        volume_multiplier = min(recent_volume / avg_volume, 5.0) if avg_volume > 0 else 1.0
        
        if volume_multiplier < 2.5:  # Need 2.5x volume minimum
            return 0.0
        
        # Price breakout confirmation
        recent_high = max(highs[max(0, i-10):i])
        if prices[i] < recent_high * 0.95:  # Must be near breakout
            return 0.0
        
        return momentum_score * volume_multiplier

    def _analyze_volume_quality(self, volumes: List[float], i: int) -> Dict[str, float]:
        """Analyze volume quality"""
        # Recent volume analysis
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume_5 = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
        avg_volume_20 = sum(volumes[max(0, i-25):i-5]) / 20 if i > 25 else recent_volume
        
        volume_ratio_5 = recent_volume / avg_volume_5 if avg_volume_5 > 0 else 1.0
        volume_ratio_20 = recent_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
        
        # Volume trend
        volume_trend = (volumes[i] - volumes[max(0, i-5)]) / volumes[max(0, i-5)] if i > 5 and volumes[max(0, i-5)] > 0 else 0
        
        return {
            "volume_ratio": max(volume_ratio_5, volume_ratio_20),
            "volume_trend": volume_trend,
            "recent_volume": recent_volume,
        }

    def _balanced_technical_analysis(self, prices: List[float], highs: List[float], lows: List[float], i: int) -> Dict[str, float]:
        """Balanced technical analysis"""
        if i < 20:
            return {"rsi": 50.0, "trend_strength": 0.0, "price_position": 0.5}
        
        # RSI calculation
        rsi = self._balanced_rsi(prices[max(0, i-14):i+1])
        
        # Trend strength calculation
        short_trend = (prices[i] - prices[i-5]) / prices[i-5] if i >= 5 else 0
        medium_trend = (prices[i] - prices[i-10]) / prices[i-10] if i >= 10 else 0
        long_trend = (prices[i] - prices[i-20]) / prices[i-20] if i >= 20 else 0
        
        # Weighted trend strength
        trend_strength = (short_trend * 0.5 + medium_trend * 0.3 + long_trend * 0.2) / 5.0
        trend_strength = max(-1.0, min(1.0, trend_strength))
        
        # Price position in recent range
        recent_high = max(highs[max(0, i-10):i])
        recent_low = min(lows[max(0, i-10):i])
        price_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        return {
            "rsi": rsi,
            "trend_strength": trend_strength,
            "price_position": price_position,
        }

    def _balanced_rsi(self, prices: List[float], period: int = 14) -> float:
        """Balanced RSI calculation"""
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

    def _balanced_quality_filters(self, prices: List[float], volumes: List[float], i: int, is_long: bool) -> bool:
        """Balanced quality filters"""
        if i < 15:
            return False
        
        # Price stability check
        recent_prices = prices[max(0, i-10):i+1]
        price_volatility = max(recent_prices) - min(recent_prices)
        avg_price = sum(recent_prices) / len(recent_prices)
        volatility_ratio = price_volatility / avg_price if avg_price > 0 else 1.0
        
        # Allow moderate volatility
        if volatility_ratio > 0.20:  # More than 20% range in 10 periods
            return False
        
        # Volume consistency check
        recent_volumes = volumes[max(0, i-5):i+1]
        volume_consistency = min(recent_volumes) / max(recent_volumes) if max(recent_volumes) > 0 else 0
        
        if volume_consistency < 0.25:  # Volume varies too much
            return False
        
        return True

    def _balanced_penny_stock_filters(self, prices: List[float], volumes: List[float], highs: List[float], lows: List[float], i: int) -> bool:
        """Balanced penny stock quality filters"""
        if i < 15:
            return False
        
        # Minimum price requirement
        current_price = prices[i]
        if current_price < 0.25:  # Too cheap
            return False
        
        # Price range check (avoid extreme moves)
        recent_high = max(highs[max(0, i-15):i])
        recent_low = min(lows[max(0, i-15):i])
        
        # Avoid stocks that moved >150% in last 15 periods
        if recent_low > 0 and (recent_high / recent_low) > 2.5:
            return False
        
        # Volume quality check
        recent_volumes = volumes[max(0, i-10):i+1]
        avg_recent_volume = sum(recent_volumes) / len(recent_volumes)
        
        # Minimum volume requirement (scaled with price)
        min_volume = max(50000, current_price * 500000)  # Scale with price
        if avg_recent_volume < min_volume:
            return False
        
        # Price momentum consistency
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        
        # Both timeframes must be positive
        if momentum_5 <= 0.5 or momentum_10 <= 1.0:
            return False
        
        return True

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[BacktestSignal]:
        """Run balanced backtest"""
        print(f"Starting BALANCED backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")
        print("⚖️  BALANCE: Quality trades with reasonable frequency")

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
                print(f"  Balanced Momentum: {len(momentum_signals)} signals")
                all_signals.extend(momentum_signals)

            if "Penny Stocks" in indicators:
                penny_signals = self.simulate_penny_stocks_indicator(ticker, bars)
                print(f"  Balanced Penny Stocks: {len(penny_signals)} signals")
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
                "trend_strength",
                "volume_ratio",
                "price_position",
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
                }
                writer.writerow(row)

        print(f"Saved {len(signals)} BALANCED signals to {filename}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Balanced backtest")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help="Ticker symbols (if empty, uses balanced stocks)",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=["Momentum", "Penny Stocks"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output",
        default="balanced_trading_backtest.csv",
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

    # Use balanced stocks if no tickers provided
    if not args.tickers:
        engine = BalancedBacktestEngine(api_key, secret_key)
        tickers = engine.BALANCED_STOCKS
        print(f"Using balanced stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = BalancedBacktestEngine(api_key, secret_key)
    signals = await engine.backtest_indicators(
        tickers, args.start_date, args.end_date, args.indicators
    )

    # Save results
    engine.save_to_csv(signals, args.output)

    # Print summary
    print("\n⚖️  BALANCED BACKTEST COMPLETED!")
    print(f"Total signals generated: {len(signals)}")
    print("🎯 Goal: Quality trades with profitable consistency")

    if signals:
        # Count by indicator
        indicator_counts = {}
        ticker_counts = {}
        for signal in signals:
            indicator_counts[signal.indicator] = indicator_counts.get(signal.indicator, 0) + 1
            ticker_counts[signal.ticker] = ticker_counts.get(signal.ticker, 0) + 1

        print("\n📊 Balanced Signals by indicator:")
        for indicator, count in sorted(indicator_counts.items()):
            print(f"  {indicator}: {count}")

        print("\n📈 Balanced Signals by ticker:")
        for ticker, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {ticker}: {count}")
    else:
        print("\n⚠️  No balanced signals generated - try different parameters")


if __name__ == "__main__":
    asyncio.run(main())
