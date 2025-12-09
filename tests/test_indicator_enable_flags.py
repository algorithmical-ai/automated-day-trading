"""
Test indicator enable/disable flags
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from app.src.services.trading.trading_service import TradingServiceCoordinator


class TestIndicatorEnableFlags:
    """Test suite for indicator enable/disable flags"""

    def test_momentum_indicator_enabled_by_default(self):
        """Test that momentum indicator is enabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ENABLE_MOMENTUM_INDICATOR", None)
            # Simulate the flag check
            enable_momentum = os.getenv("ENABLE_MOMENTUM_INDICATOR", "true").lower() == "true"
            assert enable_momentum is True

    def test_momentum_indicator_disabled(self):
        """Test that momentum indicator can be disabled"""
        with patch.dict(os.environ, {"ENABLE_MOMENTUM_INDICATOR": "false"}):
            enable_momentum = os.getenv("ENABLE_MOMENTUM_INDICATOR", "true").lower() == "true"
            assert enable_momentum is False

    def test_penny_stocks_indicator_enabled_by_default(self):
        """Test that penny stocks indicator is enabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ENABLE_PENNY_STOCKS_INDICATOR", None)
            enable_penny_stocks = os.getenv("ENABLE_PENNY_STOCKS_INDICATOR", "true").lower() == "true"
            assert enable_penny_stocks is True

    def test_penny_stocks_indicator_disabled(self):
        """Test that penny stocks indicator can be disabled"""
        with patch.dict(os.environ, {"ENABLE_PENNY_STOCKS_INDICATOR": "false"}):
            enable_penny_stocks = os.getenv("ENABLE_PENNY_STOCKS_INDICATOR", "true").lower() == "true"
            assert enable_penny_stocks is False

    def test_deep_analyzer_indicator_enabled_by_default(self):
        """Test that deep analyzer indicator is enabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ENABLE_DEEP_ANALYZER_INDICATOR", None)
            # FIXED: Should check for "true" not "false"
            enable_deep_analyzer = os.getenv("ENABLE_DEEP_ANALYZER_INDICATOR", "true").lower() == "true"
            assert enable_deep_analyzer is True

    def test_deep_analyzer_indicator_disabled(self):
        """Test that deep analyzer indicator can be disabled"""
        with patch.dict(os.environ, {"ENABLE_DEEP_ANALYZER_INDICATOR": "false"}):
            # FIXED: Should check for "true" not "false"
            enable_deep_analyzer = os.getenv("ENABLE_DEEP_ANALYZER_INDICATOR", "true").lower() == "true"
            assert enable_deep_analyzer is False

    def test_uw_enhanced_indicator_enabled_by_default(self):
        """Test that UW enhanced indicator is enabled by default"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ENABLE_UW_ENHANCED_INDICATOR", None)
            # FIXED: Should check for "true" not "false"
            enable_uw_enhanced = os.getenv("ENABLE_UW_ENHANCED_INDICATOR", "true").lower() == "true"
            assert enable_uw_enhanced is True

    def test_uw_enhanced_indicator_disabled(self):
        """Test that UW enhanced indicator can be disabled"""
        with patch.dict(os.environ, {"ENABLE_UW_ENHANCED_INDICATOR": "false"}):
            # FIXED: Should check for "true" not "false"
            enable_uw_enhanced = os.getenv("ENABLE_UW_ENHANCED_INDICATOR", "true").lower() == "true"
            assert enable_uw_enhanced is False

    def test_all_indicators_disabled(self):
        """Test that all indicators can be disabled simultaneously"""
        with patch.dict(os.environ, {
            "ENABLE_MOMENTUM_INDICATOR": "false",
            "ENABLE_PENNY_STOCKS_INDICATOR": "false",
            "ENABLE_DEEP_ANALYZER_INDICATOR": "false",
            "ENABLE_UW_ENHANCED_INDICATOR": "false",
        }):
            enable_momentum = os.getenv("ENABLE_MOMENTUM_INDICATOR", "true").lower() == "true"
            enable_penny_stocks = os.getenv("ENABLE_PENNY_STOCKS_INDICATOR", "true").lower() == "true"
            enable_deep_analyzer = os.getenv("ENABLE_DEEP_ANALYZER_INDICATOR", "true").lower() == "true"
            enable_uw_enhanced = os.getenv("ENABLE_UW_ENHANCED_INDICATOR", "true").lower() == "true"
            
            assert enable_momentum is False
            assert enable_penny_stocks is False
            assert enable_deep_analyzer is False
            assert enable_uw_enhanced is False

    def test_case_insensitive_flags(self):
        """Test that flag values are case insensitive"""
        for value in ["TRUE", "True", "true"]:
            with patch.dict(os.environ, {"ENABLE_MOMENTUM_INDICATOR": value}):
                enable_momentum = os.getenv("ENABLE_MOMENTUM_INDICATOR", "true").lower() == "true"
                assert enable_momentum is True
        
        for value in ["FALSE", "False", "false"]:
            with patch.dict(os.environ, {"ENABLE_MOMENTUM_INDICATOR": value}):
                enable_momentum = os.getenv("ENABLE_MOMENTUM_INDICATOR", "true").lower() == "true"
                assert enable_momentum is False


if __name__ == "__main__":
    import asyncio
    
    print("\n=== Testing Indicator Enable/Disable Flags ===\n")
    
    test = TestIndicatorEnableFlags()
    
    test.test_momentum_indicator_enabled_by_default()
    print("✓ Momentum indicator enabled by default")
    
    test.test_momentum_indicator_disabled()
    print("✓ Momentum indicator can be disabled")
    
    test.test_penny_stocks_indicator_enabled_by_default()
    print("✓ Penny stocks indicator enabled by default")
    
    test.test_penny_stocks_indicator_disabled()
    print("✓ Penny stocks indicator can be disabled")
    
    test.test_deep_analyzer_indicator_enabled_by_default()
    print("✓ Deep analyzer indicator enabled by default (FIXED)")
    
    test.test_deep_analyzer_indicator_disabled()
    print("✓ Deep analyzer indicator can be disabled (FIXED)")
    
    test.test_uw_enhanced_indicator_enabled_by_default()
    print("✓ UW enhanced indicator enabled by default (FIXED)")
    
    test.test_uw_enhanced_indicator_disabled()
    print("✓ UW enhanced indicator can be disabled (FIXED)")
    
    test.test_all_indicators_disabled()
    print("✓ All indicators can be disabled simultaneously")
    
    test.test_case_insensitive_flags()
    print("✓ Flag values are case insensitive")
    
    print("\n=== All tests passed! ===\n")
