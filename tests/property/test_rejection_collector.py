"""
Property-based tests for RejectionCollector.

Feature: penny-stock-entry-validation
"""

from hypothesis import given, strategies as st, settings
from app.src.services.trading.validation.rejection_collector import RejectionCollector


# Feature: penny-stock-entry-validation, Property 26: Rejection collector maintains proper structure
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=('Lu',))),
    indicator=st.text(min_size=1, max_size=50),
    reason_long=st.one_of(st.none(), st.text(min_size=1, max_size=200)),
    reason_short=st.one_of(st.none(), st.text(min_size=1, max_size=200)),
    momentum=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    continuation=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
)
def test_property_26_rejection_collector_maintains_proper_structure(
    ticker, indicator, reason_long, reason_short, momentum, continuation
):
    """
    Property 26: Rejection collector maintains proper structure
    
    For any rejection added to the collector, the internal data structure should be
    a dictionary containing all required fields (ticker, indicator,
    reason_not_to_enter_long, reason_not_to_enter_short, technical_indicators, timestamp).
    
    Validates: Requirements 8.4
    """
    # Skip if both reasons are None (invalid)
    if reason_long is None and reason_short is None:
        reason_long = "test reason"
    
    collector = RejectionCollector()
    
    technical_indicators = {
        "momentum_score": momentum,
        "continuation_score": continuation
    }
    
    collector.add_rejection(
        ticker=ticker,
        indicator=indicator,
        reason_long=reason_long,
        reason_short=reason_short,
        technical_indicators=technical_indicators
    )
    
    records = collector.get_records()
    
    # Should have exactly one record
    assert len(records) == 1
    
    record = records[0]
    
    # Verify all required fields are present
    assert "ticker" in record
    assert "indicator" in record
    assert "timestamp" in record
    
    # Verify field values
    assert record["ticker"] == ticker
    assert record["indicator"] == indicator
    assert isinstance(record["timestamp"], str)
    assert len(record["timestamp"]) > 0
    
    # Verify optional fields are included when provided
    if reason_long is not None:
        assert "reason_not_to_enter_long" in record
        assert record["reason_not_to_enter_long"] == reason_long
    
    if reason_short is not None:
        assert "reason_not_to_enter_short" in record
        assert record["reason_not_to_enter_short"] == reason_short
    
    if technical_indicators is not None:
        assert "technical_indicators" in record
        assert record["technical_indicators"] == technical_indicators


# Feature: penny-stock-entry-validation, Property 27: Passing tickers excluded from rejection batch
@settings(max_examples=100)
@given(
    passing_tickers=st.lists(
        st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
        min_size=0,
        max_size=10,
        unique=True
    ),
    failing_tickers=st.lists(
        st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
        min_size=1,
        max_size=10,
        unique=True
    )
)
def test_property_27_passing_tickers_excluded_from_rejection_batch(passing_tickers, failing_tickers):
    """
    Property 27: Passing tickers excluded from rejection batch
    
    For any entry cycle with mixed results (some passing, some failing), only the
    tickers that failed validation should appear in the rejection records batch.
    
    Validates: Requirements 8.5
    """
    # Ensure no overlap between passing and failing tickers
    failing_tickers = [t for t in failing_tickers if t not in passing_tickers]
    if not failing_tickers:
        failing_tickers = ["FAIL"]
    
    collector = RejectionCollector()
    
    # Add rejections only for failing tickers
    for ticker in failing_tickers:
        collector.add_rejection(
            ticker=ticker,
            indicator="test",
            reason_long="test reason"
        )
    
    # Passing tickers are NOT added to the collector
    # (they pass validation, so no rejection record is created)
    
    records = collector.get_records()
    
    # Verify only failing tickers are in the batch
    assert len(records) == len(failing_tickers)
    
    record_tickers = {record["ticker"] for record in records}
    
    # All failing tickers should be in records
    for ticker in failing_tickers:
        assert ticker in record_tickers
    
    # No passing tickers should be in records
    for ticker in passing_tickers:
        assert ticker not in record_tickers


@settings(max_examples=100)
@given(
    num_rejections=st.integers(min_value=0, max_value=50)
)
def test_rejection_collector_count(num_rejections):
    """
    Test that rejection collector correctly counts records.
    """
    collector = RejectionCollector()
    
    for i in range(num_rejections):
        collector.add_rejection(
            ticker=f"TICK{i}",
            indicator="test",
            reason_long="test reason"
        )
    
    assert collector.count() == num_rejections
    assert collector.has_records() == (num_rejections > 0)


def test_rejection_collector_clear():
    """
    Test that clear() removes all records.
    """
    collector = RejectionCollector()
    
    collector.add_rejection(ticker="AAPL", indicator="test", reason_long="test")
    collector.add_rejection(ticker="GOOGL", indicator="test", reason_short="test")
    
    assert collector.count() == 2
    
    collector.clear()
    
    assert collector.count() == 0
    assert not collector.has_records()
    assert collector.get_records() == []


def test_rejection_collector_validates_required_fields():
    """
    Test that collector validates required fields.
    """
    collector = RejectionCollector()
    
    # Empty ticker should raise ValueError
    try:
        collector.add_rejection(ticker="", indicator="test", reason_long="test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "ticker" in str(e).lower()
    
    # Empty indicator should raise ValueError
    try:
        collector.add_rejection(ticker="AAPL", indicator="", reason_long="test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "indicator" in str(e).lower()
    
    # Both reasons None should raise ValueError
    try:
        collector.add_rejection(ticker="AAPL", indicator="test", reason_long=None, reason_short=None)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "reason" in str(e).lower()


def test_rejection_collector_get_records_returns_copy():
    """
    Test that get_records() returns a copy, not the original list.
    """
    collector = RejectionCollector()
    
    collector.add_rejection(ticker="AAPL", indicator="test", reason_long="test")
    
    records1 = collector.get_records()
    records2 = collector.get_records()
    
    # Should be equal but not the same object
    assert records1 == records2
    assert records1 is not records2
    
    # Modifying returned list should not affect collector
    records1.append({"ticker": "FAKE"})
    assert collector.count() == 1
