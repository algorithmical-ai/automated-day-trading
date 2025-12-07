"""
Unit tests for Risk Management utilities

Tests the core risk management functions:
- Stop loss calculation
- Position sizing
- Entry filtering
- Pricing logic
"""

import pytest
from app.src.services.trading.risk_management import RiskManagement


class TestStopLossCalculation:
    """Test stop loss calculation with 2.0x ATR and bounds"""

    def test_stop_loss_penny_stock_within_bounds(self):
        """Test stop loss for penny stock with ATR resulting in value within bounds"""
        # Entry price: $3.00, ATR: $0.15 (5% of price)
        # 2.0x ATR = 10%, should be capped to -8% (max for penny stocks)
        result = RiskManagement.calculate_stop_loss(
            entry_price=3.0, atr=0.15, is_penny_stock=True
        )
        assert result == -8.0

    def test_stop_loss_penny_stock_below_min(self):
        """Test stop loss for penny stock with low ATR"""
        # Entry price: $4.00, ATR: $0.04 (1% of price)
        # 2.0x ATR = 2%, should be capped to -4% (min for penny stocks)
        result = RiskManagement.calculate_stop_loss(
            entry_price=4.0, atr=0.04, is_penny_stock=True
        )
        assert result == -4.0

    def test_stop_loss_standard_stock_within_bounds(self):
        """Test stop loss for standard stock"""
        # Entry price: $50.00, ATR: $1.50 (3% of price)
        # 2.0x ATR = 6%, should be capped to -6% (max for standard stocks)
        result = RiskManagement.calculate_stop_loss(
            entry_price=50.0, atr=1.50, is_penny_stock=False
        )
        assert result == -6.0

    def test_stop_loss_standard_stock_below_min(self):
        """Test stop loss for standard stock with low ATR"""
        # Entry price: $100.00, ATR: $1.00 (1% of price)
        # 2.0x ATR = 2%, should be capped to -4% (min for standard stocks)
        result = RiskManagement.calculate_stop_loss(
            entry_price=100.0, atr=1.00, is_penny_stock=False
        )
        assert result == -4.0

    def test_stop_loss_auto_detect_penny_stock(self):
        """Test automatic penny stock detection"""
        # Price < $5 should be detected as penny stock
        result = RiskManagement.calculate_stop_loss(entry_price=3.0, atr=0.15)
        assert -8.0 <= result <= -4.0

    def test_stop_loss_auto_detect_standard_stock(self):
        """Test automatic standard stock detection"""
        # Price >= $5 should be detected as standard stock
        result = RiskManagement.calculate_stop_loss(entry_price=50.0, atr=1.50)
        assert -6.0 <= result <= -4.0

    def test_stop_loss_invalid_entry_price(self):
        """Test stop loss with invalid entry price"""
        result = RiskManagement.calculate_stop_loss(entry_price=0.0, atr=0.10)
        assert result == -4.0  # Default

    def test_stop_loss_invalid_atr(self):
        """Test stop loss with invalid ATR"""
        result = RiskManagement.calculate_stop_loss(entry_price=50.0, atr=0.0)
        assert result == -4.0  # Default


