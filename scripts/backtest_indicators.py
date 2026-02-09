#!/usr/bin/env python3
"""
Backtesting script for trading indicators using Alpaca historical data.

This script fetches historical market data from Alpaca and backtests various technical
indicators over a specified time period, outputting CSV files with buy/sell signals.
"""

import os
import sys
import csv
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any
from dataclasses import dataclass
import requests
from dotenv import load_dotenv

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.src.services.trading.technical_indicator_calculator import (
    TechnicalIndicatorCalculator,
)


@dataclass
class BacktestSignal:
    """Represents a trading signal from backtesting"""

    timestamp: str
    ticker: str
    action: str  # 'buy_to_open' or 'sell_to_open' for long/short trades
    price: float
    indicator: str
    signal_type: str  # 'entry' or 'exit'
    reason: str
    technical_indicators: Dict[str, Any]


class AlpacaHistoricalClient:
    """Client for fetching historical data from Alpaca"""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://data.alpaca.markets/v2"
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "accept": "application/json",
        }

    async def fetch_bars(
        self,
        symbols: List[str],
        timeframe: str = "1Min",
        start: str = None,
        end: str = None,
        limit: int = 10000,
    ) -> Dict[str, List[Dict]]:
        """
        Fetch historical bar data from Alpaca

        Args:
            symbols: List of ticker symbols
            timeframe: Timeframe for bars (1Min, 5Min, 15Min, 1Hour, 1Day)
            start: Start date in ISO format
            end: End date in ISO format
            limit: Maximum number of bars to fetch

        Returns:
            Dictionary mapping symbol to list of bar data
        """
        if not start or not end:
            raise ValueError("Start and end dates are required")

        # Join symbols for URL
        symbols_str = ",".join(symbols)

        url = f"{self.base_url}/stocks/bars"
        params = {
            "symbols": symbols_str,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": limit,
            "adjustment": "raw",
            "feed": "sip",
            "sort": "asc",
        }

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            return data.get("bars", {})

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from Alpaca: {e}")
            return {}

    async def fetch_bars_batch(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        batch_days: int = 7,
    ) -> Dict[str, List[Dict]]:
        """
        Fetch bars in batches to handle large date ranges

        Args:
            symbols: List of ticker symbols
            start_date: Start datetime
            end_date: End datetime
            batch_days: Number of days per batch

        Returns:
            Dictionary mapping symbol to list of all bar data
        """
        all_bars = {}
        current_start = start_date

        while current_start < end_date:
            current_end = min(current_start + timedelta(days=batch_days), end_date)

            # Format dates for API
            start_str = current_start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            end_str = current_end.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            print(f"Fetching data from {start_str} to {end_str}")

            batch_bars = await self.fetch_bars(
                symbols=symbols, start=start_str, end=end_str, limit=10000
            )

            # Merge with existing data
            for symbol, bars in batch_bars.items():
                if symbol not in all_bars:
                    all_bars[symbol] = []
                all_bars[symbol].extend(bars)

            current_start = current_end

            # Rate limiting
            await asyncio.sleep(1)

        return all_bars


