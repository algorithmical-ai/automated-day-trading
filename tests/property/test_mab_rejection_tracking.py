"""
Property-based tests for MAB rejection tracking.

Feature: mab-rejection-logging
Property 1: MAB Rejection Logging for Long Positions
Validates: Requirements 1.1, 5.1
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
def momentum_score(draw):
    """Generate random momentum scores."""
    return draw(st.floats(min_value=-15.0, max_value=15.0, allow_nan=False, allow_infinity=False))


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


class TestMABRejectionTracking:
    """Test MAB rejection tracking."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_rejected_tickers_for_long_position(self, ticker, score, stats):
        """
        Property: Tickers rejected by MAB for long entry should have reason_long populated.
        
        For any ticker with positive momentum score that is rejected by MAB,
        the rejection info should have reason_long populated and reason_short empty.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []  # Empty - all candidates are rejected
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
        
        # Verify the ticker is in rejected_info
        assert ticker in rejected_info, f"Ticker {ticker} should be in rejected_info"
        
        # Verify reason_long is populated
        assert rejected_info[ticker]['reason_long'], \
            f"reason_long should be populated for long position but got: {rejected_info[ticker]}"
        
        # Verify reason_short is empty
        assert rejected_info[ticker]['reason_short'] == '', \
            f"reason_short should be empty for long position but got: {rejected_info[ticker]['reason_short']}"
        
        # Verify momentum_score is preserved
        assert rejected_info[ticker]['momentum_score'] == score, \
            f"momentum_score should be {score} but got: {rejected_info[ticker]['momentum_score']}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_rejected_tickers_for_short_position(self, ticker, score, stats):
        """
        Property: Tickers rejected by MAB for short entry should have reason_short populated.
        
        For any ticker with negative momentum score that is rejected by MAB,
        the rejection info should have reason_short populated and reason_long empty.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []  # Empty - all candidates are rejected
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
        
        # Verify the ticker is in rejected_info
        assert ticker in rejected_info, f"Ticker {ticker} should be in rejected_info"
        
        # Verify reason_short is populated
        assert rejected_info[ticker]['reason_short'], \
            f"reason_short should be populated for short position but got: {rejected_info[ticker]}"
        
        # Verify reason_long is empty
        assert rejected_info[ticker]['reason_long'] == '', \
            f"reason_long should be empty for short position but got: {rejected_info[ticker]['reason_long']}"
        
        # Verify momentum_score is preserved
        assert rejected_info[ticker]['momentum_score'] == score, \
            f"momentum_score should be {score} but got: {rejected_info[ticker]['momentum_score']}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False)
    )
    async def test_selected_tickers_not_in_rejected_info(self, ticker, score):
        """
        Property: Tickers selected by MAB should not appear in rejected_info.
        
        For any ticker that is selected by MAB, it should not appear in the
        rejection info dictionary.
        """
        indicator = "Test Indicator"
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
            f"Selected ticker {ticker} should not be in rejected_info but got: {rejected_info}"
    
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
            unique_by=lambda x: x[0]  # Unique tickers
        )
    )
    async def test_rejection_info_contains_all_rejected_tickers(self, tickers):
        """
        Property: Rejection info should contain all tickers that are not selected.
        
        For any set of candidates where none are selected, the rejection info
        should contain all of them.
        """
        indicator = "Test Indicator"
        ticker_candidates = tickers
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
        for ticker, _, _ in tickers:
            assert ticker in rejected_info, \
                f"Ticker {ticker} should be in rejected_info but got: {list(rejected_info.keys())}"
    
    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty_rejected_info(self):
        """
        Property: Empty candidate list should return empty rejection info.
        
        For an empty list of candidates, the rejection info should be empty.
        """
        indicator = "Test Indicator"
        ticker_candidates = []
        selected_tickers = []
        
        # Get rejection info
        rejected_info = await MABService.get_rejected_tickers_with_reasons(
            indicator=indicator,
            ticker_candidates=ticker_candidates,
            selected_tickers=selected_tickers
        )
        
        # Verify rejection info is empty
        assert rejected_info == {}, \
            f"Rejection info should be empty but got: {rejected_info}"
