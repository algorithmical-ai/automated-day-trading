"""
Validation rules for penny stock entry decisions.

This module defines the abstract ValidationRule interface and concrete
implementations for various validation checks.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.src.services.trading.validation.models import (
    TrendMetrics,
    QuoteData,
    ValidationResult
)


class ValidationRule(ABC):
    """
    Abstract base class for validation rules.
    
    Each rule validates a ticker against specific entry criteria and returns
    a ValidationResult indicating whether the ticker passed and reasons for rejection.
    """
    
    @abstractmethod
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """
        Validate a ticker against this rule.
        
        Args:
            ticker: Stock ticker symbol
            trend_metrics: Calculated trend metrics
            quote_data: Current quote data
            bars: Historical price bars
            
        Returns:
            ValidationResult containing:
            - passed: bool
            - reason_long: Optional[str] (rejection reason for long entry)
            - reason_short: Optional[str] (rejection reason for short entry)
        """
        pass


class DataQualityRule(ValidationRule):
    """
    Validates data quality requirements.
    
    Checks:
    - Sufficient number of bars available
    - Valid market data present
    """
    
    def __init__(self, required_bars: int = 5):
        """
        Initialize data quality rule.
        
        Args:
            required_bars: Minimum number of bars required
        """
        self.required_bars = required_bars
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Validate data quality."""
        # Check if bars are present
        if not bars:
            reason = "No market data response"
            return ValidationResult(
                passed=False,
                reason_long=reason,
                reason_short=reason
            )
        
        # Check if we have enough bars
        if len(bars) < self.required_bars:
            reason = f"Insufficient bars data (need {self.required_bars}, got {len(bars)})"
            return ValidationResult(
                passed=False,
                reason_long=reason,
                reason_short=reason
            )
        
        return ValidationResult(passed=True)


class LiquidityRule(ValidationRule):
    """
    Validates liquidity through bid-ask spread analysis.
    
    Checks:
    - Bid and ask prices are valid (positive)
    - Bid-ask spread is within acceptable range
    """
    
    def __init__(self, max_spread_percent: float = 2.0):
        """
        Initialize liquidity rule.
        
        Args:
            max_spread_percent: Maximum acceptable bid-ask spread percentage
        """
        self.max_spread_percent = max_spread_percent
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Validate liquidity."""
        # Check for valid bid/ask
        if quote_data.bid <= 0 or quote_data.ask <= 0:
            reason = f"Invalid bid/ask: bid={quote_data.bid}, ask={quote_data.ask}"
            return ValidationResult(
                passed=False,
                reason_long=reason,
                reason_short=reason
            )
        
        # Check bid-ask spread
        if quote_data.spread_percent > self.max_spread_percent:
            reason = (
                f"Bid-ask spread too wide: {quote_data.spread_percent:.2f}% > "
                f"{self.max_spread_percent}%"
            )
            return ValidationResult(
                passed=False,
                reason_long=reason,
                reason_short=reason
            )
        
        return ValidationResult(passed=True)


class TrendDirectionRule(ValidationRule):
    """
    Validates trend direction aligns with entry direction.
    
    Checks:
    - Upward trends block short entries
    - Downward trends block long entries
    """
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Validate trend direction."""
        momentum = trend_metrics.momentum_score
        
        # Determine rejection reasons based on trend direction
        if momentum < 0:
            # Downward trend - reject long entry
            reason_long = f"Recent bars show downward trend ({momentum:.2f}%), not suitable for long entry"
            return ValidationResult(
                passed=False,
                reason_long=reason_long,
                reason_short=None  # Short entry may still be valid
            )
        elif momentum > 0:
            # Upward trend - reject short entry
            reason_short = f"Recent bars show upward trend ({momentum:.2f}%), not suitable for short entry"
            return ValidationResult(
                passed=False,
                reason_long=None,  # Long entry may still be valid
                reason_short=reason_short
            )
        else:
            # No clear trend
            return ValidationResult(passed=True)


