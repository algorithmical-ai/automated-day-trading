"""
Property-based tests for MAB long position rejection logging.

Feature: mab-rejection-logging
Property 1: MAB Rejection Logging for Long Positions
Validates: Requirements 1.1, 5.1
"""

import pytest
from hypothesis import given, strategies as st
from unittest.mock import AsyncMock, patch, MagicMock
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


class TestMABLongRejectionLogging:
    """Test MAB long position rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_long_rejection_logged_with_reason_long_populated(self, ticker, score, stats):
        """
        Property: Long position MAB rejections should have reason_long populated.
        
        For any ticker with positive momentum score that is rejected by MAB,
        the log entry should have reason_not_to_enter_long populated and
        reason_not_to_enter_short empty.
        """
        indicator = "Penny Stocks"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []  # Empty - all candidates are rejected
        
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
                
                # Verify rejection info
                assert ticker in rejected_info
                assert rejected_info[ticker]['reason_long'], \
                    "reason_long should be populated for long position"
                assert rejected_info[ticker]['reason_short'] == '', \
                    "reason_short should be empty for long position"
                
                # Simulate logging (as would happen in the indicator)
                for tick, rejection_data in rejected_info.items():
                    await DynamoDBClient.log_inactive_ticker(
                        ticker=tick,
                        indicator=indicator,
                        reason_not_to_enter_long=rejection_data.get('reason_long', ''),
                        reason_not_to_enter_short=rejection_data.get('reason_short', ''),
                        technical_indicators={}
                    )
                
                # Verify log_inactive_ticker was called with correct parameters
                mock_log.assert_called_once()
                call_kwargs = mock_log.call_args[1]
                
                assert call_kwargs['ticker'] == ticker
                assert call_kwargs['indicator'] == indicator
                assert call_kwargs['reason_not_to_enter_long'], \
                    "reason_not_to_enter_long should be populated"
                assert call_kwargs['reason_not_to_enter_short'] == '', \
                    "reason_not_to_enter_short should be empty"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_long_rejection_reason_contains_mab_prefix(self, ticker, score, stats):
        """
        Property: Long rejection reason should contain "MAB rejected:" prefix.
        
        For any long position rejection, the reason_not_to_enter_long should
        start with "MAB rejected:" to clearly indicate it's a MAB rejection.
        """
        indicator = "Penny Stocks"
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
            
            # Verify reason_long contains MAB prefix
            reason_long = rejected_info[ticker]['reason_long']
            assert reason_long.startswith("MAB rejected:"), \
                f"reason_long should start with 'MAB rejected:' but got: {reason_long}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_long_rejection_reason_includes_stats(self, ticker, score, stats):
        """
        Property: Long rejection reason should include success/failure stats.
        
        For any long position rejection, the reason_not_to_enter_long should
        include the success count, failure count, and total trades.
        """
        indicator = "Penny Stocks"
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
            
            # Verify reason_long contains stats
            reason_long = rejected_info[ticker]['reason_long']
            assert "successes:" in reason_long, \
                f"reason_long should contain 'successes:' but got: {reason_long}"
            assert "failures:" in reason_long, \
                f"reason_long should contain 'failures:' but got: {reason_long}"
            assert "total:" in reason_long, \
                f"reason_long should contain 'total:' but got: {reason_long}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False)
    )
    async def test_long_selected_ticker_not_logged(self, ticker, score):
        """
        Property: Long tickers selected by MAB should not be logged as rejected.
        
        For any ticker that is selected by MAB for long entry, it should not
        appear in the rejection info and should not be logged.
        """
        indicator = "Penny Stocks"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = [ticker]  # Ticker is selected
        
        # Get rejection info
        rejected_info = await MABService.get_rejected_tickers_with_reasons(
            indicator=indicator,
            ticker_candidates=ticker_candidates,
            selected_tickers=selected_tickers
        )
        
        # Verify the ticker is NOT in rejected_info
        assert ticker not in rejected_info, \
            f"Selected ticker {ticker} should not be in rejected_info"
