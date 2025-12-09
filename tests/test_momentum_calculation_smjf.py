"""
Test momentum calculation with SMJF data from MCP tool
"""

import pytest
from app.src.services.trading.momentum_indicator import MomentumIndicator


class TestMomentumCalculationSMJF:
    """Test momentum calculation with real SMJF data"""

    def test_momentum_calculation_with_upward_trend(self):
        """Test momentum calculation with SMJF data showing upward trend"""
        # Create datetime_price dict with SMJF data (4.4 to 4.87)
        # Simulating 200 entries with gradual increase
        datetime_price = {}
        
        # Generate 200 price points from 4.4 to 4.87
        start_price = 4.4
        end_price = 4.87
        num_points = 200
        
        for i in range(num_points):
            # Linear interpolation from start to end
            price = start_price + (end_price - start_price) * (i / (num_points - 1))
            # Create proper ISO format timestamps
            day = 5 + (i // 100)
            hour = 9 + ((i % 100) // 4)
            minute = 34 + ((i % 4) * 15)
            timestamp = f"2025-12-{day:02d}T{hour:02d}:{minute:02d}:00-05:00"
            datetime_price[timestamp] = price
        
        # Calculate momentum
        momentum_score, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # With upward trend from 4.4 to 4.87, momentum should be positive
        # Expected change: (4.87 - 4.4) / 4.4 * 100 ≈ 10.68%
        assert momentum_score > 0, f"Expected positive momentum, got {momentum_score:.2f}% with reason: {reason}"
        assert momentum_score > 3.0, f"Expected momentum > 3%, got {momentum_score:.2f}% with reason: {reason}"
        
        print(f"✓ Momentum calculation correct: {momentum_score:.2f}% (reason: {reason})")

    def test_momentum_calculation_with_exact_smjf_prices(self):
        """Test momentum calculation with exact SMJF price progression"""
        # Create datetime_price dict with exact progression from 4.4 to 4.87
        datetime_price = {}
        
        # Generate prices with small increments using proper ISO timestamps
        start = 4.4
        end = 4.87
        for i in range(200):
            price = start + (end - start) * (i / 199)
            # Create proper ISO format timestamps
            day = 5 + (i // 100)
            hour = 9 + ((i % 100) // 4)
            minute = 34 + ((i % 4) * 15)
            timestamp = f"2025-12-{day:02d}T{hour:02d}:{minute:02d}:00-05:00"
            datetime_price[timestamp] = price
        
        # Calculate momentum
        momentum_score, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Verify momentum is positive
        assert momentum_score > 0, f"Expected positive momentum, got {momentum_score:.2f}%. Reason: {reason}"
        
        # Verify momentum is reasonable (between 3% and 15% for this trend)
        assert 3.0 < momentum_score < 15.0, f"Expected momentum between 3-15%, got {momentum_score:.2f}%"
        
        print(f"✓ Exact SMJF momentum: {momentum_score:.2f}%")

    def test_momentum_calculation_with_dict_format(self):
        """Test that momentum calculation works with dict format"""
        # Simple dict with 10 prices showing upward trend
        datetime_price = {
            "2025-12-05T09:34:00-05:00": 4.4,
            "2025-12-05T09:35:00-05:00": 4.42,
            "2025-12-05T09:36:00-05:00": 4.44,
            "2025-12-05T09:37:00-05:00": 4.46,
            "2025-12-05T09:38:00-05:00": 4.48,
            "2025-12-05T09:39:00-05:00": 4.50,
            "2025-12-05T09:40:00-05:00": 4.65,
            "2025-12-05T09:41:00-05:00": 4.75,
            "2025-12-05T09:42:00-05:00": 4.80,
            "2025-12-05T09:43:00-05:00": 4.87,
        }
        
        momentum_score, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should have positive momentum
        assert momentum_score > 0, f"Expected positive momentum, got {momentum_score:.2f}%"
        
        print(f"✓ Dict format momentum: {momentum_score:.2f}%")

    def test_momentum_calculation_not_zero_with_valid_data(self):
        """Test that momentum is NOT zero when valid price data exists"""
        # Create datetime_price with clear upward trend
        datetime_price = {}
        for i in range(100):
            price = 4.4 + (i / 100) * 0.47  # From 4.4 to 4.87
            datetime_price[f"2025-12-05T{9 + i // 60}:{34 + (i % 60)}:00-05:00"] = price
        
        momentum_score, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Momentum should NOT be zero
        assert momentum_score != 0.0, f"Momentum should not be zero with valid upward trend data. Reason: {reason}"
        
        # Momentum should be positive for upward trend
        assert momentum_score > 0, f"Momentum should be positive for upward trend, got {momentum_score:.2f}%"
        
        print(f"✓ Momentum is not zero: {momentum_score:.2f}%")
