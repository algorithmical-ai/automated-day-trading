"""
Integration tests for simplified penny stock validation system.

These tests verify the end-to-end flow of the simplified validation system.
"""

import pytest
from app.src.models.simplified_validation import Quote, TrendMetrics
from app.src.services.trading.trend_metrics_calculator import TrendMetricsCalculator
from app.src.services.trading.simplified_validator import SimplifiedValidator
from app.src.services.trading.evaluation_record_builder import EvaluationRecordBuilder


class TestSimplifiedValidationIntegration:
    """Integration tests for simplified validation system."""
    
    def test_end_to_end_upward_trend_validation(self):
        """Test complete validation flow for upward trending stock."""
        # Arrange: Create upward trending price bars
        bars = [
            {'c': 1.00},
            {'c': 1.05},
            {'c': 1.10},
            {'c': 1.15},
            {'c': 1.20}
        ]
        
        # Act: Calculate trend metrics
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Assert: Momentum should be positive
        assert trend_metrics.momentum_score > 0, "Upward trend should have positive momentum"
        assert trend_metrics.peak_price == 1.20
        assert trend_metrics.bottom_price == 1.00
        assert 0.0 <= trend_metrics.continuation_score <= 1.0
        
        # Act: Validate with good quote
        quote = Quote(ticker="TEST", bid=1.19, ask=1.21)
        validator = SimplifiedValidator(max_bid_ask_spread=2.0)
        result = validator.validate("TEST", trend_metrics, quote)
        
        # Assert: Long should be valid, short should be rejected
        assert result.is_valid_for_long, "Long entry should be valid for upward trend"
        assert not result.is_valid_for_short, "Short entry should be rejected for upward trend"
        assert "upward trend" in result.reason_not_to_enter_short.lower()
    
    def test_end_to_end_downward_trend_validation(self):
        """Test complete validation flow for downward trending stock."""
        # Arrange: Create downward trending price bars
        bars = [
            {'c': 2.00},
            {'c': 1.95},
            {'c': 1.90},
            {'c': 1.85},
            {'c': 1.80}
        ]
        
        # Act: Calculate trend metrics
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Assert: Momentum should be negative
        assert trend_metrics.momentum_score < 0, "Downward trend should have negative momentum"
        assert trend_metrics.peak_price == 2.00
        assert trend_metrics.bottom_price == 1.80
        
        # Act: Validate with good quote
        quote = Quote(ticker="TEST", bid=1.79, ask=1.81)
        validator = SimplifiedValidator(max_bid_ask_spread=2.0)
        result = validator.validate("TEST", trend_metrics, quote)
        
        # Assert: Short should be valid, long should be rejected
        assert not result.is_valid_for_long, "Long entry should be rejected for downward trend"
        assert result.is_valid_for_short, "Short entry should be valid for downward trend"
        assert "downward trend" in result.reason_not_to_enter_long.lower()
    
    def test_end_to_end_wide_spread_rejection(self):
        """Test that wide bid-ask spread rejects both directions."""
        # Arrange: Create neutral price bars
        bars = [
            {'c': 1.50},
            {'c': 1.51},
            {'c': 1.50},
            {'c': 1.51},
            {'c': 1.50}
        ]
        
        # Act: Calculate trend metrics
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Act: Validate with wide spread quote
        quote = Quote(ticker="TEST", bid=1.45, ask=1.55)  # ~6.7% spread
        validator = SimplifiedValidator(max_bid_ask_spread=2.0)
        result = validator.validate("TEST", trend_metrics, quote)
        
        # Assert: Both directions should be rejected
        assert not result.is_valid_for_long, "Long should be rejected for wide spread"
        assert not result.is_valid_for_short, "Short should be rejected for wide spread"
        assert "spread too wide" in result.reason_not_to_enter_long.lower()
        assert "spread too wide" in result.reason_not_to_enter_short.lower()
        assert result.reason_not_to_enter_long == result.reason_not_to_enter_short
    
    def test_end_to_end_record_building(self):
        """Test complete flow including record building."""
        # Arrange
        bars = [
            {'c': 1.00},
            {'c': 1.05},
            {'c': 1.10},
            {'c': 1.15},
            {'c': 1.20}
        ]
        
        # Act: Full pipeline
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        quote = Quote(ticker="AAPL", bid=1.19, ask=1.21)
        validator = SimplifiedValidator(max_bid_ask_spread=2.0)
        result = validator.validate("AAPL", trend_metrics, quote)
        
        builder = EvaluationRecordBuilder(indicator_name="Penny Stocks")
        record = builder.build_record("AAPL", result, trend_metrics)
        
        # Assert: Record has all required fields
        assert record['ticker'] == "AAPL"
        assert record['indicator'] == "Penny Stocks"
        assert 'reason_not_to_enter_long' in record
        assert 'reason_not_to_enter_short' in record
        assert 'technical_indicators' in record
        assert 'timestamp' in record
        
        # Assert: Technical indicators are populated
        tech_indicators = record['technical_indicators']
        assert 'momentum_score' in tech_indicators
        assert 'continuation_score' in tech_indicators
        assert 'peak_price' in tech_indicators
        assert 'bottom_price' in tech_indicators
        assert 'reason' in tech_indicators
        
        # Assert: Values match
        assert tech_indicators['momentum_score'] == trend_metrics.momentum_score
        assert tech_indicators['peak_price'] == 1.20
        assert tech_indicators['bottom_price'] == 1.00
    
    def test_edge_case_single_bar(self):
        """Test handling of single bar edge case."""
        # Arrange: Single bar
        bars = [{'c': 1.50}]
        
        # Act
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Assert: Should handle gracefully
        assert trend_metrics.momentum_score == 0.0
        assert trend_metrics.peak_price == 1.50
        assert trend_metrics.bottom_price == 1.50
        assert "1 bars" in trend_metrics.reason
    
    def test_edge_case_identical_prices(self):
        """Test handling of identical prices."""
        # Arrange: All prices the same
        bars = [
            {'c': 2.00},
            {'c': 2.00},
            {'c': 2.00},
            {'c': 2.00},
            {'c': 2.00}
        ]
        
        # Act
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Assert: Should handle gracefully
        assert trend_metrics.momentum_score == 0.0
        assert trend_metrics.continuation_score == 0.0
        assert trend_metrics.peak_price == 2.00
        assert trend_metrics.bottom_price == 2.00
    
    def test_edge_case_invalid_prices_filtered(self):
        """Test that invalid prices are filtered out."""
        # Arrange: Mix of valid and invalid prices
        bars = [
            {'c': 1.00},
            {'c': None},  # Invalid
            {'c': 1.10},
            {'c': -1.0},  # Invalid
            {'c': 1.20}
        ]
        
        # Act
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Assert: Should only use valid prices
        assert trend_metrics.peak_price == 1.20
        assert trend_metrics.bottom_price == 1.00
        # Should have calculated based on 3 valid bars
        assert "3 bars" in trend_metrics.reason
