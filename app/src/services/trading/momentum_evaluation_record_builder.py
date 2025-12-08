"""
Momentum evaluation record builder for database storage.

This module builds structured evaluation records with comprehensive
technical indicators and symmetric rejection reasons.
"""

from datetime import datetime, timezone
from typing import Dict, Any
from app.src.models.momentum_validation import TechnicalIndicators, ValidationResult


class MomentumEvaluationRecordBuilder:
    """Build evaluation records for momentum trading."""
    
    def __init__(self, indicator_name: str = "Momentum Trading"):
        """
        Initialize builder with configuration.
        
        Args:
            indicator_name: Name of the indicator (default: "Momentum Trading")
        """
        self.indicator_name = indicator_name
    
    def build_record(
        self,
        ticker: str,
        validation_result: ValidationResult,
        technical_indicators: TechnicalIndicators
    ) -> Dict[str, Any]:
        """
        Build evaluation record for database.
        
        Args:
            ticker: Stock ticker symbol
            validation_result: Result of validation checks
            technical_indicators: Calculated technical indicators
            
        Returns:
            Dictionary with all required fields for database storage
        """
        # Generate ISO 8601 timestamp
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Build technical indicators dictionary
        tech_indicators_dict = technical_indicators.to_dict()
        
        # Verify symmetric rejection (for momentum trading, both reasons should always be identical)
        if not validation_result.is_valid and not validation_result.is_symmetric_rejection:
            # This should not happen in momentum trading, but log if it does
            from loguru import logger
            logger.warning(
                f"Non-symmetric rejection detected for {ticker}: "
                f"long='{validation_result.reason_not_to_enter_long}', "
                f"short='{validation_result.reason_not_to_enter_short}'"
            )
        
        # Build complete record
        record = {
            "ticker": ticker,
            "indicator": self.indicator_name,
            "reason_not_to_enter_long": validation_result.reason_not_to_enter_long,
            "reason_not_to_enter_short": validation_result.reason_not_to_enter_short,
            "technical_indicators": tech_indicators_dict,
            "timestamp": timestamp
        }
        
        return record
