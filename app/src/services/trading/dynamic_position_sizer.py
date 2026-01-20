"""
Dynamic Position Sizer

Calculates position size based on confidence score.
Lower confidence trades get smaller position sizes to limit exposure.
"""

from app.src.services.trading.peak_detection_models import PositionSizeResult
from app.src.services.trading.peak_detection_config import PeakDetectionConfig, DEFAULT_CONFIG


class DynamicPositionSizer:
    """Calculates position size based on confidence score.
    
    Position sizing tiers:
    - High confidence (>= 0.8): 100% of standard position
    - Medium confidence (0.6-0.8): 75% of standard position
    - Low confidence (0.4-0.6): 50% of standard position
    - Below 0.4: Reject entry
    
    Minimum position size of $50 is enforced to avoid excessive commission impact.
    """
    
    MIN_POSITION_SIZE: float = 50.0  # Minimum $50 position
    
    # Confidence tiers
    HIGH_CONFIDENCE_THRESHOLD: float = 0.8
    MEDIUM_CONFIDENCE_THRESHOLD: float = 0.6
    LOW_CONFIDENCE_THRESHOLD: float = 0.4
    
    # Position size multipliers
    HIGH_CONFIDENCE_MULTIPLIER: float = 1.0  # 100%
    MEDIUM_CONFIDENCE_MULTIPLIER: float = 0.75  # 75%
    LOW_CONFIDENCE_MULTIPLIER: float = 0.5  # 50%
    
    @classmethod
    def calculate_position_size(
        cls,
        standard_position_size: float,
        confidence_score: float,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> PositionSizeResult:
        """Calculate position size based on confidence.
        
        Args:
            standard_position_size: The standard position size in dollars
            confidence_score: Confidence score from 0.0 to 1.0
            config: Configuration object (optional)
            
        Returns:
            PositionSizeResult with size and metadata
        """
        # Use config values if provided
        if config:
            min_position = config.min_position_size
            high_threshold = config.high_confidence_threshold
            medium_threshold = config.medium_confidence_threshold
            low_threshold = config.min_confidence_threshold
        else:
            min_position = cls.MIN_POSITION_SIZE
            high_threshold = cls.HIGH_CONFIDENCE_THRESHOLD
            medium_threshold = cls.MEDIUM_CONFIDENCE_THRESHOLD
            low_threshold = cls.LOW_CONFIDENCE_THRESHOLD
        
        # Determine multiplier based on confidence tier
        if confidence_score >= high_threshold:
            multiplier = cls.HIGH_CONFIDENCE_MULTIPLIER
            reason = f"High confidence ({confidence_score:.2f} >= {high_threshold}): 100% position"
        elif confidence_score >= medium_threshold:
            multiplier = cls.MEDIUM_CONFIDENCE_MULTIPLIER
            reason = f"Medium confidence ({confidence_score:.2f} >= {medium_threshold}): 75% position"
        elif confidence_score >= low_threshold:
            multiplier = cls.LOW_CONFIDENCE_MULTIPLIER
            reason = f"Low confidence ({confidence_score:.2f} >= {low_threshold}): 50% position"
        else:
            # Below minimum threshold - should be rejected
            # Return zero position size with rejection reason
            return PositionSizeResult(
                position_size_dollars=0.0,
                position_size_percent=0.0,
                confidence_score=confidence_score,
                reason=f"Confidence too low ({confidence_score:.2f} < {low_threshold}): entry rejected",
            )
        
        # Calculate position size
        position_size = standard_position_size * multiplier
        
        # Enforce minimum position size
        if position_size < min_position and position_size > 0:
            position_size = min_position
            reason += f" (adjusted to minimum ${min_position:.2f})"
        
        return PositionSizeResult(
            position_size_dollars=position_size,
            position_size_percent=multiplier,
            confidence_score=confidence_score,
            reason=reason,
        )
    
    @classmethod
    def should_reject_entry(
        cls,
        confidence_score: float,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> tuple[bool, str]:
        """Check if entry should be rejected due to low confidence.
        
        Args:
            confidence_score: Confidence score from 0.0 to 1.0
            config: Configuration object
            
        Returns:
            Tuple of (should_reject, reason)
        """
        low_threshold = config.min_confidence_threshold if config else cls.LOW_CONFIDENCE_THRESHOLD
        
        if confidence_score < low_threshold:
            return True, f"Confidence too low: {confidence_score:.2f} < {low_threshold}"
        
        return False, ""
    
    @classmethod
    def get_position_multiplier(
        cls,
        confidence_score: float,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> float:
        """Get the position size multiplier for a given confidence score.
        
        Args:
            confidence_score: Confidence score from 0.0 to 1.0
            config: Configuration object
            
        Returns:
            Position size multiplier (0.0, 0.5, 0.75, or 1.0)
        """
        if config:
            high_threshold = config.high_confidence_threshold
            medium_threshold = config.medium_confidence_threshold
            low_threshold = config.min_confidence_threshold
        else:
            high_threshold = cls.HIGH_CONFIDENCE_THRESHOLD
            medium_threshold = cls.MEDIUM_CONFIDENCE_THRESHOLD
            low_threshold = cls.LOW_CONFIDENCE_THRESHOLD
        
        if confidence_score >= high_threshold:
            return cls.HIGH_CONFIDENCE_MULTIPLIER
        elif confidence_score >= medium_threshold:
            return cls.MEDIUM_CONFIDENCE_MULTIPLIER
        elif confidence_score >= low_threshold:
            return cls.LOW_CONFIDENCE_MULTIPLIER
        else:
            return 0.0  # Rejected
