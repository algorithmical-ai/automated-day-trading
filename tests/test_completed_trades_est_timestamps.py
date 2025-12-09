"""
Unit tests for completed trades EST timestamp handling.

Tests the conversion of exit_timestamp from UTC to EST and verification
that enter_timestamp is correctly copied from created_at field.
"""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

from app.src.services.trading.base_trading_indicator import BaseTradingIndicator
from app.src.db.dynamodb_client import _get_est_timestamp


class MockIndicator(BaseTradingIndicator):
    """Mock indicator for testing"""
    @classmethod
    def indicator_name(cls) -> str:
        return "test_indicator"


class TestCompletedTradesTimestamps:
    """Test suite for completed trades timestamp handling"""
    
    @pytest.mark.asyncio
    async def test_exit_timestamp_uses_est_timezone(self):
        """Test that exit_timestamp is generated in EST timezone"""
        with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
             patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
             patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
            
            # Setup mocks
            mock_db.get_all_momentum_trades = AsyncMock(return_value=[
                {
                    "ticker": "AAPL",
                    "action": "buy_to_open",
                    "enter_price": 100.0,
                    "enter_reason": "test",
                    "created_at": _get_est_timestamp()
                }
            ])
            mock_db.add_completed_trade = AsyncMock(return_value=True)
            mock_db.delete_momentum_trade = AsyncMock(return_value=True)
            mock_mab.record_trade_outcome = AsyncMock(return_value=None)
            mock_webhook.return_value = AsyncMock(return_value=None)
            
            # Capture the exit_timestamp
            captured_exit_timestamp = None
            
            async def capture_exit_timestamp(*args, **kwargs):
                nonlocal captured_exit_timestamp
                captured_exit_timestamp = kwargs.get('exit_timestamp')
                return True
            
            mock_db.add_completed_trade.side_effect = capture_exit_timestamp
            
            # Execute the trade exit
            await MockIndicator._exit_trade(
                ticker="AAPL",
                original_action="buy_to_open",
                enter_price=100.0,
                exit_price=105.0,
                exit_reason="test exit"
            )
            
            # Verify exit_timestamp was captured
            assert captured_exit_timestamp is not None
            
            # Parse the timestamp
            exit_dt = datetime.fromisoformat(captured_exit_timestamp)
            
            # Verify it has timezone info
            assert exit_dt.tzinfo is not None
            
            # Verify it's in EST/EDT (UTC offset should be -5 or -4 hours)
            utc_offset_hours = exit_dt.utcoffset().total_seconds() / 3600
            assert utc_offset_hours in [-5.0, -4.0], \
                f"Expected EST/EDT offset (-5 or -4), got {utc_offset_hours}"
    
    @pytest.mark.asyncio
    async def test_enter_timestamp_fallback_uses_est_timezone(self):
        """Test that enter_timestamp fallback uses EST timezone when active trade is missing"""
        with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
             patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
             patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
            
            # Setup mocks with NO active trade (empty list)
            mock_db.get_all_momentum_trades = AsyncMock(return_value=[])
            mock_db.add_completed_trade = AsyncMock(return_value=True)
            mock_db.delete_momentum_trade = AsyncMock(return_value=True)
            mock_mab.record_trade_outcome = AsyncMock(return_value=None)
            mock_webhook.return_value = AsyncMock(return_value=None)
            
            # Capture the enter_timestamp
            captured_enter_timestamp = None
            
            async def capture_enter_timestamp(*args, **kwargs):
                nonlocal captured_enter_timestamp
                captured_enter_timestamp = kwargs.get('enter_timestamp')
                return True
            
            mock_db.add_completed_trade.side_effect = capture_enter_timestamp
            
            # Execute the trade exit
            await MockIndicator._exit_trade(
                ticker="AAPL",
                original_action="buy_to_open",
                enter_price=100.0,
                exit_price=105.0,
                exit_reason="test exit"
            )
            
            # Verify enter_timestamp was captured
            assert captured_enter_timestamp is not None
            
            # Parse the timestamp
            enter_dt = datetime.fromisoformat(captured_enter_timestamp)
            
            # Verify it has timezone info
            assert enter_dt.tzinfo is not None
            
            # Verify it's in EST/EDT (UTC offset should be -5 or -4 hours)
            utc_offset_hours = enter_dt.utcoffset().total_seconds() / 3600
            assert utc_offset_hours in [-5.0, -4.0], \
                f"Expected EST/EDT offset (-5 or -4), got {utc_offset_hours}"
    
    @pytest.mark.asyncio
    async def test_timestamp_format_includes_timezone_offset(self):
        """Test that timestamps include timezone offset in ISO 8601 format"""
        with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
             patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
             patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
            
            # Setup mocks
            created_at = _get_est_timestamp()
            mock_db.get_all_momentum_trades = AsyncMock(return_value=[
                {
                    "ticker": "AAPL",
                    "action": "buy_to_open",
                    "enter_price": 100.0,
                    "enter_reason": "test",
                    "created_at": created_at
                }
            ])
            mock_db.add_completed_trade = AsyncMock(return_value=True)
            mock_db.delete_momentum_trade = AsyncMock(return_value=True)
            mock_mab.record_trade_outcome = AsyncMock(return_value=None)
            mock_webhook.return_value = AsyncMock(return_value=None)
            
            # Capture both timestamps
            captured_enter_timestamp = None
            captured_exit_timestamp = None
            
            async def capture_timestamps(*args, **kwargs):
                nonlocal captured_enter_timestamp, captured_exit_timestamp
                captured_enter_timestamp = kwargs.get('enter_timestamp')
                captured_exit_timestamp = kwargs.get('exit_timestamp')
                return True
            
            mock_db.add_completed_trade.side_effect = capture_timestamps
            
            # Execute the trade exit
            await MockIndicator._exit_trade(
                ticker="AAPL",
                original_action="buy_to_open",
                enter_price=100.0,
                exit_price=105.0,
                exit_reason="test exit"
            )
            
            # Verify timestamps contain timezone offset in string format
            # EST/EDT offsets are -05:00 or -04:00
            assert '-05:00' in captured_enter_timestamp or '-04:00' in captured_enter_timestamp, \
                f"Enter timestamp should contain EST/EDT offset: {captured_enter_timestamp}"
            assert '-05:00' in captured_exit_timestamp or '-04:00' in captured_exit_timestamp, \
                f"Exit timestamp should contain EST/EDT offset: {captured_exit_timestamp}"
    
    def test_dst_boundary_winter_to_spring(self):
        """Test timestamp generation around DST spring forward boundary"""
        # DST typically starts second Sunday in March at 2:00 AM
        # Test that timestamps generated in winter have -05:00 offset
        est_tz = ZoneInfo('America/New_York')
        
        # January (definitely EST)
        winter_dt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=est_tz)
        winter_offset = winter_dt.utcoffset().total_seconds() / 3600
        assert winter_offset == -5.0, "January should be EST (-5)"
        
        # July (definitely EDT)
        summer_dt = datetime(2025, 7, 15, 12, 0, 0, tzinfo=est_tz)
        summer_offset = summer_dt.utcoffset().total_seconds() / 3600
        assert summer_offset == -4.0, "July should be EDT (-4)"
    
    def test_get_est_timestamp_helper_function(self):
        """Test that _get_est_timestamp helper returns EST timezone"""
        timestamp = _get_est_timestamp()
        
        # Parse the timestamp
        dt = datetime.fromisoformat(timestamp)
        
        # Verify it has timezone info
        assert dt.tzinfo is not None
        
        # Verify it's in EST/EDT
        utc_offset_hours = dt.utcoffset().total_seconds() / 3600
        assert utc_offset_hours in [-5.0, -4.0], \
            f"Expected EST/EDT offset (-5 or -4), got {utc_offset_hours}"
        
        # Verify timestamp contains offset in string
        assert '-05:00' in timestamp or '-04:00' in timestamp, \
            f"Timestamp should contain EST/EDT offset: {timestamp}"
    
    @pytest.mark.asyncio
    async def test_enter_timestamp_copied_from_created_at(self):
        """Test that enter_timestamp is correctly copied from created_at field"""
        with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
             patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
             patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
            
            # Setup mocks with specific created_at
            created_at = "2025-12-01T10:30:00-05:00"
            mock_db.get_all_momentum_trades = AsyncMock(return_value=[
                {
                    "ticker": "AAPL",
                    "action": "buy_to_open",
                    "enter_price": 100.0,
                    "enter_reason": "test",
                    "created_at": created_at
                }
            ])
            mock_db.add_completed_trade = AsyncMock(return_value=True)
            mock_db.delete_momentum_trade = AsyncMock(return_value=True)
            mock_mab.record_trade_outcome = AsyncMock(return_value=None)
            mock_webhook.return_value = AsyncMock(return_value=None)
            
            # Capture the enter_timestamp
            captured_enter_timestamp = None
            
            async def capture_enter_timestamp(*args, **kwargs):
                nonlocal captured_enter_timestamp
                captured_enter_timestamp = kwargs.get('enter_timestamp')
                return True
            
            mock_db.add_completed_trade.side_effect = capture_enter_timestamp
            
            # Execute the trade exit
            await MockIndicator._exit_trade(
                ticker="AAPL",
                original_action="buy_to_open",
                enter_price=100.0,
                exit_price=105.0,
                exit_reason="test exit"
            )
            
            # Verify enter_timestamp matches created_at exactly
            assert captured_enter_timestamp == created_at, \
                f"Enter timestamp should match created_at: {captured_enter_timestamp} != {created_at}"
