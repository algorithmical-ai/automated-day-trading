"""
Data models for simplified penny stock validation.

This module contains the core data structures used in the simplified
validation system for penny stock trade entry decisions.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class TrendMetrics:
    """Trend analysis metrics calculated from price bars."""
    
    momentum_score: float  # Amplified trend strength (can be large positive/negative)
    continuation_score: float  # 0.0-1.0, proportion of moves in trend direction
    peak_price: float  # Highest price in recent bars
    bottom_price: float  # Lowest price in recent bars
    reason: str  # Human-readable description
    
    def __str__(self) -> str:
        return (
            f"TrendMetrics(momentum={self.momentum_score:.2f}, "
            f"continuation={self.continuation_score:.2f}, "
            f"peak=${self.peak_price:.2f}, bottom=${self.bottom_price:.2f})"
        )


@dataclass
class Quote:
    """Market quote data for a ticker."""
    
    ticker: str
    bid: float
    ask: float
    
    @property
    def mid_price(self) -> float:
        """Calculate mid-price between bid and ask."""
        return (self.bid + self.ask) / 2
    
    @property
    def spread_percent(self) -> float:
        """Calculate bid-ask spread as percentage of mid-price."""
        if self.mid_price == 0:
            return 0.0
        return ((self.ask - self.bid) / self.mid_price) * 100
    
    def __str__(self) -> str:
        return (
            f"Quote({self.ticker}: bid=${self.bid:.2f}, "
            f"ask=${self.ask:.2f}, spread={self.spread_percent:.2f}%)"
        )



@dataclass
class ValidationResult:
    """Result of validation checks for trade entry."""
    
    reason_not_to_enter_long: str  # Empty string if valid for long entry
    reason_not_to_enter_short: str  # Empty string if valid for short entry
    
    @property
    def is_valid_for_long(self) -> bool:
        """Check if long entry is valid (empty rejection reason)."""
        return self.reason_not_to_enter_long == ""
    
    @property
    def is_valid_for_short(self) -> bool:
        """Check if short entry is valid (empty rejection reason)."""
        return self.reason_not_to_enter_short == ""
    
    def __str__(self) -> str:
        long_status = "VALID" if self.is_valid_for_long else "REJECTED"
        short_status = "VALID" if self.is_valid_for_short else "REJECTED"
        return f"ValidationResult(long={long_status}, short={short_status})"


@dataclass
class EvaluationRecord:
    """Complete evaluation record for database storage."""
    
    ticker: str
    indicator: str  # "Penny Stocks"
    reason_not_to_enter_long: str
    reason_not_to_enter_short: str
    technical_indicators: Dict[str, Any]  # JSON with momentum_score, continuation_score, etc.
    timestamp: str  # ISO 8601 format
    
    def __str__(self) -> str:
        return (
            f"EvaluationRecord({self.ticker}, indicator={self.indicator}, "
            f"timestamp={self.timestamp})"
        )
