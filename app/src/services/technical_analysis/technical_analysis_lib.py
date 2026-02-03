"""
Enhanced Technical Analysis Library

This module provides advanced technical analysis capabilities using TA-Lib for
indicator calculations. It includes additional indicators beyond standard TA-Lib
and provides enhanced analysis for trading decisions.

Features:
- TA-Lib compatible indicator calculations
- Custom VWAP and VWMA calculations
- Statistical analysis including outlier detection
- Comprehensive technical indicator suite
- Memory-optimized caching for indicators (TTL-based)
"""

# pylint: disable=no-member
import asyncio
import gc
import os
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

# Try to import talib, but handle gracefully if not available
try:
    import talib  # pylint: disable=import-error
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    talib = None  # type: ignore
    import warnings
    warnings.warn("TA-Lib not available. Some technical indicators will not work.")

from app.src.common.loguru_logger import logger
from app.src.common.alpaca import AlpacaClient


# MEMORY OPTIMIZATION: No caching for Basic dyno (512MB)
# Process one ticker at a time, discard immediately
# Caching was removed to minimize RAM usage

class IndicatorCache:
    """Disabled cache - no-op for memory constrained environments."""
    
    async def get(self, ticker: str) -> Optional[Dict[str, Any]]:
        return None  # Always miss - no caching
    
    async def put(self, ticker: str, data: Dict[str, Any]) -> None:
        pass  # Don't store anything
    
    async def clear(self) -> None:
        gc.collect()
    
    async def cleanup_expired(self) -> int:
        gc.collect()
        return 0
    
    async def stats(self) -> Dict[str, Any]:
        return {"size": 0, "max_size": 0, "ttl_seconds": 0, "hits": 0, "misses": 0, "hit_rate": "0%", "status": "DISABLED"}


# Disabled cache for 512MB Basic dyno
_indicator_cache = IndicatorCache()


