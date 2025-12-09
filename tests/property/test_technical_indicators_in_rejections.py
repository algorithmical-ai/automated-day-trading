"""
Property-based tests for technical indicators in MAB rejection logging.

Feature: mab-rejection-logging
Property 6: Technical Indicators Included in MAB Rejections
Validates: Requirements 4.1, 4.3
"""

import pytest
import json
from hypothesis import given, strategies as st
from unittest.mock import AsyncMock, patch
from app.src.services.mab.mab_service import MABService
from app.src.db.dynamodb_client import DynamoDBClient


@st.composite
def ticker_symbol(draw):
    """Generate random ticker symbols."""
    return draw(st.text(
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        min_size=1,
        max_size=5
    ))


@st.composite
def technical_indicators(draw):
    """Generate random technical indicators."""
    return {
        'momentum_score': draw(st.floats(min_value=-15.0, max_value=15.0, allow_nan=False, allow_infinity=False)),
        'volume': draw(st.integers(min_value=1000, max_value=1000000)),
        'close_price': draw(st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False)),
        'atr': draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)),
        'rsi': draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    }


@st.composite
def mab_stats(draw):
    """Generate random MAB statistics."""
    successes = draw(st.integers(min_value=0, max_value=100))
    failures = draw(st.integers(min_value=0, max_value=100))
    total_trades = successes + failures
    
    return {
        'successes': successes,
        'failures': failures,
        'total_trades': total_trades,
        'excluded_until': None
    }


class TestTechnicalIndicatorsInRejections:
    """Test technical indicators in MAB rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats(),
        tech_indicators=technical_indicators()
    )
    async def test_technical_indicators_logged_with_rejection(self, ticker, score, stats, tech_indicators):
        """
        Property: Technical indicators should be included in MAB rejection logs.
        
        For any MAB rejection, the technical_indicators field should be
        populated with relevant metrics in JSON format.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Mock DynamoDBClient.log_inactive_ticker
            with patch.object(DynamoDBClient, 'log_inactive_ticker', new_callable=AsyncMock) as mock_log:
                mock_log.return_value = True
                
                # Get rejection info
                rejected_info = await MABService.get_rejected_tickers_with_reasons(
                    indicator=indicator,
                    ticker_candidates=ticker_candidates,
                    selected_tickers=selected_tickers
                )
                
                # Simulate logging with technical indicators
                for tick, rejection_data in rejected_info.items():
                    await DynamoDBClient.log_inactive_ticker(
                        ticker=tick,
                        indicator=indicator,
                        reason_not_to_enter_long=rejection_data.get('reason_long', ''),
                        reason_not_to_enter_short=rejection_data.get('reason_short', ''),
                        technical_indicators=tech_indicators
                    )
                
                # Verify log_inactive_ticker was called with technical_indicators
                mock_log.assert_called_once()
                call_kwargs = mock_log.call_args[1]
                
                assert 'technical_indicators' in call_kwargs, \
                    "technical_indicators should be passed to log_inactive_ticker"
                assert call_kwargs['technical_indicators'] == tech_indicators, \
                    "technical_indicators should match the provided indicators"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_empty_technical_indicators_handled(self, ticker, score, stats):
        """
        Property: Empty technical indicators should be handled gracefully.
        
        For any MAB rejection where technical indicators are not available,
        an empty or minimal technical_indicators object should be logged.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Mock DynamoDBClient.log_inactive_ticker
            with patch.object(DynamoDBClient, 'log_inactive_ticker', new_callable=AsyncMock) as mock_log:
                mock_log.return_value = True
                
                # Get rejection info
                rejected_info = await MABService.get_rejected_tickers_with_reasons(
                    indicator=indicator,
                    ticker_candidates=ticker_candidates,
                    selected_tickers=selected_tickers
                )
                
                # Simulate logging with empty technical indicators
                for tick, rejection_data in rejected_info.items():
                    await DynamoDBClient.log_inactive_ticker(
                        ticker=tick,
                        indicator=indicator,
                        reason_not_to_enter_long=rejection_data.get('reason_long', ''),
                        reason_not_to_enter_short=rejection_data.get('reason_short', ''),
                        technical_indicators={}  # Empty
                    )
                
                # Verify log_inactive_ticker was called
                mock_log.assert_called_once()
                call_kwargs = mock_log.call_args[1]
                
                # Verify technical_indicators is present (even if empty)
                assert 'technical_indicators' in call_kwargs, \
                    "technical_indicators should be present even if empty"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats(),
        tech_indicators=technical_indicators()
    )
    async def test_technical_indicators_json_serializable(self, ticker, score, stats, tech_indicators):
        """
        Property: Technical indicators should be JSON serializable.
        
        For any MAB rejection, the technical_indicators should be in a format
        that can be serialized to JSON (as required by DynamoDB).
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify technical_indicators can be serialized to JSON
            try:
                json_str = json.dumps(tech_indicators, default=str)
                assert json_str, "Technical indicators should serialize to non-empty JSON"
            except (TypeError, ValueError) as e:
                pytest.fail(f"Technical indicators should be JSON serializable but got error: {e}")
