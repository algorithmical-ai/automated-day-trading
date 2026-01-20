"""
Peak Detection Models

Result dataclasses for the peak detection and enhanced validation pipeline.
These models capture the output of each validation component.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class PeakDetectionResult:
    """Result of peak detection analysis."""
    peak_proximity_score: float  # 0.0-1.0, 1.0 = at peak
    peak_price: float
    current_price: float
    lookback_bars: int
    is_at_peak: bool  # True if score > threshold
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class VolumeConfirmationResult:
    """Result of volume confirmation analysis."""
    volume_confirmation_score: float  # 0.0-1.0
    current_volume: int
    average_volume: float
    volume_ratio: float  # current / average
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class MomentumAccelerationResult:
    """Result of momentum acceleration analysis."""
    acceleration: float  # Raw acceleration value
    normalized_acceleration: float  # -1.0 to 1.0
    is_decelerating: bool
    momentum_values: List[float] = field(default_factory=list)  # Last 3 momentum values
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class ConfidenceComponents:
    """Individual components that make up the confidence score."""
    momentum_score: float
    peak_proximity_score: float
    volume_confirmation_score: float
    momentum_acceleration_score: float
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for JSON serialization."""
        return {
            "momentum_score": self.momentum_score,
            "peak_proximity_score": self.peak_proximity_score,
            "volume_confirmation_score": self.volume_confirmation_score,
            "momentum_acceleration_score": self.momentum_acceleration_score,
        }


@dataclass
class EnhancedConfidenceResult:
    """Result of enhanced confidence calculation."""
    confidence_score: float  # 0.0-1.0
    components: ConfidenceComponents
    rejection_reason: Optional[str] = None  # Set if confidence too low
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "confidence_score": self.confidence_score,
            "components": self.components.to_dict(),
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class PositionSizeResult:
    """Result of position size calculation."""
    position_size_dollars: float
    position_size_percent: float  # Percentage of standard size (0.5, 0.75, or 1.0)
    confidence_score: float
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class ValidationResult:
    """Complete validation result for a ticker."""
    ticker: str
    timestamp: str
    passed: bool
    rejection_reason: Optional[str] = None
    
    # Component results (optional - may be None if validation failed early)
    peak_detection: Optional[PeakDetectionResult] = None
    volume_confirmation: Optional[VolumeConfirmationResult] = None
    momentum_acceleration: Optional[MomentumAccelerationResult] = None
    confidence: Optional[EnhancedConfidenceResult] = None
    position_size: Optional[PositionSizeResult] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "passed": self.passed,
            "rejection_reason": self.rejection_reason,
        }
        
        if self.peak_detection:
            result["peak_detection"] = self.peak_detection.to_dict()
        if self.volume_confirmation:
            result["volume_confirmation"] = self.volume_confirmation.to_dict()
        if self.momentum_acceleration:
            result["momentum_acceleration"] = self.momentum_acceleration.to_dict()
        if self.confidence:
            result["confidence"] = self.confidence.to_dict()
        if self.position_size:
            result["position_size"] = self.position_size.to_dict()
        
        return result
    
    def to_json(self) -> str:
        """Serialize to JSON for logging."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> "ValidationResult":
        """Deserialize from JSON.
        
        Args:
            json_str: JSON string representation
            
        Returns:
            ValidationResult instance
        """
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationResult":
        """Create from dictionary.
        
        Args:
            data: Dictionary with validation result data
            
        Returns:
            ValidationResult instance
        """
        # Parse nested objects if present
        peak_detection = None
        if "peak_detection" in data and data["peak_detection"]:
            peak_detection = PeakDetectionResult(**data["peak_detection"])
        
        volume_confirmation = None
        if "volume_confirmation" in data and data["volume_confirmation"]:
            volume_confirmation = VolumeConfirmationResult(**data["volume_confirmation"])
        
        momentum_acceleration = None
        if "momentum_acceleration" in data and data["momentum_acceleration"]:
            momentum_acceleration = MomentumAccelerationResult(**data["momentum_acceleration"])
        
        confidence = None
        if "confidence" in data and data["confidence"]:
            conf_data = data["confidence"]
            components = ConfidenceComponents(**conf_data["components"])
            confidence = EnhancedConfidenceResult(
                confidence_score=conf_data["confidence_score"],
                components=components,
                rejection_reason=conf_data.get("rejection_reason"),
            )
        
        position_size = None
        if "position_size" in data and data["position_size"]:
            position_size = PositionSizeResult(**data["position_size"])
        
        return cls(
            ticker=data["ticker"],
            timestamp=data["timestamp"],
            passed=data["passed"],
            rejection_reason=data.get("rejection_reason"),
            peak_detection=peak_detection,
            volume_confirmation=volume_confirmation,
            momentum_acceleration=momentum_acceleration,
            confidence=confidence,
            position_size=position_size,
        )
    
    @classmethod
    def create_rejection(
        cls,
        ticker: str,
        reason: str,
        peak_detection: Optional[PeakDetectionResult] = None,
        volume_confirmation: Optional[VolumeConfirmationResult] = None,
        momentum_acceleration: Optional[MomentumAccelerationResult] = None,
    ) -> "ValidationResult":
        """Factory method to create a rejection result.
        
        Args:
            ticker: Stock ticker symbol
            reason: Rejection reason
            peak_detection: Optional peak detection result
            volume_confirmation: Optional volume confirmation result
            momentum_acceleration: Optional momentum acceleration result
            
        Returns:
            ValidationResult with passed=False
        """
        return cls(
            ticker=ticker,
            timestamp=datetime.utcnow().isoformat() + "Z",
            passed=False,
            rejection_reason=reason,
            peak_detection=peak_detection,
            volume_confirmation=volume_confirmation,
            momentum_acceleration=momentum_acceleration,
        )
    
    @classmethod
    def create_success(
        cls,
        ticker: str,
        peak_detection: PeakDetectionResult,
        volume_confirmation: VolumeConfirmationResult,
        momentum_acceleration: MomentumAccelerationResult,
        confidence: EnhancedConfidenceResult,
        position_size: PositionSizeResult,
    ) -> "ValidationResult":
        """Factory method to create a successful validation result.
        
        Args:
            ticker: Stock ticker symbol
            peak_detection: Peak detection result
            volume_confirmation: Volume confirmation result
            momentum_acceleration: Momentum acceleration result
            confidence: Confidence calculation result
            position_size: Position size result
            
        Returns:
            ValidationResult with passed=True
        """
        return cls(
            ticker=ticker,
            timestamp=datetime.utcnow().isoformat() + "Z",
            passed=True,
            rejection_reason=None,
            peak_detection=peak_detection,
            volume_confirmation=volume_confirmation,
            momentum_acceleration=momentum_acceleration,
            confidence=confidence,
            position_size=position_size,
        )