class TestPositionSizing:
    """Test position sizing calculation"""

    def test_position_size_base_case(self):
        """Test base position size with normal volatility"""
        # Entry price: $50, ATR: $1.00 (2% of price) - normal volatility
        result = RiskManagement.calculate_position_size(
            entry_price=50.0, atr=1.00, is_penny_stock=False
        )
        assert result == 2000.0  # Full base size

    def test_position_size_high_volatility(self):
        """Test position size reduction for high volatility"""
        # Entry price: $50, ATR: $3.00 (6% of price) - very high volatility
        result = RiskManagement.calculate_position_size(
            entry_price=50.0, atr=3.00, is_penny_stock=False
        )
        assert result == 500.0  # 25% of base (2000 * 0.25)

    def test_position_size_penny_stock(self):
        """Test position size reduction for penny stocks"""
        # Entry price: $3.00, ATR: $0.06 (2% of price) - normal volatility
        # Should be reduced by 25% for penny stock: 2000 * 0.75 = 1500
        result = RiskManagement.calculate_position_size(
            entry_price=3.0, atr=0.06, is_penny_stock=True
        )
        assert result == 1500.0

    def test_position_size_penny_stock_high_volatility(self):
        """Test position size for penny stock with high volatility"""
        # Entry price: $3.00, ATR: $0.18 (6% of price) - very high volatility
        # Should be: 2000 * 0.25 (volatility) * 0.75 (penny stock) = 375
        # But minimum is 500
        result = RiskManagement.calculate_position_size(
            entry_price=3.0, atr=0.18, is_penny_stock=True
        )
        assert result == 500.0  # Minimum enforced

    def test_position_size_minimum_enforced(self):
        """Test that minimum position size is enforced"""
        # Very high volatility should still result in minimum $500
        result = RiskManagement.calculate_position_size(
            entry_price=10.0, atr=1.0, is_penny_stock=False
        )
        assert result >= 500.0

    def test_position_size_invalid_entry_price(self):
        """Test position size with invalid entry price"""
        result = RiskManagement.calculate_position_size(
            entry_price=0.0, atr=0.10, is_penny_stock=False
        )
        assert result == 500.0  # Minimum

    def test_position_size_no_atr(self):
        """Test position size when ATR is not available"""
        result = RiskManagement.calculate_position_size(
            entry_price=50.0, atr=None, is_penny_stock=False
        )
        assert result == 2000.0  # Full base size


