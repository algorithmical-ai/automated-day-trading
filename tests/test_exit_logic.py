"""
Tests for comprehensive exit logic in base trading indicator
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator


class TestExitLogic:
    """Test comprehensive exit logic"""

    @pytest.fixture
    def mock_indicator(self):
        """Create a mock indicator class"""
        class MockIndicator(BaseTradingIndicator):
            @classmethod
            def indicator_name(cls) -> str:
                return "Test Indicator"
            
            @classmethod
            async def entry_service(cls):
                pass
            
            @classmethod
            async def exit_service(cls):
                pass
        
        # Set default configuration
        MockIndicator.min_holding_period_seconds = 30
        MockIndicator.minutes_before_close_to_exit = 15
        MockIndicator.stop_loss_threshold = -2.5
        MockIndicator.trailing_stop_activation_profit = 0.5
        MockIndicator.trailing_stop_percent = 2.5
        MockIndicator.trailing_stop_short_multiplier = 1.5
        MockIndicator.trailing_stop_cooldown_seconds = 30
        
        return MockIndicator

    def test_calculate_profit_percent_long(self, mock_indicator):
        """Test profit calculation for long positions"""
        # Long position: buy at 100, sell at 105 = 5% profit
        profit = mock_indicator._calculate_profit_percent(100.0, 105.0, "buy_to_open")
        assert profit == pytest.approx(5.0, rel=0.01)
        
        # Long position: buy at 100, sell at 95 = -5% loss
        profit = mock_indicator._calculate_profit_percent(100.0, 95.0, "buy_to_open")
        assert profit == pytest.approx(-5.0, rel=0.01)

    def test_calculate_profit_percent_short(self, mock_indicator):
        """Test profit calculation for short positions"""
        # Short position: sell at 100, buy back at 95 = 5% profit
        profit = mock_indicator._calculate_profit_percent(100.0, 95.0, "sell_to_open")
        assert profit == pytest.approx(5.0, rel=0.01)
        
        # Short position: sell at 100, buy back at 105 = -5% loss
        profit = mock_indicator._calculate_profit_percent(100.0, 105.0, "sell_to_open")
        assert profit == pytest.approx(-5.0, rel=0.01)

    def test_check_holding_period_passed(self, mock_indicator):
        """Test holding period check when period has passed"""
        # Create timestamp 60 seconds ago
        created_at = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        
        passed, minutes = mock_indicator._check_holding_period(created_at, min_holding_seconds=30)
        
        assert passed is True
        assert minutes >= 1.0  # At least 1 minute

    def test_check_holding_period_not_passed(self, mock_indicator):
        """Test holding period check when period has not passed"""
        # Create timestamp 10 seconds ago
        created_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        
        passed, minutes = mock_indicator._check_holding_period(created_at, min_holding_seconds=30)
        
        assert passed is False
        assert minutes < 0.5  # Less than 30 seconds

    def test_check_holding_period_no_timestamp(self, mock_indicator):
        """Test holding period check with no timestamp"""
        passed, minutes = mock_indicator._check_holding_period(None)
        
        assert passed is True
        assert minutes == 0.0

    @pytest.mark.asyncio
    async def test_check_hard_stop_loss_triggered(self, mock_indicator):
        """Test hard stop loss when triggered"""
        should_exit, reason, profit = await mock_indicator._check_hard_stop_loss(
            ticker="AAPL",
            enter_price=100.0,
            current_price=97.0,  # -3% loss
            action="buy_to_open",
            dynamic_stop_loss=-2.5,
        )
        
        assert should_exit is True
        assert "Hard stop loss triggered" in reason
        assert profit == pytest.approx(-3.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_check_hard_stop_loss_not_triggered(self, mock_indicator):
        """Test hard stop loss when not triggered"""
        should_exit, reason, profit = await mock_indicator._check_hard_stop_loss(
            ticker="AAPL",
            enter_price=100.0,
            current_price=99.0,  # -1% loss
            action="buy_to_open",
            dynamic_stop_loss=-2.5,
        )
        
        assert should_exit is False
        assert reason is None
        assert profit == pytest.approx(-1.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_check_end_of_day_closure_profitable(self, mock_indicator):
        """Test end-of-day closure for profitable trade"""
        with patch.object(mock_indicator, '_is_near_market_close', return_value=True):
            should_exit, reason = await mock_indicator._check_end_of_day_closure(
                ticker="AAPL",
                profit_percent=2.5,  # Profitable
            )
            
            assert should_exit is True
            assert "End-of-day closure" in reason

    @pytest.mark.asyncio
    async def test_check_end_of_day_closure_losing(self, mock_indicator):
        """Test end-of-day closure for losing trade (should hold)"""
        with patch.object(mock_indicator, '_is_near_market_close', return_value=True):
            should_exit, reason = await mock_indicator._check_end_of_day_closure(
                ticker="AAPL",
                profit_percent=-1.5,  # Losing
            )
            
            assert should_exit is False
            assert reason is None

    @pytest.mark.asyncio
    async def test_check_end_of_day_closure_not_near_close(self, mock_indicator):
        """Test end-of-day closure when not near market close"""
        with patch.object(mock_indicator, '_is_near_market_close', return_value=False):
            should_exit, reason = await mock_indicator._check_end_of_day_closure(
                ticker="AAPL",
                profit_percent=2.5,
            )
            
            assert should_exit is False
            assert reason is None

    @pytest.mark.asyncio
    async def test_check_trailing_stop_not_activated(self, mock_indicator):
        """Test trailing stop when not yet activated"""
        created_at = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        
        should_exit, reason, profit = await mock_indicator._check_trailing_stop_exit(
            ticker="AAPL",
            enter_price=100.0,
            current_price=100.3,  # 0.3% profit
            action="buy_to_open",
            peak_profit_percent=0.3,  # Below activation threshold of 0.5%
            created_at=created_at,
            technical_indicators=None,
        )
        
        assert should_exit is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_check_trailing_stop_triggered(self, mock_indicator):
        """Test trailing stop when triggered"""
        created_at = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        
        should_exit, reason, profit = await mock_indicator._check_trailing_stop_exit(
            ticker="AAPL",
            enter_price=100.0,
            current_price=102.0,  # 2% profit
            action="buy_to_open",
            peak_profit_percent=5.0,  # Peak was 5%, now at 2% = 3% drop
            created_at=created_at,
            technical_indicators=None,
        )
        
        assert should_exit is True
        assert "Trailing stop triggered" in reason
        assert "3.00%" in reason  # Drop from peak

    @pytest.mark.asyncio
    async def test_get_current_price_for_exit_long(self, mock_indicator):
        """Test getting current price for long exit (uses bid)"""
        mock_quote_response = {
            "quote": {
                "quotes": {
                    "AAPL": {
                        "bp": 150.25,  # Bid price
                        "ap": 150.30,  # Ask price
                    }
                }
            }
        }
        
        with patch('app.src.common.alpaca.AlpacaClient.quote', new_callable=AsyncMock) as mock_quote:
            mock_quote.return_value = mock_quote_response
            
            price = await mock_indicator._get_current_price_for_exit("AAPL", "buy_to_open")
            
            assert price == 150.25  # Should use bid for long exit

    @pytest.mark.asyncio
    async def test_get_current_price_for_exit_short(self, mock_indicator):
        """Test getting current price for short exit (uses ask)"""
        mock_quote_response = {
            "quote": {
                "quotes": {
                    "AAPL": {
                        "bp": 150.25,  # Bid price
                        "ap": 150.30,  # Ask price
                    }
                }
            }
        }
        
        with patch('app.src.common.alpaca.AlpacaClient.quote', new_callable=AsyncMock) as mock_quote:
            mock_quote.return_value = mock_quote_response
            
            price = await mock_indicator._get_current_price_for_exit("AAPL", "sell_to_open")
            
            assert price == 150.30  # Should use ask for short exit

    @pytest.mark.asyncio
    async def test_should_exit_trade_stop_loss(self, mock_indicator):
        """Test comprehensive exit logic - stop loss triggered"""
        trade = {
            "ticker": "AAPL",
            "action": "buy_to_open",
            "enter_price": 100.0,
            "peak_profit_percent": 0.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
            "dynamic_stop_loss": -2.5,
        }
        
        mock_quote_response = {
            "quote": {
                "quotes": {
                    "AAPL": {
                        "bp": 97.0,  # -3% loss, triggers stop loss
                        "ap": 97.05,
                    }
                }
            }
        }
        
        with patch('app.src.common.alpaca.AlpacaClient.quote', new_callable=AsyncMock) as mock_quote:
            mock_quote.return_value = mock_quote_response
            
            should_exit, reason, current_price, profit = await mock_indicator._should_exit_trade(
                trade, technical_indicators=None
            )
            
            assert should_exit is True
            assert "Hard stop loss triggered" in reason
            assert current_price == 97.0
            assert profit < -2.5

    @pytest.mark.asyncio
    async def test_should_exit_trade_no_exit(self, mock_indicator):
        """Test comprehensive exit logic - no exit conditions met"""
        trade = {
            "ticker": "AAPL",
            "action": "buy_to_open",
            "enter_price": 100.0,
            "peak_profit_percent": 0.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
            "dynamic_stop_loss": -2.5,
        }
        
        mock_quote_response = {
            "quote": {
                "quotes": {
                    "AAPL": {
                        "bp": 100.5,  # Small profit, no exit conditions
                        "ap": 100.55,
                    }
                }
            }
        }
        
        with patch('app.src.common.alpaca.AlpacaClient.quote', new_callable=AsyncMock) as mock_quote:
            mock_quote.return_value = mock_quote_response
            with patch.object(mock_indicator, '_is_near_market_close', return_value=False):
                should_exit, reason, current_price, profit = await mock_indicator._should_exit_trade(
                    trade, technical_indicators=None
                )
                
                assert should_exit is False
                assert reason is None
                assert current_price == 100.5
                assert profit == pytest.approx(0.5, rel=0.01)

    @pytest.mark.asyncio
    async def test_should_exit_trade_holding_period_not_met(self, mock_indicator):
        """Test comprehensive exit logic - holding period not met"""
        trade = {
            "ticker": "AAPL",
            "action": "buy_to_open",
            "enter_price": 100.0,
            "peak_profit_percent": 0.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),  # Only 10 seconds
            "dynamic_stop_loss": -2.5,
        }
        
        should_exit, reason, current_price, profit = await mock_indicator._should_exit_trade(
            trade, technical_indicators=None
        )
        
        assert should_exit is False
        assert reason is None
        assert current_price == 0.0
        assert profit == 0.0
