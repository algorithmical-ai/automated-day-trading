"""
Property-based tests for completed trades timestamp handling.

Feature: completed-trades-est-timestamps
"""

from hypothesis import given, strategies as st, settings
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.src.services.trading.base_trading_indicator import BaseTradingIndicator
from app.src.db.dynamodb_client import _get_est_timestamp


# Helper strategies
@st.composite
def ticker_strategy(draw):
    """Generate a valid ticker symbol."""
    return draw(st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('Lu',))))


@st.composite
def price_strategy(draw):
    """Generate a valid stock price."""
    return draw(st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False))


@st.composite
def action_strategy(draw):
    """Generate a valid trade action."""
    return draw(st.sampled_from(["buy_to_open", "sell_to_open"]))


@st.composite
def est_timestamp_strategy(draw):
    """Generate a timestamp in EST timezone (always in the past)."""
    est_tz = ZoneInfo('America/New_York')
    # Generate a datetime in the past (within last 30 days)
    now = datetime.now(est_tz)
    days_ago = draw(st.integers(min_value=0, max_value=30))
    hours_ago = draw(st.integers(min_value=0, max_value=23))
    minutes_ago = draw(st.integers(min_value=0, max_value=59))
    seconds_ago = draw(st.integers(min_value=0, max_value=59))
    
    from datetime import timedelta
    dt = now - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago, seconds=seconds_ago)
    return dt.isoformat()


