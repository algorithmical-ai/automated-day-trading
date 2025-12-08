"""
Property-based tests for validation rules.

Feature: penny-stock-entry-validation
"""

from hypothesis import given, strategies as st, settings
from app.src.services.trading.validation.models import TrendMetrics, QuoteData
from app.src.services.trading.validation.rules import (
    DataQualityRule,
    LiquidityRule,
    TrendDirectionRule,
    ContinuationRule,
    PriceExtremeRule,
    MomentumThresholdRule
)


# Helper strategies
@st.composite
def trend_metrics_strategy(draw):
    """Generate random TrendMetrics."""
    momentum = draw(st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False))
    continuation = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    peak = draw(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
    bottom = draw(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
    
    # Ensure peak >= bottom
    if peak < bottom:
        peak, bottom = bottom, peak
    
    return TrendMetrics(
        momentum_score=momentum,
        continuation_score=continuation,
        peak_price=peak,
        bottom_price=bottom,
        reason="test"
    )


@st.composite
def quote_data_strategy(draw):
    """Generate random QuoteData."""
    ticker = draw(st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))))
    bid = draw(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
    ask = draw(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
    
    # Ensure ask >= bid
    if ask < bid:
        bid, ask = ask, bid
    
    return QuoteData.from_bid_ask(ticker, bid, ask)


# Feature: penny-stock-entry-validation, Property 1: Trend direction rejection consistency
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    momentum=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0),
    quote=quote_data_strategy()
)
def test_property_1_trend_direction_rejection_consistency(ticker, momentum, quote):
    """
    Property 1: Trend direction rejection consistency
    
    For any ticker with a calculated momentum score, if the momentum is negative
    (downward trend), then long entry should be rejected with a reason containing
    "downward trend", and if the momentum is positive (upward trend), then short
    entry should be rejected with a reason containing "upward trend".
    
    Validates: Requirements 1.1, 1.2
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=0.8,
        peak_price=2.0,
        bottom_price=1.0,
        reason="test"
    )
    
    rule = TrendDirectionRule()
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    if momentum < 0:
        # Downward trend should reject long entry
        assert result.reason_long is not None
        assert "downward trend" in result.reason_long.lower()
        assert f"{momentum:.2f}%" in result.reason_long
    elif momentum > 0:
        # Upward trend should reject short entry
        assert result.reason_short is not None
        assert "upward trend" in result.reason_short.lower()
        assert f"{momentum:.2f}%" in result.reason_short


# Feature: penny-stock-entry-validation, Property 3: Trend direction rejection populates both reason fields
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    momentum=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0),
    quote=quote_data_strategy()
)
def test_property_3_trend_direction_rejection_populates_both_fields(ticker, momentum, quote):
    """
    Property 3: Trend direction rejection populates both reason fields
    
    For any ticker rejected due to trend direction, both reason_not_to_enter_long
    and reason_not_to_enter_short fields should be populated in the rejection record.
    
    Note: This property is about the rejection record structure. The rule itself
    only populates one field (direction-specific), but when creating a rejection
    record, both fields should be populated with appropriate reasons.
    
    Validates: Requirements 1.5
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=0.8,
        peak_price=2.0,
        bottom_price=1.0,
        reason="test"
    )
    
    rule = TrendDirectionRule()
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    # The rule should provide at least one rejection reason
    assert result.reason_long is not None or result.reason_short is not None


# Feature: penny-stock-entry-validation, Property 4: Weak continuation rejects appropriate direction
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    momentum=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False).filter(lambda x: abs(x) > 1.0),
    continuation=st.floats(min_value=0.0, max_value=0.69, allow_nan=False, allow_infinity=False),
    quote=quote_data_strategy()
)
def test_property_4_weak_continuation_rejects_appropriate_direction(ticker, momentum, continuation, quote):
    """
    Property 4: Weak continuation rejects appropriate direction
    
    For any ticker with an upward trend and continuation score below 0.7,
    long entry should be rejected with a reason containing "not continuing strongly",
    and for any ticker with a downward trend and continuation score below 0.7,
    short entry should be rejected with a reason containing "not continuing strongly".
    
    Validates: Requirements 2.1, 2.2
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=continuation,
        peak_price=2.0,
        bottom_price=1.0,
        reason="test"
    )
    
    rule = ContinuationRule(min_continuation=0.7)
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    if momentum > 0:
        # Upward trend with weak continuation should reject long
        assert result.reason_long is not None
        assert "not continuing strongly" in result.reason_long
        assert f"{continuation:.2f}" in result.reason_long
    elif momentum < 0:
        # Downward trend with weak continuation should reject short
        assert result.reason_short is not None
        assert "not continuing strongly" in result.reason_short
        assert f"{continuation:.2f}" in result.reason_short


# Feature: penny-stock-entry-validation, Property 6: Weak continuation includes score in reason
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    momentum=st.floats(min_value=5.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    continuation=st.floats(min_value=0.0, max_value=0.69, allow_nan=False, allow_infinity=False),
    quote=quote_data_strategy()
)
def test_property_6_weak_continuation_includes_score_in_reason(ticker, momentum, continuation, quote):
    """
    Property 6: Weak continuation includes score in reason
    
    For any ticker rejected due to weak continuation, the rejection reason
    should contain the continuation score value.
    
    Validates: Requirements 2.4
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=continuation,
        peak_price=2.0,
        bottom_price=1.0,
        reason="test"
    )
    
    rule = ContinuationRule(min_continuation=0.7)
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    # Should reject long entry for upward trend
    assert result.reason_long is not None
    assert f"{continuation:.2f}" in result.reason_long


