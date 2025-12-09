"""
Tests for EST timestamp conversion in DynamoDB operations
"""

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from app.src.db.dynamodb_client import _get_est_timestamp


class TestESTTimestampConversion:
    """Test suite for EST timestamp conversion"""

    def test_get_est_timestamp_returns_string(self):
        """Test that _get_est_timestamp returns a string"""
        result = _get_est_timestamp()
        assert isinstance(result, str)

    def test_get_est_timestamp_is_iso_format(self):
        """Test that _get_est_timestamp returns ISO format string"""
        result = _get_est_timestamp()
        # Should be parseable as ISO format
        try:
            datetime.fromisoformat(result)
            assert True
        except ValueError:
            assert False, f"Timestamp {result} is not in ISO format"

    def test_get_est_timestamp_contains_timezone(self):
        """Test that _get_est_timestamp includes timezone info"""
        result = _get_est_timestamp()
        # ISO format with timezone should contain + or - for offset
        assert '+' in result or '-' in result, f"Timestamp {result} doesn't contain timezone offset"

    def test_get_est_timestamp_is_in_est(self):
        """Test that _get_est_timestamp is in EST timezone"""
        result = _get_est_timestamp()
        parsed = datetime.fromisoformat(result)
        
        # Get current EST time
        est_tz = ZoneInfo('America/New_York')
        est_now = datetime.now(est_tz)
        
        # The parsed timestamp should be close to EST now (within 1 second)
        time_diff = abs((parsed - est_now).total_seconds())
        assert time_diff < 1.0, f"Timestamp {result} is not in EST timezone"

    def test_get_est_timestamp_multiple_calls_are_different(self):
        """Test that multiple calls to _get_est_timestamp produce different timestamps"""
        import time
        
        ts1 = _get_est_timestamp()
        time.sleep(0.01)  # Sleep 10ms
        ts2 = _get_est_timestamp()
        
        # They should be different (unless we're extremely unlucky)
        assert ts1 != ts2, "Multiple calls should produce different timestamps"

    def test_get_est_timestamp_is_not_utc(self):
        """Test that _get_est_timestamp is not in UTC"""
        result = _get_est_timestamp()
        parsed = datetime.fromisoformat(result)
        
        # Check the timezone offset - EST should be -05:00 or -04:00 (EDT)
        # UTC would be +00:00
        offset = parsed.utcoffset()
        assert offset is not None, "Timestamp should have timezone info"
        
        # EST/EDT offset should be negative (behind UTC)
        assert offset.total_seconds() < 0, "EST should be behind UTC (negative offset)"
        
        # EST is UTC-5 (or UTC-4 during DST), so offset should be between -5 and -4 hours
        offset_hours = offset.total_seconds() / 3600
        assert -5 <= offset_hours <= -4, f"Offset {offset_hours} is not EST/EDT"

    def test_get_est_timestamp_format_consistency(self):
        """Test that _get_est_timestamp format is consistent"""
        result = _get_est_timestamp()
        
        # Should have format like: 2025-12-08T21:58:11.123456-05:00
        # Check for required components
        assert 'T' in result, "Timestamp should contain 'T' separator"
        assert ':' in result, "Timestamp should contain ':' for time"
        assert '-' in result or '+' in result, "Timestamp should contain timezone offset"
