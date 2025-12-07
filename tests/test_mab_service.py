"""
Unit tests for MAB Service.

Tests basic functionality of the Multi-Armed Bandit service including:
- Thompson Sampling algorithm
- Statistics management
- Ticker exclusion
"""
import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.src.services.mab.mab_service import MABService
from app.src.models.trade_models import MABStats


class TestMABService:
    """Test suite for MAB Service."""
    
    @pytest.fixture
    def mab_service(self):
        """Create MAB service instance."""
        return MABService()
    
    def test_thompson_sampling_empty_list(self, mab_service):
        """Test Thompson Sampling with empty list."""
        result = mab_service.thompson_sampling([])
        assert result == []
    
    def test_thompson_sampling_single_ticker(self, mab_service):
        """Test Thompson Sampling with single ticker."""
        stats_list = [{'successes': 5, 'failures': 2}]
        result = mab_service.thompson_sampling(stats_list)
        assert result == [0]
    
    def test_thompson_sampling_multiple_tickers(self, mab_service):
        """Test Thompson Sampling with multiple tickers."""
        # Set seed for reproducibility
        np.random.seed(42)
        
        stats_list = [
            {'successes': 10, 'failures': 2},  # High success rate
            {'successes': 2, 'failures': 10},  # Low success rate
            {'successes': 0, 'failures': 0},   # New ticker
        ]
        
        result = mab_service.thompson_sampling(stats_list)
        
        # Should return all indices
        assert len(result) == 3
        assert set(result) == {0, 1, 2}
        
        # First ticker should generally rank higher (but not guaranteed due to sampling)
        # Just verify we get valid indices
        assert all(0 <= i < 3 for i in result)
    
    def test_is_excluded_no_exclusion(self, mab_service):
        """Test exclusion check when ticker is not excluded."""
        stats = {'successes': 5, 'failures': 2}
        assert not mab_service._is_excluded(stats)
    
    def test_is_excluded_none_stats(self, mab_service):
        """Test exclusion check with None stats."""
        assert not mab_service._is_excluded(None)
    
    def test_is_excluded_expired(self, mab_service):
        """Test exclusion check when exclusion has expired."""
        # Exclusion expired 1 hour ago
        excluded_until = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        stats = {
            'successes': 5,
            'failures': 2,
            'excluded_until': excluded_until
        }
        assert not mab_service._is_excluded(stats)
    
    def test_is_excluded_active(self, mab_service):
        """Test exclusion check when ticker is currently excluded."""
        # Exclusion expires in 1 hour
        excluded_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        stats = {
            'successes': 5,
            'failures': 2,
            'excluded_until': excluded_until
        }
        assert mab_service._is_excluded(stats)
    
    @pytest.mark.asyncio
    async def test_get_stats_not_found(self, mab_service):
        """Test getting stats for non-existent ticker."""
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            
            result = await mab_service.get_stats('momentum', 'AAPL')
            
            assert result is None
            mock_get.assert_called_once_with(
                table_name='MABStats',
                key={'indicator_ticker': 'momentum#AAPL'}
            )
    
    @pytest.mark.asyncio
    async def test_get_stats_found(self, mab_service):
        """Test getting stats for existing ticker."""
        expected_stats = {
            'indicator_ticker': 'momentum#AAPL',
            'successes': 10,
            'failures': 3,
            'total_trades': 13
        }
        
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = expected_stats
            
            result = await mab_service.get_stats('momentum', 'AAPL')
            
            assert result == expected_stats
            mock_get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_stats_new_ticker_success(self, mab_service):
        """Test updating stats for new ticker with successful trade."""
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get, \
             patch.object(mab_service.dynamodb_client, 'put_item', new_callable=AsyncMock) as mock_put:
            
            mock_get.return_value = None  # New ticker
            mock_put.return_value = True
            
            result = await mab_service.update_stats('momentum', 'AAPL', success=True)
            
            assert result is True
            mock_put.assert_called_once()
            
            # Verify the item being put
            call_args = mock_put.call_args
            item = call_args.kwargs['item']
            assert item['indicator_ticker'] == 'momentum#AAPL'
            assert item['successes'] == 1
            assert item['failures'] == 0
            assert item['total_trades'] == 1
    
    @pytest.mark.asyncio
    async def test_update_stats_new_ticker_failure(self, mab_service):
        """Test updating stats for new ticker with failed trade."""
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get, \
             patch.object(mab_service.dynamodb_client, 'put_item', new_callable=AsyncMock) as mock_put:
            
            mock_get.return_value = None  # New ticker
            mock_put.return_value = True
            
            result = await mab_service.update_stats('momentum', 'AAPL', success=False)
            
            assert result is True
            
            # Verify the item being put
            call_args = mock_put.call_args
            item = call_args.kwargs['item']
            assert item['successes'] == 0
            assert item['failures'] == 1
            assert item['total_trades'] == 1
    
    @pytest.mark.asyncio
    async def test_update_stats_existing_ticker(self, mab_service):
        """Test updating stats for existing ticker."""
        existing_stats = {
            'indicator_ticker': 'momentum#AAPL',
            'successes': 5,
            'failures': 2,
            'total_trades': 7
        }
        
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get, \
             patch.object(mab_service.dynamodb_client, 'update_item', new_callable=AsyncMock) as mock_update:
            
            mock_get.return_value = existing_stats
            mock_update.return_value = True
            
            result = await mab_service.update_stats('momentum', 'AAPL', success=True)
            
            assert result is True
            mock_update.assert_called_once()
            
            # Verify the update expression
            call_args = mock_update.call_args
            values = call_args.kwargs['expression_attribute_values']
            assert values[':s'] == 6  # successes incremented
            assert values[':f'] == 2  # failures unchanged
            assert values[':t'] == 8  # total incremented
    
    @pytest.mark.asyncio
    async def test_exclude_ticker_new(self, mab_service):
        """Test excluding a new ticker."""
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get, \
             patch.object(mab_service.dynamodb_client, 'put_item', new_callable=AsyncMock) as mock_put:
            
            mock_get.return_value = None  # New ticker
            mock_put.return_value = True
            
            result = await mab_service.exclude_ticker('penny_stocks', 'AAPL', duration_hours=24)
            
            assert result is True
            mock_put.assert_called_once()
            
            # Verify exclusion was set
            call_args = mock_put.call_args
            item = call_args.kwargs['item']
            assert item['indicator_ticker'] == 'penny_stocks#AAPL'
            assert item['excluded_until'] is not None
    
    @pytest.mark.asyncio
    async def test_exclude_ticker_existing(self, mab_service):
        """Test excluding an existing ticker."""
        existing_stats = {
            'indicator_ticker': 'penny_stocks#AAPL',
            'successes': 2,
            'failures': 5,
            'total_trades': 7
        }
        
        with patch.object(mab_service.dynamodb_client, 'get_item', new_callable=AsyncMock) as mock_get, \
             patch.object(mab_service.dynamodb_client, 'update_item', new_callable=AsyncMock) as mock_update:
            
            mock_get.return_value = existing_stats
            mock_update.return_value = True
            
            result = await mab_service.exclude_ticker('penny_stocks', 'AAPL', duration_hours=24)
            
            assert result is True
            mock_update.assert_called_once()
            
            # Verify exclusion was set
            call_args = mock_update.call_args
            values = call_args.kwargs['expression_attribute_values']
            assert ':eu' in values
            assert values[':eu'] is not None
    
    @pytest.mark.asyncio
    async def test_select_tickers_empty_candidates(self, mab_service):
        """Test selecting tickers with empty candidate list."""
        result = await mab_service.select_tickers('momentum', [], 'long', 5)
        assert result == []
    
    @pytest.mark.asyncio
    async def test_select_tickers_with_exclusions(self, mab_service):
        """Test selecting tickers with some excluded."""
        candidates = ['AAPL', 'GOOGL', 'MSFT']
        
        # GOOGL is excluded
        excluded_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        
        with patch.object(mab_service, 'get_stats', new_callable=AsyncMock) as mock_get_stats, \
             patch.object(mab_service, 'thompson_sampling') as mock_thompson:
            
            # Mock stats: AAPL and MSFT are valid, GOOGL is excluded
            async def get_stats_side_effect(indicator, ticker):
                if ticker == 'GOOGL':
                    return {
                        'successes': 0,
                        'failures': 5,
                        'total_trades': 5,
                        'excluded_until': excluded_until
                    }
                return {
                    'successes': 5,
                    'failures': 2,
                    'total_trades': 7
                }
            
            mock_get_stats.side_effect = get_stats_side_effect
            mock_thompson.return_value = [0, 1]  # Rank AAPL first, then MSFT
            
            result = await mab_service.select_tickers('momentum', candidates, 'long', 5)
            
            # Should only return AAPL and MSFT (GOOGL excluded)
            assert len(result) == 2
            assert 'GOOGL' not in result
            assert 'AAPL' in result
            assert 'MSFT' in result
    
    @pytest.mark.asyncio
    async def test_select_tickers_top_k_limit(self, mab_service):
        """Test selecting tickers respects top_k limit."""
        candidates = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'NVDA']
        
        with patch.object(mab_service, 'get_stats', new_callable=AsyncMock) as mock_get_stats, \
             patch.object(mab_service, 'thompson_sampling') as mock_thompson:
            
            # All tickers have stats
            mock_get_stats.return_value = {
                'successes': 5,
                'failures': 2,
                'total_trades': 7
            }
            
            # Thompson sampling ranks them in order
            mock_thompson.return_value = [0, 1, 2, 3, 4]
            
            result = await mab_service.select_tickers('momentum', candidates, 'long', top_k=3)
            
            # Should only return top 3
            assert len(result) == 3
            assert result == ['AAPL', 'GOOGL', 'MSFT']
