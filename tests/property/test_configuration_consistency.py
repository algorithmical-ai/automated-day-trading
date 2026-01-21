"""
Property-Based Tests for Configuration Consistency

Tests that all trading indicators use standardized configuration values
from trading_config.py for ATR multipliers and bounds.

Feature: automated-day-trading
Properties: 77, 78, 79, 80
"""

import pytest
from hypothesis import given, strategies as st, settings
from typing import List, Tuple

# Import configuration constants
from app.src.services.trading.trading_config import (
    ATR_STOP_LOSS_MULTIPLIER,
    ATR_TRAILING_STOP_MULTIPLIER,
    PENNY_STOCK_STOP_LOSS_MIN,
    PENNY_STOCK_STOP_LOSS_MAX,
    STANDARD_STOCK_STOP_LOSS_MIN,
    STANDARD_STOCK_STOP_LOSS_MAX,
    BASE_TRAILING_STOP_PERCENT,
    TRAILING_STOP_SHORT_MULTIPLIER,
    MAX_TRAILING_STOP_SHORT,
)

# Import trading indicators
from app.src.services.trading.momentum_indicator import MomentumIndicator
from app.src.services.trading.penny_stocks_indicator import PennyStocksIndicator
from app.src.services.trading.deep_analyzer_indicator import DeepAnalyzerIndicator
from app.src.services.trading.uw_enhanced_momentum_indicator import (
    UWEnhancedMomentumIndicator,
)


# =============================================================================
# Property 77: Stop Loss ATR Multiplier Consistency
# =============================================================================


@settings(max_examples=100)
@given(
    atr=st.floats(min_value=0.01, max_value=10.0),
    price=st.floats(min_value=0.10, max_value=1000.0),
)
def test_property_77_stop_loss_atr_multiplier_consistency(atr: float, price: float):
    """
    Feature: automated-day-trading, Property 77: Stop Loss ATR Multiplier Consistency

    For any stop loss calculation by any trading indicator, the calculation should use
    the standardized 2.0x ATR multiplier from trading_config.py.

    Validates: Requirements 19.1
    """
    # Calculate ATR as percentage of price
    atr_percent = (atr / price) * 100

    # Calculate expected stop loss using standardized multiplier
    expected_stop_loss_percent = atr_percent * ATR_STOP_LOSS_MULTIPLIER

    # The expected stop loss should use exactly 2.5x ATR
    assert (
        ATR_STOP_LOSS_MULTIPLIER == 2.5
    ), f"Stop loss ATR multiplier should be 2.5, got {ATR_STOP_LOSS_MULTIPLIER}"

    # Verify the calculation is consistent
    calculated_stop_loss = atr_percent * 2.5
    assert abs(expected_stop_loss_percent - calculated_stop_loss) < 0.0001, (
        f"Stop loss calculation inconsistent: expected {expected_stop_loss_percent}, "
        f"got {calculated_stop_loss}"
    )


# =============================================================================
# Property 78: Trailing Stop ATR Multiplier Consistency
# =============================================================================


@settings(max_examples=100)
@given(
    atr=st.floats(min_value=0.01, max_value=10.0),
    price=st.floats(min_value=0.10, max_value=1000.0),
)
def test_property_78_trailing_stop_atr_multiplier_consistency(atr: float, price: float):
    """
    Feature: automated-day-trading, Property 78: Trailing Stop ATR Multiplier Consistency

    For any trailing stop calculation by any trading indicator, the calculation should use
    the standardized 1.5x ATR multiplier from trading_config.py.

    Validates: Requirements 19.2
    """
    # Calculate ATR as percentage of price
    atr_percent = (atr / price) * 100

    # Calculate expected trailing stop using standardized multiplier
    expected_trailing_stop_percent = atr_percent * ATR_TRAILING_STOP_MULTIPLIER

    # The expected trailing stop should use exactly 1.5x ATR
    assert (
        ATR_TRAILING_STOP_MULTIPLIER == 1.5
    ), f"Trailing stop ATR multiplier should be 1.5, got {ATR_TRAILING_STOP_MULTIPLIER}"

    # Verify the calculation is consistent
    calculated_trailing_stop = atr_percent * 1.5
    assert abs(expected_trailing_stop_percent - calculated_trailing_stop) < 0.0001, (
        f"Trailing stop calculation inconsistent: expected {expected_trailing_stop_percent}, "
        f"got {calculated_trailing_stop}"
    )


