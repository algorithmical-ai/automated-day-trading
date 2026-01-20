"""
Enhanced Validation Pipeline

Orchestrates all validation components for penny stock entry decisions.
Executes checks in order with early rejection for efficiency.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime

from app.src.common.loguru_logger import logger
from app.src.services.trading.peak_detection_config import PeakDetectionConfig, DEFAULT_CONFIG
from app.src.services.trading.peak_detection_models import (
    ValidationResult,
    PeakDetectionResult,
    VolumeConfirmationResult,
    MomentumAccelerationResult,
    EnhancedConfidenceResult,
    PositionSizeResult,
)
from app.src.services.trading.peak_detector import PeakDetector
from app.src.services.trading.volume_analyzer import VolumeAnalyzer
from app.src.services.trading.momentum_acceleration_analyzer import MomentumAccelerationAnalyzer
from app.src.services.trading.enhanced_confidence_calculator import EnhancedConfidenceCalculator
from app.src.services.trading.dynamic_position_sizer import DynamicPositionSizer


class EnhancedValidationPipeline:
    """Orchestrates all validation components for entry decisions.
    
    Validation order:
    1. Peak detection - reject if price is at/near local peak
    2. Volume confirmation - check if volume supports the move
    3. Momentum deceleration - reject if momentum is slowing
    4. Confidence calculation - combine all factors
    5. Position sizing - determine position size based on confidence
    
    Early rejection stops the pipeline and returns immediately.
    """
    
    def __init__(self, config: PeakDetectionConfig = DEFAULT_CONFIG):
        """Initialize pipeline with configuration.
        
        Args:
            config: Configuration object for all validation parameters
        """
        self.config = config
    
    def validate_entry(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
        current_price: float,
        momentum_score: float,
        standard_position_size: float,
    ) -> ValidationResult:
        """Run full validation pipeline for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            bars: Historical price bars
            current_price: Current price
            momentum_score: Calculated momentum score (percentage)
            standard_position_size: Standard position size in dollars
            
        Returns:
            ValidationResult with all component results
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Track component results for logging
        peak_result: Optional[PeakDetectionResult] = None
        volume_result: Optional[VolumeConfirmationResult] = None
        accel_result: Optional[MomentumAccelerationResult] = None
        confidence_result: Optional[EnhancedConfidenceResult] = None
        position_result: Optional[PositionSizeResult] = None
        
        # STEP 1: Peak Detection
        should_reject, reason, peak_result = PeakDetector.should_reject_entry(
            bars=bars,
            current_price=current_price,
            config=self.config,
        )
        
        if should_reject:
            logger.debug(f"[{ticker}] Peak detection rejection: {reason}")
            return ValidationResult.create_rejection(
                ticker=ticker,
                reason=reason,
                peak_detection=peak_result,
            )
        
        # STEP 2: Volume Confirmation
        # Note: We don't reject on low volume, but it affects confidence
        _, _, volume_result = VolumeAnalyzer.is_volume_confirmed(
            bars=bars,
            min_score=0.0,  # Don't reject, just measure
            config=self.config,
        )
        
        # STEP 3: Momentum Deceleration
        should_reject, reason, accel_result = MomentumAccelerationAnalyzer.should_reject_entry(
            bars=bars,
            config=self.config,
        )
        
        if should_reject:
            logger.debug(f"[{ticker}] Momentum deceleration rejection: {reason}")
            return ValidationResult.create_rejection(
                ticker=ticker,
                reason=reason,
                peak_detection=peak_result,
                volume_confirmation=volume_result,
                momentum_acceleration=accel_result,
            )
        
        # STEP 4: Confidence Calculation
        should_reject, reason, confidence_result = EnhancedConfidenceCalculator.should_reject_entry(
            momentum_score=momentum_score,
            peak_proximity_score=peak_result.peak_proximity_score,
            volume_confirmation_score=volume_result.volume_confirmation_score,
            momentum_acceleration=accel_result.normalized_acceleration,
            config=self.config,
        )
        
        if should_reject:
            logger.debug(f"[{ticker}] Low confidence rejection: {reason}")
            return ValidationResult.create_rejection(
                ticker=ticker,
                reason=reason,
                peak_detection=peak_result,
                volume_confirmation=volume_result,
                momentum_acceleration=accel_result,
            )
        
        # STEP 5: Position Sizing
        position_result = DynamicPositionSizer.calculate_position_size(
            standard_position_size=standard_position_size,
            confidence_score=confidence_result.confidence_score,
            config=self.config,
        )
        
        # Check if position sizing rejected (confidence below threshold)
        if position_result.position_size_dollars == 0:
            logger.debug(f"[{ticker}] Position sizing rejection: {position_result.reason}")
            return ValidationResult.create_rejection(
                ticker=ticker,
                reason=position_result.reason,
                peak_detection=peak_result,
                volume_confirmation=volume_result,
                momentum_acceleration=accel_result,
            )
        
        # All checks passed
        logger.info(
            f"[{ticker}] Validation PASSED: confidence={confidence_result.confidence_score:.2f}, "
            f"position=${position_result.position_size_dollars:.2f} ({position_result.position_size_percent*100:.0f}%)"
        )
        
        return ValidationResult.create_success(
            ticker=ticker,
            peak_detection=peak_result,
            volume_confirmation=volume_result,
            momentum_acceleration=accel_result,
            confidence=confidence_result,
            position_size=position_result,
        )
    
    def get_validation_summary(self, result: ValidationResult) -> Dict[str, Any]:
        """Get a summary of validation result for logging.
        
        Args:
            result: ValidationResult to summarize
            
        Returns:
            Dictionary with summary information
        """
        summary = {
            "ticker": result.ticker,
            "passed": result.passed,
            "timestamp": result.timestamp,
        }
        
        if result.rejection_reason:
            summary["rejection_reason"] = result.rejection_reason
        
        if result.peak_detection:
            summary["peak_proximity_score"] = result.peak_detection.peak_proximity_score
            summary["is_at_peak"] = result.peak_detection.is_at_peak
        
        if result.volume_confirmation:
            summary["volume_score"] = result.volume_confirmation.volume_confirmation_score
            summary["volume_ratio"] = result.volume_confirmation.volume_ratio
        
        if result.momentum_acceleration:
            summary["acceleration"] = result.momentum_acceleration.acceleration
            summary["is_decelerating"] = result.momentum_acceleration.is_decelerating
        
        if result.confidence:
            summary["confidence_score"] = result.confidence.confidence_score
        
        if result.position_size:
            summary["position_size"] = result.position_size.position_size_dollars
            summary["position_percent"] = result.position_size.position_size_percent
        
        return summary


# Singleton instance with default config
_default_pipeline: Optional[EnhancedValidationPipeline] = None


def get_validation_pipeline(config: PeakDetectionConfig = DEFAULT_CONFIG) -> EnhancedValidationPipeline:
    """Get or create the validation pipeline instance.
    
    Args:
        config: Configuration object
        
    Returns:
        EnhancedValidationPipeline instance
    """
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = EnhancedValidationPipeline(config)
    return _default_pipeline
