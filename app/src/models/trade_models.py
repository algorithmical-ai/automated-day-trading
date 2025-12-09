"""
Data models for automated day trading application.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
from datetime import datetime, timezone


@dataclass
class ActiveTrade:
    """Represents an active trade position."""
    ticker: str
    action: str  # "buy_to_open" or "sell_to_open"
    indicator: str
    enter_price: float
    enter_reason: str
    technical_indicators_for_enter: Dict[str, Any]
    dynamic_stop_loss: float
    trailing_stop: float
    peak_profit_percent: float
    entry_score: Optional[float] = None  # For Deep Analyzer
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActiveTrade':
        """Create instance from DynamoDB data."""
        return cls(**data)


@dataclass
class CompletedTrade:
    """Represents a completed trade with profit/loss."""
    date: str  # yyyy-mm-dd
    ticker: str
    indicator: str
    action: str
    enter_price: float
    exit_price: float
    enter_timestamp: str  # ISO timestamp in UTC
    exit_timestamp: str  # ISO timestamp in UTC
    profit_or_loss: float
    enter_reason: str
    exit_reason: str
    technical_indicators_for_enter: Dict[str, Any]
    technical_indicators_for_exit: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompletedTrade':
        """Create instance from DynamoDB data."""
        return cls(**data)


@dataclass
class InactiveTicker:
    """Represents a ticker that was evaluated but not traded."""
    ticker: str
    indicator: str
    timestamp: str  # ISO timestamp in UTC
    reason_not_to_enter_long: str
    reason_not_to_enter_short: str
    technical_indicators: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InactiveTicker':
        """Create instance from DynamoDB data."""
        return cls(**data)


@dataclass
class ThresholdAdjustmentEvent:
    """Represents a threshold adjustment event from LLM analysis."""
    date: str  # yyyy-mm-dd
    indicator: str
    last_updated: str  # ISO timestamp in EST
    threshold_change: Dict[str, Any]  # Old and new values
    max_long_trades: int
    max_short_trades: int
    llm_response: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ThresholdAdjustmentEvent':
        """Create instance from DynamoDB data."""
        return cls(**data)


@dataclass
class MABStats:
    """Represents multi-armed bandit statistics for ticker selection."""
    indicator_ticker: str  # "indicator#ticker" (kept for backward compatibility)
    successes: int
    failures: int
    total_trades: int
    last_updated: str  # ISO timestamp in UTC
    excluded_until: Optional[str] = None  # ISO timestamp for temporary exclusion
    ticker: Optional[str] = None  # DynamoDB partition key
    indicator: Optional[str] = None  # DynamoDB sort key
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        data = asdict(self)
        # Ensure ticker and indicator are set from indicator_ticker if not already set
        if self.ticker is None and self.indicator_ticker:
            parts = self.indicator_ticker.split('#')
            if len(parts) == 2:
                data['indicator'] = parts[0]
                data['ticker'] = parts[1]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MABStats':
        """Create instance from DynamoDB data."""
        return cls(**data)