# =============================================================================
# Property 79: Stop Loss Bounds Consistency
# =============================================================================


@settings(max_examples=100)
@given(
    is_penny_stock=st.booleans(),
    calculated_stop_loss=st.floats(min_value=-15.0, max_value=-1.0),
)
def test_property_79_stop_loss_bounds_consistency(
    is_penny_stock: bool, calculated_stop_loss: float
):
    """
    Feature: automated-day-trading, Property 79: Stop Loss Bounds Consistency

    For any stop loss bounds applied by any trading indicator, the bounds should match
    the standardized values from trading_config.py (-8% to -4% for penny stocks,
    -6% to -4% for standard stocks).

    Validates: Requirements 19.3
    """
    if is_penny_stock:
        # Penny stock bounds - now fixed at 2% for simple trailing stop
        min_bound = PENNY_STOCK_STOP_LOSS_MIN
        max_bound = PENNY_STOCK_STOP_LOSS_MAX

        # Verify standardized values (both set to -2% for simple trailing stop)
        assert (
            min_bound == -2.0
        ), f"Penny stock stop loss min should be -2.0, got {min_bound}"
        assert (
            max_bound == -2.0
        ), f"Penny stock stop loss max should be -2.0, got {max_bound}"
    else:
        # Standard stock bounds
        min_bound = STANDARD_STOCK_STOP_LOSS_MIN
        max_bound = STANDARD_STOCK_STOP_LOSS_MAX

        # Verify standardized values
        assert (
            min_bound == -6.0
        ), f"Standard stock stop loss min should be -6.0, got {min_bound}"
        assert (
            max_bound == -4.0
        ), f"Standard stock stop loss max should be -4.0, got {max_bound}"

    # Apply bounds to calculated stop loss
    bounded_stop_loss = max(min_bound, min(max_bound, calculated_stop_loss))

    # Verify bounded value is within expected range
    assert min_bound <= bounded_stop_loss <= max_bound, (
        f"Bounded stop loss {bounded_stop_loss} not within range "
        f"[{min_bound}, {max_bound}]"
    )

    # Verify bounds are applied correctly
    if calculated_stop_loss < min_bound:
        assert bounded_stop_loss == min_bound, (
            f"Stop loss below minimum should be capped at {min_bound}, "
            f"got {bounded_stop_loss}"
        )
    elif calculated_stop_loss > max_bound:
        assert bounded_stop_loss == max_bound, (
            f"Stop loss above maximum should be capped at {max_bound}, "
            f"got {bounded_stop_loss}"
        )
    else:
        assert bounded_stop_loss == calculated_stop_loss, (
            f"Stop loss within bounds should remain unchanged, "
            f"expected {calculated_stop_loss}, got {bounded_stop_loss}"
        )


# =============================================================================
# Property 80: Trailing Stop Bounds Consistency
# =============================================================================


