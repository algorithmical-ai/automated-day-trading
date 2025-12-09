"""
Property-based tests for selected ticker exclusion from rejection logging.

Feature: mab-rejection-logging
Property 8: Selected Tickers Not Logged
Validates: Requirements 5.4
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


class TestSelectedTickerExclusion:
    """Test selected ticker exclusion from rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_selected_ticker_not_logged(self, ticker, score, stats):
        """
        Property: Selected tickers should not be logged as rejected.
        
        For any ticker that is selected by MAB, it should not appear in
        the rejection info and should not be logged.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = [ticker]  # Ticker is selected
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify the ticker is NOT in rejected_info
            assert ticker not in rejected_info, \
                f"Selected ticker {ticker} should not be in rejected_info"
    
    @pytest.mark.asyncio
    @given(
        tickers=st.lists(
            st.tuples(
                ticker_symbol(),
                st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
                st.just("test reason")
            ),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0]
        )
    )
    async def test_all_selected_tickers_not_logged(self, tickers):
        """
        Property: All selected tickers should not be logged.
        
        For any set of tickers where all are selected, none should appear
        in the rejection info.
        """
        indicator = "Test Indicator"
        ticker_candidates = tickers
        selected_tickers = [t[0] for t in tickers]  # All are selected
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = {
                'successes': 0,
                'failures': 0,
                'total_trades': 0,
                'excluded_until': None
            }
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify no tickers are in rejected_info
            assert rejected_info == {}, \
                f"No selected tickers should be in rejected_info but got: {rejected_info}"
    
    @pytest.mark.asyncio
    @given(
        selected_ticker=ticker_symbol(),
        rejected_ticker=ticker_symbol(),
        selected_score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        rejected_score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_mixed_selected_and_rejected_tickers(self, selected_ticker, rejected_ticker, selected_score, rejected_score, stats):
        """
        Property: Only rejected tickers should be logged, not selected ones.
        
        For a mix of selected and rejected tickers, only the rejected ones
        should appear in the rejection info.
        """
        # Ensure tickers are different
        if selected_ticker == rejected_ticker:
            return
        
        indicator = "Test Indicator"
        ticker_candidates = [
            (selected_ticker, selected_score, "selected"),
            (rejected_ticker, rejected_score, "rejected")
        ]
        selected_tickers = [selected_ticker]  # Only one is selected
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify selected ticker is NOT in rejected_info
            assert selected_ticker not in rejected_info, \
                f"Selected ticker {selected_ticker} should not be in rejected_info"
            
            # Verify rejected ticker IS in rejected_info
            assert rejected_ticker in rejected_info, \
                f"Rejected ticker {rejected_ticker} should be in rejected_info"
    
    @pytest.mark.asyncio
    async def test_empty_selected_tickers_all_logged(self):
        """
        Property: When no tickers are selected, all should be logged as rejected.
        
        For an empty selected_tickers list, all candidates should appear
        in the rejection info.
        """
        indicator = "Test Indicator"
        ticker_candidates = [
            ("AAPL", 2.5, "reason1"),
            ("BBBB", 3.0, "reason2"),
            ("CCCC", 1.8, "reason3")
        ]
        selected_tickers = []  # None are selected
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = {
                'successes': 0,
                'failures': 0,
                'total_trades': 0,
                'excluded_until': None
            }
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify all tickers are in rejected_info
            for ticker, _, _ in ticker_candidates:
                assert ticker in rejected_info, \
                    f"Ticker {ticker} should be in rejected_info when not selected"
