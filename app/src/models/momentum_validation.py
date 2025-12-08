"""
Data models for momentum trading validation.

This module contains the core data structures used in the momentum trading
validation system with symmetric rejection logic.
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any


@dataclass
class TechnicalIndicators:
    """Comprehensive technical analysis indicators."""
    
    # Momentum indicators
    rsi: float  # Relative Strength Index
    macd: List[float]  # [macd, signal, histogram]
    stoch: List[float]  # [%K, %D]
    cci: float  # Commodity Channel Index
    willr: float  # Williams %R
    roc: float  # Rate of Change
    
    # Trend indicators
    adx: float  # Average Directional Index
    ema_fast: float  # Fast EMA
    ema_slow: float  # Slow EMA
    
    # Volatility indicators
    bollinger: List[float]  # [upper, middle, lower]
    atr: float  # Average True Range
    
    # Volume indicators
    volume: int
    volume_sma: float
    obv: float  # On-Balance Volume
    mfi: float  # Money Flow Index
    ad: float  # Accumulation/Distribution
    
    # Price averages
    vwap: float  # Volume Weighted Average Price
    vwma: float  # Volume Weighted Moving Average
    wma: float  # Weighted Moving Average
    close_price: float
    
    # Time series data
    datetime_price: List[Tuple[str, float]]  # [(timestamp, price), ...]
    
    def __str__(self) -> str:
        return (
            f"TechnicalIndicators(RSI={self.rsi:.2f}, "
            f"MACD={self.macd[0]:.2f}, "
            f"ADX={self.adx:.2f}, "
            f"ATR={self.atr:.2f}, "
            f"volume={self.volume})"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'rsi': self.rsi,
            'macd': self.macd,
            'stoch': self.stoch,
            'cci': self.cci,
            'willr': self.willr,
            'roc': self.roc,
            'adx': self.adx,
            'ema_fast': self.ema_fast,
            'ema_slow': self.ema_slow,
            'bollinger': self.bollinger,
            'atr': self.atr,
            'volume': self.volume,
            'volume_sma': self.volume_sma,
            'obv': self.obv,
            'mfi': self.mfi,
            'ad': self.ad,
            'vwap': self.vwap,
            'vwma': self.vwma,
            'wma': self.wma,
            'close_price': self.close_price,
            'datetime_price': self.datetime_price
        }


@dataclass
class ValidationResult:
    """Result of validation checks with symmetric rejection support."""
    
    reason_not_to_enter_long: str  # Empty string if valid
    reason_not_to_enter_short: str  # Empty string if valid
    
    @property
    def is_valid(self) -> bool:
        """Check if entry is valid (both reasons empty)."""
        return (self.reason_not_to_enter_long == "" and 
                self.reason_not_to_enter_short == "")
    
    @property
    def is_symmetric_rejection(self) -> bool:
        """Check if rejection is symmetric (both reasons identical)."""
        return (self.reason_not_to_enter_long == 
                self.reason_not_to_enter_short)
    
    def __str__(self) -> str:
        if self.is_valid:
            return "ValidationResult(VALID for both directions)"
        elif self.is_symmetric_rejection:
            return f"ValidationResult(REJECTED: {self.reason_not_to_enter_long})"
        else:
            return (
                f"ValidationResult(long={self.reason_not_to_enter_long}, "
                f"short={self.reason_not_to_enter_short})"
            )


@dataclass
class MomentumEvaluationRecord:
    """Complete evaluation record for database storage."""
    
    ticker: str
    indicator: str  # "Momentum Trading"
    reason_not_to_enter_long: str
    reason_not_to_enter_short: str
    technical_indicators: Dict[str, Any]
    timestamp: str  # ISO 8601 format
    
    def __str__(self) -> str:
        return (
            f"MomentumEvaluationRecord({self.ticker}, "
            f"indicator={self.indicator}, "
            f"timestamp={self.timestamp})"
        )
