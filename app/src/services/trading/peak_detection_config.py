"""
Peak Detection Configuration

Configuration dataclass for peak detection and enhanced validation parameters.
All thresholds are configurable to allow tuning without code changes.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class PeakDetectionConfig:
    """Configuration for peak detection and enhanced validation.
    
    This configuration controls all aspects of the enhanced penny stock
    validation pipeline including peak detection, volume confirmation,
    momentum acceleration, stop losses, and position sizing.
    """
    
    # Peak detection parameters - TIGHTENED to prevent entering near peaks
    peak_proximity_threshold: float = 0.80  # TIGHTENED: from 0.90 - reject entries closer to recent highs
    peak_lookback_bars: int = 10  # RAISED: from 7 - longer lookback for better peak detection

    # Volume confirmation parameters - require stronger volume confirmation
    volume_lookback_bars: int = 20  # RAISED: from 15 - longer volume baseline for reliability
    high_volume_multiplier: float = 1.5  # TIGHTENED: from 1.3 - require real volume confirmation

    # Momentum acceleration parameters - reject decelerating momentum
    momentum_deceleration_threshold: float = -2.0  # TIGHTENED: from -3.0 - catch slowing momentum earlier
    momentum_normalization_range: float = 5.0  # Values beyond +/-5 are clamped

    # Stop loss parameters - WIDENED to give penny stocks room to breathe
    initial_stop_loss_percent: float = -4.0  # WIDENED: from -2.0% - penny stocks need more room
    early_exit_loss_percent: float = -2.5  # WIDENED: from -1.5% - avoid premature exits on noise
    early_exit_time_seconds: int = 60  # RAISED: from 30s - give trades more time
    initial_period_seconds: int = 120  # RAISED: from 60s - longer initial protection
    emergency_stop_percent: float = -7.0  # WIDENED: from -5.0% - penny stocks can swing

    # Position sizing parameters - RAISED thresholds for higher quality entries
    min_confidence_threshold: float = 0.5  # RAISED: from 0.3 - require higher confidence
    min_position_size: float = 50.0  # Minimum $50 position
    high_confidence_threshold: float = 0.8  # RAISED: from 0.7 - harder to reach full size
    medium_confidence_threshold: float = 0.65  # RAISED: from 0.5 - harder to reach 75% size

    # Confidence calculation weights (must sum to 1.0) - balanced for quality
    momentum_weight: float = 0.25  # REDUCED: from 0.35 - don't overweight momentum alone
    peak_proximity_weight: float = 0.25
    volume_weight: float = 0.30  # INCREASED: from 0.25 - volume confirmation is critical
    acceleration_weight: float = 0.20  # INCREASED: from 0.15 - momentum direction matters
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for serialization."""
        return {
            "peak_proximity_threshold": self.peak_proximity_threshold,
            "peak_lookback_bars": self.peak_lookback_bars,
            "volume_lookback_bars": self.volume_lookback_bars,
            "high_volume_multiplier": self.high_volume_multiplier,
            "momentum_deceleration_threshold": self.momentum_deceleration_threshold,
            "momentum_normalization_range": self.momentum_normalization_range,
            "initial_stop_loss_percent": self.initial_stop_loss_percent,
            "early_exit_loss_percent": self.early_exit_loss_percent,
            "early_exit_time_seconds": self.early_exit_time_seconds,
            "initial_period_seconds": self.initial_period_seconds,
            "emergency_stop_percent": self.emergency_stop_percent,
            "min_confidence_threshold": self.min_confidence_threshold,
            "min_position_size": self.min_position_size,
            "high_confidence_threshold": self.high_confidence_threshold,
            "medium_confidence_threshold": self.medium_confidence_threshold,
            "momentum_weight": self.momentum_weight,
            "peak_proximity_weight": self.peak_proximity_weight,
            "volume_weight": self.volume_weight,
            "acceleration_weight": self.acceleration_weight,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PeakDetectionConfig":
        """Create configuration from dictionary (JSON deserialization).
        
        Args:
            data: Dictionary with configuration values
            
        Returns:
            PeakDetectionConfig instance with values from dictionary
        """
        # Filter to only known fields to handle extra keys gracefully
        known_fields = {
            "peak_proximity_threshold", "peak_lookback_bars",
            "volume_lookback_bars", "high_volume_multiplier",
            "momentum_deceleration_threshold", "momentum_normalization_range",
            "initial_stop_loss_percent", "early_exit_loss_percent",
            "early_exit_time_seconds", "initial_period_seconds",
            "emergency_stop_percent", "min_confidence_threshold",
            "min_position_size", "high_confidence_threshold",
            "medium_confidence_threshold", "momentum_weight",
            "peak_proximity_weight", "volume_weight", "acceleration_weight",
        }
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)
    
    def validate(self) -> bool:
        """Validate configuration values are within acceptable ranges.
        
        Returns:
            True if configuration is valid, raises ValueError otherwise
        """
        # Validate thresholds are in valid ranges
        if not 0.0 <= self.peak_proximity_threshold <= 1.0:
            raise ValueError(f"peak_proximity_threshold must be 0.0-1.0, got {self.peak_proximity_threshold}")
        
        if self.peak_lookback_bars < 3:
            raise ValueError(f"peak_lookback_bars must be >= 3, got {self.peak_lookback_bars}")
        
        if self.volume_lookback_bars < 5:
            raise ValueError(f"volume_lookback_bars must be >= 5, got {self.volume_lookback_bars}")
        
        if self.high_volume_multiplier <= 0:
            raise ValueError(f"high_volume_multiplier must be > 0, got {self.high_volume_multiplier}")
        
        # Stop losses should be negative
        if self.initial_stop_loss_percent > 0:
            raise ValueError(f"initial_stop_loss_percent must be <= 0, got {self.initial_stop_loss_percent}")
        
        if self.early_exit_loss_percent > 0:
            raise ValueError(f"early_exit_loss_percent must be <= 0, got {self.early_exit_loss_percent}")
        
        if self.emergency_stop_percent > 0:
            raise ValueError(f"emergency_stop_percent must be <= 0, got {self.emergency_stop_percent}")
        
        # Time values should be positive
        if self.early_exit_time_seconds <= 0:
            raise ValueError(f"early_exit_time_seconds must be > 0, got {self.early_exit_time_seconds}")
        
        if self.initial_period_seconds <= 0:
            raise ValueError(f"initial_period_seconds must be > 0, got {self.initial_period_seconds}")
        
        # Confidence thresholds
        if not 0.0 <= self.min_confidence_threshold <= 1.0:
            raise ValueError(f"min_confidence_threshold must be 0.0-1.0, got {self.min_confidence_threshold}")
        
        if self.min_position_size < 0:
            raise ValueError(f"min_position_size must be >= 0, got {self.min_position_size}")
        
        # Weights should sum to 1.0 (with small tolerance for floating point)
        weight_sum = (self.momentum_weight + self.peak_proximity_weight + 
                      self.volume_weight + self.acceleration_weight)
        if abs(weight_sum - 1.0) > 0.001:
            raise ValueError(f"Confidence weights must sum to 1.0, got {weight_sum}")
        
        return True


# Default configuration instance
DEFAULT_CONFIG = PeakDetectionConfig()