class TestEntryFiltering:
    """Test entry filtering logic"""

    def test_entry_filters_all_pass(self):
        """Test when all entry filters pass"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=5.0,  # Within 1.5-15%
            adx=25.0,  # Above 20
            volume=1000,
            volume_sma=500,  # 2x SMA (above 1.5x)
            price=10.0,  # Above $0.10
        )
        assert passes is True
        assert "passed" in reason.lower()

    def test_entry_filters_momentum_too_low(self):
        """Test rejection when momentum is too low"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=1.0,  # Below 1.5%
            adx=25.0,
            volume=1000,
            volume_sma=500,
            price=10.0,
        )
        assert passes is False
        assert "momentum too low" in reason.lower()

    def test_entry_filters_momentum_too_high(self):
        """Test rejection when momentum is too high"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=20.0,  # Above 15%
            adx=25.0,
            volume=1000,
            volume_sma=500,
            price=10.0,
        )
        assert passes is False
        assert "momentum too high" in reason.lower()

    def test_entry_filters_adx_too_low(self):
        """Test rejection when ADX is too low"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=5.0,
            adx=15.0,  # Below 20
            volume=1000,
            volume_sma=500,
            price=10.0,
        )
        assert passes is False
        assert "adx too low" in reason.lower()

    def test_entry_filters_volume_too_low(self):
        """Test rejection when volume is too low"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=5.0,
            adx=25.0,
            volume=700,  # 1.4x SMA (below 1.5x)
            volume_sma=500,
            price=10.0,
        )
        assert passes is False
        assert "volume too low" in reason.lower()

    def test_entry_filters_price_too_low(self):
        """Test rejection when price is too low"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=5.0,
            adx=25.0,
            volume=1000,
            volume_sma=500,
            price=0.05,  # Below $0.10
        )
        assert passes is False
        assert "price too low" in reason.lower()

    def test_entry_filters_negative_momentum(self):
        """Test with negative momentum (absolute value used)"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=-5.0,  # Absolute value is 5.0, within range
            adx=25.0,
            volume=1000,
            volume_sma=500,
            price=10.0,
        )
        assert passes is True

    def test_entry_filters_zero_volume_sma(self):
        """Test when volume SMA is zero"""
        passes, reason = RiskManagement.passes_entry_filters(
            momentum=5.0,
            adx=25.0,
            volume=1000,
            volume_sma=0,  # Zero SMA
            price=10.0,
        )
        # Should pass if volume is positive
        assert passes is True


class TestPricingLogic:
    """Test bid/ask pricing logic for entry and exit"""

    def test_get_entry_price_long(self):
        """Test entry price for long position (should use ask)"""
        price = RiskManagement.get_entry_price(
            direction="long", bid=100.0, ask=100.5
        )
        assert price == 100.5  # Ask price

    def test_get_entry_price_short(self):
        """Test entry price for short position (should use bid)"""
        price = RiskManagement.get_entry_price(
            direction="short", bid=100.0, ask=100.5
        )
        assert price == 100.0  # Bid price

    def test_get_exit_price_long(self):
        """Test exit price for long position (should use bid)"""
        price = RiskManagement.get_exit_price(
            direction="long", bid=100.0, ask=100.5
        )
        assert price == 100.0  # Bid price

    def test_get_exit_price_short(self):
        """Test exit price for short position (should use ask)"""
        price = RiskManagement.get_exit_price(
            direction="short", bid=100.0, ask=100.5
        )
        assert price == 100.5  # Ask price

    def test_get_entry_price_case_insensitive(self):
        """Test that direction is case-insensitive"""
        price_lower = RiskManagement.get_entry_price(
            direction="long", bid=100.0, ask=100.5
        )
        price_upper = RiskManagement.get_entry_price(
            direction="LONG", bid=100.0, ask=100.5
        )
        assert price_lower == price_upper


class TestProfitLossCalculation:
    """Test profit/loss calculation"""

    def test_profit_loss_long_profit(self):
        """Test profit calculation for long position"""
        # Entry at 100, exit at 105 = 5% profit
        pl = RiskManagement.calculate_profit_loss(
            direction="long", entry_price=100.0, exit_price=105.0
        )
        assert pl == pytest.approx(5.0, rel=0.01)

    def test_profit_loss_long_loss(self):
        """Test loss calculation for long position"""
        # Entry at 100, exit at 95 = -5% loss
        pl = RiskManagement.calculate_profit_loss(
            direction="long", entry_price=100.0, exit_price=95.0
        )
        assert pl == pytest.approx(-5.0, rel=0.01)

    def test_profit_loss_short_profit(self):
        """Test profit calculation for short position"""
        # Entry at 100, exit at 95 = 5% profit (price went down)
        pl = RiskManagement.calculate_profit_loss(
            direction="short", entry_price=100.0, exit_price=95.0
        )
        assert pl == pytest.approx(5.0, rel=0.01)

    def test_profit_loss_short_loss(self):
        """Test loss calculation for short position"""
        # Entry at 100, exit at 105 = -5% loss (price went up)
        pl = RiskManagement.calculate_profit_loss(
            direction="short", entry_price=100.0, exit_price=105.0
        )
        assert pl == pytest.approx(-5.0, rel=0.01)

    def test_profit_loss_no_change(self):
        """Test when entry and exit prices are the same"""
        pl = RiskManagement.calculate_profit_loss(
            direction="long", entry_price=100.0, exit_price=100.0
        )
        assert pl == pytest.approx(0.0, rel=0.01)

    def test_profit_loss_invalid_entry_price(self):
        """Test with invalid entry price"""
        pl = RiskManagement.calculate_profit_loss(
            direction="long", entry_price=0.0, exit_price=100.0
        )
        assert pl == 0.0  # Returns 0 for invalid entry


class TestPriceValidation:
    """Test price validation"""

    def test_validate_prices_valid(self):
        """Test validation with valid prices"""
        is_valid, reason = RiskManagement.validate_prices(
            bid=100.0, ask=100.5, current_price=100.25
        )
        assert is_valid is True
        assert "valid" in reason.lower()

    def test_validate_prices_invalid_bid(self):
        """Test validation with invalid bid"""
        is_valid, reason = RiskManagement.validate_prices(bid=0.0, ask=100.5)
        assert is_valid is False
        assert "bid" in reason.lower()

    def test_validate_prices_invalid_ask(self):
        """Test validation with invalid ask"""
        is_valid, reason = RiskManagement.validate_prices(bid=100.0, ask=0.0)
        assert is_valid is False
        assert "ask" in reason.lower()

    def test_validate_prices_bid_greater_than_ask(self):
        """Test validation when bid > ask"""
        is_valid, reason = RiskManagement.validate_prices(bid=101.0, ask=100.0)
        assert is_valid is False
        assert "bid" in reason.lower() and "ask" in reason.lower()

    def test_validate_prices_wide_spread(self):
        """Test validation with wide spread (> 10%)"""
        is_valid, reason = RiskManagement.validate_prices(bid=100.0, ask=115.0)
        assert is_valid is False
        assert "spread" in reason.lower()

    def test_validate_prices_without_current_price(self):
        """Test validation without current price"""
        is_valid, reason = RiskManagement.validate_prices(bid=100.0, ask=100.5)
        assert is_valid is True
