"""
Momentum validator for trade entry decisions.

This module implements symmetric validation logic where all rejections
apply equally to both long and short positions.
"""

from typing import Tuple
from app.src.models.momentum_validation import TechnicalIndicators, ValidationResult


class MomentumValidator:
    """Apply symmetric validation rules for momentum trading."""
    
    def __init__(
        self,
        min_price: float = 0.10,
        min_volume: int = 500,
        min_volume_ratio: float = 1.5,
        max_atr_percent: float = 5.0,
        warrant_suffixes: Tuple[str, ...] = ('W', 'R', 'RT', 'WS')
    ):
        """
        Initialize validator with configuration.
        
        Args:
            min_price: Minimum price threshold (default: $0.10)
            min_volume: Minimum volume threshold (default: 500)
            min_volume_ratio: Minimum volume/SMA ratio (default: 1.5)
            max_atr_percent: Maximum ATR percentage (default: 5.0%)
            warrant_suffixes: Tuple of warrant/derivative suffixes to exclude
        """
        self.min_price = min_price
        self.min_volume = min_volume
        self.min_volume_ratio = min_volume_ratio
        self.max_atr_percent = max_atr_percent
        self.warrant_suffixes = warrant_suffixes
    
    def validate(
        self,
        ticker: str,
        technical_indicators: TechnicalIndicators
    ) -> ValidationResult:
        """
        Validate ticker for entry using symmetric rules.
        
        All validation rules apply equally to both long and short positions.
        If any rule fails, both directions are rejected with identical reasons.
        
        Args:
            ticker: Stock ticker symbol
            technical_indicators: Calculated technical indicators
            
        Returns:
            ValidationResult with symmetric rejection (both reasons identical)
        """
        # Check 1: Security type (warrant/derivative filter)
        if self._is_warrant_or_derivative(ticker):
            reason = f"Excluded: {ticker} is a warrant/option (ends with W/R/RT/etc)"
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # Check 2: Price floor
        if technical_indicators.close_price < self.min_price:
            reason = (
                f"Price too low: ${technical_indicators.close_price:.2f} < "
                f"${self.min_price:.2f} minimum (too risky)"
            )
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # Check 3: Absolute volume
        if technical_indicators.volume < self.min_volume:
            reason = (
                f"Volume too low: {technical_indicators.volume} < "
                f"{self.min_volume} minimum"
            )
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # Check 4: Volume ratio
        if technical_indicators.volume_sma <= 0:
            reason = "Invalid volume SMA"
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        volume_ratio = technical_indicators.volume / technical_indicators.volume_sma
        if volume_ratio < self.min_volume_ratio:
            reason = (
                f"Volume ratio too low: {volume_ratio:.1f}x < "
                f"{self.min_volume_ratio:.1f}x SMA "
                f"(volume: {technical_indicators.volume:,}, "
                f"SMA: {technical_indicators.volume_sma:,.0f})"
            )
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # Check 5: Volatility (ATR percentage)
        if technical_indicators.close_price <= 0:
            reason = "Invalid price for ATR calculation"
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        atr_percent = (technical_indicators.atr / technical_indicators.close_price) * 100
        if atr_percent > self.max_atr_percent:
            reason = (
                f"Too volatile: ATR: {atr_percent:.1f}% "
                f"(exceeds {self.max_atr_percent:.1f}% limit)"
            )
            return ValidationResult(
                reason_not_to_enter_long=reason,
                reason_not_to_enter_short=reason
            )
        
        # All checks passed - valid for both directions
        return ValidationResult(
            reason_not_to_enter_long="",
            reason_not_to_enter_short=""
        )
    
    def _is_warrant_or_derivative(self, ticker: str) -> bool:
        """
        Check if ticker is a warrant or derivative security.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            True if ticker ends with warrant/derivative suffix
        """
        ticker_upper = ticker.upper()
        return any(ticker_upper.endswith(suffix) for suffix in self.warrant_suffixes)
