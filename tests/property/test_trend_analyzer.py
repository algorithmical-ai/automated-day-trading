"""
Property-based tests for TrendAnalyzer component.

Feature: penny-stock-entry-validation
"""

from hypothesis import given, strategies as st, settings, assume
from app.src.services.trading.validation.trend_analyzer import TrendAnalyzer
from app.src.services.trading.validation.models import TrendMetrics


# Helper strategy for generating price bars
@st.composite
def price_bars(draw, min_bars=3, max_bars=10, min_price=0.01, max_price=5.0):
    """Generate a list of price bar dictionaries."""
    num_bars = draw(st.integers(min_value=min_bars, max_value=max_bars))
    bars = []
    for _ in range(num_bars):
        price = draw(st.floats(min_value=min_price, max_value=max_price, allow_nan=False, allow_infinity=False))
        bars.append({"c": price})
    return bars


# Feature: penny-stock-entry-validation, Property 2: Momentum score includes percentage in reason
@settings(max_examples=100)
@given(bars=price_bars(min_bars=5, max_bars=10))
def test_property_2_momentum_score_includes_percentage_in_reason(bars):
    """
    Property 2: Momentum score includes percentage in reason
    
    For any ticker rejected due to trend direction, the rejection reason
    should contain the momentum score as a percentage value.
    
    Validates: Requirements 1.4
    """
    metrics = TrendAnalyzer.calculate_trend_metrics(bars)
    
    # The reason should contain percentage information
    # We verify this by checking that the reason contains a percentage value
    # (a number followed by %)
    assert "%" in metrics.reason, "Reason should contain percentage symbol"
    
    # The reason should contain the overall change percentage
    # Extract prices to calculate expected change
    prices = [bar["c"] for bar in bars[-5:] if "c" in bar]
    if len(prices) >= 2:
        first_price = prices[0]
        last_price = prices[-1]
        if first_price > 0:
            expected_change = ((last_price - first_price) / first_price) * 100
            # Check that the change percentage appears in the reason
            assert f"{expected_change:.2f}%" in metrics.reason


# Feature: penny-stock-entry-validation, Property 5: Continuation score calculation correctness
@settings(max_examples=100)
@given(bars=price_bars(min_bars=5, max_bars=10))
def test_property_5_continuation_score_calculation_correctness(bars):
    """
    Property 5: Continuation score calculation correctness
    
    For any sequence of price bars, the continuation score should equal
    the proportion of recent price changes that move in the overall trend direction.
    
    Validates: Requirements 2.3
    """
    metrics = TrendAnalyzer.calculate_trend_metrics(bars)
    
    # Extract prices from recent bars
    recent_bars = bars[-5:] if len(bars) >= 5 else bars
    prices = [bar["c"] for bar in recent_bars if "c" in bar]
    
    if len(prices) < 3:
        # Insufficient data, continuation should be 0
        assert metrics.continuation_score == 0.0
        return
    
    # Calculate expected continuation manually
    last_3_prices = prices[-3:]
    if len(last_3_prices) >= 2:
        recent_changes = [
            last_3_prices[i] - last_3_prices[i - 1]
            for i in range(1, len(last_3_prices))
        ]
        
        if recent_changes:
            if metrics.momentum_score > 0:
                # Upward trend: proportion of positive changes
                expected_continuation = sum(1 for c in recent_changes if c > 0) / len(recent_changes)
            else:
                # Downward trend: proportion of negative changes
                expected_continuation = sum(1 for c in recent_changes if c < 0) / len(recent_changes)
            
            # Verify the continuation score matches
            assert abs(metrics.continuation_score - expected_continuation) < 0.01


# Feature: penny-stock-entry-validation, Property 9: Price extreme percentage calculation
@settings(max_examples=100)
@given(
    current_price=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    extreme_price=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False)
)
def test_property_9_price_extreme_percentage_calculation(current_price, extreme_price):
    """
    Property 9: Price extreme percentage calculation
    
    For any current price and extreme price (peak or bottom), the calculated
    percentage difference should equal ((current_price - extreme_price) / extreme_price) * 100.
    
    Validates: Requirements 3.3
    """
    result = TrendAnalyzer.calculate_price_extreme_percentage(current_price, extreme_price)
    
    # Calculate expected value
    expected = ((current_price - extreme_price) / extreme_price) * 100
    
    # Verify the calculation is correct
    assert abs(result - expected) < 0.01, f"Expected {expected}, got {result}"


@settings(max_examples=100)
@given(bars=price_bars(min_bars=3, max_bars=10))
def test_trend_analyzer_always_returns_valid_metrics(bars):
    """
    Test that TrendAnalyzer always returns valid TrendMetrics for any input.
    """
    metrics = TrendAnalyzer.calculate_trend_metrics(bars)
    
    # Verify we get a TrendMetrics object
    assert isinstance(metrics, TrendMetrics)
    
    # Verify all fields are present and have valid types
    assert isinstance(metrics.momentum_score, float)
    assert isinstance(metrics.continuation_score, float)
    assert isinstance(metrics.peak_price, float)
    assert isinstance(metrics.bottom_price, float)
    assert isinstance(metrics.reason, str)
    
    # Verify continuation score is in valid range
    assert 0.0 <= metrics.continuation_score <= 1.0
    
    # Verify peak >= bottom (when both are non-zero)
    if metrics.peak_price > 0 and metrics.bottom_price > 0:
        assert metrics.peak_price >= metrics.bottom_price


@settings(max_examples=100)
@given(
    numerator=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    denominator=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
)
def test_safe_divide_handles_zero_denominator(numerator, denominator):
    """
    Test that safe_divide handles zero denominators correctly.
    """
    result = TrendAnalyzer.safe_divide(numerator, denominator, default=0.0)
    
    if denominator == 0:
        assert result == 0.0
    elif abs(denominator) < 1e-10:
        # Very small denominator, skip this test case
        assume(False)
    else:
        expected = numerator / denominator
        # Check if result is finite
        if abs(expected) < 1e10:  # Avoid overflow cases
            assert abs(result - expected) < 0.0001


def test_trend_analyzer_with_insufficient_bars():
    """
    Test that TrendAnalyzer handles insufficient bars gracefully.
    """
    # Empty bars
    metrics = TrendAnalyzer.calculate_trend_metrics([])
    assert metrics.momentum_score == 0.0
    assert metrics.continuation_score == 0.0
    
    # Single bar
    metrics = TrendAnalyzer.calculate_trend_metrics([{"c": 1.0}])
    assert metrics.momentum_score == 0.0
    assert metrics.continuation_score == 0.0
    
    # Two bars
    metrics = TrendAnalyzer.calculate_trend_metrics([{"c": 1.0}, {"c": 1.1}])
    assert metrics.momentum_score == 0.0
    assert metrics.continuation_score == 0.0


def test_trend_analyzer_with_identical_prices():
    """
    Test that TrendAnalyzer handles identical prices (no movement).
    """
    bars = [{"c": 2.5} for _ in range(5)]
    metrics = TrendAnalyzer.calculate_trend_metrics(bars)
    
    # No price movement should result in zero momentum
    assert metrics.momentum_score == 0.0
    assert metrics.peak_price == 2.5
    assert metrics.bottom_price == 2.5