class IndicatorBacktester:
    """Backtesting engine for technical indicators"""

    def __init__(self, alpaca_client: AlpacaHistoricalClient):
        self.alpaca_client = alpaca_client
        self.signals: List[BacktestSignal] = []

    def generate_rsi_signals(
        self, bars: List[Dict], ticker: str
    ) -> List[BacktestSignal]:
        """Generate RSI-based trading signals"""
        signals = []

        if len(bars) < 15:  # Need enough data for RSI calculation
            return signals

        # Calculate indicators for each point in time
        for i in range(14, len(bars)):
            current_bars = bars[: i + 1]  # Use data up to current point
            indicators = TechnicalIndicatorCalculator.calculate_indicators(current_bars)

            current_bar = bars[i]
            timestamp = current_bar["t"]
            price = current_bar["c"]

            # RSI strategy
            rsi = indicators.rsi

            # Buy signal: RSI oversold
            if rsi < 30:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="buy_to_open",
                        price=price,
                        indicator="RSI",
                        signal_type="entry",
                        reason=f"RSI oversold: {rsi:.2f}",
                        technical_indicators=indicators.to_dict(),
                    )
                )

            # Sell signal: RSI overbought
            elif rsi > 70:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="sell_to_open",
                        price=price,
                        indicator="RSI",
                        signal_type="entry",
                        reason=f"RSI overbought: {rsi:.2f}",
                        technical_indicators=indicators.to_dict(),
                    )
                )

        return signals

    def generate_macd_signals(
        self, bars: List[Dict], ticker: str
    ) -> List[BacktestSignal]:
        """Generate MACD-based trading signals"""
        signals = []

        if len(bars) < 27:  # Need enough data for MACD calculation
            return signals

        prev_macd_hist = None

        for i in range(26, len(bars)):
            current_bars = bars[: i + 1]
            indicators = TechnicalIndicatorCalculator.calculate_indicators(current_bars)

            current_bar = bars[i]
            timestamp = current_bar["t"]
            price = current_bar["c"]

            macd_line, signal_line, histogram = indicators.macd

            # MACD crossover strategy
            if prev_macd_hist is not None:
                # Bullish crossover: histogram crosses above zero
                if prev_macd_hist < 0 and histogram > 0:
                    signals.append(
                        BacktestSignal(
                            timestamp=timestamp,
                            ticker=ticker,
                            action="buy_to_open",
                            price=price,
                            indicator="MACD",
                            signal_type="entry",
                            reason=(
                                f"MACD bullish crossover: " f"hist {histogram:.4f}"
                            ),
                            technical_indicators=indicators.to_dict(),
                        )
                    )

                # Bearish crossover: histogram crosses below zero
                elif prev_macd_hist > 0 and histogram < 0:
                    signals.append(
                        BacktestSignal(
                            timestamp=timestamp,
                            ticker=ticker,
                            action="sell_to_open",
                            price=price,
                            indicator="MACD",
                            signal_type="entry",
                            reason=(
                                f"MACD bearish crossover: " f"hist {histogram:.4f}"
                            ),
                            technical_indicators=indicators.to_dict(),
                        )
                    )

            prev_macd_hist = histogram

        return signals

    def generate_bollinger_signals(
        self, bars: List[Dict], ticker: str
    ) -> List[BacktestSignal]:
        """Generate Bollinger Bands-based trading signals"""
        signals = []

        if len(bars) < 21:  # Need enough data for Bollinger Bands
            return signals

        for i in range(20, len(bars)):
            current_bars = bars[: i + 1]
            indicators = TechnicalIndicatorCalculator.calculate_indicators(current_bars)

            current_bar = bars[i]
            timestamp = current_bar["t"]
            price = current_bar["c"]

            upper_band, middle_band, lower_band = indicators.bollinger

            # Bollinger Bands strategy
            # Buy when price touches lower band (oversold)
            if price <= lower_band:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="buy_to_open",
                        price=price,
                        indicator="Bollinger",
                        signal_type="entry",
                        reason=(
                            f"Price at lower band: " f"{price:.2f} <= {lower_band:.2f}"
                        ),
                        technical_indicators=indicators.to_dict(),
                    )
                )

            # Sell when price touches upper band (overbought)
            elif price >= upper_band:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="sell_to_open",
                        price=price,
                        indicator="Bollinger",
                        signal_type="entry",
                        reason=(
                            f"Price at upper band: " f"{price:.2f} >= {upper_band:.2f}"
                        ),
                        technical_indicators=indicators.to_dict(),
                    )
                )

        return signals

    def generate_stochastic_signals(
        self, bars: List[Dict], ticker: str
    ) -> List[BacktestSignal]:
        """Generate Stochastic oscillator-based trading signals"""
        signals = []

        if len(bars) < 15:  # Need enough data for Stochastic
            return signals

        for i in range(14, len(bars)):
            current_bars = bars[: i + 1]
            indicators = TechnicalIndicatorCalculator.calculate_indicators(current_bars)

            current_bar = bars[i]
            timestamp = current_bar["t"]
            price = current_bar["c"]

            stoch_k, stoch_d = indicators.stoch

            # Stochastic oscillator strategy
            # Buy when Stochastic is oversold (%K below 20)
            if stoch_k < 20:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="buy_to_open",
                        price=price,
                        indicator="Stochastic",
                        signal_type="entry",
                        reason=f"Stochastic oversold: %K {stoch_k:.2f}",
                        technical_indicators=indicators.to_dict(),
                    )
                )

            # Sell when Stochastic is overbought (%K above 80)
            elif stoch_k > 80:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="sell_to_open",
                        price=price,
                        indicator="Stochastic",
                        signal_type="entry",
                        reason=(f"Stochastic overbought: " f"%K {stoch_k:.2f}"),
                        technical_indicators=indicators.to_dict(),
                    )
                )

        return signals

    def generate_cci_signals(
        self, bars: List[Dict], ticker: str
    ) -> List[BacktestSignal]:
        """Generate Commodity Channel Index-based trading signals"""
        signals = []

        if len(bars) < 21:  # Need enough data for CCI
            return signals

        for i in range(20, len(bars)):
            current_bars = bars[: i + 1]
            indicators = TechnicalIndicatorCalculator.calculate_indicators(current_bars)

            current_bar = bars[i]
            timestamp = current_bar["t"]
            price = current_bar["c"]

            cci = indicators.cci

            # CCI strategy
            # Buy when CCI is oversold (below -100)
            if cci < -100:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="buy_to_open",
                        price=price,
                        indicator="CCI",
                        signal_type="entry",
                        reason=f"CCI oversold: {cci:.2f}",
                        technical_indicators=indicators.to_dict(),
                    )
                )

            # Sell when CCI is overbought (above 100)
            elif cci > 100:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="sell_to_open",
                        price=price,
                        indicator="CCI",
                        signal_type="entry",
                        reason=f"CCI overbought: {cci:.2f}",
                        technical_indicators=indicators.to_dict(),
                    )
                )

        return signals

    def generate_williams_r_signals(
        self, bars: List[Dict], ticker: str
    ) -> List[BacktestSignal]:
        """Generate Williams %R-based trading signals"""
        signals = []

        if len(bars) < 15:  # Need enough data for Williams %R
            return signals

        for i in range(14, len(bars)):
            current_bars = bars[: i + 1]
            indicators = TechnicalIndicatorCalculator.calculate_indicators(current_bars)

            current_bar = bars[i]
            timestamp = current_bar["t"]
            price = current_bar["c"]

            willr = indicators.willr

            # Williams %R strategy
            # Buy when Williams %R is oversold (below -80)
            if willr < -80:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="buy_to_open",
                        price=price,
                        indicator="Williams_R",
                        signal_type="entry",
                        reason=f"Williams %R oversold: {willr:.2f}",
                        technical_indicators=indicators.to_dict(),
                    )
                )

            # Sell when Williams %R is overbought (above -20)
            elif willr > -20:
                signals.append(
                    BacktestSignal(
                        timestamp=timestamp,
                        ticker=ticker,
                        action="sell_to_open",
                        price=price,
                        indicator="Williams_R",
                        signal_type="entry",
                        reason=(f"Williams %R overbought: " f"{willr:.2f}"),
                        technical_indicators=indicators.to_dict(),
                    )
                )

        return signals

    async def backtest_ticker(
        self, ticker: str, bars: List[Dict], indicators: List[str]
    ) -> List[BacktestSignal]:
        """Backtest all indicators for a single ticker"""
        all_signals = []

        print(f"Backtesting {ticker} with {len(bars)} bars...")

        # Generate signals for each indicator
        if "RSI" in indicators:
            signals = self.generate_rsi_signals(bars, ticker)
            all_signals.extend(signals)
            print(f"  RSI: {len(signals)} signals")

        if "MACD" in indicators:
            signals = self.generate_macd_signals(bars, ticker)
            all_signals.extend(signals)
            print(f"  MACD: {len(signals)} signals")

        if "Bollinger" in indicators:
            signals = self.generate_bollinger_signals(bars, ticker)
            all_signals.extend(signals)
            print(f"  Bollinger: {len(signals)} signals")

        if "Stochastic" in indicators:
            signals = self.generate_stochastic_signals(bars, ticker)
            all_signals.extend(signals)
            print(f"  Stochastic: {len(signals)} signals")

        if "CCI" in indicators:
            signals = self.generate_cci_signals(bars, ticker)
            all_signals.extend(signals)
            print(f"  CCI: {len(signals)} signals")

        if "Williams_R" in indicators:
            signals = self.generate_williams_r_signals(bars, ticker)
            all_signals.extend(signals)
            print(f"  Williams %R: {len(signals)} signals")

        return all_signals

    async def run_backtest(
        self,
        tickers: List[str],
        start_date: datetime,
        end_date: datetime,
        indicators: List[str],
    ) -> List[BacktestSignal]:
        """Run backtest for all tickers and indicators"""
        print(f"Starting backtest from {start_date.date()} to {end_date.date()}")
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

            signals = await self.backtest_ticker(ticker, bars, indicators)
            all_signals.extend(signals)

        # Sort signals by timestamp
        all_signals.sort(key=lambda x: x.timestamp)

        return all_signals

    def save_to_csv(self, signals: List[BacktestSignal], filename: str):
        """Save signals to CSV file"""
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
            "rsi",
            "macd",
            "macd_signal",
            "macd_histogram",
            "bollinger_upper",
            "bollinger_middle",
            "bollinger_lower",
            "stoch_k",
            "stoch_d",
            "cci",
            "willr",
            "atr",
            "volume",
        ]

        with open(filename, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for signal in signals:
                indicators = signal.technical_indicators

                # Handle both dict and tuple formats for nested indicators
                macd_data = indicators.get("macd", {})
                if isinstance(macd_data, (list, tuple)) and len(macd_data) >= 3:
                    macd_val, signal_val, hist_val = (
                        macd_data[0],
                        macd_data[1],
                        macd_data[2],
                    )
                elif isinstance(macd_data, dict):
                    macd_val = macd_data.get("macd", "")
                    signal_val = macd_data.get("signal", "")
                    hist_val = macd_data.get("hist", "")
                else:
                    macd_val, signal_val, hist_val = "", "", ""

                bollinger_data = indicators.get("bollinger", {})
                if (
                    isinstance(bollinger_data, (list, tuple))
                    and len(bollinger_data) >= 3
                ):
                    upper_val, middle_val, lower_val = (
                        bollinger_data[0],
                        bollinger_data[1],
                        bollinger_data[2],
                    )
                elif isinstance(bollinger_data, dict):
                    upper_val = bollinger_data.get("upper", "")
                    middle_val = bollinger_data.get("middle", "")
                    lower_val = bollinger_data.get("lower", "")
                else:
                    upper_val, middle_val, lower_val = "", "", ""

                stoch_data = indicators.get("stoch", {})
                if isinstance(stoch_data, (list, tuple)) and len(stoch_data) >= 2:
                    k_val, d_val = stoch_data[0], stoch_data[1]
                elif isinstance(stoch_data, dict):
                    k_val = stoch_data.get("k", "")
                    d_val = stoch_data.get("d", "")
                else:
                    k_val, d_val = "", ""

                row = {
                    "timestamp": signal.timestamp,
                    "ticker": signal.ticker,
                    "action": signal.action,
                    "price": signal.price,
                    "indicator": signal.indicator,
                    "signal_type": signal.signal_type,
                    "reason": signal.reason,
                    "rsi": indicators.get("rsi", ""),
                    "macd": macd_val,
                    "macd_signal": signal_val,
                    "macd_histogram": hist_val,
                    "bollinger_upper": upper_val,
                    "bollinger_middle": middle_val,
                    "bollinger_lower": lower_val,
                    "stoch_k": k_val,
                    "stoch_d": d_val,
                    "cci": indicators.get("cci", ""),
                    "willr": indicators.get("willr", ""),
                    "atr": indicators.get("atr", ""),
                    "volume": indicators.get("volume", ""),
                }

                writer.writerow(row)

        print(f"Saved {len(signals)} signals to {filename}")


async def main():
    """Main function to run the backtesting"""
    parser = argparse.ArgumentParser(
        description="Backtest trading indicators with Alpaca data"
    )
    parser.add_argument(
        "--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date", type=str, required=True, help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        nargs="+",
        default=["AAPL", "TSLA"],
        help="Ticker symbols",
    )
    parser.add_argument(
        "--indicators",
        type=str,
        nargs="+",
        default=["RSI", "MACD", "Bollinger", "Stochastic", "CCI", "Williams_R"],
        choices=["RSI", "MACD", "Bollinger", "Stochastic", "CCI", "Williams_R"],
        help="Indicators to backtest",
    )
    parser.add_argument(
        "--output", type=str, default="backtest_results.csv", help="Output CSV filename"
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Get API keys from environment
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        print(
            "Error: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in environment variables"
        )
        sys.exit(1)

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        print("Error: Dates must be in YYYY-MM-DD format")
        sys.exit(1)

    # Create Alpaca client
    alpaca_client = AlpacaHistoricalClient(api_key, secret_key)

    # Create backtester
    backtester = IndicatorBacktester(alpaca_client)

    # Run backtest
    try:
        signals = await backtester.run_backtest(
            tickers=args.tickers,
            start_date=start_date,
            end_date=end_date,
            indicators=args.indicators,
        )

        # Save results
        backtester.save_to_csv(signals, args.output)

        # Print summary
        print(f"\nBacktest completed!")
        print(f"Total signals generated: {len(signals)}")

        # Summary by indicator
        indicator_counts = {}
        for signal in signals:
            indicator_counts[signal.indicator] = (
                indicator_counts.get(signal.indicator, 0) + 1
            )

        print("\nSignals by indicator:")
        for indicator, count in sorted(indicator_counts.items()):
            print(f"  {indicator}: {count}")

        # Summary by ticker
        ticker_counts = {}
        for signal in signals:
            ticker_counts[signal.ticker] = ticker_counts.get(signal.ticker, 0) + 1

        print("\nSignals by ticker:")
        for ticker, count in sorted(ticker_counts.items()):
            print(f"  {ticker}: {count}")

    except Exception as e:
        print(f"Error during backtesting: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
