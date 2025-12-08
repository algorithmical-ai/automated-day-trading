"""
Rejection collector for accumulating validation failures.

This module provides a collector that accumulates rejection records during
an entry cycle for batch writing to the database.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.src.services.trading.validation.models import RejectionRecord


class RejectionCollector:
    """
    Collects rejection records during an entry cycle.
    
    Accumulates rejections in memory and provides them for batch writing
    to the database at the end of the cycle.
    """
    
    def __init__(self):
        """Initialize the rejection collector."""
        self._records: List[Dict[str, Any]] = []
    
    def add_rejection(
        self,
        ticker: str,
        indicator: str,
        reason_long: Optional[str] = None,
        reason_short: Optional[str] = None,
        technical_indicators: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add a rejection record to the batch.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Name of the trading indicator
            reason_long: Rejection reason for long entry (optional)
            reason_short: Rejection reason for short entry (optional)
            technical_indicators: Dictionary of technical metrics (optional)
            
        Raises:
            ValueError: If ticker or indicator is empty, or if both reasons are None
        """
        # Validate required fields
        if not ticker or not ticker.strip():
            raise ValueError("ticker cannot be empty")
        
        if not indicator or not indicator.strip():
            raise ValueError("indicator cannot be empty")
        
        if reason_long is None and reason_short is None:
            raise ValueError("At least one rejection reason must be provided")
        
        # Create rejection record
        record = RejectionRecord(
            ticker=ticker,
            indicator=indicator,
            reason_not_to_enter_long=reason_long,
            reason_not_to_enter_short=reason_short,
            technical_indicators=technical_indicators,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Add to internal list
        self._records.append(record.to_dict())
    
    def get_records(self) -> List[Dict[str, Any]]:
        """
        Get all collected rejection records.
        
        Returns:
            List of rejection record dictionaries
        """
        return self._records.copy()
    
    def clear(self) -> None:
        """Clear all collected records."""
        self._records.clear()
    
    def count(self) -> int:
        """
        Get the number of collected records.
        
        Returns:
            Number of rejection records
        """
        return len(self._records)
    
    def has_records(self) -> bool:
        """
        Check if any records have been collected.
        
        Returns:
            True if records exist, False otherwise
        """
        return len(self._records) > 0
