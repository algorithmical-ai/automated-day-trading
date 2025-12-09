"""
Property-based tests for Momentum Indicator MAB rejection logging.

Feature: mab-rejection-logging
Property 1: MAB Rejection Logging for Long Positions
Validates: Requirements 1.1, 5.1
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


class TestMomentumIndicatorMABRejectionLogging:
    """Test Momentum Indicator MAB rejection logging."""
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=1.5, max_value=15.0, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_momentum_long_rejection_logged(self, ticker, score, stats):
        """
        Property: Momentum indicator should log long position MAB rejections.
        
        For any ticker with positive momentum score that is rejected by MAB,
        the log entry should have reason_not_to_enter_long populated.
        """
        indicator = "Momentum Trading"
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
            
            # Verify rejection info
            assert ticker in rejected_info
            assert rejected_info[ticker]['reason_long'], \
                "reason_long should be populated for long position"
            assert rejected_info[ticker]['reason_short'] == '', \
                "reason_short should be empty for long position"
    
    @pytest.mark.asyncio
    @given(
        ticker=ticker_symbol(),
        score=st.floats(min_value=-15.0, max_value=-1.5, allow_nan=False, allow_infinity=False),
        stats=mab_stats()
    )
    async def test_momentum_short_rejection_logged(self, ticker, score, stats):
        """
        Property: Momentum indicator should log short position MAB rejections.
        
        For any ticker with negative momentum score that is rejected by MAB,
        the log entry should have reason_not_to_enter_short populated.
        """
        indicator = "Momentum Trading"
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
            
            # Verify rejection info
            assert ticker in rejected_info
            assert rejected_info[ticker]['reason_short'], \
                "reason_short should be populated for short position"
            assert rejected_info[ticker]['reason_long'] == '', \
                "reason_long should be empty for short position"
    
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
    async def test_momentum_multiple_rejections_logged(self, tickers):
        """
        Property: Momentum indicator should log all MAB rejections.
        
        For any set of candidates where none are selected, all should be
        logged as rejected.
        """
        indicator = "Momentum Trading"
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
                    f"Ticker {ticker} should be in rejected_info"