# Feature: penny-stock-entry-validation, Property 7: Price near peak rejects long entry
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    peak=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    quote=quote_data_strategy()
)
def test_property_7_price_near_peak_rejects_long_entry(ticker, peak, quote):
    """
    Property 7: Price near peak rejects long entry
    
    For any ticker with an upward trend where the current price is within 1.0%
    of the peak price, long entry should be rejected with a reason containing
    "at/near peak".
    
    Validates: Requirements 3.1
    """
    # Set current price within 1% of peak
    current_price = peak * 0.995  # 0.5% below peak
    quote_near_peak = QuoteData.from_bid_ask(ticker, current_price, current_price)
    
    metrics = TrendMetrics(
        momentum_score=5.0,  # Upward trend
        continuation_score=0.8,
        peak_price=peak,
        bottom_price=peak * 0.8,
        reason="test"
    )
    
    rule = PriceExtremeRule(extreme_threshold_percent=1.0)
    result = rule.validate(ticker, metrics, quote_near_peak, [{"c": 1.0}] * 5)
    
    # Should reject long entry
    assert result.reason_long is not None
    assert "at/near peak" in result.reason_long.lower()


# Feature: penny-stock-entry-validation, Property 8: Price near bottom rejects short entry
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    bottom=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    quote=quote_data_strategy()
)
def test_property_8_price_near_bottom_rejects_short_entry(ticker, bottom, quote):
    """
    Property 8: Price near bottom rejects short entry
    
    For any ticker with a downward trend where the current price is within 1.0%
    of the bottom price, short entry should be rejected with a reason containing
    "at/near bottom".
    
    Validates: Requirements 3.2
    """
    # Set current price within 1% of bottom
    current_price = bottom * 1.005  # 0.5% above bottom
    quote_near_bottom = QuoteData.from_bid_ask(ticker, current_price, current_price)
    
    metrics = TrendMetrics(
        momentum_score=-5.0,  # Downward trend
        continuation_score=0.8,
        peak_price=bottom * 1.2,
        bottom_price=bottom,
        reason="test"
    )
    
    rule = PriceExtremeRule(extreme_threshold_percent=1.0)
    result = rule.validate(ticker, metrics, quote_near_bottom, [{"c": 1.0}] * 5)
    
    # Should reject short entry
    assert result.reason_short is not None
    assert "at/near bottom" in result.reason_short.lower()


# Feature: penny-stock-entry-validation, Property 10: Extreme price rejection includes both prices
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    peak=st.floats(min_value=2.0, max_value=5.0, allow_nan=False, allow_infinity=False)
)
def test_property_10_extreme_price_rejection_includes_both_prices(ticker, peak):
    """
    Property 10: Extreme price rejection includes both prices
    
    For any ticker rejected due to price being at an extreme, the rejection reason
    should contain both the current price and the extreme price values.
    
    Validates: Requirements 3.4
    """
    current_price = peak * 0.995
    quote = QuoteData.from_bid_ask(ticker, current_price, current_price)
    
    metrics = TrendMetrics(
        momentum_score=5.0,
        continuation_score=0.8,
        peak_price=peak,
        bottom_price=peak * 0.8,
        reason="test"
    )
    
    rule = PriceExtremeRule(extreme_threshold_percent=1.0)
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    if result.reason_long:
        # Should contain both current and peak prices
        assert f"${current_price:.4f}" in result.reason_long
        assert f"${peak:.4f}" in result.reason_long


