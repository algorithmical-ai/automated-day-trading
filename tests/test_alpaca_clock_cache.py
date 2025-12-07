"""
Unit tests for Alpaca clock caching functionality
"""
import pytest
from datetime import datetime, timezone, timedelta
from app.src.common.alpaca import AlpacaClient


class TestAlpacaClockCache:
    """Test suite for clock caching functionality"""

    def setup_method(self):
        """Reset cache before each test"""
        AlpacaClient._clock_cache = None
        AlpacaClient._clock_cache_timestamp = None

    def test_cache_validation_empty_cache(self):
        """Test that empty cache is invalid"""
        assert AlpacaClient._is_clock_cache_valid() is False

    def test_cache_validation_fresh_cache(self):
        """Test that fresh cache is valid"""
        AlpacaClient._clock_cache = {"is_open": True}
        AlpacaClient._clock_cache_timestamp = datetime.now(timezone.utc)
        assert AlpacaClient._is_clock_cache_valid() is True

    def test_cache_validation_expired_cache(self):
        """Test that expired cache is invalid"""
        AlpacaClient._clock_cache = {"is_open": True}
        # Set timestamp to 11 minutes ago (beyond TTL)
        AlpacaClient._clock_cache_timestamp = datetime.now(timezone.utc) - timedelta(
            seconds=660
        )
        assert AlpacaClient._is_clock_cache_valid() is False

    def test_cache_validation_almost_expired(self):
        """Test that cache just before expiry is still valid"""
        AlpacaClient._clock_cache = {"is_open": True}
        # Set timestamp to 9 minutes ago (within TTL)
        AlpacaClient._clock_cache_timestamp = datetime.now(timezone.utc) - timedelta(
            seconds=540
        )
        assert AlpacaClient._is_clock_cache_valid() is True

    def test_cache_validation_exactly_at_ttl(self):
        """Test cache at exactly TTL boundary"""
        AlpacaClient._clock_cache = {"is_open": True}
        # Set timestamp to exactly 10 minutes ago
        AlpacaClient._clock_cache_timestamp = datetime.now(timezone.utc) - timedelta(
            seconds=600
        )
        # Should be invalid (>= TTL)
        assert AlpacaClient._is_clock_cache_valid() is False

    def test_cache_validation_missing_timestamp(self):
        """Test that cache without timestamp is invalid"""
        AlpacaClient._clock_cache = {"is_open": True}
        AlpacaClient._clock_cache_timestamp = None
        assert AlpacaClient._is_clock_cache_valid() is False

    def test_cache_validation_missing_data(self):
        """Test that timestamp without data is invalid"""
        AlpacaClient._clock_cache = None
        AlpacaClient._clock_cache_timestamp = datetime.now(timezone.utc)
        assert AlpacaClient._is_clock_cache_valid() is False

    def test_cache_ttl_constant(self):
        """Test that TTL is set to 10 minutes (600 seconds)"""
        assert AlpacaClient._clock_cache_ttl_seconds == 600
