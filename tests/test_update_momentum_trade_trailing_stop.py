"""
Tests for DynamoDBClient.update_momentum_trade_trailing_stop method
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.src.db.dynamodb_client import DynamoDBClient


class TestUpdateMomentumTradeTrailingStop:
    """Test suite for update_momentum_trade_trailing_stop method"""

    @pytest.mark.asyncio
    async def test_update_momentum_trade_trailing_stop_success(self):
        """Test successful update of trailing stop for a momentum trade"""
        # Mock the instance and update_item method
        mock_instance = AsyncMock()
        mock_instance.update_item = AsyncMock(return_value=True)
        
        with patch.object(DynamoDBClient, '_get_instance', return_value=mock_instance):
            result = await DynamoDBClient.update_momentum_trade_trailing_stop(
                ticker='AAPL',
                indicator='Momentum Trading',
                trailing_stop=2.5,
                peak_profit_percent=5.0,
                skipped_exit_reason='Trade profitable: 5.00%'
            )
        
        assert result is True
        mock_instance.update_item.assert_called_once()
        
        # Verify the call parameters
        call_args = mock_instance.update_item.call_args
        assert call_args[1]['table_name'] == 'ActiveTickersForAutomatedDayTrader'
        assert call_args[1]['key'] == {'ticker': 'AAPL'}
        assert 'trailing_stop' in call_args[1]['update_expression']
        assert 'peak_profit_percent' in call_args[1]['update_expression']
        assert 'skipped_exit_reason' in call_args[1]['update_expression']

    @pytest.mark.asyncio
    async def test_update_momentum_trade_trailing_stop_failure(self):
        """Test failed update of trailing stop"""
        mock_instance = AsyncMock()
        mock_instance.update_item = AsyncMock(return_value=False)
        
        with patch.object(DynamoDBClient, '_get_instance', return_value=mock_instance):
            result = await DynamoDBClient.update_momentum_trade_trailing_stop(
                ticker='TSLA',
                indicator='Momentum Trading',
                trailing_stop=3.0,
                peak_profit_percent=2.5,
                skipped_exit_reason='Trade not yet profitable: 2.50%'
            )
        
        assert result is False

    @pytest.mark.asyncio
    async def test_update_momentum_trade_trailing_stop_with_different_values(self):
        """Test update with various trailing stop and profit values"""
        mock_instance = AsyncMock()
        mock_instance.update_item = AsyncMock(return_value=True)
        
        test_cases = [
            (1.5, 0.5, 'Small profit'),
            (5.0, 10.0, 'Large profit'),
            (0.5, 0.1, 'Minimal profit'),
            (8.0, 15.0, 'Exceptional profit'),
        ]
        
        with patch.object(DynamoDBClient, '_get_instance', return_value=mock_instance):
            for trailing_stop, peak_profit, reason in test_cases:
                result = await DynamoDBClient.update_momentum_trade_trailing_stop(
                    ticker='TEST',
                    indicator='Momentum Trading',
                    trailing_stop=trailing_stop,
                    peak_profit_percent=peak_profit,
                    skipped_exit_reason=reason
                )
                assert result is True

    @pytest.mark.asyncio
    async def test_update_momentum_trade_trailing_stop_expression_values(self):
        """Test that expression attribute values are correctly set"""
        mock_instance = AsyncMock()
        mock_instance.update_item = AsyncMock(return_value=True)
        
        with patch.object(DynamoDBClient, '_get_instance', return_value=mock_instance):
            await DynamoDBClient.update_momentum_trade_trailing_stop(
                ticker='GOOG',
                indicator='Momentum Trading',
                trailing_stop=2.75,
                peak_profit_percent=7.5,
                skipped_exit_reason='Holding for more profit'
            )
        
        call_args = mock_instance.update_item.call_args
        expr_values = call_args[1]['expression_attribute_values']
        
        assert expr_values[':ts'] == 2.75
        assert expr_values[':pp'] == 7.5
        assert expr_values[':ser'] == 'Holding for more profit'

    @pytest.mark.asyncio
    async def test_update_momentum_trade_trailing_stop_multiple_tickers(self):
        """Test updating trailing stop for multiple tickers"""
        mock_instance = AsyncMock()
        mock_instance.update_item = AsyncMock(return_value=True)
        
        tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN']
        
        with patch.object(DynamoDBClient, '_get_instance', return_value=mock_instance):
            for ticker in tickers:
                result = await DynamoDBClient.update_momentum_trade_trailing_stop(
                    ticker=ticker,
                    indicator='Momentum Trading',
                    trailing_stop=2.5,
                    peak_profit_percent=5.0,
                    skipped_exit_reason='Trade profitable'
                )
                assert result is True
        
        # Verify update_item was called for each ticker
        assert mock_instance.update_item.call_count == len(tickers)
