"""
Evaluation record builder for database storage.

This module builds structured evaluation records that include
ticker information, validation results, and technical indicators.
"""

from datetime import datetime, timezone
from typing import Dict, Any
from app.src.models.simplified_validation import TrendMetrics, ValidationResult


class EvaluationRecordBuilder:
    """Build evaluation records for database storage."""
    
    def __init__(self, indicator_name: str = "Penny Stocks"):
        """
        Initialize builder with configuration.
        
        Args:
            indicator_name: Name of the indicator (default: "Penny Stocks")
        """
        self.indicator_name = indicator_name
    
    def build_record(
        self,
        ticker: str,
        validation_result: ValidationResult,
        trend_metrics: TrendMetrics
    ) -> Dict[str, Any]:
        """
        Build evaluation record for database.
        
        Args:
            ticker: Stock ticker symbol
            validation_result: Result of validation checks
            trend_metrics: Calculated trend metrics
            
        Returns:
            Dictionary with all required fields for database storage
        """
        # Generate ISO 8601 timestamp
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Build technical indicators JSON
        technical_indicators = {
            "momentum_score": trend_metrics.momentum_score,
            "continuation_score": trend_metrics.continuation_score,
            "peak_price": trend_metrics.peak_price,
            "bottom_price": trend_metrics.bottom_price,
            "reason": trend_metrics.reason
        }
        
        # Build complete record
        record = {
            "ticker": ticker,
            "indicator": self.indicator_name,
            "reason_not_to_enter_long": validation_result.reason_not_to_enter_long,
            "reason_not_to_enter_short": validation_result.reason_not_to_enter_short,
            "technical_indicators": technical_indicators,
            "timestamp": timestamp
        }
        
        return record
