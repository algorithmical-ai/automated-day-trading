"""
Integration tests for momentum trading validation system.

These tests verify the end-to-end flow of the momentum validation system
with symmetric rejection logic.
"""

import pytest
from app.src.models.momentum_validation import TechnicalIndicators, ValidationResult
from app.src.services.trading.technical_indicator_calculator import TechnicalIndicatorCalculator
from app.src.services.trading.momentum_validator import MomentumValidator
from app.src.services.trading.momentum_evaluation_record_builder import MomentumEvaluationRecordBuilder


class TestMomentumValidationIntegration:
    """Integration tests for momentum validation system."""
    
    def test_end_to_end_valid_ticker(self):
        """Test complete validation flow for valid ticker."""
        # Arrange: Create valid price bars with low volatility and good volume
        bars = [
            {'c': 100.0, 'h': 100.2, 'l': 99.8, 'o': 100.0, 'v': 1000, 't': '2025-12-08T10:00:00Z'},
            {'c': 100.1, 'h': 100.3, 'l': 99.9, 'o': 100.0, 'v': 1200, 't': '2025-12-08T10:01:00Z'},
            {'c': 100.2, 'h': 100.4, 'l': 100.0, 'o': 100.1, 'v': 1500, 't': '2025-12-08T10:02:00Z'},
            {'c': 100.3, 'h': 100.5, 'l': 100.1, 'o': 100.2, 'v': 1800, 't': '2025-12-08T10:03:00Z'},
            {'c': 100.4, 'h': 100.6, 'l': 100.2, 'o': 100.3, 'v': 3000, 't': '2025-12-08T10:04:00Z'}  # High volume, low volatility
        ]
        
        # Act: Calculate technical indicators
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Assert: Indicators calculated
        assert tech_indicators.close_price == 100.4
        assert tech_indicators.volume == 3000
        assert tech_indicators.volume_sma > 0
        
        # Act: Validate
        validator = MomentumValidator()
        result = validator.validate("AAPL", tech_indicators)
        
        # Assert: Should be valid (passes all checks)
        assert result.is_valid, "Should be valid for entry"
        assert result.reason_not_to_enter_long == ""
        assert result.reason_not_to_enter_short == ""
        assert result.is_symmetric_rejection  # Empty strings are symmetric
    
    def test_end_to_end_warrant_rejection(self):
        """Test rejection of warrant/derivative securities."""
        # Arrange: Create valid price bars
        bars = [
            {'c': 10.0, 'h': 10.5, 'l': 9.5, 'o': 9.8, 'v': 1000, 't': '2025-12-08T10:00:00Z'},
            {'c': 10.5, 'h': 11.0, 'l': 10.0, 'o': 10.0, 'v': 1200, 't': '2025-12-08T10:01:00Z'}
        ]
        
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Act: Validate warrant ticker
        validator = MomentumValidator()
        result = validator.validate("AAPLW", tech_indicators)  # Warrant suffix
        
        # Assert: Should be rejected symmetrically
        assert not result.is_valid
        assert "warrant" in result.reason_not_to_enter_long.lower()
        assert "warrant" in result.reason_not_to_enter_short.lower()
        assert result.is_symmetric_rejection
        assert result.reason_not_to_enter_long == result.reason_not_to_enter_short
    
    def test_end_to_end_low_price_rejection(self):
        """Test rejection of low-priced stocks."""
        # Arrange: Create bars with low price
        bars = [
            {'c': 0.05, 'h': 0.06, 'l': 0.04, 'o': 0.045, 'v': 1000, 't': '2025-12-08T10:00:00Z'},
            {'c': 0.06, 'h': 0.07, 'l': 0.05, 'o': 0.05, 'v': 1200, 't': '2025-12-08T10:01:00Z'}
        ]
        
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Act: Validate
        validator = MomentumValidator(min_price=0.10)
        result = validator.validate("PENNY", tech_indicators)
        
        # Assert: Should be rejected symmetrically
        assert not result.is_valid
        assert "price too low" in result.reason_not_to_enter_long.lower()
        assert "price too low" in result.reason_not_to_enter_short.lower()
        assert result.is_symmetric_rejection
        assert result.reason_not_to_enter_long == result.reason_not_to_enter_short
    
    def test_end_to_end_low_volume_rejection(self):
        """Test rejection of low volume stocks."""
        # Arrange: Create bars with low volume
        bars = [
            {'c': 10.0, 'h': 10.5, 'l': 9.5, 'o': 9.8, 'v': 100, 't': '2025-12-08T10:00:00Z'},
            {'c': 10.5, 'h': 11.0, 'l': 10.0, 'o': 10.0, 'v': 150, 't': '2025-12-08T10:01:00Z'}
        ]
        
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Act: Validate
        validator = MomentumValidator(min_volume=500)
        result = validator.validate("LOWVOL", tech_indicators)
        
        # Assert: Should be rejected symmetrically
        assert not result.is_valid
        assert "volume too low" in result.reason_not_to_enter_long.lower()
        assert "volume too low" in result.reason_not_to_enter_short.lower()
        assert result.is_symmetric_rejection
        assert result.reason_not_to_enter_long == result.reason_not_to_enter_short
    
    def test_end_to_end_record_building(self):
        """Test complete flow including record building."""
        # Arrange
        bars = [
            {'c': 10.0, 'h': 10.5, 'l': 9.5, 'o': 9.8, 'v': 1000, 't': '2025-12-08T10:00:00Z'},
            {'c': 10.5, 'h': 11.0, 'l': 10.0, 'o': 10.0, 'v': 1200, 't': '2025-12-08T10:01:00Z'}
        ]
        
        # Act: Full pipeline
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        validator = MomentumValidator()
        result = validator.validate("AAPL", tech_indicators)
        
        builder = MomentumEvaluationRecordBuilder(indicator_name="Momentum Trading")
        record = builder.build_record("AAPL", result, tech_indicators)
        
        # Assert: Record has all required fields
        assert record['ticker'] == "AAPL"
        assert record['indicator'] == "Momentum Trading"
        assert 'reason_not_to_enter_long' in record
        assert 'reason_not_to_enter_short' in record
        assert 'technical_indicators' in record
        assert 'timestamp' in record
        
        # Assert: Technical indicators are comprehensive
        tech_dict = record['technical_indicators']
        assert 'rsi' in tech_dict
        assert 'macd' in tech_dict
        assert 'bollinger' in tech_dict
        assert 'adx' in tech_dict
        assert 'ema_fast' in tech_dict
        assert 'ema_slow' in tech_dict
        assert 'volume_sma' in tech_dict
        assert 'obv' in tech_dict
        assert 'mfi' in tech_dict
        assert 'ad' in tech_dict
        assert 'stoch' in tech_dict
        assert 'cci' in tech_dict
        assert 'atr' in tech_dict
        assert 'willr' in tech_dict
        assert 'roc' in tech_dict
        assert 'vwap' in tech_dict
        assert 'vwma' in tech_dict
        assert 'wma' in tech_dict
        assert 'volume' in tech_dict
        assert 'close_price' in tech_dict
        assert 'datetime_price' in tech_dict
    
    def test_symmetric_rejection_property(self):
        """Test that all rejections are symmetric."""
        # Test various rejection scenarios
        test_cases = [
            # Warrant
            ("TESTW", [{'c': 10.0, 'h': 10.5, 'l': 9.5, 'o': 9.8, 'v': 1000, 't': '2025-12-08T10:00:00Z'}]),
            # Low price
            ("TEST", [{'c': 0.05, 'h': 0.06, 'l': 0.04, 'o': 0.045, 'v': 1000, 't': '2025-12-08T10:00:00Z'}]),
            # Low volume
            ("TEST", [{'c': 10.0, 'h': 10.5, 'l': 9.5, 'o': 9.8, 'v': 100, 't': '2025-12-08T10:00:00Z'}]),
        ]
        
        validator = MomentumValidator()
        
        for ticker, bars in test_cases:
            tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
            result = validator.validate(ticker, tech_indicators)
            
            # All rejections should be symmetric
            if not result.is_valid:
                assert result.is_symmetric_rejection, f"Rejection for {ticker} should be symmetric"
                assert result.reason_not_to_enter_long == result.reason_not_to_enter_short
    
    def test_edge_case_insufficient_data(self):
        """Test handling of insufficient data."""
        # Arrange: Empty bars
        bars = []
        
        # Act
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Assert: Should return default indicators
        assert tech_indicators.close_price == 0.0
        assert tech_indicators.volume == 0
        assert tech_indicators.rsi == 50.0  # Default RSI
    
    def test_edge_case_single_bar(self):
        """Test handling of single bar."""
        # Arrange: Single bar
        bars = [{'c': 10.0, 'h': 10.5, 'l': 9.5, 'o': 9.8, 'v': 1000, 't': '2025-12-08T10:00:00Z'}]
        
        # Act
        tech_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Assert: Should handle gracefully
        assert tech_indicators.close_price == 10.0
        assert tech_indicators.volume == 1000
