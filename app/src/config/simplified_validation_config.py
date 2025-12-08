"""
Configuration for simplified penny stock validation.

This module provides configuration values for the simplified validation system,
with defaults and environment variable overrides.
"""

import os
from loguru import logger


class SimplifiedValidationConfig:
    """Configuration for simplified penny stock validation."""
    
    # Bid-ask spread threshold
    MAX_BID_ASK_SPREAD = float(os.getenv('MAX_BID_ASK_SPREAD', '2.0'))
    
    # Number of recent bars to analyze
    RECENT_BARS_COUNT = int(os.getenv('RECENT_BARS_COUNT', '5'))
    
    # Indicator name
    INDICATOR_NAME = os.getenv('INDICATOR_NAME', 'Penny Stocks')
    
    @classmethod
    def validate(cls):
        """Validate configuration values."""
        errors = []
        
        # Validate MAX_BID_ASK_SPREAD
        if cls.MAX_BID_ASK_SPREAD <= 0:
            errors.append(f"MAX_BID_ASK_SPREAD must be positive, got {cls.MAX_BID_ASK_SPREAD}")
        if cls.MAX_BID_ASK_SPREAD > 100:
            errors.append(f"MAX_BID_ASK_SPREAD seems unreasonably high: {cls.MAX_BID_ASK_SPREAD}%")
        
        # Validate RECENT_BARS_COUNT
        if cls.RECENT_BARS_COUNT < 1:
            errors.append(f"RECENT_BARS_COUNT must be at least 1, got {cls.RECENT_BARS_COUNT}")
        if cls.RECENT_BARS_COUNT > 200:
            errors.append(f"RECENT_BARS_COUNT seems unreasonably high: {cls.RECENT_BARS_COUNT}")
        
        # Validate INDICATOR_NAME
        if not cls.INDICATOR_NAME or not cls.INDICATOR_NAME.strip():
            errors.append("INDICATOR_NAME cannot be empty")
        
        if errors:
            for error in errors:
                logger.error(f"Configuration validation error: {error}")
            raise ValueError(f"Invalid configuration: {'; '.join(errors)}")
        
        logger.info(
            f"Simplified validation configuration validated: "
            f"MAX_BID_ASK_SPREAD={cls.MAX_BID_ASK_SPREAD}%, "
            f"RECENT_BARS_COUNT={cls.RECENT_BARS_COUNT}, "
            f"INDICATOR_NAME='{cls.INDICATOR_NAME}'"
        )
    
    @classmethod
    def get_max_bid_ask_spread(cls) -> float:
        """Get maximum bid-ask spread percentage."""
        return cls.MAX_BID_ASK_SPREAD
    
    @classmethod
    def get_recent_bars_count(cls) -> int:
        """Get number of recent bars to analyze."""
        return cls.RECENT_BARS_COUNT
    
    @classmethod
    def get_indicator_name(cls) -> str:
        """Get indicator name."""
        return cls.INDICATOR_NAME


# Validate configuration on module import
try:
    SimplifiedValidationConfig.validate()
except ValueError as e:
    logger.warning(f"Configuration validation failed, using defaults: {e}")
