"""
Enhanced Confidence Calculator

Combines all validation factors into a single predictive confidence score.
The confidence score is used to determine position sizing and entry decisions.
"""

from typing import Optional

from app.src.services.trading.peak_detection_models import (
    ConfidenceComponents,
    EnhancedConfidenceResult,
)
from app.src.services.trading.peak_detection_config import PeakDetectionConfig, DEFAULT_CONFIG


class EnhancedConfidenceCalculator:
    """Calculates enhanced confidence score from multiple factors.
    
    The confidence score combines:
    - Momentum score (higher = better)
    - Peak proximity score (lower = better, inverted)
    - Volume confirmation score (higher = better)
    - Momentum acceleration (higher = better)
    
    Algorithm:
    1. Normalize momentum_score to 0-1 range (5% to 20% -> 0 to 1)
    2. Invert peak_proximity: peak_factor = 1.0 - peak_proximity_score
    3. volume_factor = volume_confirmation_score (already 0-1)
    4. acceleration_factor = (momentum_acceleration + 1.0) / 2.0  # -1 to 1 -> 0 to 1
    5. confidence = weighted sum of all factors
    6. If confidence < MIN_CONFIDENCE_THRESHOLD: set rejection_reason
    """
    
    # Default weights (must sum to 1.0)
    MOMENTUM_WEIGHT: float = 0.25
    PEAK_PROXIMITY_WEIGHT: float = 0.25
    VOLUME_WEIGHT: float = 0.25
    ACCELERATION_WEIGHT: float = 0.25
    
    MIN_CONFIDENCE_THRESHOLD: float = 0.4
    
    # Momentum normalization range
    MIN_MOMENTUM_FOR_NORMALIZATION: float = 5.0  # 5% momentum = 0.0 score
    MAX_MOMENTUM_FOR_NORMALIZATION: float = 20.0  # 20% momentum = 1.0 score
    
    @classmethod
    def calculate_confidence(
        cls,
        momentum_score: float,
        peak_proximity_score: float,
        volume_confirmation_score: float,
        momentum_acceleration: float,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> EnhancedConfidenceResult:
        """Calculate enhanced confidence score.
        
        Args:
            momentum_score: Raw momentum score (percentage, e.g., 5.0 for 5%)
            peak_proximity_score: Peak proximity score (0.0-1.0, 1.0 = at peak)
            volume_confirmation_score: Volume confirmation score (0.0-1.0)
            momentum_acceleration: Normalized momentum acceleration (-1.0 to 1.0)
            config: Configuration object
            
        Returns:
            EnhancedConfidenceResult with score and components
        """
        # Use config weights if provided
        if config:
            momentum_weight = config.momentum_weight
            peak_proximity_weight = config.peak_proximity_weight
            volume_weight = config.volume_weight
            acceleration_weight = config.acceleration_weight
            min_confidence = config.min_confidence_threshold
        else:
            momentum_weight = cls.MOMENTUM_WEIGHT
            peak_proximity_weight = cls.PEAK_PROXIMITY_WEIGHT
            volume_weight = cls.VOLUME_WEIGHT
            acceleration_weight = cls.ACCELERATION_WEIGHT
            min_confidence = cls.MIN_CONFIDENCE_THRESHOLD
        
        # 1. Normalize momentum score to 0-1 range
        # 5% momentum = 0.0, 20% momentum = 1.0
        momentum_range = cls.MAX_MOMENTUM_FOR_NORMALIZATION - cls.MIN_MOMENTUM_FOR_NORMALIZATION
        momentum_normalized = (momentum_score - cls.MIN_MOMENTUM_FOR_NORMALIZATION) / momentum_range
        momentum_normalized = max(0.0, min(1.0, momentum_normalized))
        
        # 2. Invert peak proximity (closer to peak = lower confidence)
        # peak_proximity_score of 1.0 (at peak) -> peak_factor of 0.0
        # peak_proximity_score of 0.0 (far from peak) -> peak_factor of 1.0
        peak_factor = 1.0 - peak_proximity_score
        peak_factor = max(0.0, min(1.0, peak_factor))
        
        # 3. Volume factor (already 0-1)
        volume_factor = max(0.0, min(1.0, volume_confirmation_score))
        
        # 4. Acceleration factor: convert -1 to 1 range to 0 to 1
        # -1.0 (strong deceleration) -> 0.0
        # 0.0 (no change) -> 0.5
        # 1.0 (strong acceleration) -> 1.0
        acceleration_factor = (momentum_acceleration + 1.0) / 2.0
        acceleration_factor = max(0.0, min(1.0, acceleration_factor))
        
        # 5. Calculate weighted confidence score
        confidence_score = (
            momentum_normalized * momentum_weight +
            peak_factor * peak_proximity_weight +
            volume_factor * volume_weight +
            acceleration_factor * acceleration_weight
        )
        
        # Ensure confidence is in valid range
        confidence_score = max(0.0, min(1.0, confidence_score))
        
        # Create components for logging
        components = ConfidenceComponents(
            momentum_score=momentum_normalized,
            peak_proximity_score=peak_factor,  # Store the inverted value
            volume_confirmation_score=volume_factor,
            momentum_acceleration_score=acceleration_factor,
        )
        
        # 6. Check if confidence is below threshold
        rejection_reason: Optional[str] = None
        if confidence_score < min_confidence:
            rejection_reason = (
                f"Confidence too low: {confidence_score:.2f} < {min_confidence} "
                f"(momentum={momentum_normalized:.2f}, peak={peak_factor:.2f}, "
                f"volume={volume_factor:.2f}, accel={acceleration_factor:.2f})"
            )
        
        return EnhancedConfidenceResult(
            confidence_score=confidence_score,
            components=components,
            rejection_reason=rejection_reason,
        )
    
    @classmethod
    def should_reject_entry(
        cls,
        momentum_score: float,
        peak_proximity_score: float,
        volume_confirmation_score: float,
        momentum_acceleration: float,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> tuple[bool, str, EnhancedConfidenceResult]:
        """Check if entry should be rejected due to low confidence.
        
        Args:
            momentum_score: Raw momentum score
            peak_proximity_score: Peak proximity score
            volume_confirmation_score: Volume confirmation score
            momentum_acceleration: Normalized momentum acceleration
            config: Configuration object
            
        Returns:
            Tuple of (should_reject, reason, result)
        """
        result = cls.calculate_confidence(
            momentum_score=momentum_score,
            peak_proximity_score=peak_proximity_score,
            volume_confirmation_score=volume_confirmation_score,
            momentum_acceleration=momentum_acceleration,
            config=config,
        )
        
        if result.rejection_reason:
            return True, result.rejection_reason, result
        
        return False, "", result