class TechnicalAnalysisLib:
    """
    Enhanced technical analysis library using TA-Lib for indicator calculations,
    including additional indicators.
    """

    # Default periods for indicators
    _default_periods = {
        "rsi": 14,
        "macd": (12, 26, 9),
        "bollinger": (20, 2),
        "adx": 14,
        "ema_fast": 12,
        "ema_slow": 26,
        "volume_sma": 20,
        "obv": 1,
        "mfi": 14,
        "ad": 1,
        "stoch": (14, 3, 3),
        "cci": 20,
        "atr": 14,
        "willr": 14,
        "roc": 14,
        "wma": 20,  # For WMA
    }
    max_data_points = 1000

    @classmethod
    def _prepare_price_data(cls, prices: pd.DataFrame) -> pd.DataFrame:
        """Prepare price data for TA-Lib calculations."""
        required_columns = ["high", "low", "close", "open", "volume"]
        df = prices.copy()

        # Fill NaNs and clip values
        for col in required_columns:
            if col in df.columns:
                df[col] = df[col].ffill().bfill()
                if col in ["high", "low", "close", "open"]:
                    df[col] = df[col].clip(lower=0.01)
        df[required_columns] = df[required_columns].astype(np.float64)
        return df[required_columns]

    @classmethod
    def _calculate_vwap(cls, prices: pd.DataFrame) -> float:
        """Calculate Volume Weighted Average Price (VWAP) - Custom as not in TA-Lib."""
        try:
            high, low, close, volume = (
                prices["high"],
                prices["low"],
                prices["close"],
                prices["volume"],
            )
            typical_price = (high + low + close) / 3
            cumulative_tp_volume = (typical_price * volume).cumsum()
            cumulative_volume = volume.cumsum()

            # Check for zero or invalid cumulative volume to prevent division warnings
            cum_vol_last = cumulative_volume.iloc[-1]
            if pd.isna(cum_vol_last) or cum_vol_last == 0:
                # Fallback to simple average of close prices if volume is zero/NaN
                return float(close.iloc[-1]) if not close.empty else 0.0

            cum_tp_vol_last = cumulative_tp_volume.iloc[-1]
            if pd.isna(cum_tp_vol_last):
                return float(close.iloc[-1]) if not close.empty else 0.0

            vwap = cum_tp_vol_last / cum_vol_last

            # Check for NaN or Inf result
            if pd.isna(vwap) or np.isinf(vwap):
                return float(close.iloc[-1]) if not close.empty else 0.0

            return float(vwap)
        except Exception as e:
            logger.info(f"Error calculating VWAP: {e}")
            return 0.0

    @classmethod
    def _calculate_vwma(cls, prices: pd.DataFrame) -> float:
        """Calculate Volume Weighted Moving Average (VWMA) - Custom as not directly in TA-Lib."""
        try:
            period = cls._default_periods.get(
                "volume_sma", 20
            )  # Reuse volume_sma period
            if len(prices) < period:
                return float(prices["close"].iloc[-1])
            recent_data = prices.tail(period)
            typical_price = (
                recent_data["high"] + recent_data["low"] + recent_data["close"]
            ) / 3

            # Check for zero or invalid volume sum to prevent division warnings
            volume_sum = recent_data["volume"].sum()
            if pd.isna(volume_sum) or volume_sum == 0:
                # Fallback to simple average of typical prices if volume is zero/NaN
                return (
                    float(typical_price.mean())
                    if not typical_price.empty
                    else float(recent_data["close"].iloc[-1])
                )

            weighted_sum = (typical_price * recent_data["volume"]).sum()
            if pd.isna(weighted_sum):
                return (
                    float(typical_price.mean())
                    if not typical_price.empty
                    else float(recent_data["close"].iloc[-1])
                )

            vwma = weighted_sum / volume_sum

            # Check for NaN or Inf result
            if pd.isna(vwma) or np.isinf(vwma):
                return (
                    float(typical_price.mean())
                    if not typical_price.empty
                    else float(recent_data["close"].iloc[-1])
                )

            return float(vwma)
        except Exception as e:
            logger.info(f"Error calculating VWMA: {e}")
            return 0.0

    @classmethod
    async def _create_default_indicators(
        cls, ticker: str
    ) -> Dict[str, Any]:  # noqa: ARG002
        """Default indicators for insufficient data."""
        return {
            "rsi": 50.0,
            "macd": (0.0, 0.0, 0.0),
            "bollinger": (100.0 * 1.02, 100.0, 100.0 * 0.98),
            "adx": 20.0,
            "ema_fast": 100.0,
            "ema_slow": 100.0,
            "volume_sma": 25000.0,
            "obv": 0.0,
            "mfi": 50.0,
            "ad": 0.0,
            "stoch": (50.0, 50.0),
            "cci": 0.0,
            "atr": 100.0 * 0.01,
            "willr": -50.0,
            "roc": 0.0,
            "vwma": 0.0,
            "wma": 0.0,
            "vwap": 0.0,
            "volume": 0.0,
            "close_price": 0.0,
            "datetime_price": {},
        }

    @classmethod
    def _bars_to_dataframe(cls, bars: list, ticker: str) -> pd.DataFrame:
        """
        Convert bars from Alpaca API response to pandas DataFrame.

        Args:
            bars: List of bar dictionaries from Alpaca API
            ticker: Ticker symbol

        Returns:
            DataFrame with columns: high, low, close, open, volume, timestamp, price
        """
        if not bars:
            return pd.DataFrame()

        data = []
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            try:
                # Extract bar data
                timestamp_str = bar.get("t", "")
                open_price = float(bar.get("o", 0.0))
                high_price = float(bar.get("h", 0.0))
                low_price = float(bar.get("l", 0.0))
                close_price = float(bar.get("c", 0.0))
                volume = float(bar.get("v", 0.0))

                # Parse timestamp (already in EST from get_market_data)
                timestamp = None
                if timestamp_str:
                    try:
                        # Parse ISO format timestamp
                        timestamp = pd.to_datetime(timestamp_str)
                    except Exception:
                        pass

                data.append(
                    {
                        "timestamp": (
                            timestamp if timestamp is not None else pd.Timestamp.now()
                        ),
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": volume,
                        "price": close_price,  # Use close as price
                        "ticker": ticker,
                    }
                )
            except (ValueError, TypeError, KeyError) as e:
                logger.debug(f"Skipping invalid bar: {e}")
                continue

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        # Sort by timestamp ascending
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp")
            df = df.reset_index(drop=True)

        return df

    @classmethod
    async def get_cache_stats(cls) -> Dict[str, Any]:
        """Get indicator cache statistics."""
        return await _indicator_cache.stats()

    @classmethod
    async def clear_cache(cls) -> None:
        """Clear the indicator cache."""
        await _indicator_cache.clear()
        gc.collect()

    @classmethod
    async def cleanup_cache(cls) -> int:
        """Cleanup expired cache entries and run garbage collection."""
        count = await _indicator_cache.cleanup_expired()
        gc.collect()
        return count

    @classmethod
    async def calculate_all_indicators(cls, ticker: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Calculate all technical indicators using TA-Lib, including additional ones.
        Uses caching to reduce memory usage and API calls.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")
            use_cache: Whether to use cached data if available (default: True)

        Returns:
            Dict with all technical indicators
        """
        # Check cache first (reduces memory churn and API calls)
        if use_cache:
            cached = await _indicator_cache.get(ticker)
            if cached is not None:
                logger.debug(f"Using cached indicators for {ticker}")
                return cached

        # Get market data from Alpaca API
        # BASIC DYNO: Only 50 bars to minimize memory (minimum needed for indicators)
        bars_data = await AlpacaClient.get_market_data(ticker, limit=50)

        if not bars_data:
            logger.warning(f"No bars data for {ticker}, returning default indicators")
            return await cls._create_default_indicators(ticker)

        # Use bars_est since timestamps are already converted to EST by get_market_data()
        bars_est_dict = bars_data.get("bars_est", {})
        ticker_bars = bars_est_dict.get(ticker, [])

        # Fallback to regular bars if bars_est is not available
        if not ticker_bars:
            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])

        if not ticker_bars or len(ticker_bars) < 5:
            logger.debug(
                f"Insufficient bars data for {ticker}: {len(ticker_bars) if ticker_bars else 0} bars"
            )
            return await cls._create_default_indicators(ticker)

        # Convert bars to DataFrame (timestamps are already in EST)
        prices = cls._bars_to_dataframe(ticker_bars, ticker)

        if prices.empty or len(prices) < 5:
            logger.debug(
                f"Insufficient data after conversion: {len(prices)} rows for {ticker}"
            )
            return await cls._create_default_indicators(ticker)

        try:
            # Prepare data
            processed_prices = cls._prepare_price_data(prices)
            processed_prices = cls._clean_and_enhance_data(processed_prices)
            recent_prices = processed_prices.tail(
                min(len(processed_prices), cls.max_data_points)
            )

            high = recent_prices["high"].values
            low = recent_prices["low"].values
            close = recent_prices["close"].values
            volume = recent_prices["volume"].values
            open_ = recent_prices["open"].values  # Avoid keyword conflict

            # Ensure arrays are float64
            high = high.astype(np.float64)
            low = low.astype(np.float64)
            close = close.astype(np.float64)
            volume = volume.astype(np.float64)
            open_ = open_.astype(np.float64)

            # Check if TA-Lib is available before using it
            if not TALIB_AVAILABLE or talib is None:
                logger.warning(f"TA-Lib not available for {ticker}, using fallback indicators")
                return await cls._create_default_indicators(ticker)

            # Calculate main indicators using TA-Lib
            rsi_array = talib.RSI(close, timeperiod=cls._default_periods["rsi"])
            rsi = (
                rsi_array[-1]
                if len(rsi_array) > 0 and not np.isnan(rsi_array[-1])
                else 50.0
            )

            macd, signal, hist = talib.MACD(
                close,
                fastperiod=cls._default_periods["macd"][0],
                slowperiod=cls._default_periods["macd"][1],
                signalperiod=cls._default_periods["macd"][2],
            )
            macd = macd[-1] if len(macd) > 0 else 0.0
            signal = signal[-1] if len(signal) > 0 else 0.0
            hist = hist[-1] if len(hist) > 0 else 0.0

            upper, middle, lower = talib.BBANDS(
                close,
                timeperiod=cls._default_periods["bollinger"][0],
                nbdevup=cls._default_periods["bollinger"][1],
                nbdevdn=cls._default_periods["bollinger"][1],
                matype=0,  # Simple MA
            )
            upper = upper[-1] if len(upper) > 0 else close[-1] * 1.02
            middle = middle[-1] if len(middle) > 0 else close[-1]
            lower = lower[-1] if len(lower) > 0 else close[-1] * 0.98

            adx = (
                talib.ADX(high, low, close, timeperiod=cls._default_periods["adx"])[-1]
                if len(close) >= cls._default_periods["adx"]
                else 20.0
            )

            ema_fast = (
                talib.EMA(close, timeperiod=cls._default_periods["ema_fast"])[-1]
                if len(close) >= cls._default_periods["ema_fast"]
                else close[-1]
            )
            ema_slow = (
                talib.EMA(close, timeperiod=cls._default_periods["ema_slow"])[-1]
                if len(close) >= cls._default_periods["ema_slow"]
                else close[-1]
            )

            volume_sma = (
                talib.SMA(volume, timeperiod=cls._default_periods["volume_sma"])[-1]
                if len(volume) >= cls._default_periods["volume_sma"]
                else 1000.0
            )

            obv = talib.OBV(close, volume)[-1] if len(close) > 0 else 0.0

            mfi = (
                talib.MFI(
                    high, low, close, volume, timeperiod=cls._default_periods["mfi"]
                )[-1]
                if len(close) >= cls._default_periods["mfi"]
                else 50.0
            )

            ad = talib.AD(high, low, close, volume)[-1] if len(close) > 0 else 0.0

            slowk, slowd = talib.STOCH(
                high,
                low,
                close,
                fastk_period=cls._default_periods["stoch"][0],
                slowk_period=cls._default_periods["stoch"][1],
                slowk_matype=0,
                slowd_period=cls._default_periods["stoch"][2],
                slowd_matype=0,
            )
            slowk = slowk[-1] if len(slowk) > 0 else 50.0
            slowd = slowd[-1] if len(slowd) > 0 else 50.0

            cci = (
                talib.CCI(high, low, close, timeperiod=cls._default_periods["cci"])[-1]
                if len(close) >= cls._default_periods["cci"]
                else 0.0
            )

            atr = (
                talib.ATR(high, low, close, timeperiod=cls._default_periods["atr"])[-1]
                if len(close) >= cls._default_periods["atr"]
                else close[-1] * 0.01
            )

            willr = (
                talib.WILLR(high, low, close, timeperiod=cls._default_periods["willr"])[
                    -1
                ]
                if len(close) >= cls._default_periods["willr"]
                else -50.0
            )

            # Additional indicators
            # pylint: disable=line-too-long
            roc = (
                talib.ROC(close, timeperiod=cls._default_periods["roc"])[-1]
                if len(close) >= cls._default_periods["roc"] + 1
                else 0.0
            )

            vwap = cls._calculate_vwap(recent_prices)

            vwma = cls._calculate_vwma(recent_prices)

            # pylint: disable=line-too-long
            wma = (
                talib.WMA(close, timeperiod=cls._default_periods["wma"])[-1]
                if len(close) >= cls._default_periods["wma"]
                else close[-1]
            )

            # Volume
            volume_val = volume[-1] if len(volume) > 0 else 0.0

            # Extract datetime and price for datetime_price dict from original prices DataFrame
            datetime_price: dict = {}  # Default
            if "timestamp" in prices.columns and "price" in prices.columns:
                datetime_price_df = prices[["timestamp", "price"]].copy()
                # Ensure timestamp is datetime type
                if not pd.api.types.is_datetime64_any_dtype(
                    datetime_price_df["timestamp"]
                ):
                    datetime_price_df["timestamp"] = pd.to_datetime(
                        datetime_price_df["timestamp"]
                    )

                # Timestamps are already in EST from get_market_data(), no conversion needed
                datetime_price = {}
                for ts, price in datetime_price_df.itertuples(index=False, name=None):
                    if hasattr(ts, "isoformat"):
                        ts_str = ts.isoformat()
                    else:
                        ts_str = str(ts)
                    datetime_price[ts_str] = float(price)

            # Return all as dict to include additional
            result = {
                "rsi": float(rsi) if not np.isnan(rsi) else 50.0,
                "macd": (
                    float(macd) if not np.isnan(macd) else 0.0,
                    float(signal) if not np.isnan(signal) else 0.0,
                    float(hist) if not np.isnan(hist) else 0.0,
                ),
                "bollinger": (
                    float(upper) if not np.isnan(upper) else close[-1] * 1.02,
                    float(middle) if not np.isnan(middle) else close[-1],
                    float(lower) if not np.isnan(lower) else close[-1] * 0.98,
                ),
                "adx": float(adx) if not np.isnan(adx) else 20.0,
                "ema_fast": float(ema_fast) if not np.isnan(ema_fast) else close[-1],
                "ema_slow": float(ema_slow) if not np.isnan(ema_slow) else close[-1],
                "volume_sma": float(volume_sma) if not np.isnan(volume_sma) else 1000.0,
                "obv": float(obv) if not np.isnan(obv) else 0.0,
                "mfi": float(mfi) if not np.isnan(mfi) else 50.0,
                "ad": float(ad) if not np.isnan(ad) else 0.0,
                "stoch": (
                    float(slowk) if not np.isnan(slowk) else 50.0,
                    float(slowd) if not np.isnan(slowd) else 50.0,
                ),
                "cci": float(cci) if not np.isnan(cci) else 0.0,
                "atr": float(atr) if not np.isnan(atr) else close[-1] * 0.01,
                "willr": float(willr) if not np.isnan(willr) else -50.0,
                "roc": float(roc) if not np.isnan(roc) else 0.0,
                "vwap": float(vwap) if vwap and not np.isnan(vwap) else 0.0,
                "vwma": float(vwma) if vwma and not np.isnan(vwma) else 0.0,
                "wma": float(wma) if not np.isnan(wma) else close[-1],
                "volume": float(volume_val) if not np.isnan(volume_val) else 0.0,
                "close_price": float(close[-1]),
                "datetime_price": datetime_price,
            }

            # Cache the result before returning
            if use_cache:
                await _indicator_cache.put(ticker, result)

            # Explicitly delete large objects to help GC
            del prices, processed_prices, recent_prices
            del high, low, close, volume, open_

            return result

        except Exception as e:
            logger.info(f"Error calculating indicators for {ticker}: {e}")
            return await cls._create_default_indicators(ticker)

    @classmethod
    def _clean_and_enhance_data(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Clean data for TA-Lib calculations."""
        df = df.copy()

        # Remove outliers
        for col in ["high", "low", "close", "open"]:
            if col in df.columns:
                q1 = df[col].quantile(0.25)
                q3 = df[col].quantile(0.75)
                iqr = q3 - q1
                lower_bound = q1 - 2 * iqr
                upper_bound = q3 + 2 * iqr
                outlier_mask = (df[col] < lower_bound) | (df[col] > upper_bound)
                df.loc[outlier_mask, col] = np.nan
                df[col] = df[col].interpolate(method="linear").ffill().bfill()

        # Fix only obvious data errors, don't systematically alter OHLC relationships
        # Only fix cases where high < low (data error) or high/low are clearly
        # wrong
        mask_fix_high = (df["high"] < df["low"]) | (
            df["high"] < df[["open", "close"]].max(axis=1)
        )
        mask_fix_low = (df["low"] > df["high"]) | (
            df["low"] > df[["open", "close"]].min(axis=1)
        )

        # Only fix actual errors, not normal price relationships
        df.loc[mask_fix_high, "high"] = df.loc[
            mask_fix_high, ["high", "open", "close"]
        ].max(axis=1)
        df.loc[mask_fix_low, "low"] = df.loc[
            mask_fix_low, ["low", "open", "close"]
        ].min(axis=1)

        return df
