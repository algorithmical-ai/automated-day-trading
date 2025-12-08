"""
Monitoring and statistics for simplified validation.

This module provides utilities for tracking and logging validation
statistics during entry cycles.
"""

from typing import Dict, List
from loguru import logger


class ValidationMonitor:
    """Monitor and track validation statistics."""
    
    def __init__(self):
        """Initialize monitoring statistics."""
        self.reset()
    
    def reset(self):
        """Reset all statistics."""
        self.total_evaluated = 0
        self.valid_for_long = 0
        self.valid_for_short = 0
        self.valid_for_both = 0
        self.rejected_spread = 0
        self.rejected_momentum = 0
        self.momentum_scores: List[float] = []
    
    def record_evaluation(
        self,
        is_valid_long: bool,
        is_valid_short: bool,
        momentum_score: float,
        rejection_reason_long: str = "",
        rejection_reason_short: str = ""
    ):
        """
        Record a ticker evaluation.
        
        Args:
            is_valid_long: Whether long entry is valid
            is_valid_short: Whether short entry is valid
            momentum_score: Calculated momentum score
            rejection_reason_long: Rejection reason for long (if any)
            rejection_reason_short: Rejection reason for short (if any)
        """
        self.total_evaluated += 1
        self.momentum_scores.append(momentum_score)
        
        if is_valid_long:
            self.valid_for_long += 1
        if is_valid_short:
            self.valid_for_short += 1
        if is_valid_long and is_valid_short:
            self.valid_for_both += 1
        
        # Track rejection reasons
        if "spread" in rejection_reason_long.lower() or "spread" in rejection_reason_short.lower():
            self.rejected_spread += 1
        if "trend" in rejection_reason_long.lower() or "trend" in rejection_reason_short.lower():
            self.rejected_momentum += 1
    
    def log_cycle_summary(self):
        """Log summary statistics for the cycle."""
        if self.total_evaluated == 0:
            logger.info("No tickers evaluated in this cycle")
            return
        
        # Calculate momentum statistics
        if self.momentum_scores:
            avg_momentum = sum(self.momentum_scores) / len(self.momentum_scores)
            max_momentum = max(self.momentum_scores)
            min_momentum = min(self.momentum_scores)
            positive_momentum = sum(1 for m in self.momentum_scores if m > 0)
            negative_momentum = sum(1 for m in self.momentum_scores if m < 0)
        else:
            avg_momentum = 0.0
            max_momentum = 0.0
            min_momentum = 0.0
            positive_momentum = 0
            negative_momentum = 0
        
        logger.info(
            f"📊 Validation Cycle Summary: "
            f"{self.total_evaluated} tickers evaluated, "
            f"{self.valid_for_long} valid for LONG ({self.valid_for_long/self.total_evaluated*100:.1f}%), "
            f"{self.valid_for_short} valid for SHORT ({self.valid_for_short/self.total_evaluated*100:.1f}%), "
            f"{self.valid_for_both} valid for BOTH ({self.valid_for_both/self.total_evaluated*100:.1f}%)",
            extra={
                "operation": "validation_cycle_summary",
                "total_evaluated": self.total_evaluated,
                "valid_for_long": self.valid_for_long,
                "valid_for_short": self.valid_for_short,
                "valid_for_both": self.valid_for_both,
                "rejected_spread": self.rejected_spread,
                "rejected_momentum": self.rejected_momentum
            }
        )
        
        logger.info(
            f"📈 Momentum Distribution: "
            f"avg={avg_momentum:.2f}, "
            f"range=[{min_momentum:.2f}, {max_momentum:.2f}], "
            f"{positive_momentum} positive, {negative_momentum} negative",
            extra={
                "operation": "momentum_distribution",
                "avg_momentum": avg_momentum,
                "max_momentum": max_momentum,
                "min_momentum": min_momentum,
                "positive_count": positive_momentum,
                "negative_count": negative_momentum
            }
        )
        
        if self.rejected_spread > 0 or self.rejected_momentum > 0:
            logger.debug(
                f"Rejection breakdown: "
                f"{self.rejected_spread} spread, "
                f"{self.rejected_momentum} momentum"
            )
