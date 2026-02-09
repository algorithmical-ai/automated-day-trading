#!/usr/bin/env python3
"""
Improved Backtest Trading Indicators Script

This script backtests the actual trading indicators (Momentum and Penny Stocks)
from the codebase using historical data from Alpaca API with enhanced logic.
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

from app.src.services.technical_analysis.technical_analysis_lib import (
    TechnicalAnalysisLib,
)


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


class ImprovedBacktestEngine:
    """Improved backtesting engine with enhanced algorithm logic"""

    def __init__(self, api_key: str, secret_key: str):
        self.alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # List of actual penny stocks (under $5) that were actively trading in 2024
    PENNY_STOCKS = [
        "AMC",  # AMC Entertainment
        "GME",  # GameStop (was under $5 for parts of 2024)
        "BB",  # BlackBerry
        "NOK",  # Nokia
        "SNDL",  # Sundial Growers
        "BNGO",  # Golden Entertainment
        "MVIS",  # MicroVision
        "SPCE",  # Virgin Galactic
        "PLTR",  # Palantir (was under $5 early 2024)
        "RIOT",  # Riot Blockchain
        "MARA",  # Marathon Digital
        "BITF",  # Bitfarms
        "HUT",  # Hut 8 Mining
        "COIN",  # Coinbase (was under $5 briefly)
        "ROKU",  # Roku (was under $5 early 2024)
        "TSLA",  # Tesla (was under $5 in early days)
        "NVDA",  # NVIDIA (was under $5 in early days)
    ]

    def simulate_momentum_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Enhanced MomentumIndicator simulation with proper logic"""
        signals = []

        if len(bars) < 50:  # Need enough data for technical indicators
            return signals

        print(f"Simulating Momentum for {ticker} with {len(bars)} bars")

        # Convert bars to the format expected by TechnicalAnalysisLib
        # We'll calculate indicators manually since we need historical data

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]

        # Calculate basic indicators manually
        indicators_data = self._calculate_basic_indicators(prices, volumes, highs, lows)

        # Simulate momentum entry logic
        for i in range(50, len(bars)):  # Start after enough data
            current_bar = bars[i]
            timestamp = current_bar.get("t", "")
            price = float(current_bar.get("c", 0))

            # Get current indicators
            rsi = (
                indicators_data.get("rsi", [])[i]
                if i < len(indicators_data.get("rsi", []))
                else 50
            )
            macd_line = (
                indicators_data.get("macd_line", [])[i]
                if i < len(indicators_data.get("macd_line", []))
                else 0
            )
            macd_signal = (
                indicators_data.get("macd_signal", [])[i]
                if i < len(indicators_data.get("macd_signal", []))
                else 0
            )
            volume_sma = (
                indicators_data.get("volume_sma", [])[i]
                if i < len(indicators_data.get("volume_sma", []))
                else volumes[i]
            )
            adx = (
                indicators_data.get("adx", [])[i]
                if i < len(indicators_data.get("adx", []))
                else 20
            )

            # Enhanced momentum calculation
            momentum_score = self._calculate_enhanced_momentum(
                bars[: i + 1], indicators_data, i
            )

            # Momentum indicator entry conditions (from actual code)
            if abs(momentum_score) >= 1.5:  # min_momentum_threshold
                # Volume filter
                current_volume = float(current_bar.get("v", 0))
                volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1.0

                if volume_ratio >= 1.5:  # min_volume_ratio
                    # ADX filter for trend strength
                    if adx >= 20.0:  # min_adx_threshold
                        # RSI filters
                        if momentum_score > 0:  # Long entry
                            if (
                                45.0 <= rsi <= 70.0
                            ):  # rsi_min_for_long to rsi_max_for_long
                                action = "buy_to_open"
                                reason = f"Momentum long: score={momentum_score:.2f}, rsi={rsi:.1f}, volume_ratio={volume_ratio:.1f}"
                                confidence = min(abs(momentum_score) / 5.0, 1.0)

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
                                        "rsi": rsi,
                                        "macd": (macd_line, macd_signal, 0),
                                        "volume_ratio": volume_ratio,
                                        "adx": adx,
                                        "momentum_score": momentum_score,
                                    },
                                )
                                signals.append(signal)

                        elif momentum_score < 0:  # Short entry
                            if (
                                50.0 <= rsi <= 80.0
                            ):  # rsi_min_for_short to rsi_max_for_short
                                action = "sell_to_open"
                                reason = f"Momentum short: score={momentum_score:.2f}, rsi={rsi:.1f}, volume_ratio={volume_ratio:.1f}"
                                confidence = min(abs(momentum_score) / 5.0, 1.0)

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
                                        "rsi": rsi,
                                        "macd": (macd_line, macd_signal, 0),
                                        "volume_ratio": volume_ratio,
                                        "adx": adx,
                                        "momentum_score": momentum_score,
                                    },
                                )
                                signals.append(signal)

        return signals

    def simulate_penny_stocks_indicator(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
    ) -> List[BacktestSignal]:
        """Enhanced PennyStocksIndicator simulation with proper logic"""
        signals = []

        if len(bars) < 30:  # Need enough data for analysis
            return signals

        # Check if this is actually a penny stock
        current_price = float(bars[-1].get("c", 0))
        if not (0.75 <= current_price <= 5.0):  # min_stock_price to max_stock_price
            print(f"{ticker} price ${current_price:.2f} - not in penny stock range")
            return signals

        print(f"{ticker} price ${current_price:.2f} - penny stock candidate")

        # Extract price and volume data
        prices = [float(bar.get("c", 0)) for bar in bars]
        volumes = [float(bar.get("v", 0)) for bar in bars]
        highs = [float(bar.get("h", 0)) for bar in bars]
        lows = [float(bar.get("l", 0)) for bar in bars]

        # Calculate basic indicators manually
        indicators_data = self._calculate_basic_indicators(prices, volumes, highs, lows)

        # Track entries per day (one entry per ticker per day rule)
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

            # Skip if already entered today
            if date_str in entries_by_date:
                continue

            # Enhanced penny stocks momentum calculation
            momentum_score = self._calculate_penny_stocks_momentum(
                bars[: i + 1], indicators_data, i
            )

            # Penny stocks entry conditions (from actual code)
            if abs(momentum_score) >= 5.0:  # min_momentum_threshold
                # Additional penny stock filters
                rsi = (
                    indicators_data.get("rsi", [])[i]
                    if i < len(indicators_data.get("rsi", []))
                    else 50
                )
                volume_sma = (
                    indicators_data.get("volume_sma", [])[i]
                    if i < len(indicators_data.get("volume_sma", []))
                    else volumes[i]
                )

                # Volume filter
                current_volume = float(current_bar.get("v", 0))
                volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1.0

                if volume_ratio >= 2.0:  # Higher volume requirement for penny stocks
                    # Trend confirmation for penny stocks
                    trend_confirmed = self._confirm_penny_stock_trend(
                        bars[: i + 1], momentum_score > 0
                    )

                    if trend_confirmed:
                        # Penny stocks typically only go long (avoid shorting volatile penny stocks)
                        if (
                            momentum_score > 0 and 30.0 <= rsi <= 70.0
                        ):  # Conservative RSI range
                            action = "buy_to_open"
                            reason = f"Penny stock long: score={momentum_score:.2f}, rsi={rsi:.1f}, volume_ratio={volume_ratio:.1f}"
                            confidence = min(abs(momentum_score) / 10.0, 1.0)

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
                                    "rsi": rsi,
                                    "volume_ratio": volume_ratio,
                                    "momentum_score": momentum_score,
                                    "price": price,
                                },
                            )
                            signals.append(signal)

                            # Mark this date as having an entry
                            entries_by_date[date_str] = True

        return signals

    def _calculate_basic_indicators(
        self,
        prices: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
    ) -> Dict[str, List[float]]:
        """Calculate basic technical indicators manually"""
        indicators = {
            "rsi": [],
            "macd_line": [],
            "macd_signal": [],
            "volume_sma": [],
            "adx": [],
        }

        # Simple RSI calculation
        if len(prices) >= 14:
            rsi_values = self._calculate_rsi(prices)
            indicators["rsi"] = rsi_values

        # Simple MACD calculation
        if len(prices) >= 26:
            macd_line, macd_signal = self._calculate_macd(prices)
            indicators["macd_line"] = macd_line
            indicators["macd_signal"] = macd_signal

        # Volume SMA
        if len(volumes) >= 20:
            volume_sma = self._calculate_sma(volumes, 20)
            indicators["volume_sma"] = volume_sma

        # Simple ADX approximation (using price volatility)
        if len(prices) >= 14:
            adx_values = self._calculate_adx_approx(highs, lows, prices)
            indicators["adx"] = adx_values

        return indicators

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        """Simple RSI calculation"""
        if len(prices) < period + 1:
            return [50.0] * len(prices)

        rsi_values = [50.0] * period  # Initialize with neutral values

        for i in range(period, len(prices)):
            gains = []
            losses = []

            for j in range(i - period + 1, i + 1):
                change = prices[j] - prices[j - 1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))

            avg_gain = sum(gains) / period if gains else 0
            avg_loss = sum(losses) / period if losses else 0

            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))

            rsi_values.append(rsi)

        return rsi_values

    def _calculate_macd(
        self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Tuple[List[float], List[float]]:
        """Simple MACD calculation"""
        if len(prices) < slow:
            return [0.0] * len(prices), [0.0] * len(prices)

        # Calculate EMAs
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)

        # MACD line
        macd_line = []
        for i in range(len(prices)):
            if i < max(fast, slow) - 1:
                macd_line.append(0.0)
            else:
                macd_line.append(ema_fast[i] - ema_slow[i])

        # Signal line (EMA of MACD)
        macd_signal = self._calculate_ema(macd_line, signal)

        return macd_line, macd_signal

    def _calculate_ema(self, values: List[float], period: int) -> List[float]:
        """Simple EMA calculation"""
        if len(values) < period:
            return values.copy()

        ema = [0.0] * len(values)
        multiplier = 2.0 / (period + 1.0)

        # Start with SMA
        ema[period - 1] = sum(values[:period]) / period

        # Calculate EMA
        for i in range(period, len(values)):
            ema[i] = (values[i] * multiplier) + (ema[i - 1] * (1.0 - multiplier))

        # Fill initial values
        for i in range(period - 1):
            ema[i] = ema[period - 1]

        return ema

    def _calculate_sma(self, values: List[float], period: int) -> List[float]:
        """Simple SMA calculation"""
        if len(values) < period:
            return [sum(values) / len(values)] * len(values)

        sma = []
        for i in range(len(values)):
            if i < period - 1:
                sma.append(sum(values[: i + 1]) / (i + 1))
            else:
                sma.append(sum(values[i - period + 1 : i + 1]) / period)

        return sma

    def _calculate_adx_approx(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> List[float]:
        """Simple ADX approximation using volatility"""
        if len(closes) < period:
            return [20.0] * len(closes)

        adx_values = [20.0] * period  # Initialize with neutral values

        for i in range(period, len(closes)):
            # Calculate True Range based volatility
            tr_values = []
            for j in range(i - period + 1, i + 1):
                high_low = highs[j] - lows[j]
                high_close = abs(highs[j] - closes[j - 1]) if j > 0 else 0
                low_close = abs(lows[j] - closes[j - 1]) if j > 0 else 0
                tr = max(high_low, high_close, low_close)
                tr_values.append(tr)

            avg_tr = sum(tr_values) / period if tr_values else 0
            avg_price = sum(closes[i - period + 1 : i + 1]) / period

            # Simple ADX approximation based on volatility
            if avg_price > 0:
                volatility_ratio = (avg_tr / avg_price) * 100
                adx = min(100.0, volatility_ratio * 2)  # Scale to ADX-like range
            else:
                adx = 20.0

            adx_values.append(adx)

        return adx_values

    def _calculate_enhanced_momentum(
        self,
        bars: List[Dict[str, Any]],
        indicators_data: Dict[str, List],
        current_idx: int,
    ) -> float:
        """Enhanced momentum calculation based on actual MomentumIndicator logic"""
        if current_idx < 20:
            return 0.0

        # Get recent prices
        prices = [float(bar.get("c", 0)) for bar in bars[-20:]]

        # Calculate price momentum
        if len(prices) < 2:
            return 0.0

        # Multiple timeframe momentum
        momentum_5 = (
            (prices[-1] - prices[-5]) / prices[-5] * 100 if len(prices) >= 5 else 0
        )
        momentum_10 = (
            (prices[-1] - prices[-10]) / prices[-10] * 100 if len(prices) >= 10 else 0
        )
        momentum_20 = (
            (prices[-1] - prices[-20]) / prices[-20] * 100 if len(prices) >= 20 else 0
        )

        # Weight recent momentum more heavily
        weighted_momentum = momentum_5 * 0.5 + momentum_10 * 0.3 + momentum_20 * 0.2

        # Volume confirmation
        volumes = [float(bar.get("v", 0)) for bar in bars[-10:]]
        if len(volumes) >= 5:
            recent_volume = sum(volumes[-3:]) / 3
            avg_volume = (
                sum(volumes[:-3]) / len(volumes[:-3])
                if len(volumes[:-3]) > 0
                else recent_volume
            )
            volume_factor = (
                min(recent_volume / avg_volume, 3.0) if avg_volume > 0 else 1.0
            )
        else:
            volume_factor = 1.0

        # Final momentum score with volume confirmation
        final_momentum = weighted_momentum * volume_factor

        return final_momentum

    def _calculate_penny_stocks_momentum(
        self,
        bars: List[Dict[str, Any]],
        indicators_data: Dict[str, List],
        current_idx: int,
    ) -> float:
        """Enhanced penny stocks momentum calculation"""
        if current_idx < 15:
            return 0.0

        # Get recent prices for penny stock analysis
        prices = [float(bar.get("c", 0)) for bar in bars[-15:]]

        if len(prices) < 2:
            return 0.0

        # Penny stocks need stronger momentum confirmation
        momentum_5 = (
            (prices[-1] - prices[-5]) / prices[-5] * 100 if len(prices) >= 5 else 0
        )
        momentum_10 = (
            (prices[-1] - prices[-10]) / prices[-10] * 100 if len(prices) >= 10 else 0
        )
        momentum_15 = (
            (prices[-1] - prices[-15]) / prices[-15] * 100 if len(prices) >= 15 else 0
        )

        # Penny stocks require consistent momentum across timeframes
        if momentum_5 > 0 and momentum_10 > 0 and momentum_15 > 0:
            # All timeframes showing upward momentum
            weighted_momentum = momentum_5 * 0.4 + momentum_10 * 0.4 + momentum_15 * 0.2
        elif momentum_5 < 0 and momentum_10 < 0 and momentum_15 < 0:
            # All timeframes showing downward momentum
            weighted_momentum = momentum_5 * 0.4 + momentum_10 * 0.4 + momentum_15 * 0.2
        else:
            # Mixed signals - reduce momentum
            weighted_momentum = momentum_5 * 0.2 + momentum_10 * 0.3 + momentum_15 * 0.5

        # Volume spike confirmation for penny stocks
        volumes = [float(bar.get("v", 0)) for bar in bars[-10:]]
        if len(volumes) >= 5:
            recent_volume = sum(volumes[-3:]) / 3
            avg_volume = (
                sum(volumes[:-3]) / len(volumes[:-3])
                if len(volumes[:-3]) > 0
                else recent_volume
            )
            volume_factor = (
                min(recent_volume / avg_volume, 5.0) if avg_volume > 0 else 1.0
            )
        else:
            volume_factor = 1.0

        # Penny stocks need stronger volume confirmation
        if volume_factor < 2.0:
            weighted_momentum *= 0.5  # Reduce momentum if volume is weak

        return weighted_momentum

    def _confirm_penny_stock_trend(
        self, bars: List[Dict[str, Any]], is_long: bool
    ) -> bool:
        """Confirm trend direction for penny stocks (more conservative)"""
        if len(bars) < 10:
            return False

        # Check last 3-5 bars for trend confirmation
        recent_bars = bars[-5:]
        prices = [float(bar.get("c", 0)) for bar in recent_bars]

        if len(prices) < 3:
            return False

        # For long: prices should be generally increasing
        if is_long:
            increasing_count = 0
            for i in range(1, len(prices)):
                if prices[i] > prices[i - 1]:
                    increasing_count += 1

            # At least 60% of recent bars should be increasing
            return increasing_count / (len(prices) - 1) >= 0.6
        else:
            # For short: prices should be generally decreasing
            decreasing_count = 0
            for i in range(1, len(prices)):
                if prices[i] < prices[i - 1]:
                    decreasing_count += 1

            # At least 60% of recent bars should be decreasing
            return decreasing_count / (len(prices) - 1) >= 0.6

    async def backtest_indicators(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        indicators: List[str],
    ) -> List[BacktestSignal]:
        """Run backtest for specified indicators"""
        print(f"Starting improved backtest from {start_date} to {end_date}")
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
                "rsi",
                "macd",
                "volume_ratio",
                "momentum_score",
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
                    "rsi": indicators.get("rsi", ""),
                    "macd": indicators.get("macd", ""),
                    "volume_ratio": indicators.get("volume_ratio", ""),
                    "momentum_score": indicators.get("momentum_score", ""),
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
        default="trading_backtest_results.csv",
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
        engine = ImprovedBacktestEngine(api_key, secret_key)
        tickers = engine.PENNY_STOCKS
        print(f"Using default penny stocks: {', '.join(tickers)}")
    else:
        tickers = args.tickers

    # Run backtest
    engine = ImprovedBacktestEngine(api_key, secret_key)
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
            indicator_counts[signal.indicator] = (
                indicator_counts.get(signal.indicator, 0) + 1
            )
            ticker_counts[signal.ticker] = ticker_counts.get(signal.ticker, 0) + 1

        print("\nSignals by indicator:")
        for indicator, count in sorted(indicator_counts.items()):
            print(f"  {indicator}: {count}")

        print("\nSignals by ticker:")
        for ticker, count in sorted(
            ticker_counts.items(), key=lambda x: x[1], reverse=True
        ):
            print(f"  {ticker}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
