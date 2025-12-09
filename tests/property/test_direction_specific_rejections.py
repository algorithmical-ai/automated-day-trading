"""
Property-based tests for direction-specific rejection handling in MAB rejection logging.

Feature: mab-rejection-logging
Property 7: Direction-Specific Rejection Handling
Validates: Requirements 5.3
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


class TestDirectionSpecificRejections:
    """Test direction-specific rejection handling."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_long_rejection_only_populates_reason_long(self, ticker, score, stats):
        """
        Property: Long rejections should only populate reason_not_to_enter_long.
        
        For any ticker with positive momentum score that is rejected,
        reason_long should be populated and reason_short should be empty.
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
            
            # Verify direction-specific fields
            assert rejected_info[ticker]['reason_long'], \
                "reason_long should be populated for long rejection"
            assert rejected_info[ticker]['reason_short'] == '', \
                "reason_short should be empty for long rejection"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_short_rejection_only_populates_reason_short(self, ticker, score, stats):
        """
        Property: Short rejections should only populate reason_not_to_enter_short.
        
        For any ticker with negative momentum score that is rejected,
        reason_short should be populated and reason_long should be empty.
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
            
            # Verify direction-specific fields
            assert rejected_info[ticker]['reason_short'], \
                "reason_short should be populated for short rejection"
            assert rejected_info[ticker]['reason_long'] == '', \
                "reason_long should be empty for short rejection"
    
    @pytest.mark.asyncio
    @given(
        long_ticker=ticker_symbol(),
        short_ticker=ticker_symbol(),
        long_score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        short_score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_both_directions_rejected_both_fields_populated(self, long_ticker, short_ticker, long_score, short_score, stats):
        """
        Property: When both directions are rejected, both fields should be populated.
        
        For a mix of long and short rejections, each should have the
        appropriate field populated.
        """
        # Ensure tickers are different
        if long_ticker == short_ticker:
            return
        
        indicator = "Test Indicator"
        ticker_candidates = [
            (long_ticker, long_score, "long reason"),
            (short_ticker, short_score, "short reason")
        ]
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
            
            # Verify long ticker
            assert rejected_info[long_ticker]['reason_long'], \
                "reason_long should be populated for long ticker"
            assert rejected_info[long_ticker]['reason_short'] == '', \
                "reason_short should be empty for long ticker"
            
            # Verify short ticker
            assert rejected_info[short_ticker]['reason_short'], \
                "reason_short should be populated for short ticker"
            assert rejected_info[short_ticker]['reason_long'] == '', \
                "reason_long should be empty for short ticker"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False)
    )
    async def test_selected_long_ticker_not_logged(self, ticker, score):
        """
        Property: Selected long tickers should not be logged.
        
        For any ticker that is selected by MAB for long entry, it should not
        appear in the rejection info.
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
            f"Selected ticker {ticker} should not be in rejected_info"
