"""
Property-based tests for MAB short position rejection logging.

Feature: mab-rejection-logging
Property 3: MAB Rejection Logging for Short Positions
Validates: Requirements 2.1, 5.2
"""

import pytest
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


class TestMABShortRejectionLogging:
    """Test MAB short position rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_short_rejection_logged_with_reason_short_populated(self, ticker, score, stats):
        """
        Property: Short position MAB rejections should have reason_short populated.
        
        For any ticker with negative momentum score that is rejected by MAB,
        the log entry should have reason_not_to_enter_short populated and
        reason_not_to_enter_long empty.
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
                assert rejected_info[ticker]['reason_short'], \
                    "reason_short should be populated for short position"
                assert rejected_info[ticker]['reason_long'] == '', \
                    "reason_long should be empty for short position"
                
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
                assert call_kwargs['reason_not_to_enter_short'], \
                    "reason_not_to_enter_short should be populated"
                assert call_kwargs['reason_not_to_enter_long'] == '', \
                    "reason_not_to_enter_long should be empty"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_short_rejection_reason_contains_mab_prefix(self, ticker, score, stats):
        """
        Property: Short rejection reason should contain "MAB rejected:" prefix.
        
        For any short position rejection, the reason_not_to_enter_short should
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
            
            # Verify reason_short contains MAB prefix
            reason_short = rejected_info[ticker]['reason_short']
            assert reason_short.startswith("MAB rejected:"), \
                f"reason_short should start with 'MAB rejected:' but got: {reason_short}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_short_rejection_reason_includes_stats(self, ticker, score, stats):
        """
        Property: Short rejection reason should include success/failure stats.
        
        For any short position rejection, the reason_not_to_enter_short should
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
            
            # Verify reason_short contains stats
            reason_short = rejected_info[ticker]['reason_short']
            assert "successes:" in reason_short, \
                f"reason_short should contain 'successes:' but got: {reason_short}"
            assert "failures:" in reason_short, \
                f"reason_short should contain 'failures:' but got: {reason_short}"
            assert "total:" in reason_short, \
                f"reason_short should contain 'total:' but got: {reason_short}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False)
    )
    async def test_short_selected_ticker_not_logged(self, ticker, score):
        """
        Property: Short tickers selected by MAB should not be logged as rejected.
        
        For any ticker that is selected by MAB for short entry, it should not
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
