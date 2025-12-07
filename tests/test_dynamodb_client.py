"""
Unit tests for DynamoDB client and data models.
"""
import pytest
from datetime import datetime
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.models import (
    ActiveTrade,
    CompletedTrade,
    InactiveTicker,
    ThresholdAdjustmentEvent,
    MABStats
)

class TestDataModels:
    """Test data model serialization and deserialization."""
    
    def test_active_trade_to_dict(self):
        """Test ActiveTrade serialization."""
        trade = ActiveTrade(
            ticker="AAPL",
            action="buy_to_open",
            indicator="momentum",
            enter_price=150.0,
            enter_reason="Strong momentum",
            technical_indicators_for_enter={"rsi": 65, "adx": 25},
            dynamic_stop_loss=-0.05,
            trailing_stop=0.02,
            peak_profit_percent=0.0,
            entry_score=0.75
        )
        
        data = trade.to_dict()
        assert data['ticker'] == "AAPL"
        assert data['action'] == "buy_to_open"
        assert data['indicator'] == "momentum"
        assert data['entry_score'] == 0.75
        assert 'created_at' in data
    
    def test_active_trade_from_dict(self):
        """Test ActiveTrade deserialization."""
        data = {
            'ticker': 'TSLA',
            'action': 'sell_to_open',
            'indicator': 'penny_stocks',
            'enter_price': 200.0,
            'enter_reason': 'Downward trend',
            'technical_indicators_for_enter': {'momentum': -5.0},
            'dynamic_stop_loss': -0.04,
            'trailing_stop': 0.015,
            'peak_profit_percent': 0.0,
            'entry_score': None,
            'created_at': '2024-01-01T12:00:00'
        }
        
        trade = ActiveTrade.from_dict(data)
        assert trade.ticker == 'TSLA'
        assert trade.action == 'sell_to_open'
        assert trade.entry_score is None
    
    def test_completed_trade_to_dict(self):
        """Test CompletedTrade serialization."""
        trade = CompletedTrade(
            date='2024-01-01',
            ticker='NVDA',
            indicator='deep_analyzer',
            action='buy_to_open',
            enter_price=500.0,
            exit_price=510.0,
            enter_timestamp='2024-01-01T10:00:00',
            exit_timestamp='2024-01-01T11:00:00',
            profit_or_loss=10.0,
            enter_reason='High entry score',
            exit_reason='Profit target reached',
            technical_indicators_for_enter={'score': 0.85},
            technical_indicators_for_exit={'score': 0.60}
        )
        
        data = trade.to_dict()
        assert data['ticker'] == 'NVDA'
        assert data['profit_or_loss'] == 10.0
    
    def test_inactive_ticker_to_dict(self):
        """Test InactiveTicker serialization."""
        ticker = InactiveTicker(
            ticker='AMD',
            indicator='momentum',
            timestamp='2024-01-01T12:00:00',
            reason_not_to_enter_long='ADX too low',
            reason_not_to_enter_short='No downward momentum',
            technical_indicators={'adx': 15, 'rsi': 50}
        )
        
        data = ticker.to_dict()
        assert data['ticker'] == 'AMD'
        assert data['reason_not_to_enter_long'] == 'ADX too low'
    
    def test_threshold_adjustment_event_to_dict(self):
        """Test ThresholdAdjustmentEvent serialization."""
        event = ThresholdAdjustmentEvent(
            date='2024-01-01',
            indicator='momentum',
            last_updated='2024-01-01T12:00:00',
            threshold_change={'min_momentum': {'old': 1.5, 'new': 1.8}},
            max_long_trades=5,
            max_short_trades=5,
            llm_response='Increased threshold due to market volatility'
        )
        
        data = event.to_dict()
        assert data['indicator'] == 'momentum'
        assert data['max_long_trades'] == 5
    
    def test_mab_stats_to_dict(self):
        """Test MABStats serialization."""
        stats = MABStats(
            indicator_ticker='momentum#AAPL',
            successes=10,
            failures=5,
            total_trades=15,
            last_updated='2024-01-01T12:00:00',
            excluded_until=None
        )
        
        data = stats.to_dict()
        assert data['indicator_ticker'] == 'momentum#AAPL'
        assert data['successes'] == 10
        assert data['total_trades'] == 15


@pytest.mark.asyncio
class TestDynamoDBClient:
    """Test DynamoDB client operations."""
    
    @pytest.fixture
    def client(self):
        """Create DynamoDB client instance."""
        return DynamoDBClient()
    
    def test_client_initialization(self, client):
        """Test that client initializes correctly."""
        assert client is not None
        assert client.session is not None
        assert client.aws_region == 'us-east-1'
    
    async def test_put_item_returns_bool(self, client):
        """Test that put_item returns a boolean."""
        # This will fail if AWS credentials are invalid, but should return False gracefully
        result = await client.put_item('test_table', {'id': 'test'})
        assert isinstance(result, bool)
    
    async def test_get_item_returns_optional_dict(self, client):
        """Test that get_item returns optional dict."""
        result = await client.get_item('test_table', {'id': 'test'})
        assert result is None or isinstance(result, dict)
    
    async def test_delete_item_returns_bool(self, client):
        """Test that delete_item returns a boolean."""
        result = await client.delete_item('test_table', {'id': 'test'})
        assert isinstance(result, bool)
    
    async def test_query_returns_list(self, client):
        """Test that query returns a list."""
        result = await client.query(
            'test_table',
            'id = :id',
            {':id': 'test'}
        )
        assert isinstance(result, list)
    
    async def test_scan_returns_list(self, client):
        """Test that scan returns a list."""
        result = await client.scan('test_table')
        assert isinstance(result, list)
    
    async def test_update_item_returns_bool(self, client):
        """Test that update_item returns a boolean."""
        result = await client.update_item(
            'test_table',
            {'id': 'test'},
            'SET #attr = :val',
            {':val': 'new_value'},
            {'#attr': 'attribute'}
        )
        assert isinstance(result, bool)