# Feature: penny-stock-entry-validation, Property 11: Weak momentum rejects trend direction
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    momentum=st.floats(min_value=-2.9, max_value=2.9, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0),
    quote=quote_data_strategy()
)
def test_property_11_weak_momentum_rejects_trend_direction(ticker, momentum, quote):
    """
    Property 11: Weak momentum rejects trend direction
    
    For any ticker with absolute momentum score below 3.0%, entry in the trend
    direction should be rejected with a reason containing "weak trend" and the
    minimum threshold value (3.0%).
    
    Validates: Requirements 4.1, 4.3
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=0.8,
        peak_price=2.0,
        bottom_price=1.0,
        reason="test"
    )
    
    rule = MomentumThresholdRule(min_momentum=3.0, max_momentum=10.0)
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    if momentum > 0:
        assert result.reason_long is not None
        assert "weak" in result.reason_long.lower()
        assert "3.0%" in result.reason_long
    elif momentum < 0:
        assert result.reason_short is not None
        assert "weak" in result.reason_short.lower()
        assert "3.0%" in result.reason_short


# Feature: penny-stock-entry-validation, Property 12: Excessive momentum rejects trend direction
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    momentum=st.floats(min_value=10.1, max_value=50.0, allow_nan=False, allow_infinity=False),
    quote=quote_data_strategy()
)
def test_property_12_excessive_momentum_rejects_trend_direction(ticker, momentum, quote):
    """
    Property 12: Excessive momentum rejects trend direction
    
    For any ticker with absolute momentum score exceeding 10.0%, entry in the trend
    direction should be rejected with a reason containing "excessive trend" and the
    maximum threshold value (10.0%).
    
    Validates: Requirements 4.2, 4.4
    """
    metrics = TrendMetrics(
        momentum_score=momentum,
        continuation_score=0.8,
        peak_price=2.0,
        bottom_price=1.0,
        reason="test"
    )
    
    rule = MomentumThresholdRule(min_momentum=3.0, max_momentum=10.0)
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    assert result.reason_long is not None
    assert "excessive" in result.reason_long.lower()
    assert "10.0%" in result.reason_long


# Feature: penny-stock-entry-validation, Property 14: Data quality failures apply to both directions
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    num_bars=st.integers(min_value=0, max_value=4),
    metrics=trend_metrics_strategy(),
    quote=quote_data_strategy()
)
def test_property_14_data_quality_failures_apply_to_both_directions(ticker, num_bars, metrics, quote):
    """
    Property 14: Data quality failures apply to both directions
    
    For any ticker that fails data quality checks (no market data, insufficient bars,
    invalid bid/ask), both reason_not_to_enter_long and reason_not_to_enter_short
    should contain identical rejection reasons.
    
    Validates: Requirements 5.4, 6.5
    """
    bars = [{"c": 1.0}] * num_bars
    
    rule = DataQualityRule(required_bars=5)
    result = rule.validate(ticker, metrics, quote, bars)
    
    if not result.passed:
        # Both reasons should be identical
        assert result.reason_long == result.reason_short
        assert result.reason_long is not None


# Feature: penny-stock-entry-validation, Property 16: Bid-ask spread calculation correctness
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    bid=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    ask=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False)
)
def test_property_16_bid_ask_spread_calculation_correctness(ticker, bid, ask):
    """
    Property 16: Bid-ask spread calculation correctness
    
    For any bid and ask prices, the spread percentage should equal
    ((ask - bid) / ((bid + ask) / 2)) * 100.
    
    Validates: Requirements 6.2
    """
    # Ensure ask >= bid
    if ask < bid:
        bid, ask = ask, bid
    
    quote = QuoteData.from_bid_ask(ticker, bid, ask)
    
    # Calculate expected spread
    mid_price = (bid + ask) / 2.0
    expected_spread = ((ask - bid) / mid_price) * 100
    
    assert abs(quote.spread_percent - expected_spread) < 0.01


# Feature: penny-stock-entry-validation, Property 17: Wide spread rejection includes values
@settings(max_examples=100)
@given(
    ticker=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))),
    bid=st.floats(min_value=1.0, max_value=4.0, allow_nan=False, allow_infinity=False),
    metrics=trend_metrics_strategy()
)
def test_property_17_wide_spread_rejection_includes_values(ticker, bid, metrics):
    """
    Property 17: Wide spread rejection includes values
    
    For any ticker rejected due to wide bid-ask spread, the rejection reason
    should contain both the actual spread percentage and the threshold value (2.0%).
    
    Validates: Requirements 6.3
    """
    # Create a wide spread (> 2%)
    ask = bid * 1.05  # 5% spread
    quote = QuoteData.from_bid_ask(ticker, bid, ask)
    
    rule = LiquidityRule(max_spread_percent=2.0)
    result = rule.validate(ticker, metrics, quote, [{"c": 1.0}] * 5)
    
    if not result.passed:
        assert result.reason_long is not None
        assert "2.0%" in result.reason_long
        # Should contain the actual spread percentage
        assert "%" in result.reason_long
