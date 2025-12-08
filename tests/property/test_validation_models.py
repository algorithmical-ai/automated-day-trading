"""
Property-based tests for validation data models.

Feature: penny-stock-entry-validation
"""

from hypothesis import given, strategies as st, settings
from app.src.services.trading.validation.models import (
    TrendMetrics,
    QuoteData,
    ValidationResult,
    RejectionRecord
)


# Feature: penny-stock-entry-validation, Property 19: Rejection records contain required fields
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=('Lu',))),
    indicator=st.text(min_size=1, max_size=50),
    reason_long=st.one_of(st.none(), st.text(min_size=1, max_size=200)),
    reason_short=st.one_of(st.none(), st.text(min_size=1, max_size=200)),
    momentum=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    continuation=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    peak=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    bottom=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False)
)
def test_property_19_rejection_records_contain_required_fields(
    ticker: str,
    indicator: str,
    reason_long: str,
    reason_short: str,
    momentum: float,
    continuation: float,
    peak: float,
    bottom: float
):
    """
    Property 19: Rejection records contain required fields
    
    For any rejection record written to the database, it should contain
    ticker symbol, indicator name, timestamp, and technical indicators fields.
    
    Validates: Requirements 7.2
    """
    # Create technical indicators
    technical_indicators = {
        "momentum_score": momentum,
        "continuation_score": continuation,
        "peak_price": peak,
        "bottom_price": bottom
    }
    
    # Create rejection record
    record = RejectionRecord(
        ticker=ticker,
        indicator=indicator,
        reason_not_to_enter_long=reason_long,
        reason_not_to_enter_short=reason_short,
        technical_indicators=technical_indicators
    )
    
    # Convert to dictionary (as would be written to database)
    record_dict = record.to_dict()
    
    # Verify required fields are present
    assert "ticker" in record_dict, "ticker field must be present"
    assert "indicator" in record_dict, "indicator field must be present"
    assert "timestamp" in record_dict, "timestamp field must be present"
    
    # Verify field values
    assert record_dict["ticker"] == ticker
    assert record_dict["indicator"] == indicator
    assert isinstance(record_dict["timestamp"], str)
    assert len(record_dict["timestamp"]) > 0
    
    # Verify technical indicators are included when provided
    if technical_indicators is not None:
        assert "technical_indicators" in record_dict
        assert record_dict["technical_indicators"] == technical_indicators
    
    # Verify optional reason fields are included when provided
    if reason_long is not None:
        assert "reason_not_to_enter_long" in record_dict
        assert record_dict["reason_not_to_enter_long"] == reason_long
    
    if reason_short is not None:
        assert "reason_not_to_enter_short" in record_dict
        assert record_dict["reason_not_to_enter_short"] == reason_short


@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=('Lu',))),
    bid=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    ask=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False)
)
def test_quote_data_from_bid_ask_calculation(ticker: str, bid: float, ask: float):
    """
    Test that QuoteData correctly calculates mid_price and spread_percent.
    """
    # Ensure ask >= bid for valid quote
    if ask < bid:
        bid, ask = ask, bid
    
    quote = QuoteData.from_bid_ask(ticker, bid, ask)
    
    # Verify calculations
    expected_mid = (bid + ask) / 2.0
    expected_spread_percent = ((ask - bid) / expected_mid) * 100
    
    assert quote.ticker == ticker
    assert abs(quote.mid_price - expected_mid) < 0.0001
    assert abs(quote.spread_percent - expected_spread_percent) < 0.01


@settings(max_examples=100)
@given(
    momentum=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    continuation=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    peak=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    bottom=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False)
)
def test_trend_metrics_to_dict(momentum: float, continuation: float, peak: float, bottom: float):
    """
    Test that TrendMetrics correctly converts to dictionary.
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=continuation,
        peak_price=peak,
        bottom_price=bottom,
        reason="test reason"
    )
    
    metrics_dict = metrics.to_dict()
    
    assert metrics_dict["momentum_score"] == momentum
    assert metrics_dict["continuation_score"] == continuation
    assert metrics_dict["peak_price"] == peak
    assert metrics_dict["bottom_price"] == bottom
    assert metrics_dict["reason"] == "test reason"
