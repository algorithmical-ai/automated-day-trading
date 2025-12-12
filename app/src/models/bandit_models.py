"""
Data models for the Bandit Decision Service.
Used by the can_proceed() MCP tool for intelligent trade entry decisions.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
from datetime import datetime
from zoneinfo import ZoneInfo


def _get_est_now() -> str:
    """Get current timestamp in EST timezone."""
    est_tz = ZoneInfo('America/New_York')
    return datetime.now(est_tz).isoformat()


def _get_est_date() -> str:
    """Get current date in EST timezone (YYYY-MM-DD)."""
    est_tz = ZoneInfo('America/New_York')
    return datetime.now(est_tz).strftime('%Y-%m-%d')


@dataclass
class IntradayStats:
    """
    Statistics for a ticker's intraday performance.
    
    Used to track success/failure counts for the current trading day
    to inform bandit algorithm decisions.
    """
    ticker: str
    indicator: str
    date: str  # YYYY-MM-DD in EST
    successes: int
    failures: int
    total_decisions: int
    last_updated: str  # ISO timestamp in EST
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntradayStats':
        """Create instance from DynamoDB item."""
        return cls(
            ticker=data.get('ticker', ''),
            indicator=data.get('indicator', ''),
            date=data.get('date', ''),
            successes=int(data.get('successes', 0)),
            failures=int(data.get('failures', 0)),
            total_decisions=int(data.get('total_decisions', 0)),
            last_updated=data.get('last_updated', '')
        )
    
    @classmethod
    def create_neutral(cls, ticker: str, indicator: str) -> 'IntradayStats':
        """Create neutral stats for a new ticker (exploration mode)."""
        return cls(
            ticker=ticker,
            indicator=indicator,
            date=_get_est_date(),
            successes=0,
            failures=0,
            total_decisions=0,
            last_updated=_get_est_now()
        )


@dataclass
class BanditDecision:
    """
    Result of a bandit decision from can_proceed().
    
    Contains the decision, reasoning, and all relevant context
    for logging and debugging purposes.
    """
    decision: bool
    ticker: str
    indicator: str
    action: str
    reason: str
    intraday_stats: IntradayStats
    confidence_score: float
    current_price: float
    timestamp: str = field(default_factory=_get_est_now)
    
    def to_response_dict(self) -> Dict[str, Any]:
        """Convert to MCP response format."""
        return {
            "decision": self.decision,
            "ticker": self.ticker,
            "indicator": self.indicator,
            "action": self.action,
            "reason": self.reason,
            "confidence_score": self.confidence_score,
            "current_price": self.current_price,
            "timestamp": self.timestamp,
            "intraday_stats": {
                "date": self.intraday_stats.date,
                "successes": self.intraday_stats.successes,
                "failures": self.intraday_stats.failures,
                "total_decisions": self.intraday_stats.total_decisions
            }
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        # Flatten intraday_stats for storage
        if isinstance(data.get('intraday_stats'), dict):
            stats = data.pop('intraday_stats')
            data['stats_date'] = stats.get('date', '')
            data['stats_successes'] = stats.get('successes', 0)
            data['stats_failures'] = stats.get('failures', 0)
            data['stats_total_decisions'] = stats.get('total_decisions', 0)
        return data