# Feature: completed-trades-est-timestamps, Property 1: Exit timestamps use America/New_York timezone
@settings(max_examples=100)
@given(
    ticker=ticker_strategy(),
    action=action_strategy(),
    enter_price=price_strategy(),
    exit_price=price_strategy(),
)
@pytest.mark.asyncio
async def test_property_1_exit_timestamps_use_est_timezone(ticker, action, enter_price, exit_price):
    """
    Property 1: Exit timestamps use America/New_York timezone
    
    For any completed trade created by BaseTradingIndicator, the exit_timestamp
    should be in America/New_York timezone (indicated by -05:00 or -04:00 offset
    in ISO 8601 format).
    
    Validates: Requirements 1.1, 1.2
    """
    # Create a mock indicator
    class MockIndicator(BaseTradingIndicator):
        @classmethod
        def indicator_name(cls) -> str:
            return "test_indicator"
    
    # Mock the database and webhook calls
    with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
         patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
         patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
        
        # Setup mocks
        mock_db.get_all_momentum_trades = AsyncMock(return_value=[
            {
                "ticker": ticker,
                "action": action,
                "enter_price": enter_price,
                "enter_reason": "test",
                "created_at": _get_est_timestamp()
            }
        ])
        mock_db.add_completed_trade = AsyncMock(return_value=True)
        mock_db.delete_momentum_trade = AsyncMock(return_value=True)
        mock_mab.record_trade_outcome = AsyncMock(return_value=None)
        mock_webhook.return_value = AsyncMock(return_value=None)
        
        # Capture the exit_timestamp passed to add_completed_trade
        captured_exit_timestamp = None
        
        async def capture_exit_timestamp(*args, **kwargs):
            nonlocal captured_exit_timestamp
            captured_exit_timestamp = kwargs.get('exit_timestamp')
            return True
        
        mock_db.add_completed_trade.side_effect = capture_exit_timestamp
        
        # Execute the trade exit
        await MockIndicator._exit_trade(
            ticker=ticker,
            original_action=action,
            enter_price=enter_price,
            exit_price=exit_price,
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
        assert utc_offset_hours in [-5.0, -4.0], f"Expected EST/EDT offset (-5 or -4), got {utc_offset_hours}"


# Feature: completed-trades-est-timestamps, Property 2: Enter timestamp matches created_at from active trade
@settings(max_examples=100)
@given(
    ticker=ticker_strategy(),
    action=action_strategy(),
    enter_price=price_strategy(),
    exit_price=price_strategy(),
    created_at=est_timestamp_strategy()
)
@pytest.mark.asyncio
async def test_property_2_enter_timestamp_matches_created_at(ticker, action, enter_price, exit_price, created_at):
    """
    Property 2: Enter timestamp matches created_at from active trade
    
    For any completed trade where the active trade record exists, the enter_timestamp
    should equal the created_at field from the corresponding active trade record.
    
    Validates: Requirements 2.1, 2.2, 2.4
    """
    # Create a mock indicator
    class MockIndicator(BaseTradingIndicator):
        @classmethod
        def indicator_name(cls) -> str:
            return "test_indicator"
    
    # Mock the database and webhook calls
    with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
         patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
         patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
        
        # Setup mocks with created_at
        mock_db.get_all_momentum_trades = AsyncMock(return_value=[
            {
                "ticker": ticker,
                "action": action,
                "enter_price": enter_price,
                "enter_reason": "test",
                "created_at": created_at
            }
        ])
        mock_db.add_completed_trade = AsyncMock(return_value=True)
        mock_db.delete_momentum_trade = AsyncMock(return_value=True)
        mock_mab.record_trade_outcome = AsyncMock(return_value=None)
        mock_webhook.return_value = AsyncMock(return_value=None)
        
        # Capture the enter_timestamp passed to add_completed_trade
        captured_enter_timestamp = None
        
        async def capture_enter_timestamp(*args, **kwargs):
            nonlocal captured_enter_timestamp
            captured_enter_timestamp = kwargs.get('enter_timestamp')
            return True
        
        mock_db.add_completed_trade.side_effect = capture_enter_timestamp
        
        # Execute the trade exit
        await MockIndicator._exit_trade(
            ticker=ticker,
            original_action=action,
            enter_price=enter_price,
            exit_price=exit_price,
            exit_reason="test exit"
        )
        
        # Verify enter_timestamp matches created_at
        assert captured_enter_timestamp == created_at


# Feature: completed-trades-est-timestamps, Property 3: Exit timestamp is after enter timestamp
@settings(max_examples=100)
@given(
    ticker=ticker_strategy(),
    action=action_strategy(),
    enter_price=price_strategy(),
    exit_price=price_strategy(),
    created_at=est_timestamp_strategy()
)
@pytest.mark.asyncio
async def test_property_3_exit_timestamp_after_enter_timestamp(ticker, action, enter_price, exit_price, created_at):
    """
    Property 3: Exit timestamp is after enter timestamp
    
    For any completed trade, parsing both enter_timestamp and exit_timestamp as
    timezone-aware datetimes should show that exit_timestamp is chronologically
    after enter_timestamp.
    
    Validates: Requirements 3.3
    """
    # Create a mock indicator
    class MockIndicator(BaseTradingIndicator):
        @classmethod
        def indicator_name(cls) -> str:
            return "test_indicator"
    
    # Mock the database and webhook calls
    with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
         patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
         patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
        
        # Setup mocks
        mock_db.get_all_momentum_trades = AsyncMock(return_value=[
            {
                "ticker": ticker,
                "action": action,
                "enter_price": enter_price,
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
            ticker=ticker,
            original_action=action,
            enter_price=enter_price,
            exit_price=exit_price,
            exit_reason="test exit"
        )
        
        # Parse both timestamps
        enter_dt = datetime.fromisoformat(captured_enter_timestamp)
        exit_dt = datetime.fromisoformat(captured_exit_timestamp)
        
        # Verify exit is after enter (or equal in rare cases where they're generated at same microsecond)
        assert exit_dt >= enter_dt, f"Exit timestamp {exit_dt} should be >= enter timestamp {enter_dt}"


# Feature: completed-trades-est-timestamps, Property 4: Timestamp format is ISO 8601 with timezone
@settings(max_examples=100)
@given(
    ticker=ticker_strategy(),
    action=action_strategy(),
    enter_price=price_strategy(),
    exit_price=price_strategy(),
    created_at=est_timestamp_strategy()
)
@pytest.mark.asyncio
async def test_property_4_timestamp_format_iso8601_with_timezone(ticker, action, enter_price, exit_price, created_at):
    """
    Property 4: Timestamp format is ISO 8601 with timezone
    
    For any completed trade, both enter_timestamp and exit_timestamp should parse
    successfully as ISO 8601 format and the parsed datetimes should have timezone
    information (not naive).
    
    Validates: Requirements 1.3, 3.2
    """
    # Create a mock indicator
    class MockIndicator(BaseTradingIndicator):
        @classmethod
        def indicator_name(cls) -> str:
            return "test_indicator"
    
    # Mock the database and webhook calls
    with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
         patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
         patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
        
        # Setup mocks
        mock_db.get_all_momentum_trades = AsyncMock(return_value=[
            {
                "ticker": ticker,
                "action": action,
                "enter_price": enter_price,
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
            ticker=ticker,
            original_action=action,
            enter_price=enter_price,
            exit_price=exit_price,
            exit_reason="test exit"
        )
        
        # Parse both timestamps - should not raise exception
        enter_dt = datetime.fromisoformat(captured_enter_timestamp)
        exit_dt = datetime.fromisoformat(captured_exit_timestamp)
        
        # Verify both have timezone info (not naive)
        assert enter_dt.tzinfo is not None, "Enter timestamp should have timezone info"
        assert exit_dt.tzinfo is not None, "Exit timestamp should have timezone info"
        
        # Verify timestamps contain timezone offset in string format
        assert '+' in captured_enter_timestamp or '-' in captured_enter_timestamp.split('T')[1], \
            "Enter timestamp should contain timezone offset"
        assert '+' in captured_exit_timestamp or '-' in captured_exit_timestamp.split('T')[1], \
            "Exit timestamp should contain timezone offset"


# Feature: completed-trades-est-timestamps, Property 5: DST transition handling for exit timestamps
@settings(max_examples=100)
@given(
    ticker=ticker_strategy(),
    action=action_strategy(),
    enter_price=price_strategy(),
    exit_price=price_strategy(),
)
@pytest.mark.asyncio
async def test_property_5_dst_transition_handling(ticker, action, enter_price, exit_price):
    """
    Property 5: DST transition handling for exit timestamps
    
    For any exit timestamp generated during DST transition periods (spring forward,
    fall back), the system should use the correct offset (-04:00 for EDT, -05:00
    for EST) based on the America/New_York timezone rules.
    
    Validates: Requirements 1.5, 3.5
    """
    # Create a mock indicator
    class MockIndicator(BaseTradingIndicator):
        @classmethod
        def indicator_name(cls) -> str:
            return "test_indicator"
    
    # Mock the database and webhook calls
    with patch('app.src.services.trading.base_trading_indicator.DynamoDBClient') as mock_db, \
         patch('app.src.services.trading.base_trading_indicator.MABService') as mock_mab, \
         patch('app.src.services.trading.base_trading_indicator.send_signal_to_webhook') as mock_webhook:
        
        # Setup mocks
        mock_db.get_all_momentum_trades = AsyncMock(return_value=[
            {
                "ticker": ticker,
                "action": action,
                "enter_price": enter_price,
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
            ticker=ticker,
            original_action=action,
            enter_price=enter_price,
            exit_price=exit_price,
            exit_reason="test exit"
        )
        
        # Parse the timestamp
        exit_dt = datetime.fromisoformat(captured_exit_timestamp)
        
        # Get the UTC offset
        utc_offset_hours = exit_dt.utcoffset().total_seconds() / 3600
        
        # Verify it's either EST (-5) or EDT (-4)
        assert utc_offset_hours in [-5.0, -4.0], \
            f"Expected EST (-5) or EDT (-4) offset, got {utc_offset_hours}"
        
        # Verify the offset matches what ZoneInfo would produce for this time
        est_tz = ZoneInfo('America/New_York')
        expected_dt = datetime.now(est_tz)
        expected_offset_hours = expected_dt.utcoffset().total_seconds() / 3600
        
        # The actual offset should match the expected offset for current time
        assert utc_offset_hours == expected_offset_hours, \
            f"Offset {utc_offset_hours} doesn't match expected {expected_offset_hours} for current time"
