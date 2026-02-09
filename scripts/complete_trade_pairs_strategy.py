#!/usr/bin/env python3
"""
Complete Trade Pairs Strategy with Quality Focus

This script implements a strategy that generates complete trade pairs (entry + exit)
with proper buy/sell sequences using the working momentum logic.
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


class CompleteTradePairsStrategy:
    """Complete trade pairs strategy with quality focus"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # Use penny stocks that worked in the simple strategy
    PENNY_STOCKS = [
        "AMC", "GME", "BB", "NOK", "SNDL", "BNGO", "MVIS", "SPCE", 
        "BITF", "RIOT", "MARA", "HUT"
    ]

    def simulate_complete_trade_pairs(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[TradeAction]:
        """Simulate complete trade pairs with working momentum logic"""
        actions = []

        if len(bars) < 50:
            return actions

        print(f"Simulating Complete Trade Pairs for {ticker} with {len(bars)} bars")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]
        timestamps = [bar.get("t", "") for bar in bars]

        # Track active trades
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

            # Entry conditions (using working simple logic)
            entry_signal = self._check_entry_signal(
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
                    indicator="Complete Trade Pairs",
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
                exit_signal = self._check_exit_signal(
                    ticker, prices, volumes, highs, lows, i, trade_info
                )
                
                if exit_signal:
                    # Create exit action
                    exit_action = TradeAction(
                        timestamp=timestamp,
                        ticker=ticker,
                        action=exit_signal["action"],
                        price=price,
                        indicator="Complete Trade Pairs",
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

    def _check_entry_signal(
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
        """Check for entry signal using working simple logic"""
        
        # Max 10 trades per day
        if entries_by_date.get(date_str, 0) >= 10:
            return None

        # Simple momentum calculation (working logic)
        momentum_score = self._calculate_simple_momentum(prices, volumes, highs, lows, i)
        
        # Low threshold for signal generation
        if abs(momentum_score) < 0.05:  # 0.05% minimum momentum
            return None

        # Volume confirmation
        volume_ratio = self._calculate_volume_ratio(volumes, i)
        if volume_ratio < 1.05:  # 1.05x average volume minimum
            return None

        # Technical analysis
        rsi = self._calculate_simple_rsi(prices, i)
        trend_strength = self._calculate_trend_strength(prices, i)
        
        # Entry conditions
        if momentum_score > 0:  # Long entry
            if (rsi >= 25.0 and rsi <= 85.0 and  # Wide RSI range
                trend_strength >= -0.5):  # Any trend except strong down
                
                return {
                    "action": "buy_to_open",
                    "reason": f"Complete Pairs long: momentum={momentum_score:.3f}, rsi={rsi:.1f}, trend={trend_strength:.2f}, vol={volume_ratio:.2f}x",
                    "confidence": min(abs(momentum_score) / 0.2, 1.0),
                    "technical_indicators": {
                        "momentum_score": momentum_score,
                        "rsi": rsi,
                        "trend_strength": trend_strength,
                        "volume_ratio": volume_ratio,
                    }
                }

        elif momentum_score < 0:  # Short entry
            if (rsi >= 40.0 and rsi <= 95.0 and  # Wide overbought range
                trend_strength <= 0.5):  # Any trend except strong up
                
                return {
                    "action": "sell_to_open",
                    "reason": f"Complete Pairs short: momentum={momentum_score:.3f}, rsi={rsi:.1f}, trend={trend_strength:.2f}, vol={volume_ratio:.2f}x",
                    "confidence": min(abs(momentum_score) / 0.2, 1.0),
                    "technical_indicators": {
                        "momentum_score": momentum_score,
                        "rsi": rsi,
                        "trend_strength": trend_strength,
                        "volume_ratio": volume_ratio,
                    }
                }

        return None

    def _check_exit_signal(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        trade_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check for exit signal"""
        
        entry_price = trade_info["entry_price"]
        entry_time = trade_info["entry_time"]
        direction = trade_info["direction"]
        
        current_price = prices[i]
        
        # Calculate P&L
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:  # short
            pnl_pct = (entry_price - current_price) / entry_price * 100

        # Time-based exit (1-5 minutes for quick trades)
        time_held = i - entry_time
        if time_held >= 5:  # Max 5 minutes
            exit_reason = f"Time exit (held {time_held} min)"
            exit_action = "sell_to_close" if direction == "long" else "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Profit target (1% profit)
        if pnl_pct >= 1.0:
            exit_reason = f"Profit target reached"
            exit_action = "sell_to_close" if direction == "long" else "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.8,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Stop loss (0.5% loss)
        if pnl_pct <= -0.5:
            exit_reason = f"Stop loss triggered"
            exit_action = "sell_to_close" if direction == "long" else "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.5,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Momentum reversal exit
        momentum_score = self._calculate_simple_momentum(prices, volumes, highs, lows, i)
        if direction == "long" and momentum_score < -0.1:
            exit_reason = f"Momentum reversal"
            exit_action = "sell_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }
        elif direction == "short" and momentum_score > 0.1:
            exit_reason = f"Momentum reversal"
            exit_action = "buy_to_close"
            return {
                "action": exit_action,
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        return None

    def _calculate_simple_momentum(
        self, 
        prices: List[float], 
        volumes: List[float], 
        highs: List[float], 
        lows: List[float], 
        i: int
    ) -> float:
        """Simple momentum calculation (working logic)"""
        if i < 10:
            return 0.0

        # Multiple timeframe momentum
        momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        
        # Weighted momentum
        momentum_score = (momentum_2 * 0.5 + momentum_5 * 0.3 + momentum_10 * 0.2)
        
        # Volume-weighted momentum
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
        volume_weight = min(recent_volume / avg_volume, 2.0) if avg_volume > 0 else 1.0
        
        # Final momentum score
        final_momentum = momentum_score * volume_weight
        
        return final_momentum

    def _calculate_volume_ratio(self, volumes: List[float], i: int) -> float:
        """Calculate volume ratio"""
        recent_volume = sum(volumes[max(0, i-3):i+1]) / 3
        avg_volume = sum(volumes[max(0, i-10):i-3]) / 7 if i > 10 else recent_volume
        return recent_volume / avg_volume if avg_volume > 0 else 1.0

    def _calculate_simple_rsi(self, prices: List[float], i: int, period: int = 14) -> float:
        """Simple RSI calculation"""
        if i < period + 1:
            return 50.0
        
        recent_prices = prices[max(0, i-period):i+1]
        gains = []
        losses = []
        
        for j in range(1, len(recent_prices)):
            change = recent_prices[j] - recent_prices[j - 1]
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

    def _calculate_trend_strength(self, prices: List[float], i: int) -> float:
        """Calculate trend strength"""
        if i < 10:
            return 0.0
        
        short_trend = (prices[i] - prices[i-3]) / prices[i-3] if i >= 3 else 0
        medium_trend = (prices[i] - prices[i-8]) / prices[i-8] if i >= 8 else 0
        
        # Weighted trend strength
        trend_strength = (short_trend * 0.6 + medium_trend * 0.4)
        return max(-1.0, min(1.0, trend_strength))

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[TradeAction]:
        """Run complete trade pairs backtest"""
        print(f"Starting COMPLETE TRADE PAIRS backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")
        print("🎯 FOCUS: Complete trade pairs with proper buy/sell sequences")

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
                momentum_actions = self.simulate_complete_trade_pairs(ticker, bars)
                print(f"  Complete Trade Pairs: {len(momentum_actions)} actions")
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
                    "pnl_pct": indicators.get("pnl_pct", ""),
                    "time_held": indicators.get("time_held", ""),
                }
                writer.writerow(row)

        print(f"Saved {len(actions)} COMPLETE TRADE PAIRS actions to {filename}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Complete trade pairs strategy backtest")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help="Ticker symbols (if empty, uses penny stocks)",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=["Momentum"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output",
        default="complete_trade_pairs_2021_2026.csv",
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

    # Use penny stocks if no tickers provided
    if not args.tickers:
        engine = CompleteTradePairsStrategy(api_key, secret_key)
        tickers = engine.PENNY_STOCKS
        print(f"Using penny stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = CompleteTradePairsStrategy(api_key, secret_key)
    actions = await engine.backtest_indicators(
        tickers, args.start_date, args.end_date, args.indicators
    )

    # Save results
    engine.save_to_csv(actions, args.output)

    # Print summary
    print("\n🎯 COMPLETE TRADE PAIRS STRATEGY BACKTEST COMPLETED!")
    print(f"Total actions generated: {len(actions)}")
    print("🎯 Goal: Complete trade pairs with proper buy/sell sequences")

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
        print("\n⚠️  No complete trade pairs actions generated - try different parameters")


if __name__ == "__main__":
    asyncio.run(main())
