"""
Property-based tests for MAB rejection reason format.

Feature: mab-rejection-logging
Property 2: MAB Rejection Reason Format
Validates: Requirements 1.2, 2.2, 3.2, 3.3
"""

from hypothesis import given, strategies as st
from app.src.services.mab.mab_service import MABService


# Strategy for generating MAB statistics
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


@st.composite
def ticker_symbol(draw):
    """Generate random ticker symbols."""
    return draw(st.text(
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        min_size=1,
        max_size=5
    ))


class TestMABRejectionReasonFormat:
    """Test MAB rejection reason format."""
    
    @given(stats=mab_stats(), ticker=ticker_symbol())
    def test_rejection_reason_contains_mab_prefix(self, stats, ticker):
        """
        Property: MAB rejection reason should contain "MAB rejected:" prefix.
        
        For any MAB statistics and ticker, the rejection reason should start
        with "MAB rejected:" to clearly indicate it's a MAB rejection.
        """
        reason = MABService.get_rejection_reason(stats, ticker)
        assert reason.startswith("MAB rejected:"), \
            f"Reason should start with 'MAB rejected:' but got: {reason}"
    
    @given(stats=mab_stats(), ticker=ticker_symbol())
    def test_rejection_reason_contains_success_rate(self, stats, ticker):
        """
        Property: MAB rejection reason should include success rate information.
        
        For any MAB statistics, the rejection reason should contain the
        success count, failure count, and total trades.
        """
        reason = MABService.get_rejection_reason(stats, ticker)
        
        # Verify the reason contains success/failure/total information
        assert "successes:" in reason, \
            f"Reason should contain 'successes:' but got: {reason}"
        assert "failures:" in reason, \
            f"Reason should contain 'failures:' but got: {reason}"
        assert "total:" in reason, \
            f"Reason should contain 'total:' but got: {reason}"
    
    @given(stats=mab_stats(), ticker=ticker_symbol())
    def test_rejection_reason_contains_correct_counts(self, stats, ticker):
        """
        Property: MAB rejection reason should contain correct success/failure counts.
        
        For any MAB statistics, the rejection reason should include the exact
        success and failure counts from the stats.
        """
        reason = MABService.get_rejection_reason(stats, ticker)
        
        successes = stats['successes']
        failures = stats['failures']
        total = stats['total_trades']
        
        # Verify the counts appear in the reason
        assert f"successes: {successes}" in reason, \
            f"Reason should contain 'successes: {successes}' but got: {reason}"
        assert f"failures: {failures}" in reason, \
            f"Reason should contain 'failures: {failures}' but got: {reason}"
        assert f"total: {total}" in reason, \
            f"Reason should contain 'total: {total}' but got: {reason}"
    
    def test_rejection_reason_for_new_ticker(self):
        """
        Property: New ticker (no stats) should indicate exploration.
        
        For a new ticker with no MAB statistics, the reason should indicate
        it's being explored by Thompson Sampling.
        """
        reason = MABService.get_rejection_reason(None, "NEWCO")
        
        assert "New ticker" in reason or "explored" in reason, \
            f"Reason for new ticker should mention exploration but got: {reason}"
        assert "successes: 0" in reason, \
            f"New ticker should have 0 successes but got: {reason}"
        assert "failures: 0" in reason, \
            f"New ticker should have 0 failures but got: {reason}"
    
    @given(stats=mab_stats(), ticker=ticker_symbol())
    def test_rejection_reason_format_consistency(self, stats, ticker):
        """
        Property: Rejection reason format should be consistent.
        
        For any MAB statistics, the rejection reason should follow the
        consistent format with parentheses containing the counts.
        """
        reason = MABService.get_rejection_reason(stats, ticker)
        
        # Verify format: "MAB rejected: ... (successes: X, failures: Y, total: Z)"
        assert "(" in reason and ")" in reason, \
            f"Reason should contain parentheses for counts but got: {reason}"
        
        # Extract the part in parentheses
        paren_start = reason.rfind("(")
        paren_end = reason.rfind(")")
        assert paren_start < paren_end, \
            f"Parentheses should be properly ordered in: {reason}"
