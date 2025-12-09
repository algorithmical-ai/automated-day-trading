"""
Test momentum indicator datetime_price fix

This test verifies that the momentum indicator correctly handles
both dictionary and list formats for datetime_price data.
"""

import pytest
from datetime import datetime, timedelta
from app.src.services.trading.momentum_indicator import MomentumIndicator


class TestMomentumDatetimePriceFix:
    """Test suite for momentum datetime_price format handling"""

    def test_dict_format_with_upward_trend(self):
        """Test that dict format with upward trend produces positive momentum"""
        # Create datetime_price as dict with 10 entries showing 5% upward trend
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        datetime_price = {}
        
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)  # Gradual increase
            datetime_price[timestamp.isoformat()] = price
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should have positive momentum
        assert momentum > 0, f"Expected positive momentum for upward trend, got {momentum}"
        assert "Momentum:" in reason
        print(f"✓ Dict format upward trend: momentum={momentum:.2f}%, reason={reason}")

    def test_dict_format_with_downward_trend(self):
        """Test that dict format with downward trend produces negative momentum"""
        # Create datetime_price as dict with 10 entries showing downward trend
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        datetime_price = {}
        
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price - (i * 0.5)  # Gradual decrease
            datetime_price[timestamp.isoformat()] = price
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should have negative momentum
        assert momentum < 0, f"Expected negative momentum for downward trend, got {momentum}"
        assert "Momentum:" in reason
        print(f"✓ Dict format downward trend: momentum={momentum:.2f}%, reason={reason}")

    def test_dict_format_chronological_order(self):
        """Test that dict format maintains chronological order even with unsorted keys"""
        # Create datetime_price with timestamps out of order
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        
        # Add timestamps in reverse order
        datetime_price = {}
        for i in range(10, 0, -1):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)
            datetime_price[timestamp.isoformat()] = price
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should still calculate correctly (positive momentum)
        assert momentum > 0, f"Expected positive momentum despite unsorted dict, got {momentum}"
        print(f"✓ Dict format with unsorted keys: momentum={momentum:.2f}%")

    def test_list_format_backward_compatibility(self):
        """Test that list format still works (backward compatibility)"""
        # Create datetime_price as list (legacy format)
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        datetime_price = []
        
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)
            datetime_price.append([timestamp.isoformat(), price])
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should have positive momentum
        assert momentum > 0, f"Expected positive momentum for list format, got {momentum}"
        assert "Momentum:" in reason
        print(f"✓ List format (legacy): momentum={momentum:.2f}%, reason={reason}")

    def test_format_independence(self):
        """Test that dict and list formats produce same momentum for same data"""
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        
        # Create dict format
        datetime_price_dict = {}
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)
            datetime_price_dict[timestamp.isoformat()] = price
        
        # Create list format with same data
        datetime_price_list = []
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)
            datetime_price_list.append([timestamp.isoformat(), price])
        
        momentum_dict, _ = MomentumIndicator._calculate_momentum(datetime_price_dict)
        momentum_list, _ = MomentumIndicator._calculate_momentum(datetime_price_list)
        
        # Should be very close (within 0.01%)
        assert abs(momentum_dict - momentum_list) < 0.01, \
            f"Dict and list formats should produce same momentum: dict={momentum_dict:.4f}, list={momentum_list:.4f}"
        print(f"✓ Format independence: dict={momentum_dict:.4f}%, list={momentum_list:.4f}%")

    def test_empty_dict(self):
        """Test that empty dict returns zero momentum"""
        datetime_price = {}
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        assert momentum == 0.0
        assert "Insufficient price data" in reason
        print(f"✓ Empty dict: momentum={momentum}, reason={reason}")

    def test_insufficient_data_dict(self):
        """Test that dict with fewer than 3 entries returns zero momentum"""
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        datetime_price = {
            base_time.isoformat(): 100.0,
            (base_time + timedelta(minutes=1)).isoformat(): 101.0,
        }
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        assert momentum == 0.0
        assert "Insufficient price data" in reason
        print(f"✓ Insufficient data (2 entries): momentum={momentum}, reason={reason}")

    def test_invalid_format(self):
        """Test that invalid format returns zero momentum with error"""
        datetime_price = "invalid_string"
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        assert momentum == 0.0
        assert "Invalid datetime_price format" in reason
        print(f"✓ Invalid format: momentum={momentum}, reason={reason}")

    def test_dict_with_invalid_timestamps(self):
        """Test that dict with some invalid timestamps still processes valid ones"""
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        datetime_price = {}
        
        # Add valid entries
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)
            datetime_price[timestamp.isoformat()] = price
        
        # Add some invalid entries
        datetime_price["invalid_timestamp"] = 105.0
        datetime_price["2024-13-45T99:99:99"] = 106.0
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should still calculate from valid entries
        assert momentum > 0, f"Should process valid entries despite invalid ones, got {momentum}"
        print(f"✓ Dict with invalid timestamps: momentum={momentum:.2f}% (processed valid entries)")

    def test_dict_with_invalid_prices(self):
        """Test that dict with some invalid prices still processes valid ones"""
        base_time = datetime(2024, 12, 8, 9, 30, 0)
        base_price = 100.0
        datetime_price = {}
        
        # Add valid entries
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i)
            price = base_price + (i * 0.5)
            datetime_price[timestamp.isoformat()] = price
        
        # Add some invalid prices
        datetime_price[(base_time + timedelta(minutes=10)).isoformat()] = None
        datetime_price[(base_time + timedelta(minutes=11)).isoformat()] = -50.0
        datetime_price[(base_time + timedelta(minutes=12)).isoformat()] = "invalid"
        
        momentum, reason = MomentumIndicator._calculate_momentum(datetime_price)
        
        # Should still calculate from valid entries
        assert momentum > 0, f"Should process valid prices despite invalid ones, got {momentum}"
        print(f"✓ Dict with invalid prices: momentum={momentum:.2f}% (processed valid entries)")


if __name__ == "__main__":
    # Run tests manually
    test = TestMomentumDatetimePriceFix()
    
    print("\n=== Testing Momentum Indicator datetime_price Fix ===\n")
    
    test.test_dict_format_with_upward_trend()
    test.test_dict_format_with_downward_trend()
    test.test_dict_format_chronological_order()
    test.test_list_format_backward_compatibility()
    test.test_format_independence()
    test.test_empty_dict()
    test.test_insufficient_data_dict()
    test.test_invalid_format()
    test.test_dict_with_invalid_timestamps()
    test.test_dict_with_invalid_prices()
    
    print("\n=== All tests passed! ===\n")
