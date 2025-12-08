"""
Configuration for momentum trading validation.

This module provides configuration values for the momentum validation system,
with defaults and environment variable overrides.
"""

import os
from loguru import logger


class MomentumValidationConfig:
    """Configuration for momentum trading validation."""
    
    # Price threshold
    MIN_PRICE_THRESHOLD = float(os.getenv('MIN_PRICE_THRESHOLD', '0.10'))
    
    # Volume thresholds
    MIN_VOLUME_THRESHOLD = int(os.getenv('MIN_VOLUME_THRESHOLD', '500'))
    MIN_VOLUME_RATIO = float(os.getenv('MIN_VOLUME_RATIO', '1.5'))
    
    # Volatility threshold
    MAX_ATR_PERCENT = float(os.getenv('MAX_ATR_PERCENT', '5.0'))
    
    # Indicator name
    INDICATOR_NAME = os.getenv('MOMENTUM_INDICATOR_NAME', 'Momentum Trading')
    
    # Warrant/derivative suffixes
    WARRANT_SUFFIXES = tuple(
        os.getenv('WARRANT_SUFFIXES', 'W,R,RT,WS').split(',')
    )
    
    @classmethod
    def validate(cls):
        """Validate configuration values."""
        errors = []
        
        # Validate MIN_PRICE_THRESHOLD
        if cls.MIN_PRICE_THRESHOLD <= 0:
            errors.append(
                f"MIN_PRICE_THRESHOLD must be positive, got {cls.MIN_PRICE_THRESHOLD}"
            )
        if cls.MIN_PRICE_THRESHOLD > 100:
            errors.append(
                f"MIN_PRICE_THRESHOLD seems unreasonably high: ${cls.MIN_PRICE_THRESHOLD}"
            )
        
        # Validate MIN_VOLUME_THRESHOLD
        if cls.MIN_VOLUME_THRESHOLD < 0:
            errors.append(
                f"MIN_VOLUME_THRESHOLD must be non-negative, got {cls.MIN_VOLUME_THRESHOLD}"
            )
        if cls.MIN_VOLUME_THRESHOLD > 1000000:
            errors.append(
                f"MIN_VOLUME_THRESHOLD seems unreasonably high: {cls.MIN_VOLUME_THRESHOLD}"
            )
        
        # Validate MIN_VOLUME_RATIO
        if cls.MIN_VOLUME_RATIO <= 0:
            errors.append(
                f"MIN_VOLUME_RATIO must be positive, got {cls.MIN_VOLUME_RATIO}"
            )
        if cls.MIN_VOLUME_RATIO > 10:
            errors.append(
                f"MIN_VOLUME_RATIO seems unreasonably high: {cls.MIN_VOLUME_RATIO}x"
            )
        
        # Validate MAX_ATR_PERCENT
        if cls.MAX_ATR_PERCENT <= 0:
            errors.append(
                f"MAX_ATR_PERCENT must be positive, got {cls.MAX_ATR_PERCENT}"
            )
        if cls.MAX_ATR_PERCENT > 100:
            errors.append(
                f"MAX_ATR_PERCENT seems unreasonably high: {cls.MAX_ATR_PERCENT}%"
            )
        
        # Validate INDICATOR_NAME
        if not cls.INDICATOR_NAME or not cls.INDICATOR_NAME.strip():
            errors.append("INDICATOR_NAME cannot be empty")
        
        # Validate WARRANT_SUFFIXES
        if not cls.WARRANT_SUFFIXES:
            errors.append("WARRANT_SUFFIXES cannot be empty")
        
        if errors:
            for error in errors:
                logger.error(f"Configuration validation error: {error}")
            raise ValueError(f"Invalid configuration: {'; '.join(errors)}")
        
        logger.info(
            f"Momentum validation configuration validated: "
            f"MIN_PRICE=${cls.MIN_PRICE_THRESHOLD:.2f}, "
            f"MIN_VOLUME={cls.MIN_VOLUME_THRESHOLD}, "
            f"MIN_VOLUME_RATIO={cls.MIN_VOLUME_RATIO}x, "
            f"MAX_ATR={cls.MAX_ATR_PERCENT}%, "
            f"INDICATOR='{cls.INDICATOR_NAME}', "
            f"WARRANT_SUFFIXES={cls.WARRANT_SUFFIXES}"
        )
    
    @classmethod
    def get_min_price(cls) -> float:
        """Get minimum price threshold."""
        return cls.MIN_PRICE_THRESHOLD
    
    @classmethod
    def get_min_volume(cls) -> int:
        """Get minimum volume threshold."""
        return cls.MIN_VOLUME_THRESHOLD
    
    @classmethod
    def get_min_volume_ratio(cls) -> float:
        """Get minimum volume ratio."""
        return cls.MIN_VOLUME_RATIO
    
    @classmethod
    def get_max_atr_percent(cls) -> float:
        """Get maximum ATR percentage."""
        return cls.MAX_ATR_PERCENT
    
    @classmethod
    def get_indicator_name(cls) -> str:
        """Get indicator name."""
        return cls.INDICATOR_NAME
    
    @classmethod
    def get_warrant_suffixes(cls) -> tuple:
        """Get warrant/derivative suffixes."""
        return cls.WARRANT_SUFFIXES


# Validate configuration on module import
try:
    MomentumValidationConfig.validate()
except ValueError as e:
    logger.warning(f"Configuration validation failed, using defaults: {e}")
