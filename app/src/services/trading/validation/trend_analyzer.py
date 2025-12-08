"""
Trend analysis component for penny stock validation.

This module calculates trend metrics from price bars including momentum score,
continuation score, and price extremes.
"""

from typing import List, Dict, Any
from app.src.services.trading.validation.models import TrendMetrics


class TrendAnalyzer:
    """
    Analyzes price trends from historical bar data.
    
    Calculates momentum, continuation, and identifies price extremes
    to support entry validation decisions.
    """
    
    # Configuration
    RECENT_BARS_COUNT = 5  # Number of recent bars to analyze
    MOMENTUM_OVERALL_WEIGHT = 0.7  # Weight for overall price change
    MOMENTUM_CONSISTENCY_WEIGHT = 0.3  # Weight for consistency score
    MIN_TREND_STRENGTH = 0.7  # Minimum proportion of moves in same direction
    TREND_STRENGTH_PENALTY = 0.3  # Multiplier when trend strength is weak
    
    @classmethod
    def calculate_trend_metrics(cls, bars: List[Dict[str, Any]]) -> TrendMetrics:
        """
        Calculate all trend-related metrics from price bars.
        
        Algorithm:
        1. Extract last 5 bars (or fewer if insufficient data)
        2. Calculate overall price change: (last_price - first_price) / first_price * 100
        3. Calculate consistency: (up_moves - down_moves) / total_moves * 100
        4. Momentum = 70% overall change + 30% consistency
        5. Apply penalty if trend strength < 70% (multiply momentum by 0.3)
        6. Calculate continuation from last 2-3 bars in trend direction
        
        Args:
            bars: List of price bar dictionaries with 'c' (close) prices
            
        Returns:
            TrendMetrics containing:
            - momentum_score: float (percentage, positive=up, negative=down)
            - continuation_score: float (0.0-1.0)
            - peak_price: float
            - bottom_price: float
            - reason: str (description of calculation)
        """
        # Handle insufficient data
        if not bars or len(bars) < 3:
            return TrendMetrics(
                momentum_score=0.0,
                continuation_score=0.0,
                peak_price=0.0,
                bottom_price=0.0,
                reason="Insufficient bars data"
            )
        
        # Extract recent bars
        recent_bars = (
            bars[-cls.RECENT_BARS_COUNT:]
            if len(bars) >= cls.RECENT_BARS_COUNT
            else bars
        )
        
        # Extract close prices
        prices = []
        for bar in recent_bars:
            try:
                close_price = bar.get("c")
                if close_price is not None:
                    prices.append(float(close_price))
            except (ValueError, TypeError):
                continue
        
        # Validate we have enough valid prices
        if len(prices) < 3:
            return TrendMetrics(
                momentum_score=0.0,
                continuation_score=0.0,
                peak_price=0.0,
                bottom_price=0.0,
                reason="Insufficient valid prices"
            )
        
        # Calculate peak and bottom prices
        peak_price = max(prices)
        bottom_price = min(prices)
        
        # Calculate overall price change
        first_price = prices[0]
        last_price = prices[-1]
        
        overall_change_percent = (
            ((last_price - first_price) / first_price) * 100
            if first_price > 0
            else 0.0
        )
        
        # Calculate price changes between consecutive bars
        price_changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        
        # Count up and down moves
        up_moves = sum(1 for change in price_changes if change > 0)
        down_moves = sum(1 for change in price_changes if change < 0)
        
        # Calculate consistency score
        consistency_score = (
            ((up_moves - down_moves) / len(price_changes)) * 100
            if price_changes
            else 0.0
        )
        
        # Calculate momentum score (weighted combination)
        momentum_score = (
            cls.MOMENTUM_OVERALL_WEIGHT * overall_change_percent +
            cls.MOMENTUM_CONSISTENCY_WEIGHT * consistency_score
        )
        
        # Calculate trend strength (proportion of moves in dominant direction)
        trend_strength = (
            max(up_moves, down_moves) / len(price_changes)
            if price_changes
            else 0.0
        )
        
        # Apply penalty if trend is not strong enough
        if trend_strength < cls.MIN_TREND_STRENGTH:
            momentum_score *= cls.TREND_STRENGTH_PENALTY
        
        # Calculate continuation score (how much trend continues in recent bars)
        recent_continuation = cls._calculate_continuation(
            prices, momentum_score
        )
        
        # Build reason string
        reason = (
            f"Recent trend ({len(recent_bars)} bars): "
            f"{overall_change_percent:.2f}% change, "
            f"{up_moves} up/{down_moves} down moves, "
            f"peak=${peak_price:.4f}, bottom=${bottom_price:.4f}, "
            f"continuation={recent_continuation:.2f}"
        )
        
        return TrendMetrics(
            momentum_score=momentum_score,
            continuation_score=recent_continuation,
            peak_price=peak_price,
            bottom_price=bottom_price,
            reason=reason
        )
    
    @classmethod
    def _calculate_continuation(cls, prices: List[float], momentum_score: float) -> float:
        """
        Calculate continuation score from recent price movements.
        
        Measures the proportion of recent price changes (last 2-3 bars)
        that continue in the overall trend direction.
        
        Args:
            prices: List of prices
            momentum_score: Overall momentum score (determines trend direction)
            
        Returns:
            Continuation score (0.0-1.0)
        """
        if len(prices) < 3:
            return 0.0
        
        # Get last 3 prices for continuation analysis
        last_3_prices = prices[-3:]
        
        if len(last_3_prices) < 2:
            return 0.0
        
        # Calculate recent price changes
        recent_changes = [
            last_3_prices[i] - last_3_prices[i - 1]
            for i in range(1, len(last_3_prices))
        ]
        
        if not recent_changes:
            return 0.0
        
        # Determine if trend is upward or downward
        if momentum_score > 0:
            # Upward trend: count positive changes
            continuation = (
                sum(1 for c in recent_changes if c > 0) / len(recent_changes)
            )
        else:
            # Downward trend: count negative changes
            continuation = (
                sum(1 for c in recent_changes if c < 0) / len(recent_changes)
            )
        
        return continuation
    
    @classmethod
    def safe_divide(cls, numerator: float, denominator: float, default: float = 0.0) -> float:
        """
        Safely divide two numbers, returning default if denominator is zero.
        
        Args:
            numerator: Numerator value
            denominator: Denominator value
            default: Value to return if denominator is zero
            
        Returns:
            Result of division or default value
        """
        if denominator == 0:
            return default
        return numerator / denominator
    
    @classmethod
    def calculate_price_extreme_percentage(
        cls, current_price: float, extreme_price: float
    ) -> float:
        """
        Calculate percentage difference between current price and extreme (peak/bottom).
        
        Formula: ((current_price - extreme_price) / extreme_price) * 100
        
        Args:
            current_price: Current price
            extreme_price: Peak or bottom price
            
        Returns:
            Percentage difference
        """
        if extreme_price == 0:
            return 0.0
        return ((current_price - extreme_price) / extreme_price) * 100