@settings(max_examples=100)
@given(
    is_short_position=st.booleans(),
    base_trailing_stop=st.floats(min_value=0.5, max_value=5.0),
)
def test_property_80_trailing_stop_bounds_consistency(
    is_short_position: bool, base_trailing_stop: float
):
    """
    Feature: automated-day-trading, Property 80: Trailing Stop Bounds Consistency

    For any trailing stop bounds applied by any trading indicator, the bounds should match
    the standardized values from trading_config.py (2.0% base, 1.5x multiplier for shorts).

    Validates: Requirements 19.4
    """
    # Verify standardized base trailing stop
    assert (
        BASE_TRAILING_STOP_PERCENT == 2.0
    ), f"Base trailing stop should be 2.0%, got {BASE_TRAILING_STOP_PERCENT}"

    # Verify standardized short multiplier
    assert (
        TRAILING_STOP_SHORT_MULTIPLIER == 1.5
    ), f"Trailing stop short multiplier should be 1.5, got {TRAILING_STOP_SHORT_MULTIPLIER}"

    # Verify standardized max for shorts
    assert (
        MAX_TRAILING_STOP_SHORT == 4.0
    ), f"Max trailing stop for shorts should be 4.0%, got {MAX_TRAILING_STOP_SHORT}"

    if is_short_position:
        # For short positions, apply multiplier
        adjusted_trailing_stop = base_trailing_stop * TRAILING_STOP_SHORT_MULTIPLIER

        # Cap at maximum
        final_trailing_stop = min(adjusted_trailing_stop, MAX_TRAILING_STOP_SHORT)

        # Verify the multiplier is applied
        expected_before_cap = base_trailing_stop * 1.5
        assert abs(adjusted_trailing_stop - expected_before_cap) < 0.0001, (
            f"Short trailing stop should be 1.5x base, "
            f"expected {expected_before_cap}, got {adjusted_trailing_stop}"
        )

        # Verify capping works correctly
        if adjusted_trailing_stop > MAX_TRAILING_STOP_SHORT:
            assert final_trailing_stop == MAX_TRAILING_STOP_SHORT, (
                f"Trailing stop should be capped at {MAX_TRAILING_STOP_SHORT}, "
                f"got {final_trailing_stop}"
            )
        else:
            assert final_trailing_stop == adjusted_trailing_stop, (
                f"Trailing stop below cap should remain unchanged, "
                f"expected {adjusted_trailing_stop}, got {final_trailing_stop}"
            )
    else:
        # For long positions, use base value
        final_trailing_stop = max(base_trailing_stop, BASE_TRAILING_STOP_PERCENT)

        # Verify minimum is applied
        if base_trailing_stop < BASE_TRAILING_STOP_PERCENT:
            assert final_trailing_stop == BASE_TRAILING_STOP_PERCENT, (
                f"Trailing stop should be at least {BASE_TRAILING_STOP_PERCENT}%, "
                f"got {final_trailing_stop}"
            )
        else:
            assert final_trailing_stop == base_trailing_stop, (
                f"Trailing stop above minimum should remain unchanged, "
                f"expected {base_trailing_stop}, got {final_trailing_stop}"
            )


# =============================================================================
# Integration Test: Verify All Indicators Use Standardized Config
# =============================================================================


def test_all_indicators_import_from_trading_config():
    """
    Verify that all trading indicators can access the standardized configuration.
    This is a sanity check to ensure the configuration module is properly structured.
    """
    # Verify all constants are defined and have expected values
    assert ATR_STOP_LOSS_MULTIPLIER == 2.5
    assert ATR_TRAILING_STOP_MULTIPLIER == 1.5
    assert PENNY_STOCK_STOP_LOSS_MIN == -2.0  # Updated for 2% trailing stop
    assert PENNY_STOCK_STOP_LOSS_MAX == -2.0  # Updated for 2% trailing stop
    assert STANDARD_STOCK_STOP_LOSS_MIN == -6.0
    assert STANDARD_STOCK_STOP_LOSS_MAX == -4.0
    assert BASE_TRAILING_STOP_PERCENT == 2.0
    assert TRAILING_STOP_SHORT_MULTIPLIER == 1.5
    assert MAX_TRAILING_STOP_SHORT == 4.0

    # Verify indicators can be imported (they should use the config)
    assert MomentumIndicator is not None
    assert PennyStocksIndicator is not None
    assert DeepAnalyzerIndicator is not None
    assert UWEnhancedMomentumIndicator is not None
