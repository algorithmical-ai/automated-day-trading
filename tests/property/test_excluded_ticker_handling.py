"""
Property-based tests for excluded ticker handling in MAB rejection logging.

Feature: mab-rejection-logging
Property 5: Excluded Tickers Logged with Exclusion Reason
Validates: Requirements 1.3, 2.3
"""

import pytest
from hypothesis import given, strategies as st
from datetime import datetime, timedelta, timezone
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
def future_timestamp(draw):
    """Generate a future timestamp."""
    hours_ahead = draw(st.integers(min_value=1, max_value=24))
    future_time = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return future_time.isoformat()


class TestExcludedTickerHandling:
    """Test excluded ticker handling in MAB rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        excluded_until=future_timestamp()
    )
    async def test_excluded_ticker_logged_with_exclusion_reason(self, ticker, score, excluded_until):
        """
        Property: Excluded tickers should be logged with exclusion reason.
        
        For any ticker that is excluded (has excluded_until in future),
        the rejection reason should mention exclusion status.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []  # Empty - ticker is not selected
        
        # Create stats with exclusion
        stats = {
            'successes': 0,
            'failures': 0,
            'total_trades': 0,
            'excluded_until': excluded_until
        }
        
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
            assert ticker in rejected_info, \
                f"Excluded ticker {ticker} should be in rejected_info"
            
            # Verify the reason mentions exclusion
            reason = rejected_info[ticker]['reason_long'] or rejected_info[ticker]['reason_short']
            assert "Excluded" in reason or "excluded" in reason, \
                f"Reason should mention exclusion but got: {reason}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        excluded_until=future_timestamp()
    )
    async def test_excluded_ticker_reason_includes_end_time(self, ticker, score, excluded_until):
        """
        Property: Excluded ticker reason should include exclusion end time.
        
        For any excluded ticker, the rejection reason should include the
        excluded_until timestamp.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []
        
        # Create stats with exclusion
        stats = {
            'successes': 0,
            'failures': 0,
            'total_trades': 0,
            'excluded_until': excluded_until
        }
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify the reason includes the end time
            reason = rejected_info[ticker]['reason_long'] or rejected_info[ticker]['reason_short']
            assert excluded_until in reason, \
                f"Reason should include excluded_until time but got: {reason}"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        excluded_until=future_timestamp()
    )
    async def test_excluded_short_ticker_logged(self, ticker, score, excluded_until):
        """
        Property: Excluded short tickers should be logged with reason_short populated.
        
        For any excluded ticker with negative momentum score, the rejection
        reason should be in reason_short field.
        """
        indicator = "Test Indicator"
        ticker_candidates = [(ticker, score, "test reason")]
        selected_tickers = []
        
        # Create stats with exclusion
        stats = {
            'successes': 0,
            'failures': 0,
            'total_trades': 0,
            'excluded_until': excluded_until
        }
        
        # Mock the get_stats method
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = stats
            
            # Get rejection info
            rejected_info = await MABService.get_rejected_tickers_with_reasons(
                indicator=indicator,
                ticker_candidates=ticker_candidates,
                selected_tickers=selected_tickers
            )
            
            # Verify reason_short is populated
            assert rejected_info[ticker]['reason_short'], \
                "reason_short should be populated for excluded short ticker"
            
            # Verify reason_long is empty
            assert rejected_info[ticker]['reason_long'] == '', \
                "reason_long should be empty for excluded short ticker"
