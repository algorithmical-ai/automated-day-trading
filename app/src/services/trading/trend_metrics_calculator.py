"""
Trend metrics calculator for simplified penny stock validation.

This module calculates momentum score, continuation score, peak/bottom prices,
and generates human-readable trend descriptions from price bar data.
"""

from typing import List, Dict
from app.src.models.simplified_validation import TrendMetrics


class TrendMetricsCalculator:
    """Calculate trend-related metrics from price bars."""
    
    @staticmethod
    def calculate_metrics(bars: List[Dict]) -> TrendMetrics:
        """
        Calculate trend metrics from price bars.
        
        Args:
            bars: List of price bar dictionaries with 'c' (close) prices
            
        Returns:
            TrendMetrics containing momentum_score, continuation_score,
            peak_price, bottom_price, and human-readable reason
        """
        # Filter out invalid prices (null, negative, zero)
        valid_bars = [
            bar for bar in bars 
            if bar.get('c') is not None and bar.get('c') > 0
        ]
        
        # Handle empty bars after filtering
        if not valid_bars:
            return TrendMetrics(
                momentum_score=0.0,
                continuation_score=0.0,
                peak_price=0.0,
                bottom_price=0.0,
                reason="No valid price data available"
            )
        
        # Use last 5 bars (or fewer if insufficient)
        recent_bars = valid_bars[-5:] if len(valid_bars) >= 5 else valid_bars
        prices = [bar['c'] for bar in recent_bars]
        
        # Handle single bar
        if len(prices) == 1:
            price = prices[0]
            return TrendMetrics(
                momentum_score=0.0,
                continuation_score=0.0,
                peak_price=price,
                bottom_price=price,
                reason=f"Recent trend (1 bars): 0.00% change, 0 up/0 down moves, peak=${price:.2f}, bottom=${price:.2f}, continuation=0.0"
            )
        
        # Calculate peak and bottom
        peak_price = max(prices)
        bottom_price = min(prices)

        
        # Calculate overall price change percentage
        first_price = prices[0]
        last_price = prices[-1]
        
        if first_price == 0:
            price_change_pct = 0.0
        else:
            price_change_pct = ((last_price - first_price) / first_price) * 100
        
        # Count up and down moves
        up_moves = 0
        down_moves = 0
        
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                up_moves += 1
            elif prices[i] < prices[i-1]:
                down_moves += 1
            # Equal prices don't count as moves
        
        total_moves = up_moves + down_moves
        
        # Handle all prices identical
        if total_moves == 0:
            return TrendMetrics(
                momentum_score=0.0,
                continuation_score=0.0,
                peak_price=peak_price,
                bottom_price=bottom_price,
                reason=f"Recent trend ({len(prices)} bars): 0.00% change, 0 up/0 down moves, peak=${peak_price:.2f}, bottom=${bottom_price:.2f}, continuation=0.0"
            )
        
        # Determine trend direction and calculate continuation
        if price_change_pct > 0:
            # Upward trend - continuation is proportion of up moves
            continuation_score = up_moves / total_moves if total_moves > 0 else 0.0
        elif price_change_pct < 0:
            # Downward trend - continuation is proportion of down moves
            continuation_score = down_moves / total_moves if total_moves > 0 else 0.0
        else:
            # No overall change - use the dominant direction
            if up_moves > down_moves:
                continuation_score = up_moves / total_moves
            elif down_moves > up_moves:
                continuation_score = down_moves / total_moves
            else:
                continuation_score = 0.5
        
        # Calculate momentum score with amplification
        # Base momentum is the price change percentage
        # Amplify based on move consistency
        consistency_factor = (up_moves - down_moves) / total_moves if total_moves > 0 else 0.0
        
        # Amplification: more consistent moves = higher amplification
        # Use continuation score as amplification factor
        amplification = 1.0 + (continuation_score * 2.0)  # Range: 1.0 to 3.0
        
        momentum_score = price_change_pct * amplification
        
        # Generate human-readable reason string
        reason = (
            f"Recent trend ({len(prices)} bars): {price_change_pct:.2f}% change, "
            f"{up_moves} up/{down_moves} down moves, "
            f"peak=${peak_price:.2f}, bottom=${bottom_price:.2f}, "
            f"continuation={continuation_score:.1f}"
        )
        
        return TrendMetrics(
            momentum_score=momentum_score,
            continuation_score=continuation_score,
            peak_price=peak_price,
            bottom_price=bottom_price,
            reason=reason
        )