class ContinuationRule(ValidationRule):
    """
    Validates trend continuation strength.
    
    Checks:
    - Trend is continuing (not reversing)
    - Continuation score meets minimum threshold
    """
    
    def __init__(self, min_continuation: float = 0.7):
        """
        Initialize continuation rule.
        
        Args:
            min_continuation: Minimum continuation score required
        """
        self.min_continuation = min_continuation
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Validate trend continuation."""
        momentum = trend_metrics.momentum_score
        continuation = trend_metrics.continuation_score
        
        # Check if continuation is weak
        if continuation < self.min_continuation:
            if momentum > 0:
                # Upward trend with weak continuation - reject long
                reason_long = (
                    f"Recent bars show upward trend but trend is not continuing strongly "
                    f"(continuation={continuation:.2f} < {self.min_continuation}) - "
                    f"likely at peak, avoid long entry"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=reason_long,
                    reason_short=None
                )
            elif momentum < 0:
                # Downward trend with weak continuation - reject short
                reason_short = (
                    f"Recent bars show downward trend but trend is not continuing strongly "
                    f"(continuation={continuation:.2f} < {self.min_continuation}) - "
                    f"likely at bottom, avoid short entry"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=None,
                    reason_short=reason_short
                )
        
        return ValidationResult(passed=True)


class PriceExtremeRule(ValidationRule):
    """
    Validates price is not at extreme levels (peak/bottom).
    
    Checks:
    - Current price is not too close to peak (for long entries)
    - Current price is not too close to bottom (for short entries)
    """
    
    def __init__(self, extreme_threshold_percent: float = 1.0):
        """
        Initialize price extreme rule.
        
        Args:
            extreme_threshold_percent: Maximum distance from extreme as percentage
        """
        self.extreme_threshold_percent = extreme_threshold_percent
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Validate price extremes."""
        momentum = trend_metrics.momentum_score
        current_price = quote_data.mid_price
        peak_price = trend_metrics.peak_price
        bottom_price = trend_metrics.bottom_price
        
        # Check if we have valid prices
        if current_price <= 0 or peak_price <= 0 or bottom_price <= 0:
            return ValidationResult(passed=True)
        
        if momentum > 0:
            # Upward trend - check if at peak
            price_vs_peak = ((current_price - peak_price) / peak_price) * 100
            if price_vs_peak > -self.extreme_threshold_percent:
                reason_long = (
                    f"Current price ${current_price:.4f} is at/near peak ${peak_price:.4f} "
                    f"(diff: {price_vs_peak:.2f}%) - likely at peak, avoid long entry"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=reason_long,
                    reason_short=None
                )
        elif momentum < 0:
            # Downward trend - check if at bottom
            price_vs_bottom = ((current_price - bottom_price) / bottom_price) * 100
            if price_vs_bottom < self.extreme_threshold_percent:
                reason_short = (
                    f"Current price ${current_price:.4f} is at/near bottom ${bottom_price:.4f} "
                    f"(diff: {price_vs_bottom:.2f}%) - likely at bottom, avoid short entry"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=None,
                    reason_short=reason_short
                )
        
        return ValidationResult(passed=True)


class MomentumThresholdRule(ValidationRule):
    """
    Validates momentum is within acceptable range.
    
    Checks:
    - Momentum is above minimum threshold (trend strong enough)
    - Momentum is below maximum threshold (not overextended)
    """
    
    def __init__(self, min_momentum: float = 3.0, max_momentum: float = 10.0):
        """
        Initialize momentum threshold rule.
        
        Args:
            min_momentum: Minimum momentum percentage required
            max_momentum: Maximum momentum percentage allowed
        """
        self.min_momentum = min_momentum
        self.max_momentum = max_momentum
    
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict[str, Any]]
    ) -> ValidationResult:
        """Validate momentum thresholds."""
        momentum = trend_metrics.momentum_score
        abs_momentum = abs(momentum)
        
        # Check if momentum is too weak
        if abs_momentum < self.min_momentum:
            if momentum > 0:
                reason_long = (
                    f"Recent bars show weak upward trend: {momentum:.2f}% < "
                    f"minimum threshold {self.min_momentum}% (trend not strong enough for long entry)"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=reason_long,
                    reason_short=None
                )
            elif momentum < 0:
                reason_short = (
                    f"Recent bars show weak downward trend: {momentum:.2f}% < "
                    f"minimum threshold {self.min_momentum}% (trend not strong enough for short entry)"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=None,
                    reason_short=reason_short
                )
        
        # Check if momentum is too strong (overextended)
        if abs_momentum > self.max_momentum:
            if momentum > 0:
                reason_long = (
                    f"Recent bars show excessive upward trend: {momentum:.2f}% > "
                    f"maximum threshold {self.max_momentum}% (likely at peak, avoid long entry)"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=reason_long,
                    reason_short=None
                )
            elif momentum < 0:
                reason_short = (
                    f"Recent bars show excessive downward trend: {momentum:.2f}% > "
                    f"maximum threshold {self.max_momentum}% (likely at bottom, avoid short entry)"
                )
                return ValidationResult(
                    passed=False,
                    reason_long=None,
                    reason_short=reason_short
                )
        
        return ValidationResult(passed=True)
