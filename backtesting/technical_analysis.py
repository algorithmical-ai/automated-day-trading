"""
Synchronous Technical Analysis for Backtesting.

Replicates the indicator calculations from TechnicalAnalysisLib
but operates on pre-fetched bar data synchronously (no API calls).
"""

from typing import Dict, List, Any, Optional
import numpy as np

# Try to import talib
try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    talib = None


# Default periods matching the production code
DEFAULT_PERIODS = {
    "rsi": 14,
    "macd": (12, 26, 9),
    "bollinger": (20, 2),
    "adx": 14,
    "ema_fast": 12,
    "ema_slow": 26,
    "volume_sma": 20,
    "mfi": 14,
    "stoch": (14, 3, 3),
    "cci": 20,
    "atr": 14,
    "willr": 14,
    "roc": 14,
    "wma": 20,
}

# Minimum bars needed for indicator calculation
MIN_BARS_FOR_TA = 30


def _safe_last(arr, default=0.0):
    """Get last element of array, handling NaN."""
    if arr is None or len(arr) == 0:
        return default
    val = arr[-1]
    if np.isnan(val):
        return default
    return float(val)


def calculate_indicators(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate all technical indicators from a list of bar dicts.

    This is a synchronous version of TechnicalAnalysisLib.calculate_all_indicators().
    It takes raw bar data and computes the same indicators.

    Args:
        bars: List of bar dicts with keys: o, h, l, c, v, t

    Returns:
        Dict with all technical indicators matching production format:
        rsi, macd, bollinger, adx, ema_fast, ema_slow, volume_sma,
        mfi, stoch, cci, atr, willr, roc, vwap, vwma, wma,
        volume, close_price, datetime_price
    """
    # Default indicators for insufficient data
    defaults = _create_defaults()

    if not bars or len(bars) < 5:
        return defaults

    # Extract OHLCV arrays
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    timestamps = []

    for bar in bars:
        try:
            o = float(bar.get("o", 0))
            h = float(bar.get("h", 0))
            l = float(bar.get("l", 0))
            c = float(bar.get("c", 0))
            v = float(bar.get("v", 0))
            t = bar.get("t", "")

            if c <= 0:
                continue

            opens.append(o)
            highs.append(h)
            lows.append(l)
            closes.append(c)
            volumes.append(v)
            timestamps.append(t)
        except (ValueError, TypeError):
            continue

    if len(closes) < 5:
        return defaults

    # Convert to numpy arrays (float64 as required by TA-Lib)
    open_arr = np.array(opens, dtype=np.float64)
    high_arr = np.array(highs, dtype=np.float64)
    low_arr = np.array(lows, dtype=np.float64)
    close_arr = np.array(closes, dtype=np.float64)
    volume_arr = np.array(volumes, dtype=np.float64)

    # Clean data: clip prices to > 0.01
    close_arr = np.clip(close_arr, 0.01, None)
    high_arr = np.clip(high_arr, 0.01, None)
    low_arr = np.clip(low_arr, 0.01, None)
    open_arr = np.clip(open_arr, 0.01, None)

    # Forward-fill any remaining NaNs
    close_arr = _ffill(close_arr)
    high_arr = _ffill(high_arr)
    low_arr = _ffill(low_arr)
    open_arr = _ffill(open_arr)
    volume_arr = _ffill(volume_arr)

    n = len(close_arr)

    if not TALIB_AVAILABLE:
        # Fallback: compute basic indicators without TA-Lib
        return _compute_basic_indicators(close_arr, high_arr, low_arr, volume_arr, timestamps)

    # Calculate indicators using TA-Lib
    try:
        # RSI
        rsi_arr = talib.RSI(close_arr, timeperiod=DEFAULT_PERIODS["rsi"])
        rsi = _safe_last(rsi_arr, 50.0)

        # MACD
        macd_fast, macd_slow, macd_sig = DEFAULT_PERIODS["macd"]
        macd_line, signal_line, hist_line = talib.MACD(
            close_arr, fastperiod=macd_fast, slowperiod=macd_slow, signalperiod=macd_sig
        )
        macd = _safe_last(macd_line, 0.0)
        signal = _safe_last(signal_line, 0.0)
        hist = _safe_last(hist_line, 0.0)

        # Bollinger Bands
        bb_period, bb_std = DEFAULT_PERIODS["bollinger"]
        upper, middle, lower = talib.BBANDS(
            close_arr, timeperiod=bb_period, nbdevup=bb_std, nbdevdn=bb_std, matype=0
        )
        bb_upper = _safe_last(upper, close_arr[-1] * 1.02)
        bb_middle = _safe_last(middle, close_arr[-1])
        bb_lower = _safe_last(lower, close_arr[-1] * 0.98)

        # ADX
        adx_val = _safe_last(
            talib.ADX(high_arr, low_arr, close_arr, timeperiod=DEFAULT_PERIODS["adx"]),
            20.0
        ) if n >= DEFAULT_PERIODS["adx"] else 20.0

        # EMAs
        ema_fast = _safe_last(
            talib.EMA(close_arr, timeperiod=DEFAULT_PERIODS["ema_fast"]),
            close_arr[-1]
        ) if n >= DEFAULT_PERIODS["ema_fast"] else close_arr[-1]

        ema_slow = _safe_last(
            talib.EMA(close_arr, timeperiod=DEFAULT_PERIODS["ema_slow"]),
            close_arr[-1]
        ) if n >= DEFAULT_PERIODS["ema_slow"] else close_arr[-1]

        # Volume SMA
        vol_sma = _safe_last(
            talib.SMA(volume_arr, timeperiod=DEFAULT_PERIODS["volume_sma"]),
            1000.0
        ) if n >= DEFAULT_PERIODS["volume_sma"] else max(1000.0, np.mean(volume_arr))

        # OBV
        obv = _safe_last(talib.OBV(close_arr, volume_arr), 0.0)

        # MFI
        mfi = _safe_last(
            talib.MFI(high_arr, low_arr, close_arr, volume_arr, timeperiod=DEFAULT_PERIODS["mfi"]),
            50.0
        ) if n >= DEFAULT_PERIODS["mfi"] else 50.0

        # AD
        ad = _safe_last(talib.AD(high_arr, low_arr, close_arr, volume_arr), 0.0)

        # Stochastic
        sk_period, sk_slow, sd_period = DEFAULT_PERIODS["stoch"]
        slowk, slowd = talib.STOCH(
            high_arr, low_arr, close_arr,
            fastk_period=sk_period, slowk_period=sk_slow, slowk_matype=0,
            slowd_period=sd_period, slowd_matype=0
        )
        stoch_k = _safe_last(slowk, 50.0)
        stoch_d = _safe_last(slowd, 50.0)

        # CCI
        cci = _safe_last(
            talib.CCI(high_arr, low_arr, close_arr, timeperiod=DEFAULT_PERIODS["cci"]),
            0.0
        ) if n >= DEFAULT_PERIODS["cci"] else 0.0

        # ATR
        atr = _safe_last(
            talib.ATR(high_arr, low_arr, close_arr, timeperiod=DEFAULT_PERIODS["atr"]),
            close_arr[-1] * 0.01
        ) if n >= DEFAULT_PERIODS["atr"] else close_arr[-1] * 0.01

        # Williams %R
        willr = _safe_last(
            talib.WILLR(high_arr, low_arr, close_arr, timeperiod=DEFAULT_PERIODS["willr"]),
            -50.0
        ) if n >= DEFAULT_PERIODS["willr"] else -50.0

        # ROC
        roc = _safe_last(
            talib.ROC(close_arr, timeperiod=DEFAULT_PERIODS["roc"]),
            0.0
        ) if n >= DEFAULT_PERIODS["roc"] + 1 else 0.0

        # WMA
        wma = _safe_last(
            talib.WMA(close_arr, timeperiod=DEFAULT_PERIODS["wma"]),
            close_arr[-1]
        ) if n >= DEFAULT_PERIODS["wma"] else close_arr[-1]

        # VWAP (custom)
        vwap = _calculate_vwap(high_arr, low_arr, close_arr, volume_arr)

        # VWMA (custom)
        vwma = _calculate_vwma(high_arr, low_arr, close_arr, volume_arr, DEFAULT_PERIODS["volume_sma"])

        # Build datetime_price dict
        datetime_price = {}
        for ts, price in zip(timestamps, closes):
            if ts:
                datetime_price[ts] = price

        result = {
            "rsi": rsi,
            "macd": (macd, signal, hist),
            "bollinger": (bb_upper, bb_middle, bb_lower),
            "adx": adx_val,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "volume_sma": vol_sma,
            "obv": obv,
            "mfi": mfi,
            "ad": ad,
            "stoch": (stoch_k, stoch_d),
            "cci": cci,
            "atr": atr,
            "willr": willr,
            "roc": roc,
            "vwap": vwap,
            "vwma": vwma,
            "wma": wma,
            "volume": float(volume_arr[-1]) if len(volume_arr) > 0 else 0.0,
            "close_price": float(close_arr[-1]),
            "datetime_price": datetime_price,
        }
        return result

    except Exception as e:
        print(f"Error calculating TA indicators: {e}")
        return defaults


def _create_defaults() -> Dict[str, Any]:
    """Create default indicator values for insufficient data."""
    return {
        "rsi": 50.0,
        "macd": (0.0, 0.0, 0.0),
        "bollinger": (102.0, 100.0, 98.0),
        "adx": 20.0,
        "ema_fast": 100.0,
        "ema_slow": 100.0,
        "volume_sma": 25000.0,
        "obv": 0.0,
        "mfi": 50.0,
        "ad": 0.0,
        "stoch": (50.0, 50.0),
        "cci": 0.0,
        "atr": 1.0,
        "willr": -50.0,
        "roc": 0.0,
        "vwap": 0.0,
        "vwma": 0.0,
        "wma": 0.0,
        "volume": 0.0,
        "close_price": 0.0,
        "datetime_price": {},
    }


def _ffill(arr: np.ndarray) -> np.ndarray:
    """Forward-fill NaN values in array."""
    mask = np.isnan(arr)
    if not mask.any():
        return arr
    # Forward fill
    idx = np.where(~mask, np.arange(len(arr)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = arr[idx]
    # Backward fill remaining leading NaNs
    mask2 = np.isnan(out)
    if mask2.any():
        first_valid = np.argmin(mask2)
        out[:first_valid] = out[first_valid]
    return out


def _calculate_vwap(high, low, close, volume):
    """Calculate VWAP."""
    typical_price = (high + low + close) / 3.0
    cum_tp_vol = np.cumsum(typical_price * volume)
    cum_vol = np.cumsum(volume)
    if cum_vol[-1] == 0:
        return float(close[-1])
    vwap = cum_tp_vol[-1] / cum_vol[-1]
    if np.isnan(vwap) or np.isinf(vwap):
        return float(close[-1])
    return float(vwap)


def _calculate_vwma(high, low, close, volume, period=20):
    """Calculate VWMA over last `period` bars."""
    if len(close) < period:
        return float(close[-1])
    recent_h = high[-period:]
    recent_l = low[-period:]
    recent_c = close[-period:]
    recent_v = volume[-period:]
    typical = (recent_h + recent_l + recent_c) / 3.0
    vol_sum = np.sum(recent_v)
    if vol_sum == 0:
        return float(np.mean(typical))
    vwma = np.sum(typical * recent_v) / vol_sum
    if np.isnan(vwma) or np.isinf(vwma):
        return float(np.mean(typical))
    return float(vwma)


def _compute_basic_indicators(close, high, low, volume, timestamps):
    """Fallback indicator computation without TA-Lib.

    Computes only the most essential indicators using simple math.
    Used when TA-Lib is not installed.
    """
    n = len(close)

    # Simple RSI (14-period)
    rsi = 50.0
    if n >= 15:
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

    # Simple ATR (14-period)
    atr = close[-1] * 0.01
    if n >= 15:
        tr = np.maximum(high[1:] - low[1:],
                       np.maximum(np.abs(high[1:] - close[:-1]),
                                 np.abs(low[1:] - close[:-1])))
        atr = float(np.mean(tr[-14:]))

    # EMA (approximate with SMA)
    ema_fast = float(np.mean(close[-12:])) if n >= 12 else float(close[-1])
    ema_slow = float(np.mean(close[-26:])) if n >= 26 else float(close[-1])

    # Volume SMA
    vol_sma = float(np.mean(volume[-20:])) if n >= 20 else float(np.mean(volume))

    # ADX (approximate)
    adx = 25.0  # Default moderate trend

    # Build datetime_price
    datetime_price = {}
    for ts, price in zip(timestamps, close):
        if ts:
            datetime_price[ts] = float(price)

    return {
        "rsi": rsi,
        "macd": (0.0, 0.0, 0.0),
        "bollinger": (float(close[-1] * 1.02), float(close[-1]), float(close[-1] * 0.98)),
        "adx": adx,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "volume_sma": vol_sma,
        "obv": 0.0,
        "mfi": 50.0,
        "ad": 0.0,
        "stoch": (50.0, 50.0),
        "cci": 0.0,
        "atr": atr,
        "willr": -50.0,
        "roc": 0.0,
        "vwap": _calculate_vwap(np.array(high, dtype=np.float64), np.array(low, dtype=np.float64),
                                np.array(close, dtype=np.float64), np.array(volume, dtype=np.float64)),
        "vwma": 0.0,
        "wma": float(close[-1]),
        "volume": float(volume[-1]),
        "close_price": float(close[-1]),
        "datetime_price": datetime_price,
    }
