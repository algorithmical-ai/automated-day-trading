"""
Test threshold adjustment service enable/disable flag
"""

import os
import pytest
from unittest.mock import patch
from app.src.services.threshold_adjustment.threshold_adjustment_service import ThresholdAdjustmentService


class TestThresholdAdjustmentFlag:
    """Test suite for threshold adjustment service flag"""

    def test_is_enabled_when_true(self):
        """Test that service is enabled when env var is 'true'"""
        with patch.dict(os.environ, {"ENABLE_THRESHOLD_ADJUSTMENT": "true"}):
            assert ThresholdAdjustmentService.is_enabled() is True

    def test_is_enabled_when_false(self):
        """Test that service is disabled when env var is 'false'"""
        with patch.dict(os.environ, {"ENABLE_THRESHOLD_ADJUSTMENT": "false"}):
            assert ThresholdAdjustmentService.is_enabled() is False

    def test_is_disabled_by_default(self):
        """Test that service is disabled when env var is not set"""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("ENABLE_THRESHOLD_ADJUSTMENT", None)
            assert ThresholdAdjustmentService.is_enabled() is False

    def test_is_enabled_case_insensitive(self):
        """Test that 'TRUE', 'True', 'true' all work"""
        for value in ["TRUE", "True", "true"]:
            with patch.dict(os.environ, {"ENABLE_THRESHOLD_ADJUSTMENT": value}):
                assert ThresholdAdjustmentService.is_enabled() is True

    def test_is_disabled_for_other_values(self):
        """Test that any value other than 'true' disables the service"""
        for value in ["1", "yes", "on", "enabled", "TRUE1", ""]:
            with patch.dict(os.environ, {"ENABLE_THRESHOLD_ADJUSTMENT": value}):
                assert ThresholdAdjustmentService.is_enabled() is False

    @pytest.mark.asyncio
    async def test_start_when_disabled(self):
        """Test that start() returns early when service is disabled"""
        with patch.dict(os.environ, {"ENABLE_THRESHOLD_ADJUSTMENT": "false"}):
            # Reset running state
            ThresholdAdjustmentService.running = False
            
            # Start should return immediately without setting running=True
            await ThresholdAdjustmentService.start()
            
            # Service should not be running
            assert ThresholdAdjustmentService.running is False


if __name__ == "__main__":
    import asyncio
    
    print("\n=== Testing Threshold Adjustment Service Flag ===\n")
    
    test = TestThresholdAdjustmentFlag()
    
    test.test_is_enabled_when_true()
    print("✓ Service enabled when ENABLE_THRESHOLD_ADJUSTMENT=true")
    
    test.test_is_enabled_when_false()
    print("✓ Service disabled when ENABLE_THRESHOLD_ADJUSTMENT=false")
    
    test.test_is_disabled_by_default()
    print("✓ Service disabled by default (no env var)")
    
    test.test_is_enabled_case_insensitive()
    print("✓ Case insensitive: TRUE, True, true all work")
    
    test.test_is_disabled_for_other_values()
    print("✓ Other values disable the service")
    
    print("\n=== All tests passed! ===\n")
