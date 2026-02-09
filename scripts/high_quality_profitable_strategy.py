#!/usr/bin/env python3
"""
High Quality Profitable Trading Strategy

This script implements a high-quality profitable trading strategy that:
1. Generates only high-quality profitable trades
2. Prioritizes quality over quantity (fewer trades)
3. Works for both Momentum and Penny Stocks indicators
4. Creates complete trade pairs with proper buy/sell sequences
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

        while current_start <= end_dt:
            # Keep date windows contiguous and non-overlapping.
            days = max(1, batch_days)
            batch_end = min(current_start + timedelta(days=days - 1), end_dt)

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

            current_start = batch_end + timedelta(days=1)
            batch_num += 1

            # Rate limiting
            await asyncio.sleep(1)

        # Sort bars by timestamp
        for symbol in symbols:
            all_bars[symbol].sort(key=lambda x: x["t"])

        return all_bars


class HighQualityProfitableStrategy:
    """High quality profitable trading strategy"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # Quality stocks for profitable trading
    MOMENTUM_STOCKS = [
        "META", "TSLA", "NFLX", "SPY"
    ]

    PENNY_STOCKS = [
        "SNDL", "RIOT"
    ]
    
    MOMENTUM_MAX_MONTHLY_TRADES = 3
    PENNY_MAX_MONTHLY_TRADES = 4

    PENNY_MIN_PRICE = 0.2
    PENNY_MAX_PRICE = 5.0
    PENNY_MIN_DOLLAR_VOLUME = 50_000

    def simulate_high_quality_trades(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
        indicator_type: str,
    ) -> List[TradeAction]:
        """Simulate high quality trades with strict filters"""
        actions = []

        if len(bars) < 100:
            return actions

        print(f"Simulating High Quality {indicator_type} for {ticker} with {len(bars)} bars")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]
        timestamps = [bar.get("t", "") for bar in bars]

        # Track active trades
        active_trades = {}
        entries_by_date = {}
        entries_by_month = {}
        trade_counter = 0

        for i in range(50, len(bars)):
            timestamp = timestamps[i]
            price = prices[i]
            
            # Extract date from timestamp
            if "T" in timestamp:
                date_str = timestamp.split("T")[0]
            else:
                date_str = timestamp[:10]
            month_str = date_str[:7]

            # Strict entry conditions
            entry_signal = self._check_high_quality_entry(
                ticker, prices, volumes, highs, lows, i, date_str, 
                entries_by_date, entries_by_month, indicator_type
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
                    indicator=f"High Quality {indicator_type}",
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
                    "direction": "long" if entry_signal["action"] == "buy_to_open" else "short",
                    "peak_profit_pct": 0.0,
                    "indicator_type": indicator_type,
                    "entry_volatility": entry_signal["technical_indicators"].get("volatility", 0.01),
                }
                
                entries_by_date[date_str] = entries_by_date.get(date_str, 0) + 1
                entries_by_month[month_str] = entries_by_month.get(month_str, 0) + 1

            # Check for exits on active trades
            trades_to_close = []
            for trade_id, trade_info in active_trades.items():
                exit_signal = self._check_high_quality_exit(
                    ticker, prices, volumes, highs, lows, i, trade_info
                )
                
                if exit_signal:
                    # Create exit action
                    exit_action = TradeAction(
                        timestamp=timestamp,
                        ticker=ticker,
                        action=exit_signal["action"],
                        price=price,
                        indicator=f"High Quality {indicator_type}",
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

    def _check_high_quality_entry(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        date_str: str,
        entries_by_date: Dict[str, int],
        entries_by_month: Dict[str, int],
        indicator_type: str
    ) -> Optional[Dict[str, Any]]:
        """Check for high quality entry conditions"""
        month_str = date_str[:7]

        # Keep momentum indicator on its intended universe.
        if indicator_type == "Momentum" and ticker not in self.MOMENTUM_STOCKS:
            return None
        
        # Very strict frequency limits for quality over quantity
        max_daily_entries = 1
        max_monthly_entries = (
            self.MOMENTUM_MAX_MONTHLY_TRADES
            if indicator_type == "Momentum"
            else self.PENNY_MAX_MONTHLY_TRADES
        )
        if entries_by_date.get(date_str, 0) >= max_daily_entries:
            return None
        if entries_by_month.get(month_str, 0) >= max_monthly_entries:
            return None

        # Indicator-specific universe guard
        current_price = prices[i]
        if indicator_type == "PennyStocks":
            if current_price >= self.PENNY_MAX_PRICE or current_price < self.PENNY_MIN_PRICE:
                return None
            return self._check_penny_volatility_entry(
                ticker=ticker,
                prices=prices,
                volumes=volumes,
                highs=highs,
                lows=lows,
                i=i,
                current_price=current_price,
            )

        # Momentum branch only
        if current_price < self.PENNY_MAX_PRICE:
            return None

        # High quality momentum calculation
        momentum_score = self._calculate_high_quality_momentum(prices, volumes, highs, lows, i)
        
        # High momentum threshold
        min_momentum = 0.55 if indicator_type == "Momentum" else 0.75
        if momentum_score < min_momentum:
            return None

        # Strong volume confirmation
        volume_analysis = self._analyze_high_quality_volume(volumes, i)
        min_volume_ratio = 1.35 if indicator_type == "Momentum" else 1.6
        if volume_analysis["volume_ratio"] < min_volume_ratio:
            return None
        if volume_analysis["volume_trend"] < 0.01:
            return None

        # Avoid illiquid entries
        dollar_volume = current_price * volumes[i]
        min_dollar_volume = 120_000 if indicator_type == "Momentum" else 25_000
        if dollar_volume < min_dollar_volume:
            return None

        # Technical analysis
        tech_analysis = self._high_quality_technical_analysis(prices, highs, lows, i)
        
        # Long-only quality entry conditions
        if (
            tech_analysis["trend_regime_ok"]
            and tech_analysis["rsi"] >= 45.0
            and tech_analysis["rsi"] <= 72.0
            and tech_analysis["trend_strength"] >= 0.004
            and tech_analysis["volatility"] >= 0.006
            and tech_analysis["volatility"] <= 0.08
            and tech_analysis["price_position"] >= 0.35
            and tech_analysis["price_position"] <= 0.92
        ):
            if self._high_quality_entry_filters(prices, volumes, highs, lows, i, is_long=True):
                return {
                    "action": "buy_to_open",
                    "reason": (
                        f"HIGH QUALITY {indicator_type} long: "
                        f"momentum={momentum_score:.2f}, rsi={tech_analysis['rsi']:.1f}, "
                        f"trend={tech_analysis['trend_strength']:.2f}, "
                        f"vol={volume_analysis['volume_ratio']:.1f}x"
                    ),
                    "confidence": min(momentum_score / 1.8, 1.0),
                    "technical_indicators": {
                        "momentum_score": momentum_score,
                        "rsi": tech_analysis["rsi"],
                        "trend_strength": tech_analysis["trend_strength"],
                        "volume_ratio": volume_analysis["volume_ratio"],
                        "price_position": tech_analysis["price_position"],
                        "volatility": tech_analysis["volatility"],
                        "volume_trend": volume_analysis["volume_trend"],
                        "sma50": tech_analysis["sma50"],
                        "sma200": tech_analysis["sma200"],
                    },
                }

        return None

    def _check_penny_volatility_entry(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """Long/short penny-stock entries that ride directional volatility."""
        if i < 30:
            return None

        lookback_start = max(0, i - 20)
        recent_high = max(highs[lookback_start:i])
        recent_low = min(lows[lookback_start:i])
        if recent_high <= recent_low:
            return None

        volatility = (recent_high - recent_low) / current_price if current_price > 0 else 0.0
        if volatility < 0.015 or volatility > 0.35:
            return None

        volume_analysis = self._analyze_high_quality_volume(volumes, i)
        if volume_analysis["volume_ratio"] < 1.8:
            return None
        if volume_analysis["volume_trend"] < 0.03:
            return None

        dollar_volume = current_price * volumes[i]
        if dollar_volume < self.PENNY_MIN_DOLLAR_VOLUME:
            return None

        rsi = self._high_quality_rsi(prices[max(0, i - 14) : i + 1], period=14)
        trend_strength = (
            (prices[i] - prices[i - 8]) / prices[i - 8]
            if i >= 8 and prices[i - 8] > 0
            else 0.0
        )
        directional_score = self._calculate_penny_directional_score(prices, i)
        price_position = (current_price - recent_low) / (recent_high - recent_low)
        short_ma_8 = (
            sum(prices[i - 7 : i + 1]) / 8
            if i >= 7
            else sum(prices[max(0, i - 7) : i + 1]) / len(prices[max(0, i - 7) : i + 1])
        )
        long_ma_20 = (
            sum(prices[i - 19 : i + 1]) / 20
            if i >= 19
            else sum(prices[max(0, i - 19) : i + 1]) / len(prices[max(0, i - 19) : i + 1])
        )

        breakout_buffer = max(0.002, min(0.01, volatility * 0.25))
        breakout_up = current_price >= recent_high * (1 + breakout_buffer * 0.25)
        breakout_down = current_price <= recent_low * (1 - breakout_buffer * 0.35)

        confidence = min(
            (abs(directional_score) / 1.2) + max(0.0, volume_analysis["volume_ratio"] - 1.5) * 0.15,
            1.0,
        )

        if (
            breakout_up
            and directional_score >= 1.50
            and rsi >= 65.0
            and rsi <= 85.0
            and trend_strength >= 0.0
            and price_position >= 0.50
            and volatility <= 0.05
            and volume_analysis["volume_ratio"] >= 6.0
            and short_ma_8 > long_ma_20
        ):
            return {
                "action": "buy_to_open",
                "reason": (
                    f"HIGH QUALITY PennyStocks long: score={directional_score:.2f}, "
                    f"rsi={rsi:.1f}, vol={volume_analysis['volume_ratio']:.1f}x, "
                    f"range={volatility * 100:.1f}%"
                ),
                "confidence": confidence,
                "technical_indicators": {
                    "momentum_score": directional_score,
                    "rsi": rsi,
                    "trend_strength": trend_strength,
                    "volume_ratio": volume_analysis["volume_ratio"],
                    "price_position": price_position,
                    "volatility": volatility,
                    "volume_trend": volume_analysis["volume_trend"],
                },
            }

        if (
            breakout_down
            and directional_score <= -2.2
            and rsi >= 20.0
            and rsi <= 33.0
            and trend_strength <= -0.002
            and price_position <= 0.35
            and volatility <= 0.045
            and volume_analysis["volume_ratio"] >= 8.0
            and short_ma_8 < long_ma_20
        ):
            return {
                "action": "sell_to_open",
                "reason": (
                    f"HIGH QUALITY PennyStocks short: score={directional_score:.2f}, "
                    f"rsi={rsi:.1f}, vol={volume_analysis['volume_ratio']:.1f}x, "
                    f"range={volatility * 100:.1f}%"
                ),
                "confidence": confidence,
                "technical_indicators": {
                    "momentum_score": directional_score,
                    "rsi": rsi,
                    "trend_strength": trend_strength,
                    "volume_ratio": volume_analysis["volume_ratio"],
                    "price_position": price_position,
                    "volatility": volatility,
                    "volume_trend": volume_analysis["volume_trend"],
                },
            }

        return None

    def _check_high_quality_exit(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        trade_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check for high quality exit conditions"""
        indicator_type = trade_info.get("indicator_type", "Momentum")
        if indicator_type == "PennyStocks":
            return self._check_penny_volatility_exit(
                ticker=ticker,
                prices=prices,
                volumes=volumes,
                highs=highs,
                lows=lows,
                i=i,
                trade_info=trade_info,
            )
        
        entry_price = trade_info["entry_price"]
        entry_time = trade_info["entry_time"]
        direction = trade_info["direction"]
        
        current_price = prices[i]
        
        # Calculate P&L
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = 0.0

        peak_profit_pct = max(trade_info.get("peak_profit_pct", pnl_pct), pnl_pct)
        trade_info["peak_profit_pct"] = peak_profit_pct

        # Quality exits: let winners run with asymmetric risk/reward.
        time_held = i - entry_time
        if time_held >= 60:
            exit_reason = f"Time exit (held {time_held} min)"
            return {
                "action": "sell_to_close",
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.6,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Profit target
        if pnl_pct >= 2.3:
            exit_reason = f"Profit target reached"
            return {
                "action": "sell_to_close",
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.9,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Tight stop loss
        if pnl_pct <= -0.6:
            exit_reason = f"Stop loss triggered"
            return {
                "action": "sell_to_close",
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.4,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        # Trailing profit protection once trade has moved in our favor.
        if peak_profit_pct >= 0.9 and pnl_pct <= peak_profit_pct - 0.5:
            return {
                "action": "sell_to_close",
                "reason": f"Trailing stop (peak {peak_profit_pct:.2f}%, now {pnl_pct:.2f}%)",
                "confidence": 0.75,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }

        # Strong momentum reversal exit
        momentum_score = self._calculate_high_quality_momentum(prices, volumes, highs, lows, i)
        if direction == "long" and momentum_score < -0.2:
            exit_reason = f"Strong momentum reversal"
            return {
                "action": "sell_to_close",
                "reason": f"{exit_reason}, P&L: {pnl_pct:.2f}%",
                "confidence": 0.7,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held}
            }

        return None

    def _check_penny_volatility_exit(
        self,
        ticker: str,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
        i: int,
        trade_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Direction-aware exits for volatile penny-stock long/short trades."""
        entry_price = trade_info["entry_price"]
        entry_time = trade_info["entry_time"]
        direction = trade_info["direction"]
        current_price = prices[i]

        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
            close_action = "sell_to_close"
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
            close_action = "buy_to_close"

        peak_profit_pct = max(trade_info.get("peak_profit_pct", pnl_pct), pnl_pct)
        trade_info["peak_profit_pct"] = peak_profit_pct

        time_held = i - entry_time
        entry_volatility = float(trade_info.get("entry_volatility", 0.02))
        profit_target = max(1.2, min(4.0, entry_volatility * 45))
        stop_loss = max(0.45, min(1.2, profit_target * 0.45))
        trailing_gap = max(0.35, min(1.0, profit_target * 0.35))

        if time_held >= 35:
            return {
                "action": close_action,
                "reason": f"Time exit (held {time_held} min), P&L: {pnl_pct:.2f}%",
                "confidence": 0.55,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }

        if pnl_pct >= profit_target:
            return {
                "action": close_action,
                "reason": f"Profit target reached ({profit_target:.2f}%), P&L: {pnl_pct:.2f}%",
                "confidence": 0.9,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }

        if pnl_pct <= -stop_loss:
            return {
                "action": close_action,
                "reason": f"Stop loss triggered ({stop_loss:.2f}%), P&L: {pnl_pct:.2f}%",
                "confidence": 0.45,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }

        if peak_profit_pct >= 0.8 and pnl_pct <= peak_profit_pct - trailing_gap:
            return {
                "action": close_action,
                "reason": (
                    f"Trailing stop (peak {peak_profit_pct:.2f}%, "
                    f"drawdown {peak_profit_pct - pnl_pct:.2f}%)"
                ),
                "confidence": 0.72,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }

        directional_score = self._calculate_penny_directional_score(prices, i)
        if direction == "long" and directional_score < -0.25:
            return {
                "action": close_action,
                "reason": f"Momentum reversal exit, P&L: {pnl_pct:.2f}%",
                "confidence": 0.68,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }
        if direction == "short" and directional_score > 0.25:
            return {
                "action": close_action,
                "reason": f"Momentum reversal exit, P&L: {pnl_pct:.2f}%",
                "confidence": 0.68,
                "technical_indicators": {"pnl_pct": pnl_pct, "time_held": time_held},
            }

        return None

    def _calculate_high_quality_momentum(
        self, 
        prices: List[float], 
        volumes: List[float], 
        highs: List[float], 
        lows: List[float], 
        i: int
    ) -> float:
        """High quality momentum calculation"""
        if i < 30:
            return 0.0

        # Multiple timeframe momentum with higher weights
        momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        momentum_20 = (prices[i] - prices[i-20]) / prices[i-20] * 100 if i >= 20 else 0
        momentum_30 = (prices[i] - prices[i-30]) / prices[i-30] * 100 if i >= 30 else 0
        
        # Weighted momentum (emphasize shorter timeframes)
        momentum_score = (momentum_2 * 0.3 + momentum_5 * 0.3 + momentum_10 * 0.2 + momentum_20 * 0.1 + momentum_30 * 0.1)
        
        # Strong volume-weighted momentum
        recent_window = volumes[max(0, i - 5) : i + 1]
        recent_volume = sum(recent_window) / len(recent_window) if recent_window else 0.0
        avg_window = volumes[max(0, i - 20) : i - 5] if i > 20 else recent_window
        avg_volume = sum(avg_window) / len(avg_window) if avg_window else recent_volume
        volume_weight = min(recent_volume / avg_volume, 3.0) if avg_volume > 0 else 1.0
        
        # Price range momentum
        recent_high = max(highs[max(0, i-10):i])
        recent_low = min(lows[max(0, i-10):i])
        range_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        # Volatility boost (only for moderate volatility)
        recent_volatility = (max(prices[max(0, i-10):i+1]) - min(prices[max(0, i-10):i+1])) / prices[i]
        volatility_boost = 1.0 + min(recent_volatility * 2, 1.0)  # Max 2x boost
        
        # Final momentum score
        final_momentum = momentum_score * volume_weight * (0.3 + range_position * 0.7) * volatility_boost
        
        return final_momentum

    def _calculate_penny_directional_score(self, prices: List[float], i: int) -> float:
        """Directional momentum score tuned for penny-stock volatility swings."""
        if i < 15:
            return 0.0

        p_now = prices[i]
        p_3 = prices[i - 3]
        p_8 = prices[i - 8]
        p_15 = prices[i - 15]
        if p_3 <= 0 or p_8 <= 0 or p_15 <= 0:
            return 0.0

        m3 = (p_now - p_3) / p_3 * 100
        m8 = (p_now - p_8) / p_8 * 100
        m15 = (p_now - p_15) / p_15 * 100
        return m3 * 0.5 + m8 * 0.3 + m15 * 0.2

    def _analyze_high_quality_volume(self, volumes: List[float], i: int) -> Dict[str, float]:
        """Analyze high quality volume"""
        # Recent volume analysis
        recent_window = volumes[max(0, i - 5) : i + 1]
        recent_volume = sum(recent_window) / len(recent_window) if recent_window else 0.0
        avg_window_10 = volumes[max(0, i - 15) : i - 5] if i > 15 else recent_window
        avg_window_20 = volumes[max(0, i - 25) : i - 5] if i > 25 else recent_window
        avg_volume_10 = sum(avg_window_10) / len(avg_window_10) if avg_window_10 else recent_volume
        avg_volume_20 = sum(avg_window_20) / len(avg_window_20) if avg_window_20 else recent_volume
        
        volume_ratio_10 = recent_volume / avg_volume_10 if avg_volume_10 > 0 else 1.0
        volume_ratio_20 = recent_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
        
        # Volume trend
        short_window = volumes[max(0, i - 3) : i + 1]
        long_window = volumes[max(0, i - 8) : i - 3]
        short_avg = sum(short_window) / len(short_window) if short_window else 0.0
        long_avg = sum(long_window) / len(long_window) if long_window else 0.0
        volume_trend = ((short_avg - long_avg) / long_avg) if long_avg > 0 else 0.0
        
        return {
            "volume_ratio": max(volume_ratio_10, volume_ratio_20),
            "volume_trend": volume_trend,
            "recent_volume": recent_volume,
        }

    def _high_quality_technical_analysis(self, prices: List[float], highs: List[float], lows: List[float], i: int) -> Dict[str, float]:
        """High quality technical analysis"""
        if i < 30:
            return {
                "rsi": 50.0,
                "trend_strength": 0.0,
                "price_position": 0.5,
                "volatility": 0.01,
                "trend_regime_ok": False,
                "sma50": prices[i] if i < len(prices) else 0.0,
                "sma200": prices[i] if i < len(prices) else 0.0,
            }
        
        # RSI calculation
        rsi = self._high_quality_rsi(prices[max(0, i-20):i+1])
        
        # Strong trend strength calculation
        short_trend = (prices[i] - prices[i-5]) / prices[i-5] if i >= 5 else 0
        medium_trend = (prices[i] - prices[i-15]) / prices[i-15] if i >= 15 else 0
        long_trend = (prices[i] - prices[i-25]) / prices[i-25] if i >= 25 else 0
        
        # Weighted trend strength (emphasize medium trend)
        trend_strength = (short_trend * 0.3 + medium_trend * 0.5 + long_trend * 0.2)
        trend_strength = max(-1.0, min(1.0, trend_strength))
        
        # Price position in recent range
        recent_high = max(highs[max(0, i-15):i])
        recent_low = min(lows[max(0, i-15):i])
        price_position = (prices[i] - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        
        # Volatility
        recent_prices = prices[max(0, i-15):i+1]
        volatility = (max(recent_prices) - min(recent_prices)) / sum(recent_prices) * len(recent_prices) if recent_prices else 0.01

        # Trend regime: only take longs in clear uptrends.
        if i >= 200:
            sma50 = sum(prices[i - 49 : i + 1]) / 50
            sma200 = sum(prices[i - 199 : i + 1]) / 200
            trend_regime_ok = prices[i] > sma50 and sma50 > sma200 and sma50 >= sma200 * 1.005
        else:
            sma50 = sum(prices[max(0, i - 49) : i + 1]) / len(prices[max(0, i - 49) : i + 1])
            sma200 = sma50
            trend_regime_ok = False
        
        return {
            "rsi": rsi,
            "trend_strength": trend_strength,
            "price_position": price_position,
            "volatility": volatility,
            "trend_regime_ok": trend_regime_ok,
            "sma50": sma50,
            "sma200": sma200,
        }

    def _high_quality_rsi(self, prices: List[float], period: int = 20) -> float:
        """High quality RSI calculation"""
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

    def _high_quality_entry_filters(self, prices: List[float], volumes: List[float], highs: List[float], lows: List[float], i: int, is_long: bool) -> bool:
        """High quality entry filters"""
        if i < 20:
            return False
        if not is_long:
            return False
        
        # Price stability check (moderate volatility)
        recent_prices = prices[max(0, i-10):i+1]
        price_volatility = max(recent_prices) - min(recent_prices)
        avg_price = sum(recent_prices) / len(recent_prices)
        volatility_ratio = price_volatility / avg_price if avg_price > 0 else 1.0
        
        # Moderate volatility range (not too low, not too high)
        if volatility_ratio < 0.006 or volatility_ratio > 0.10:
            return False
        
        # Volume consistency check
        recent_volumes = volumes[max(0, i-5):i+1]
        volume_consistency = min(recent_volumes) / max(recent_volumes) if max(recent_volumes) > 0 else 0
        
        if volume_consistency < 0.25:
            return False
        
        # Price momentum consistency
        momentum_2 = (prices[i] - prices[i-2]) / prices[i-2] * 100 if i >= 2 else 0
        momentum_5 = (prices[i] - prices[i-5]) / prices[i-5] * 100 if i >= 5 else 0
        momentum_10 = (prices[i] - prices[i-10]) / prices[i-10] * 100 if i >= 10 else 0
        if not (momentum_2 > 0.03 and momentum_5 > 0.07 and momentum_10 > 0.12):
            return False

        # Avoid chasing extreme breakouts.
        recent_high_20 = max(highs[max(0, i - 20) : i])
        if recent_high_20 > 0 and prices[i] > recent_high_20 * 1.02:
            return False

        return True

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[TradeAction]:
        """Run high quality backtest"""
        print(f"Starting HIGH QUALITY backtest from {start_date} to {end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Indicators: {', '.join(indicators)}")
        print("🎯 FOCUS: High quality profitable trades (quality over quantity)")

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

            for indicator in indicators:
                if indicator == "Momentum":
                    momentum_actions = self.simulate_high_quality_trades(ticker, bars, "Momentum")
                    print(f"  High Quality Momentum: {len(momentum_actions)} actions")
                    all_actions.extend(momentum_actions)
                elif indicator == "PennyStocks":
                    penny_actions = self.simulate_high_quality_trades(ticker, bars, "PennyStocks")
                    print(f"  High Quality PennyStocks: {len(penny_actions)} actions")
                    all_actions.extend(penny_actions)

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
                "volume_trend",
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
                    "volume_trend": indicators.get("volume_trend", ""),
                    "pnl_pct": indicators.get("pnl_pct", ""),
                    "time_held": indicators.get("time_held", ""),
                }
                writer.writerow(row)

        print(f"Saved {len(actions)} HIGH QUALITY actions to {filename}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="High quality profitable strategy backtest")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help="Ticker symbols (if empty, uses appropriate stocks for indicators)",
    )
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=["Momentum", "PennyStocks"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output",
        default="high_quality_profitable_trading_2021_2026.csv",
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

    # Use appropriate stocks if no tickers provided
    if not args.tickers:
        engine = HighQualityProfitableStrategy(api_key, secret_key)
        tickers = []
        if "Momentum" in args.indicators:
            tickers.extend(engine.MOMENTUM_STOCKS)
        if "PennyStocks" in args.indicators:
            tickers.extend(engine.PENNY_STOCKS)
        # Remove duplicates
        tickers = list(set(tickers))
        print(f"Using quality stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = HighQualityProfitableStrategy(api_key, secret_key)
    actions = await engine.backtest_indicators(
        tickers, args.start_date, args.end_date, args.indicators
    )

    # Save results
    engine.save_to_csv(actions, args.output)

    # Print summary
    print("\n🎯 HIGH QUALITY PROFITABLE STRATEGY BACKTEST COMPLETED!")
    print(f"Total actions generated: {len(actions)}")
    print("🎯 Goal: High quality profitable trades (quality over quantity)")

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
        print("\n⚠️  No high quality actions generated - try different parameters")


if __name__ == "__main__":
    asyncio.run(main())
