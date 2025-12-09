"""
Property-based tests for new ticker handling in MAB rejection logging.

Feature: mab-rejection-logging
Property 4: New Tickers Not Logged as Rejected
Validates: Requirements 1.4, 2.4
"""

import pytest
from hypothesis import given, strategies as st
from unittest.mock import AsyncMock, patch
from app.src.services.mab.mab_service import MABService


@st.composite
def ticker_symbol(draw):
    """Generate random ticker symbols."""
    return draw(st.text(
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        min_size=1,
        max_size=5
    ))


class TestNewTickerHandling:
    """Test new ticker handling in MAB rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False)
    )
    async def test_new_ticker_logged_with_exploration_reason(self, ticker, score):
        """
        Property: New tickers (no MAB stats) should be logged with exploration reason.
        
        For any new ticker with no historical MAB data that is not selected,
        it should appear in the rejection info with a reason indicating it was
        explored by Thompson Sampling.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []  # Empty - ticker is not selected
        
        # Mock the get_stats method to return None (new ticker)
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = None  # No stats = new ticker
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify the new ticker IS in rejected_info with exploration reason
            assert ticker in rejected_info, \
                f"New ticker {ticker} should be in rejected_info"
            assert "explored" in rejected_info[ticker]['reason_long'].lower() or \
                   "explored" in rejected_info[ticker]['reason_short'].lower(), \
                f"New ticker reason should mention exploration but got: {rejected_info[ticker]}"
    
    @pytest.mark.asyncio
    @given(
        tickers=st.lists(
            st.tuples(
                ticker_symbol(),
                st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
                st.just("test reason")
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0]
        )
    )
    async def test_all_new_tickers_logged_with_exploration_reason(self, tickers):
        """
        Property: All new tickers should be logged with exploration reason.
        
        For any set of new tickers (no stats) that are not selected,
        all should appear in the rejection info with exploration reasons.
        """
        indicator = "Test Indicator"
        ticker_candidates = tickers
        selected_tickers = []  # None are selected
        
        # Mock the get_stats method to return None for all (all new tickers)
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = None  # No stats = new ticker
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify all tickers are in rejected_info with exploration reason
            for ticker, _, _ in tickers:
                assert ticker in rejected_info, \
                    f"New ticker {ticker} should be in rejected_info"
                assert "explored" in rejected_info[ticker]['reason_long'].lower() or \
                       "explored" in rejected_info[ticker]['reason_short'].lower(), \
                    f"New ticker {ticker} reason should mention exploration"
    
    @pytest.mark.asyncio
    @given(
        new_ticker=ticker_symbol(),
        old_ticker=ticker_symbol(),
        new_score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        old_score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False)
    )
    async def test_mixed_new_and_old_tickers_both_logged(self, new_ticker, old_ticker, new_score, old_score):
        """
        Property: Both new and old tickers should be logged with appropriate reasons.
        
        For a mix of new and old tickers that are not selected, both should appear
        in the rejection info with appropriate reasons (exploration for new, stats for old).
        """
        # Ensure tickers are different
        if new_ticker == old_ticker:
            return
        
        indicator = "Test Indicator"
        ticker_candidates = [
            (new_ticker, new_score, "new ticker"),
            (old_ticker, old_score, "old ticker")
        ]
        selected_tickers = []  # None are selected
        
        # Mock the get_stats method
        async def mock_get_stats_impl(ind, tick):
            if tick == new_ticker:
                return None  # New ticker
            else:
                return {  # Old ticker with stats
                    'successes': 5,
                    'failures': 5,
                    'total_trades': 10,
                    'excluded_until': None
                }
        
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.side_effect = mock_get_stats_impl
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify both tickers are in rejected_info
            assert new_ticker in rejected_info, \
                f"New ticker {new_ticker} should be in rejected_info"
            assert old_ticker in rejected_info, \
                f"Old ticker {old_ticker} should be in rejected_info"
            
            # Verify new ticker has exploration reason
            assert "explored" in rejected_info[new_ticker]['reason_long'].lower() or \
                   "explored" in rejected_info[new_ticker]['reason_short'].lower(), \
                f"New ticker reason should mention exploration"
            
            # Verify old ticker has MAB rejection reason
            assert "MAB rejected" in rejected_info[old_ticker]['reason_long'] or \
                   "MAB rejected" in rejected_info[old_ticker]['reason_short'], \
                f"Old ticker reason should mention MAB rejection"
