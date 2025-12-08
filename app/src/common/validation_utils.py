"""
Utility functions for validation operations.

This module provides helper functions for safe mathematical operations
and data validation used in the simplified validation system.
"""

from typing import List, Dict, Any
from loguru import logger


def safe_division(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Perform safe division with zero-denominator handling.
    
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


def filter_valid_prices(bars: List[Dict[str, Any]]) -> List[float]:
    """
    Filter out invalid prices from price bars.
    
    Removes bars with null, negative, or zero prices.
    
    Args:
        bars: List of price bar dictionaries with 'c' (close) field
        
    Returns:
        List of valid close prices
    """
    valid_prices = []
    
    for bar in bars:
        try:
            price = bar.get('c')
            if price is not None and price > 0:
                valid_prices.append(float(price))
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid price in bar: {e}")
            continue
    
    return valid_prices


def validate_quote_data(bid: float, ask: float) -> bool:
    """
    Validate bid and ask prices.
    
    Args:
        bid: Bid price
        ask: Ask price
        
    Returns:
        True if both prices are valid (positive), False otherwise
    """
    return bid > 0 and ask > 0


def calculate_spread_percent(bid: float, ask: float) -> float:
    """
    Calculate bid-ask spread as percentage of mid-price.
    
    Uses safe division to handle edge cases.
    
    Args:
        bid: Bid price
        ask: Ask price
        
    Returns:
        Spread percentage, or 0.0 if mid-price is zero
    """
    mid_price = (bid + ask) / 2.0
    spread = ask - bid
    return safe_division(spread * 100, mid_price, default=0.0)
