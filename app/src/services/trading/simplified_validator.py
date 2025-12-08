"""
Simplified validator for penny stock trade entry decisions.

This module implements the streamlined validation logic that uses
momentum score as the primary driver for trend-based decisions.
"""

from app.src.models.simplified_validation import TrendMetrics, Quote, ValidationResult


class SimplifiedValidator:
    """Apply simplified validation rules for trade entry."""
    
    def __init__(self, max_bid_ask_spread: float = 2.0):
        """
        Initialize validator with configuration.
        
        Args:
            max_bid_ask_spread: Maximum allowed bid-ask spread percentage (default: 2.0)
        """
        self.max_bid_ask_spread = max_bid_ask_spread
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote: Quote
    ) -> ValidationResult:
        """
        Validate ticker for entry.
        
        Args:
            ticker: Stock ticker symbol
            trend_metrics: Calculated trend metrics
            quote: Current market quote
            
        Returns:
            ValidationResult with rejection reasons (empty strings for valid directions)
        """
        reason_long = ""
        reason_short = ""
        
        # Check for invalid bid/ask prices
        if quote.bid <= 0 or quote.ask <= 0:
            reason = "Invalid bid/ask prices"
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # Check bid-ask spread (applies to both directions)
        if quote.spread_percent > self.max_bid_ask_spread:
            reason = f"Bid-ask spread too wide: {quote.spread_percent:.2f}% > {self.max_bid_ask_spread:.1f}%"
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # Check momentum for long entry
        if trend_metrics.momentum_score < 0:
            reason_long = f"Recent bars show downward trend ({trend_metrics.momentum_score:.2f}%), not suitable for long entry"
        
        # Check momentum for short entry
        if trend_metrics.momentum_score > 0:
            reason_short = f"Recent bars show upward trend ({trend_metrics.momentum_score:.2f}%), not suitable for short entry"
        
        return ValidationResult(
            reason_not_to_enter_long=reason_long,
            reason_not_to_enter_short=reason_short
        )
