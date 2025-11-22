"""
Common utility functions
"""

import functools
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Union
from typing_extensions import Dict

import pytz

from app.src.common.loguru_logger import logger
from app.src.models.technical_indicators import TechnicalIndicators

def adjust_date_backward(date_str: str) -> str:
    """
    Adjust date backward by one day.

    Args:
        date_str: Date string in format YYYY-MM-DD

    Returns:
        Adjusted date string
    """
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        adjusted_date = date - timedelta(days=1)
        return adjusted_date.strftime("%Y-%m-%d")
    except Exception:
        # If parsing fails, return original date
        return date_str


def convert_utc_to_est(utc_timestamp: Union[str, datetime]) -> str:
    """
    Convert UTC/GMT timestamp to EST timezone.

    Args:
        utc_timestamp: UTC timestamp as string (ISO format), datetime object, or pandas Timestamp

    Returns:
        EST timestamp as ISO format string with timezone offset
    """
    # EST timezone (handles both EST and EDT automatically)
    est_tz = pytz.timezone("America/New_York")
    utc_tz = pytz.UTC

    # Handle pandas Timestamp objects
    if hasattr(utc_timestamp, "to_pydatetime"):
        # Convert pandas Timestamp to Python datetime
        dt = utc_timestamp.to_pydatetime()
        # Ensure timezone-aware and convert to UTC if needed
        if dt.tzinfo is None:
            dt = utc_tz.localize(dt)
        else:
            dt = dt.astimezone(utc_tz)
    # Parse if string, otherwise use datetime object
    elif isinstance(utc_timestamp, str):
        # Handle various formats
        if utc_timestamp.endswith("Z"):
            dt = datetime.fromisoformat(utc_timestamp.replace("Z", "+00:00"))
        elif "+" in utc_timestamp or utc_timestamp.count("-") >= 3:
            dt = datetime.fromisoformat(utc_timestamp)
        else:
            # Try ISO format without timezone
            dt = datetime.fromisoformat(utc_timestamp)
            dt = utc_tz.localize(dt)
    else:
        dt = utc_timestamp

    # Ensure UTC timezone (for datetime objects that weren't handled above)
    if dt.tzinfo is None:
        dt = utc_tz.localize(dt)
    else:
        dt = dt.astimezone(utc_tz)

    # Convert to EST
    est_dt = dt.astimezone(est_tz)

    # Return as ISO format string with timezone offset
    return est_dt.isoformat()


def measure_latency(func: Callable) -> Callable:
    """
    Decorator to measure and log the execution latency of async functions.

    Usage:
        @measure_latency
        async def my_function():
            ...

    Args:
        func: The async function to measure

    Returns:
        Wrapped function that logs execution time
    """
    if not hasattr(func, "__name__"):
        return func

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        func_name = func.__name__
        class_name = args[0].__class__.__name__ if args and hasattr(args[0], "__class__") else ""
        display_name = f"{class_name}.{func_name}" if class_name else func_name

        try:
            result = await func(*args, **kwargs)
            elapsed_time = time.perf_counter() - start_time
            logger.info(f"⏱️  {display_name} completed in {elapsed_time:.3f}s")
            return result
        except Exception as e:
            elapsed_time = time.perf_counter() - start_time
            logger.warning(f"⏱️  {display_name} failed after {elapsed_time:.3f}s: {str(e)}")
            raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        func_name = func.__name__
        class_name = args[0].__class__.__name__ if args and hasattr(args[0], "__class__") else ""
        display_name = f"{class_name}.{func_name}" if class_name else func_name

        try:
            result = func(*args, **kwargs)
            elapsed_time = time.perf_counter() - start_time
            logger.info(f"⏱️  {display_name} completed in {elapsed_time:.3f}s")
            return result
        except Exception as e:
            elapsed_time = time.perf_counter() - start_time
            logger.warning(f"⏱️  {display_name} failed after {elapsed_time:.3f}s: {str(e)}")
            raise

    # Check if function is a coroutine function (async)
    if hasattr(func, "__code__") and func.__code__.co_flags & 0x80:  # CO_COROUTINE flag
        return async_wrapper
    else:
        return sync_wrapper


def dict_to_technical_indicators(
    indicators_dict: Dict
) -> TechnicalIndicators | None:
    """
    Convert a dictionary to TechnicalIndicators object

    Args:
        indicators_dict: Dictionary with technical indicators data

    Returns:
        TechnicalIndicators object or None if conversion fails
    """
    try:
        # Handle nested structures (macd, bollinger, stoch)
        macd_data = indicators_dict.get("macd", {})
        if isinstance(macd_data, dict):
            macd = (
                macd_data.get("macd", 0.0),
                macd_data.get("signal", 0.0),
                macd_data.get("hist", 0.0),
            )
        else:
            macd = (
                tuple(macd_data)
                if isinstance(macd_data, (list, tuple))
                else (0.0, 0.0, 0.0)
            )

        bollinger_data = indicators_dict.get("bollinger", {})
        if isinstance(bollinger_data, dict):
            bollinger = (
                bollinger_data.get("upper", 0.0),
                bollinger_data.get("middle", 0.0),
                bollinger_data.get("lower", 0.0),
            )
        else:
            bollinger = (
                tuple(bollinger_data)
                if isinstance(bollinger_data, (list, tuple))
                else (0.0, 0.0, 0.0)
            )

        stoch_data = indicators_dict.get("stoch", {})
        if isinstance(stoch_data, dict):
            stoch = (stoch_data.get("k", 0.0), stoch_data.get("d", 0.0))
        else:
            stoch = (
                tuple(stoch_data)
                if isinstance(stoch_data, (list, tuple))
                else (0.0, 0.0)
            )

        datetime_price = indicators_dict.get("datetime_price", ())
        if not isinstance(datetime_price, tuple):
            datetime_price = (
                tuple(datetime_price)
                if isinstance(datetime_price, (list, tuple))
                else ()
            )

        return TechnicalIndicators(
            rsi=float(indicators_dict.get("rsi", 0.0)),
            macd=macd,
            bollinger=bollinger,
            adx=float(indicators_dict.get("adx", 0.0)),
            ema_fast=float(indicators_dict.get("ema_fast", 0.0)),
            ema_slow=float(indicators_dict.get("ema_slow", 0.0)),
            volume_sma=float(indicators_dict.get("volume_sma", 0.0)),
            obv=float(indicators_dict.get("obv", 0.0)),
            mfi=float(indicators_dict.get("mfi", 0.0)),
            ad=float(indicators_dict.get("ad", 0.0)),
            stoch=stoch,
            cci=float(indicators_dict.get("cci", 0.0)),
            atr=float(indicators_dict.get("atr", 0.0)),
            willr=float(indicators_dict.get("willr", 0.0)),
            roc=float(indicators_dict.get("roc", 0.0)),
            vwap=float(indicators_dict.get("vwap", 0.0)),
            vwma=float(indicators_dict.get("vwma", 0.0)),
            wma=float(indicators_dict.get("wma", 0.0)),
            volume=float(indicators_dict.get("volume", 0.0)),
            close_price=float(indicators_dict.get("close_price", 0.0)),
            datetime_price=datetime_price,
        )
    except Exception as e:
        logger.error(
            f"Error converting dict to TechnicalIndicators: {e}", exc_info=True
        )
        return None
