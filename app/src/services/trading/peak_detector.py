"""
Peak Detector

Identifies when price is at or near a local peak within a configurable lookback window.
This helps avoid entering trades at price peaks that are likely to reverse.
"""

from typing import Dict, List, Any

from app.src.services.trading.peak_detection_models import PeakDetectionResult
from app.src.services.trading.peak_detection_config import PeakDetectionConfig, DEFAULT_CONFIG


class PeakDetector:
    """Detects when price is at or near a local peak.
    
    The peak proximity score indicates how close the current price is to the
    recent peak price. A score of 1.0 means the price is at the peak, while
    lower scores indicate the price is further below the peak.
    
    Algorithm:
    1. Extract high prices from last `lookback_bars` bars
    2. Find peak_price = max(high prices)
    3. Calculate distance_from_peak = (peak_price - current_price) / peak_price
    4. peak_proximity_score = 1.0 - (distance_from_peak / 0.03)  # Normalize to 3% range
    5. Clamp score to [0.0, 1.0]
    """
    
    DEFAULT_LOOKBACK_BARS: int = 10
    DEFAULT_PEAK_THRESHOLD: float = 0.85
    NORMALIZATION_RANGE: float = 0.03  # 3% range for normalization
    
    @classmethod
    def detect_peak(
        cls,
        bars: List[Dict[str, Any]],
        current_price: float,
        lookback_bars: int = DEFAULT_LOOKBACK_BARS,
        peak_threshold: float = DEFAULT_PEAK_THRESHOLD,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> PeakDetectionResult:
        """Calculate peak proximity score.
        
        Args:
            bars: List of price bars with 'h' (high), 'l' (low), 'c' (close) keys
            current_price: Current price to compare against peak
            lookback_bars: Number of bars to look back for peak detection
            peak_threshold: Threshold above which entry is rejected
            config: Configuration object (optional, uses defaults if not provided)
            
        Returns:
            PeakDetectionResult with score and metadata
        """
        # Use config values if provided
        if config:
            lookback_bars = config.peak_lookback_bars
            peak_threshold = config.peak_proximity_threshold
        
        # Handle edge cases
        if not bars or len(bars) == 0:
            # No data - return neutral score
            return PeakDetectionResult(
                peak_proximity_score=0.5,
                peak_price=current_price,
                current_price=current_price,
                lookback_bars=0,
                is_at_peak=False,
            )
        
        if current_price <= 0:
            # Invalid price - return neutral score
            return PeakDetectionResult(
                peak_proximity_score=0.5,
                peak_price=0.0,
                current_price=current_price,
                lookback_bars=len(bars),
                is_at_peak=False,
            )
        
        # Get recent bars for lookback
        recent_bars = bars[-lookback_bars:] if len(bars) >= lookback_bars else bars
        actual_lookback = len(recent_bars)
        
        # Extract high prices from bars
        high_prices = []
        for bar in recent_bars:
            # Try 'h' (high) first, fall back to 'c' (close)
            high = bar.get('h')
            if high is None or high <= 0:
                high = bar.get('c', 0)
            if high and high > 0:
                high_prices.append(float(high))
        
        if not high_prices:
            # No valid prices - return neutral score
            return PeakDetectionResult(
                peak_proximity_score=0.5,
                peak_price=current_price,
                current_price=current_price,
                lookback_bars=actual_lookback,
                is_at_peak=False,
            )
        
        # Find peak price
        peak_price = max(high_prices)
        
        # Handle case where peak_price is 0 or negative
        if peak_price <= 0:
            return PeakDetectionResult(
                peak_proximity_score=0.5,
                peak_price=peak_price,
                current_price=current_price,
                lookback_bars=actual_lookback,
                is_at_peak=False,
            )
        
        # Calculate distance from peak as percentage
        distance_from_peak = (peak_price - current_price) / peak_price
        
        # Calculate peak proximity score
        # Score of 1.0 when at peak (distance = 0)
        # Score of 0.5 when 1.5% below peak
        # Score of 0.0 when 3% or more below peak
        peak_proximity_score = 1.0 - (distance_from_peak / cls.NORMALIZATION_RANGE)
        
        # Clamp to [0.0, 1.0]
        peak_proximity_score = max(0.0, min(1.0, peak_proximity_score))
        
        # Determine if at peak (above threshold)
        is_at_peak = peak_proximity_score > peak_threshold
        
        return PeakDetectionResult(
            peak_proximity_score=peak_proximity_score,
            peak_price=peak_price,
            current_price=current_price,
            lookback_bars=actual_lookback,
            is_at_peak=is_at_peak,
        )
    
    @classmethod
    def should_reject_entry(
        cls,
        bars: List[Dict[str, Any]],
        current_price: float,
        config: PeakDetectionConfig = DEFAULT_CONFIG,
    ) -> tuple[bool, str, PeakDetectionResult]:
        """Check if entry should be rejected due to peak proximity.
        
        Args:
            bars: List of price bars
            current_price: Current price
            config: Configuration object
            
        Returns:
            Tuple of (should_reject, reason, result)
        """
        result = cls.detect_peak(
            bars=bars,
            current_price=current_price,
            config=config,
        )
        
        if result.is_at_peak:
            reason = (
                f"Price too close to local peak: score={result.peak_proximity_score:.2f} "
                f"(threshold={config.peak_proximity_threshold}), "
                f"current=${current_price:.4f}, peak=${result.peak_price:.4f}"
            )
            return True, reason, result
        
        return False, "", result
