#!/usr/bin/env python3
"""
Practical Quality Profitable Trading Strategy with Complete Trade Pairs

This script implements a practical quality-focused profitable trading strategy that:
1. Generates quality profitable trades with reasonable frequency
2. Creates complete trade pairs (entry + exit)
3. Outputs each action as separate CSV rows
4. Prioritizes practical quality over theoretical perfection
"""

import asyncio
import argparse
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import requests
from dotenv import load_dotenv


@dataclass
class TradeAction:
    """Represents a single trade action (entry or exit)"""
    
    timestamp: str
    ticker: str
    action: str  # buy_to_open, sell_to_open, sell_to_close, buy_to_close
    price: float
    indicator: str
    signal_type: str  # entry or exit
    reason: str
    confidence: float = 0.0
    trade_id: str = ""
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


class PracticalQualityStrategy:
    """Practical quality profitable trading strategy"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # Quality stocks for profitable trading
    QUALITY_STOCKS = [
        "AAPL",  # Apple - stable but good momentum
        "TSLA",  # Tesla - high volatility, profitable swings
        "NVDA",  # NVIDIA - strong trends
        "AMD",   # AMD - good momentum
        "META",  # Meta - volatile but profitable
        "NFLX",  # Netflix - good trends
        "AMZN",  # Amazon - large cap but moves
        "GOOGL", # Google - stable
        "MSFT",  # Microsoft - tech leader
        "SPY",   # SPY ETF - market proxy
    ]

    def simulate_practical_quality_trades(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[TradeAction]:
        """Simulate practical quality trades with complete entry/exit pairs"""
        actions = []

        if len(bars) < 50:
            return actions

        print(f"Simulating Practical Quality for {ticker} with {len(bars)} bars")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]
        timestamps = [bar.get("t", "") for bar in bars]

        # Track active trades and quality filters
        active_trades = {}
        entries_by_date = {}
        trade_counter = 0

        for i in range(30, len(bars)):
            timestamp = timestamps[i]
            price = prices[i]
            
            # Extract date from timestamp
            if "T" in timestamp:
                date_str = timestamp.split("T")[0]
            else:
                date_str = timestamp[:10]

            # Practical entry conditions
            entry_signal = self._check_practical_entry(
                ticker, prices, volumes, highs, lows, i, date_str, entries_by_date
            )

            if entry_signal and not active_trades:
                # Create new trade entry
                trade_counter += 1
                trade_id = f"{ticker}_{trade_counter}_{date_str}"
                
                action = TradeAction(
                    timestamp=timestamp,
                    ticker=ticker,
                    action=entry_signal["action"],
                    price=price,
                    indicator="Practical Quality",
                    signal_type="entry",
                    reason=entry_signal["reason"],
                    confidence=entry_signal["confidence"],
                    trade_id=trade_id,
                    technical_indicators=entry_signal["technical_indicators"]
                )
                
                actions.append(action)
                active_trades[trade_id] = {
                    "entry_price": price,
                    "entry_time": i,
                    "entry_action": entry_signal["action"],
                    "direction": "long" if entry_signal["action"] == "buy_to_open" else "short"
                }
                
                entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1

            # Check for exits on active trades
            trades_to_close = []
            for trade_id, trade_info in active_trades.items():
                exit_signal = self._check_practical_exit(
                    ticker, prices, volumes, highs, lows, i, trade_info
                )
                
                if exit_signal:
                    # Create exit action
                    exit_action = TradeAction(
                        timestamp=timestamp,
                        ticker=ticker,
                        action=exit_signal["action"],
                        price=price,
                        indicator="Practical Quality",
                        signal_type="exit",
                        reason=exit_signal["reason"],
                        confidence=exit_signal["confidence"],
                        trade_id=trade_id,
                        technical_indicators=exit_signal["technical_indicators"]
                    )
                    
                    actions.append(exit_action)
                    trades_to_close.append(trade_id)

            # Remove closed trades
            for trade_id in trades_to_close:
                del active_trades[trade_id]

        return actions

    def _check_practical_entry(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        date_str: str,
        entries_by_date: Dict[str, int]
    ) -> Optional[Dict[str, Any]]:
        """Check for practical entry conditions"""
        
        # Max 5 practical trades per day
        if entries_by_date.get(date_str, 0) >= 5:
            return None

        # Practical momentum calculation
        momentum_score = self._calculate_practical_momentum(prices, volumes, highs, lows, i)
        
        # Practical momentum threshold
        if abs(momentum_score) < 0.1:  # 0.1% minimum momentum
            return None

        # Volume confirmation
        volume_analysis = self._analyze_practical_volume(volumes, i)
        if volume_analysis["volume_ratio"] < 1.1:  # 1.1x average volume minimum
            return None

        # Technical analysis
        tech_analysis = self._practical_technical_analysis(prices, highs, lows, i)
        
        # Practical entry conditions
        if momentum_score > 0:  # Long entry
            if (tech_analysis["rsi"] >= 30.0 and tech_analysis["rsi"] <= 80.0 and  # Wide RSI range
                tech_analysis["trend_strength"] >= 0.1 and  # Weak uptrend minimum
                tech_analysis["volatility"] >= 0.003 and  # Minimum volatility
                tech_analysis["price_position"] >= 0.3):  # Mid-to-upper range position
                
                # Additional practical filters
                if self._practical_entry_filters(prices, volumes, i, is_long=True):
                    return {
                        "action": "buy_to_open",
                        "reason": f"PRACTICAL Quality long: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x",
                        "confidence": min(abs(momentum_score) / 0.5, 1.0),
                        "technical_indicators": {
                            "momentum_score": momentum_score,
                            "rsi": tech_analysis["rsi"],
                            "trend_strength": tech_analysis["trend_strength"],
                            "volume_ratio": volume_analysis["volume_ratio"],
                            "price_position": tech_analysis["price_position"],
                            "volatility": tech_analysis["volatility"],
                        }
                    }

        elif momentum_score < 0:  # Short entry
            if (tech_analysis["rsi"] >= 50.0 and tech_analysis["rsi"] <= 95.0 and  # Wide overbought range
                tech_analysis["trend_strength"] <= -0.1 and  # Weak downtrend minimum
                tech_analysis["volatility"] >= 0.003 and  # Minimum volatility
                tech_analysis["price_position"] <= 0.7):  # Mid-to-lower range position
                
                # Additional practical filters
                if self._practical_entry_filters(prices, volumes, i, is_long=False):
                    return {
                        "action": "sell_to_open",
                        "reason": f"PRACTICAL Quality short: score={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, trend={tech_analysis['trend_strength']:.2f}, vol={volume_analysis['volume_ratio']:.1f}x",
                        "confidence": min(abs(momentum_score) / 0.5, 1.0),
                        "technical_indicators": {
                            "momentum_score": momentum_score,
                            "rsi": tech_analysis["rsi"],
                            "trend_strength": tech_analysis["trend_strength"],
                            "volume_ratio": volume_analysis["volume_ratio"],
                            "price_position": tech_analysis["price_position"],
                            "volatility": tech_analysis["volatility"],
                        }
                    }

        return None

    def _check_practical_exit(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        trade_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check for practical exit conditions"""
        
        entry_price = trade_info["entry_price"]
        entry_time = trade_info["entry_time"]
        direction = trade_info["direction"]
        
        current_price = prices[i]
        
        # Calculate P&L
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:  # short
            pnl_pct = (entry_price - current_price) / entry_price * 100

        # Time-based exit (2-8 minutes for practical trades)
        time_held = i - entry_time
        if time_held >= 8:  # Max 8 minutes
            exit_reason = f"Time exit (held {time_held} min)"
            exit_action = "sell_to_close" if direction == "long" else "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Profit target (1.5% profit for practical trades)
        if pnl_pct >= 1.5:
            exit_reason = f"Profit target reached"
            exit_action = "sell_to_close" if direction == "long" else "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.7,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Stop loss (0.8% loss for practical trades)
        if pnl_pct <= -0.8:
            exit_reason = f"Stop loss triggered"
            exit_action = "sell_to_close" if direction == "long" else "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.5,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Momentum reversal exit
        momentum_score = self._calculate_practical_momentum(prices, volumes, highs, lows, i)
        if direction == "long" and momentum_score < -0.2:
            exit_reason = f"Momentum reversal"
            exit_action = "sell_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }
        elif direction == "short" and momentum_score > 0.2:
            exit_reason = f"Momentum reversal"
            exit_action = "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        return None

    def _calculate_practical_momentum(
        self, 
        prices: List[float], 
        volumes: List[float], 
        highs: List[float], 
        lows: List[float], 
        i: int
    ) -> float:
        """Practical momentum calculation"""
        if i < 20:
            return 0.0

        # Multiple timeframe momentum
        momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        momentum_20 = (prices[i] - prices[i-20]) / prices[i-20] * 100 if i >= 20 else 0
        
        # Weighted momentum (practical)
        momentum_score = (momentum_2 * 0.4 + momentum_5 * 0.3 + momentum_10 * 0.2 + momentum_20 * 0.1)
        
        # Volume-weighted momentum (practical)
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
        volume_weight = min(recent_volume / avg_volume, 2.0) if avg_volume > 0 else 1.0
        
        # Price range momentum
        recent_high = max(highs[max(0, i-5):i])
        recent_low = min(lows[max(0, i-5):i])
        range_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        # Volatility boost (practical)
        recent_volatility = (max(prices[max(0, i-5):i+1]) - min(prices[max(0, i-5):i+1])) / prices[i]
        volatility_boost = 1.0 + min(recent_volatility * 3, 0.8)  # Max 1.8x boost
        
        # Final momentum score
        final_momentum = momentum_score * volume_weight * (0.4 + range_position * 0.6) * volatility_boost
        
        return final_momentum

    def _analyze_practical_volume(self, volumes: List[float], i: int) -> Dict[str, float]:
        """Analyze practical volume"""
        # Recent volume analysis
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume_5 = sum(volumes[max(0, i-8):i-3]) / 5 if i > 8 else recent_volume
        avg_volume_20 = sum(volumes[max(0, i-20):i-5]) / 15 if i > 20 else recent_volume
        
        volume_ratio_5 = recent_volume / avg_volume_5 if avg_volume_5 > 0 else 1.0
        volume_ratio_20 = recent_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
        
        # Volume trend
        volume_trend = (volumes[i] - volumes[max(0, i-5)]) / volumes[max(0, i-5)] if i > 5 and volumes[max(0, i-5)] > 0 else 0
        
        return {
            "volume_ratio": max(volume_ratio_5, volume_ratio_20),
            "volume_trend": volume_trend,
            "recent_volume": recent_volume,
        }

    def _practical_technical_analysis(self, prices: List[float], highs: List[float], lows: List[float], i: int) -> Dict[str, float]:
        """Practical technical analysis"""
        if i < 20:
            return {"rsi": 50.0, "trend_strength": 0.0, "price_position": 0.5, "volatility": 0.01}
        
        # RSI calculation
        rsi = self._practical_rsi(prices[max(0, i-14):i+1])
        
        # Trend strength calculation
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
        
        # Volatility
        recent_prices = prices[max(0, i-10):i+1]
        volatility = (max(recent_prices) - min(recent_prices)) / sum(recent_prices) * len(recent_prices) if recent_prices else 0.01
        
        return {
            "rsi": rsi,
            "trend_strength": trend_strength,
            "price_position": price_position,
            "volatility": volatility,
        }

    def _practical_rsi(self, prices: List[float], period: int = 14) -> float:
        """Practical RSI calculation"""
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

    def _practical_entry_filters(self, prices: List[float], volumes: List[float], i: int, is_long: bool) -> bool:
        """Practical entry filters"""
        if i < 10:
            return False
        
        # Price stability check
        recent_prices = prices[max(0, i-8):i+1]
        price_volatility = max(recent_prices) - min(recent_prices)
        avg_price = sum(recent_prices) / len(recent_prices)
        volatility_ratio = price_volatility / avg_price if avg_price > 0 else 1.0
        
        # Practical volatility range
        if volatility_ratio < 0.003 or volatility_ratio > 0.25:
            return False
        
        # Volume consistency check
        recent_volumes = volumes[max(0, i-3):i+1]
        volume_consistency = min(recent_volumes) / max(recent_volumes) if max(recent_volumes) > 0 else 0
        
        if volume_consistency < 0.15:  # Some volume consistency required
            return False
        
        # Price momentum consistency
        if is_long:
            momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
            momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
            return momentum_2 > 0.05 and momentum_5 > 0.08  # Weak positive momentum
        else:
            momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
            momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
            return momentum_2 < -0.05 and momentum_5 < -0.08  # Weak negative momentum
        
        return True

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[TradeAction]:
        """Run practical quality backtest"""
        print(f"Starting PRACTICAL QUALITY backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")
        print("🎯 FOCUS: Practical quality profitable trades")

        # Fetch historical data
        all_bars = await self.alpaca_client.fetch_bars_batch(
            symbols=tickers, start_date=start_date, end_date=end_date
        )

        all_actions = []

        for ticker in tickers:
            bars = all_bars.get(ticker, [])
            if not bars:
                print(f"No data found for {ticker}")
                continue

            print(f"Backtesting {ticker} with {len(bars)} bars...")

            if "Momentum" in indicators:
                momentum_actions = self.simulate_practical_quality_trades(ticker, bars)
                print(f"  Practical Quality: {len(momentum_actions)} actions")
                all_actions.extend(momentum_actions)

        return all_actions

    def save_to_csv(self, actions: List[TradeAction], filename: str):
        """Save actions to CSV file"""
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
                "trade_id",
                "momentum_score",
                "rsi",
                "trend_strength",
                "volume_ratio",
                "price_position",
                "volatility",
                "pnl_pct",
                "time_held",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for action in actions:
                indicators = action.technical_indicators or {}
                
                row = {
                    "timestamp": action.timestamp,
                    "ticker": action.ticker,
                    "action": action.action,
                    "price": action.price,
                    "indicator": action.indicator,
                    "signal_type": action.signal_type,
                    "reason": action.reason,
                    "confidence": action.confidence,
                    "trade_id": action.trade_id,
                    "momentum_score": indicators.get("momentum_score", ""),
                    "rsi": indicators.get("rsi", ""),
                    "trend_strength": indicators.get("trend_strength", ""),
                    "volume_ratio": indicators.get("volume_ratio", ""),
                    "price_position": indicators.get("price_position", ""),
                    "volatility": indicators.get("volatility", ""),
                    "pnl_pct": indicators.get("pnl_pct", ""),
                    "time_held": indicators.get("time_held", ""),
                }
                writer.writerow(row)

        print(f"Saved {len(actions)} PRACTICAL QUALITY actions to {filename}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Practical quality profitable strategy backtest")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help="Ticker symbols (if empty, uses quality stocks)",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=["Momentum"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output",
        default="practical_quality_profitable_trading_2021_2026.csv",
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

    # Use quality stocks if no tickers provided
    if not args.tickers:
        engine = PracticalQualityStrategy(api_key, secret_key)
        tickers = engine.QUALITY_STOCKS
        print(f"Using quality stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = PracticalQualityStrategy(api_key, secret_key)
    actions = await engine.backtest_indicators(
        tickers, args.start_date, args.end_date, args.indicators
    )

    # Save results
    engine.save_to_csv(actions, args.output)

    # Print summary
    print("\n🎯 PRACTICAL QUALITY PROFITABLE STRATEGY BACKTEST COMPLETED!")
    print(f"Total actions generated: {len(actions)}")
    print("🎯 Goal: Practical quality profitable trades")

    if actions:
        # Count by action type
        entry_actions = sum(1 for a in actions if a.signal_type == "entry")
        exit_actions = sum(1 for a in actions if a.signal_type == "exit")
        
        print(f"\n📊 Action Distribution:")
        print(f"  Entry actions: {entry_actions}")
        print(f"  Exit actions: {exit_actions}")
        
        # Count by ticker
        ticker_counts = {}
        for action in actions:
            ticker_counts[action.ticker] = ticker_counts.get(action.ticker, 0) + 1

        print(f"\n📈 Actions by ticker:")
        for ticker, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {ticker}: {count}")
            
        # Calculate P&L for completed trades
        completed_trades = {}
        for action in actions:
            if action.signal_type == "entry":
                completed_trades[action.trade_id] = {"entry": action, "exit": None}
            elif action.signal_type == "exit" and action.trade_id in completed_trades:
                completed_trades[action.trade_id]["exit"] = action
        
        profitable_trades = 0
        total_pnl = 0
        trade_count = 0
        
        for trade_id, trade_data in completed_trades.items():
            if trade_data["exit"] and trade_data["exit"].technical_indicators:
                pnl = trade_data["exit"].technical_indicators.get("pnl_pct", 0)
                if pnl != "":
                    total_pnl += float(pnl)
                    trade_count += 1
                    if float(pnl) > 0:
                        profitable_trades += 1
        
        if trade_count > 0:
            win_rate = (profitable_trades / trade_count) * 100
            avg_pnl = total_pnl / trade_count
            
            print(f"\n💰 Trade Performance:")
            print(f"  Completed trades: {trade_count}")
            print(f"  Win rate: {win_rate:.1f}%")
            print(f"  Average P&L: {avg_pnl:.2f}%")
            print(f"  Total P&L: {total_pnl:.2f}%")
        
        # Date range
        timestamps = [a.timestamp for a in actions]
        if timestamps:
            print(f"\n📅 Date range: {min(timestamps)[:10]} to {max(timestamps)[:10]}")
    else:
        print("\n⚠️  No practical quality actions generated - try different parameters")


if __name__ == "__main__":
    asyncio.run(main())
