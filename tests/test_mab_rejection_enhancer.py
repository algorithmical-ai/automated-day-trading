"""
Tests for MAB Rejection Enhancer functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.src.services.mab.mab_rejection_enhancer import MABRejectionEnhancer


class TestMABRejectionEnhancer:
    """Test cases for MAB Rejection Enhancer."""
    
    @pytest.fixture
    def enhancer(self):
        """Create a MAB rejection enhancer instance."""
        return MABRejectionEnhancer()
    
    @pytest.fixture
    def sample_empty_record(self):
        """Sample record with empty rejection reasons."""
        return {
            'ticker': 'AAPL',
            'indicator': 'Penny Stocks',
            'timestamp': '2024-12-10T10:30:00-05:00',
            'reason_not_to_enter_long': '',
            'reason_not_to_enter_short': '',
            'technical_indicators': '{"close_price": 150.0, "volume": 1000, "momentum_score": 2.5}'
        }
    
    @pytest.fixture
    def sample_mab_stats(self):
        """Sample MAB statistics."""
        return {
            'successes': 3,
            'failures': 7,
            'total_trades': 10,
            'excluded_until': None
        }
    
    @pytest.mark.asyncio
    async def test_generate_mab_rejection_reason_with_stats(self, enhancer, sample_mab_stats):
        """Test generating MAB rejection reason when stats are available."""
        with patch.object(enhancer.mab_service, 'get_stats', return_value=sample_mab_stats):
            result = await enhancer._generate_mab_rejection_reason('AAPL', 'Penny Stocks')
            
            assert 'reason_long' in result
            assert 'reason_short' in result
            assert 'MAB rejected' in result['reason_long']
            assert 'successes: 3' in result['reason_long']
            assert 'failures: 7' in result['reason_long']
            assert 'total: 10' in result['reason_long']
    
    @pytest.mark.asyncio
    async def test_generate_mab_rejection_reason_new_ticker(self, enhancer):
        """Test generating MAB rejection reason for new ticker (no stats)."""
        with patch.object(enhancer.mab_service, 'get_stats', return_value=None):
            result = await enhancer._generate_mab_rejection_reason('NEWT', 'Penny Stocks')
            
            assert 'reason_long' in result
            assert 'reason_short' in result
            assert 'New ticker' in result['reason_long']
            assert 'Thompson Sampling' in result['reason_long']
            assert 'successes: 0' in result['reason_long']
    
    def test_create_generic_rejection_reason_with_momentum(self, enhancer):
        """Test creating generic rejection reason when momentum data is available."""
        record = {
            'ticker': 'TEST',
            'technical_indicators': {
                'momentum_score': 0.8  # Below 1.5% threshold
            }
        }
        
        result = enhancer._create_generic_rejection_reason(record)
        
        assert 'reason_long' in result
        assert 'reason_short' in result
        assert 'Momentum too low' in result['reason_long']
        assert '0.8%' in result['reason_long']
        assert 'minimum: 1.5%' in result['reason_long']
    
    def test_create_generic_rejection_reason_no_momentum(self, enhancer):
        """Test creating generic rejection reason when no momentum data."""
        record = {
            'ticker': 'TEST',
            'technical_indicators': {}
        }
        
        result = enhancer._create_generic_rejection_reason(record)
        
        assert 'reason_long' in result
        assert 'reason_short' in result
        assert 'insufficient momentum data' in result['reason_long']
    
    def test_create_generic_rejection_reason_high_momentum(self, enhancer):
        """Test creating generic rejection reason for high momentum (likely MAB rejection)."""
        record = {
            'ticker': 'TEST',
            'technical_indicators': {
                'momentum_score': 5.2  # Above 1.5% threshold
            }
        }
        
        result = enhancer._create_generic_rejection_reason(record)
        
        assert 'reason_long' in result
        assert 'Not selected for entry' in result['reason_long']
        assert 'MAB ranking' in result['reason_long']
    
    @pytest.mark.asyncio
    async def test_enhance_real_time_record_with_mab_stats(self, sample_mab_stats):
        """Test real-time record enhancement with MAB stats available."""
        with patch('app.src.services.mab.mab_rejection_enhancer.MABRejectionEnhancer') as MockEnhancer:
            mock_instance = AsyncMock()
            MockEnhancer.return_value = mock_instance
            
            # Mock the MAB rejection reason generation
            mock_instance._generate_mab_rejection_reason.return_value = {
                'reason_long': 'MAB rejected: Low success rate (30.0%) (successes: 3, failures: 7, total: 10)',
                'reason_short': 'MAB rejected: Low success rate (30.0%) (successes: 3, failures: 7, total: 10)'
            }
            
            result = await MABRejectionEnhancer.enhance_real_time_record(
                ticker='AAPL',
                indicator='Penny Stocks',
                technical_indicators={'momentum_score': 2.5}
            )
            
            assert 'reason_long' in result
            assert 'reason_short' in result
            assert 'MAB rejected' in result['reason_long']
    
    @pytest.mark.asyncio
    async def test_enhance_real_time_record_fallback_to_generic(self):
        """Test real-time record enhancement falling back to generic reasons."""
        with patch('app.src.services.mab.mab_rejection_enhancer.MABRejectionEnhancer') as MockEnhancer:
            mock_instance = AsyncMock()
            MockEnhancer.return_value = mock_instance
            
            # Mock empty MAB rejection reasons (no MAB data)
            mock_instance._generate_mab_rejection_reason.return_value = {
                'reason_long': '',
                'reason_short': ''
            }
            
            # Mock generic reason creation
            mock_instance._create_generic_rejection_reason.return_value = {
                'reason_long': 'Momentum too low for entry: 0.8% (minimum: 1.5%)',
                'reason_short': ''
            }
            
            result = await MABRejectionEnhancer.enhance_real_time_record(
                ticker='TEST',
                indicator='Penny Stocks',
                technical_indicators={'momentum_score': 0.8}
            )
            
            assert 'reason_long' in result
            assert 'reason_short' in result
            assert 'Momentum too low' in result['reason_long']
    
    @pytest.mark.asyncio
    async def test_update_record_with_reasons_success(self, enhancer, sample_empty_record):
        """Test successful record update with enhanced reasons."""
        enhanced_reasons = {
            'reason_long': 'MAB rejected: Low success rate',
            'reason_short': ''
        }
        
        with patch.object(enhancer.dynamodb_client, 'update_item', return_value=True):
            result = await enhancer._update_record_with_reasons(
                sample_empty_record, enhanced_reasons
            )
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_update_record_with_reasons_failure(self, enhancer, sample_empty_record):
        """Test record update failure handling."""
        enhanced_reasons = {
            'reason_long': 'MAB rejected: Low success rate',
            'reason_short': ''
        }
        
        with patch.object(enhancer.dynamodb_client, 'update_item', return_value=False):
            result = await enhancer._update_record_with_reasons(
                sample_empty_record, enhanced_reasons
            )
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_enhance_record_batch_success(self, enhancer):
        """Test successful batch enhancement."""
        records = [
            {
                'ticker': 'AAPL',
                'technical_indicators': {'momentum_score': 2.5}
            },
            {
                'ticker': 'GOOGL', 
                'technical_indicators': {'momentum_score': 1.2}
            }
        ]
        
        # Mock the enhancement methods
        with patch.object(enhancer, '_generate_mab_rejection_reason') as mock_mab, \
             patch.object(enhancer, '_update_record_with_reasons', return_value=True) as mock_update:
            
            mock_mab.return_value = {
                'reason_long': 'MAB rejected: Test reason',
                'reason_short': ''
            }
            
            result = await enhancer._enhance_record_batch(records, 'Penny Stocks')
            
            assert result['enhanced'] == 2
            assert result['skipped'] == 0
            assert result['errors'] == 0
            assert mock_mab.call_count == 2
            assert mock_update.call_count == 2
    
    @pytest.mark.asyncio
    async def test_enhance_record_batch_with_errors(self, enhancer):
        """Test batch enhancement with some errors."""
        records = [
            {'ticker': 'AAPL'},  # Valid record
            {'ticker': ''},      # Invalid record (empty ticker)
            {'ticker': 'GOOGL'}  # Valid record
        ]
        
        with patch.object(enhancer, '_generate_mab_rejection_reason') as mock_mab, \
             patch.object(enhancer, '_update_record_with_reasons') as mock_update:
            
            mock_mab.return_value = {
                'reason_long': 'MAB rejected: Test reason',
                'reason_short': ''
            }
            
            # First update succeeds, second fails
            mock_update.side_effect = [True, False]
            
            result = await enhancer._enhance_record_batch(records, 'Penny Stocks')
            
            assert result['enhanced'] == 1  # One success
            assert result['skipped'] == 1   # One empty ticker
            assert result['errors'] == 1    # One update failure


if __name__ == "__main__":
    pytest.main([__file__])