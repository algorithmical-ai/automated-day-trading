"""
Momentum Acceleration Analyzer

Detects whether momentum is accelerating or decelerating.
Decelerating momentum before entry indicates the move may be ending.
"""

from typing import Dict, List, Any

from app.src.services.trading.peak_detection_models import MomentumAccelerationResult
from app.src.services.trading.peak_detection_config import PeakDetectionConfig, DEFAULT_CONFIG


class MomentumAccelerationAnalyzer:
    """Analyzes momentum acceleration to detect trend exhaustion.
    
    Momentum acceleration is the rate of change of momentum. Positive
    acceleration means momentum is increasing (trend strengthening),
    while negative acceleration means momentum is decreasing (trend weakening).
    
    Algorithm:
    1. Calculate momentum for each of last 4 bars: momentum[i] = (close[i] - close[i-1]) / close[i-1] * 100
    2. Calculate acceleration: accel = momentum[-1] - momentum[-2]
    3. normalized_acceleration = clamp(accel / NORMALIZATION_RANGE, -1.0, 1.0)
    4. is_decelerating = accel < deceleration_threshold
    """
    
    DECELERATION_THRESHOLD: float = -2.0  # Below this = strong deceleration
    NORMALIZATION_RANGE: float = 5.0  # Values beyond ±5 are clamped
    MIN_BARS_REQUIRED: int = 4  # Need at least 4 bars to calculate acceleration
    
    @classmethod
    def analyze_acceleration(
        cls,
        bars: List[Dict[str, Any]],
        deceleration_threshold: float = DECELERATION_THRESHOLD,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> MomentumAccelerationResult:
        """Calculate momentum acceleration.
        
        Args:
            bars: List of price bars with 'c' (close) key
            deceleration_threshold: Threshold below which momentum is considered decelerating
            config: Configuration object (optional, uses defaults if not provided)
            
        Returns:
            MomentumAccelerationResult with acceleration and metadata
        """
        # Use config values if provided
        if config:
            deceleration_threshold = config.momentum_deceleration_threshold
            normalization_range = config.momentum_normalization_range
        else:
            normalization_range = cls.NORMALIZATION_RANGE
        
        # Handle edge cases - insufficient data
        if not bars or len(bars) < cls.MIN_BARS_REQUIRED:
            return MomentumAccelerationResult(
                acceleration=0.0,
                normalized_acceleration=0.0,
                is_decelerating=False,
                momentum_values=[],
            )
        
        # Get last 4 bars for momentum calculation
        recent_bars = bars[-cls.MIN_BARS_REQUIRED:]
        
        # Extract close prices
        close_prices = []
        for bar in recent_bars:
            close = bar.get('c')
            if close is not None and close > 0:
                try:
                    close_prices.append(float(close))
                except (ValueError, TypeError):
                    pass
        
        # Need at least 4 valid prices
        if len(close_prices) < cls.MIN_BARS_REQUIRED:
            return MomentumAccelerationResult(
                acceleration=0.0,
                normalized_acceleration=0.0,
                is_decelerating=False,
                momentum_values=[],
            )
        
        # Calculate momentum for each bar (percentage change from previous bar)
        momentum_values = []
        for i in range(1, len(close_prices)):
            prev_price = close_prices[i - 1]
            curr_price = close_prices[i]
            if prev_price > 0:
                momentum = ((curr_price - prev_price) / prev_price) * 100
                momentum_values.append(momentum)
        
        # Need at least 2 momentum values to calculate acceleration
        if len(momentum_values) < 2:
            return MomentumAccelerationResult(
                acceleration=0.0,
                normalized_acceleration=0.0,
                is_decelerating=False,
                momentum_values=momentum_values,
            )
        
        # Calculate acceleration (change in momentum)
        # Use the last two momentum values
        acceleration = momentum_values[-1] - momentum_values[-2]
        
        # Normalize acceleration to [-1.0, 1.0] range
        normalized_acceleration = acceleration / normalization_range
        normalized_acceleration = max(-1.0, min(1.0, normalized_acceleration))
        
        # Determine if decelerating
        is_decelerating = acceleration < deceleration_threshold
        
        return MomentumAccelerationResult(
            acceleration=acceleration,
            normalized_acceleration=normalized_acceleration,
            is_decelerating=is_decelerating,
            momentum_values=momentum_values,
        )
    
    @classmethod
    def should_reject_entry(
        cls,
        bars: List[Dict[str, Any]],
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> tuple[bool, str, MomentumAccelerationResult]:
        """Check if entry should be rejected due to momentum deceleration.
        
        Args:
            bars: List of price bars
            config: Configuration object
            
        Returns:
            Tuple of (should_reject, reason, result)
        """
        result = cls.analyze_acceleration(bars=bars, config=config)
        
        if result.is_decelerating:
            reason = (
                f"Momentum decelerating: acceleration={result.acceleration:.2f} "
                f"(threshold={config.momentum_deceleration_threshold}), "
                f"recent momentum values={[f'{m:.2f}' for m in result.momentum_values[-3:]]}"
            )
            return True, reason, result
        
        return False, "", result
