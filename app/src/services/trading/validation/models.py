"""
Data models for penny stock entry validation.

This module defines the core data structures used throughout the validation pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime, timezone


@dataclass
class TrendMetrics:
    """
    Metrics describing price trend characteristics.
    
    Attributes:
        momentum_score: Percentage representing trend strength and direction
                       (positive=upward, negative=downward)
        continuation_score: Proportion (0.0-1.0) of recent price changes
                           moving in the trend direction
        peak_price: Highest price observed in the recent bars window
        bottom_price: Lowest price observed in the recent bars window
        reason: Human-readable description of the trend calculation
    """
    momentum_score: float
    continuation_score: float
    peak_price: float
    bottom_price: float
    reason: str
    
    def __str__(self) -> str:
        return (
            f"TrendMetrics(momentum={self.momentum_score:.2f}%, "
            f"continuation={self.continuation_score:.2f}, "
            f"peak=${self.peak_price:.4f}, bottom=${self.bottom_price:.4f})"
        )
    
    def __repr__(self) -> str:
        return self.__str__()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "momentum_score": self.momentum_score,
            "continuation_score": self.continuation_score,
            "peak_price": self.peak_price,
            "bottom_price": self.bottom_price,
            "reason": self.reason
        }


@dataclass
class QuoteData:
    """
    Quote data for a ticker including bid, ask, and derived metrics.
    
    Attributes:
        ticker: Stock ticker symbol
        bid: Highest price a buyer is willing to pay
        ask: Lowest price a seller is willing to accept
        mid_price: Average of bid and ask prices
        spread_percent: Bid-ask spread as percentage of mid price
    """
    ticker: str
    bid: float
    ask: float
    mid_price: float
    spread_percent: float
    
    def __str__(self) -> str:
        return (
            f"QuoteData({self.ticker}: bid=${self.bid:.4f}, "
            f"ask=${self.ask:.4f}, spread={self.spread_percent:.2f}%)"
        )
    
    def __repr__(self) -> str:
        return self.__str__()
    
    @classmethod
    def from_bid_ask(cls, ticker: str, bid: float, ask: float) -> 'QuoteData':
        """
        Create QuoteData from bid and ask prices.
        
        Args:
            ticker: Stock ticker symbol
            bid: Bid price
            ask: Ask price
            
        Returns:
            QuoteData instance with calculated mid_price and spread_percent
        """
        mid_price = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        spread = ask - bid
        spread_percent = (spread / mid_price * 100) if mid_price > 0 else 0.0
        
        return cls(
            ticker=ticker,
            bid=bid,
            ask=ask,
            mid_price=mid_price,
            spread_percent=spread_percent
        )


@dataclass
class ValidationResult:
    """
    Result of validating a ticker against entry criteria.
    
    Attributes:
        passed: Whether the ticker passed validation
        reason_long: Rejection reason for long entry (None if passed or not applicable)
        reason_short: Rejection reason for short entry (None if passed or not applicable)
    """
    passed: bool
    reason_long: Optional[str] = None
    reason_short: Optional[str] = None
    
    def __str__(self) -> str:
        if self.passed:
            return "ValidationResult(PASSED)"
        reasons = []
        if self.reason_long:
            reasons.append(f"long: {self.reason_long}")
        if self.reason_short:
            reasons.append(f"short: {self.reason_short}")
        return f"ValidationResult(FAILED - {', '.join(reasons)})"
    
    def __repr__(self) -> str:
        return self.__str__()


@dataclass
class RejectionRecord:
    """
    Record of a ticker rejection for storage in DynamoDB.
    
    Attributes:
        ticker: Stock ticker symbol
        indicator: Name of the trading indicator (e.g., "Penny Stocks")
        reason_not_to_enter_long: Rejection reason for long entry
        reason_not_to_enter_short: Rejection reason for short entry
        technical_indicators: Dictionary of technical metrics
        timestamp: ISO 8601 formatted timestamp
    """
    ticker: str
    indicator: str
    reason_not_to_enter_long: Optional[str] = None
    reason_not_to_enter_short: Optional[str] = None
    technical_indicators: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def __str__(self) -> str:
        return (
            f"RejectionRecord({self.ticker} @ {self.timestamp}: "
            f"long={bool(self.reason_not_to_enter_long)}, "
            f"short={bool(self.reason_not_to_enter_short)})"
        )
    
    def __repr__(self) -> str:
        return self.__str__()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for DynamoDB storage.
        
        Returns:
            Dictionary with all fields, excluding None values for optional fields
        """
        result = {
            "ticker": self.ticker,
            "indicator": self.indicator,
            "timestamp": self.timestamp
        }
        
        if self.reason_not_to_enter_long is not None:
            result["reason_not_to_enter_long"] = self.reason_not_to_enter_long
            
        if self.reason_not_to_enter_short is not None:
            result["reason_not_to_enter_short"] = self.reason_not_to_enter_short
            
        if self.technical_indicators is not None:
            result["technical_indicators"] = self.technical_indicators
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RejectionRecord':
        """
        Create RejectionRecord from dictionary.
        
        Args:
            data: Dictionary with rejection record fields
            
        Returns:
            RejectionRecord instance
        """
        return cls(
            ticker=data["ticker"],
            indicator=data["indicator"],
            reason_not_to_enter_long=data.get("reason_not_to_enter_long"),
            reason_not_to_enter_short=data.get("reason_not_to_enter_short"),
            technical_indicators=data.get("technical_indicators"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat())
        )
