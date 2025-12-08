"""
Utility functions for momentum validation operations.

This module provides helper functions for safe mathematical operations
and data validation used in the momentum validation system.
"""

from typing import List, Dict, Any
from loguru import logger


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Calculate ratio with zero-denominator handling.
    
    Args:
        numerator: The numerator
        denominator: The denominator
        default: Value to return if denominator is zero (default: 0.0)
        
    Returns:
        Result of division, or default if denominator is zero
    """
    if denominator == 0:
        return default
    return numerator / denominator


def safe_percentage(value: float, total: float, default: float = 0.0) -> float:
    """
    Calculate percentage with zero-total handling.
    
    Args:
        value: The value
        total: The total
        default: Value to return if total is zero (default: 0.0)
        
    Returns:
        Percentage (value/total * 100), or default if total is zero
    """
    if total == 0:
        return default
    return (value / total) * 100


def validate_price_data(bars: List[Dict[str, Any]]) -> bool:
    """
    Validate that bars contain sufficient price data.
    
    Args:
        bars: List of price bar dictionaries
        
    Returns:
        True if bars contain valid price data, False otherwise
    """
    if not bars:
        return False
    
    # Check if at least one bar has close price
    has_close = any(bar.get('c') is not None and bar.get('c') > 0 for bar in bars)
    
    return has_close


def filter_invalid_bars(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter out bars with invalid price data.
    
    Args:
        bars: List of price bar dictionaries
        
    Returns:
        List of bars with valid price data
    """
    valid_bars = []
    
    for bar in bars:
        try:
            close = bar.get('c')
            if close is not None and close > 0:
                valid_bars.append(bar)
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid bar: {e}")
            continue
    
    return valid_bars


def is_warrant_suffix(ticker: str, suffixes: tuple = ('W', 'R', 'RT', 'WS')) -> bool:
    """
    Check if ticker has a warrant/derivative suffix.
    
    Args:
        ticker: Stock ticker symbol
        suffixes: Tuple of suffixes to check
        
    Returns:
        True if ticker ends with any of the suffixes (case-insensitive)
    """
    ticker_upper = ticker.upper().strip()
    return any(ticker_upper.endswith(suffix.upper()) for suffix in suffixes)


def calculate_atr_percentage(atr: float, price: float) -> float:
    """
    Calculate ATR as percentage of price with error handling.
    
    Args:
        atr: Average True Range value
        price: Current price
        
    Returns:
        ATR percentage, or 0.0 if price is invalid
    """
    if price <= 0:
        return 0.0
    return (atr / price) * 100


def calculate_volume_ratio(volume: int, volume_sma: float) -> float:
    """
    Calculate volume ratio with error handling.
    
    Args:
        volume: Current volume
        volume_sma: Volume SMA
        
    Returns:
        Volume ratio, or 0.0 if SMA is invalid
    """
    if volume_sma <= 0:
        return 0.0
    return volume / volume_sma
