"""
Volume Analyzer

Confirms that price movements are supported by adequate volume.
Higher volume during price moves indicates stronger conviction.
"""

from typing import Dict, List, Any

from app.src.services.trading.peak_detection_models import VolumeConfirmationResult
from app.src.services.trading.peak_detection_config import PeakDetectionConfig, DEFAULT_CONFIG


class VolumeAnalyzer:
    """Analyzes volume to confirm price movements.
    
    The volume confirmation score indicates whether the current volume
    supports the price movement. Higher volume = higher confidence.
    
    Algorithm:
    1. Extract volumes from last `lookback_bars` bars
    2. Calculate average_volume = mean(volumes[:-1])  # Exclude current bar
    3. current_volume = volumes[-1]
    4. volume_ratio = current_volume / average_volume
    5. If volume_ratio >= 1.5: score = 1.0
    6. Else: score = volume_ratio / 1.5  # Linear scale
    7. Clamp score to [0.0, 1.0]
    """
    
    DEFAULT_LOOKBACK_BARS: int = 20
    HIGH_VOLUME_MULTIPLIER: float = 1.5  # 50% above average = score 1.0
    NEUTRAL_SCORE: float = 0.5  # Score when data is unavailable
    
    @classmethod
    def analyze_volume(
        cls,
        bars: List[Dict[str, Any]],
        lookback_bars: int = DEFAULT_LOOKBACK_BARS,
        high_volume_multiplier: float = HIGH_VOLUME_MULTIPLIER,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> VolumeConfirmationResult:
        """Calculate volume confirmation score.
        
        Args:
            bars: List of price bars with 'v' (volume) key
            lookback_bars: Number of bars to look back for volume average
            high_volume_multiplier: Multiplier above which score is 1.0
            config: Configuration object (optional, uses defaults if not provided)
            
        Returns:
            VolumeConfirmationResult with score and metadata
        """
        # Use config values if provided
        if config:
            lookback_bars = config.volume_lookback_bars
            high_volume_multiplier = config.high_volume_multiplier
        
        # Handle edge cases - no data
        if not bars or len(bars) == 0:
            return VolumeConfirmationResult(
                volume_confirmation_score=cls.NEUTRAL_SCORE,
                current_volume=0,
                average_volume=0.0,
                volume_ratio=0.0,
            )
        
        # Get recent bars for lookback
        recent_bars = bars[-lookback_bars:] if len(bars) >= lookback_bars else bars
        
        # Extract volumes from bars
        volumes = []
        for bar in recent_bars:
            volume = bar.get('v', 0)
            if volume is not None:
                try:
                    volumes.append(int(volume))
                except (ValueError, TypeError):
                    volumes.append(0)
        
        # Handle case with no valid volumes
        if not volumes:
            return VolumeConfirmationResult(
                volume_confirmation_score=cls.NEUTRAL_SCORE,
                current_volume=0,
                average_volume=0.0,
                volume_ratio=0.0,
            )
        
        # Get current volume (last bar)
        current_volume = volumes[-1] if volumes else 0
        
        # Calculate average volume (excluding current bar if we have enough data)
        if len(volumes) > 1:
            historical_volumes = volumes[:-1]
            average_volume = sum(historical_volumes) / len(historical_volumes)
        else:
            # Only one bar - use it as both current and average
            average_volume = float(current_volume)
        
        # Handle zero average volume
        if average_volume <= 0:
            return VolumeConfirmationResult(
                volume_confirmation_score=cls.NEUTRAL_SCORE,
                current_volume=current_volume,
                average_volume=0.0,
                volume_ratio=0.0,
            )
        
        # Calculate volume ratio
        volume_ratio = current_volume / average_volume
        
        # Calculate volume confirmation score
        # Score of 1.0 when volume is 1.5x or more above average
        # Linear scale below that
        if volume_ratio >= high_volume_multiplier:
            volume_confirmation_score = 1.0
        else:
            volume_confirmation_score = volume_ratio / high_volume_multiplier
        
        # Clamp to [0.0, 1.0]
        volume_confirmation_score = max(0.0, min(1.0, volume_confirmation_score))
        
        return VolumeConfirmationResult(
            volume_confirmation_score=volume_confirmation_score,
            current_volume=current_volume,
            average_volume=average_volume,
            volume_ratio=volume_ratio,
        )
    
    @classmethod
    def is_volume_confirmed(
        cls,
        bars: List[Dict[str, Any]],
        min_score: float = 0.5,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> tuple[bool, str, VolumeConfirmationResult]:
        """Check if volume confirms the price movement.
        
        Args:
            bars: List of price bars
            min_score: Minimum score required for confirmation
            config: Configuration object
            
        Returns:
            Tuple of (is_confirmed, reason, result)
        """
        result = cls.analyze_volume(bars=bars, config=config)
        
        if result.volume_confirmation_score < min_score:
            reason = (
                f"Volume not confirming: score={result.volume_confirmation_score:.2f} "
                f"(min={min_score}), ratio={result.volume_ratio:.2f}x average"
            )
            return False, reason, result
        
        return True, "", result
