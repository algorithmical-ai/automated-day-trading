"""
Tests for webhook notification system
Validates Requirements 13.1, 13.2, 13.3, 13.4, 13.5
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.src.services.webhook.send_signal import send_signal_to_webhook


class TestWebhookNotifications:
    """Test webhook notification system"""

    @pytest.mark.asyncio
    async def test_entry_webhook_includes_all_required_fields(self):
        """
        Test that entry webhook includes all required fields:
        ticker, action, price, reason, technical indicators, indicator name
        Validates: Requirements 13.1, 13.3
        """
        with patch('app.src.services.webhook.send_signal.AlpacaClient') as mock_alpaca, \
             patch('app.src.services.webhook.send_signal.requests.post') as mock_post, \
             patch('app.src.services.webhook.send_signal.WEBHOOK_URLS', ['http://webhook.test']):
            
            # Mock Alpaca quote response
            mock_alpaca.quote = AsyncMock(return_value={
                "quote": {
                    "quotes": {
                        "AAPL": {"ap": 150.50, "bp": 150.45}
                    }
                }
            })
            
            # Mock successful webhook response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            technical_indicators = {
                "adx": 25.5,
                "rsi": 55.0,
                "volume": 1000000,
                "atr": 2.5
            }
            
            # Call webhook for entry
            await send_signal_to_webhook(
                ticker="AAPL",
                action="buy_to_open",
                indicator="momentum_trading",
                enter_reason="Strong upward momentum",
                enter_price=150.50,
                technical_indicators=technical_indicators,
            )
            
            # Verify webhook was called
            assert mock_post.called
            call_args = mock_post.call_args
            payload = call_args[1]['json']
            
            # Verify all required fields are present
            assert payload['ticker_symbol'] == "AAPL"
            assert payload['action'] == "BUY_TO_OPEN"
            assert payload['indicator'] == "momentum_trading"
            assert payload['enter_reason'] == "Strong upward momentum"
            assert payload['technical_indicators'] == technical_indicators
            assert 'current_price' in payload

    @pytest.mark.asyncio
    async def test_exit_webhook_includes_profit_loss(self):
        """
        Test that exit webhook includes profit/loss
        Validates: Requirements 13.2, 13.3
        """
        with patch('app.src.services.webhook.send_signal.AlpacaClient') as mock_alpaca, \
             patch('app.src.services.webhook.send_signal.requests.post') as mock_post, \
             patch('app.src.services.webhook.send_signal.WEBHOOK_URLS', ['http://webhook.test']):
            
            # Mock Alpaca quote response
            mock_alpaca.quote = AsyncMock(return_value={
                "quote": {
                    "quotes": {
                        "AAPL": {"ap": 155.00, "bp": 154.95}
                    }
                }
            })
            
            # Mock successful webhook response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            technical_indicators = {
                "adx": 25.5,
                "rsi": 55.0,
            }
            
            # Call webhook for exit with profit/loss
            await send_signal_to_webhook(
                ticker="AAPL",
                action="sell_to_close",
                indicator="momentum_trading",
                enter_reason="Trailing stop triggered",
                profit_loss=59.93,  # Profit from trade
                enter_price=150.50,
                exit_price=155.00,
                technical_indicators=technical_indicators,
            )
            
            # Verify webhook was called
            assert mock_post.called
            call_args = mock_post.call_args
            payload = call_args[1]['json']
            
            # Verify exit-specific fields are present
            assert payload['ticker_symbol'] == "AAPL"
            assert payload['action'] == "SELL_TO_CLOSE"
            assert payload['indicator'] == "momentum_trading"
            assert payload['exit_reason'] == "Trailing stop triggered"
            assert payload['profit_loss'] == 59.93
            assert payload['enter_price'] == 150.50
            assert payload['exit_price'] == 155.00
            assert payload['technical_indicators'] == technical_indicators

    @pytest.mark.asyncio
    async def test_webhook_error_handling_continues_operation(self):
        """
        Test that webhook failures are logged but don't stop operation
        Validates: Requirements 13.4
        """
        with patch('app.src.services.webhook.send_signal.AlpacaClient') as mock_alpaca, \
             patch('app.src.services.webhook.send_signal.requests.post') as mock_post:
            
            # Mock Alpaca quote response
            mock_alpaca.quote = AsyncMock(return_value={
                "quote": {
                    "quotes": {
                        "AAPL": {"ap": 150.50, "bp": 150.45}
                    }
                }
            })
            
            # Mock failed webhook response
            mock_post.side_effect = Exception("Connection timeout")
            
            # Call webhook - should not raise exception
            try:
                await send_signal_to_webhook(
                    ticker="AAPL",
                    action="buy_to_open",
                    indicator="momentum_trading",
                    enter_reason="Strong upward momentum",
                    enter_price=150.50,
                )
                # If we get here, error was handled gracefully
                assert True
            except Exception:
                # Should not raise exception
                pytest.fail("Webhook error should be handled gracefully")

    @pytest.mark.asyncio
    async def test_multi_webhook_support(self):
        """
        Test that signals are sent to multiple webhook URLs
        Validates: Requirements 13.5
        """
        with patch('app.src.services.webhook.send_signal.AlpacaClient') as mock_alpaca, \
             patch('app.src.services.webhook.send_signal.requests.post') as mock_post, \
             patch('app.src.services.webhook.send_signal.WEBHOOK_URLS', 
                   ['http://webhook1.com', 'http://webhook2.com']):
            
            # Mock Alpaca quote response
            mock_alpaca.quote = AsyncMock(return_value={
                "quote": {
                    "quotes": {
                        "AAPL": {"ap": 150.50, "bp": 150.45}
                    }
                }
            })
            
            # Mock successful webhook response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            # Call webhook
            await send_signal_to_webhook(
                ticker="AAPL",
                action="buy_to_open",
                indicator="momentum_trading",
                enter_reason="Strong upward momentum",
                enter_price=150.50,
            )
            
            # Verify webhook was called for both URLs
            assert mock_post.call_count >= 2  # Should be called for each webhook URL

    @pytest.mark.asyncio
    async def test_webhook_payload_completeness(self):
        """
        Test that webhook payload includes all required fields
        Validates: Requirements 13.3
        """
        with patch('app.src.services.webhook.send_signal.AlpacaClient') as mock_alpaca, \
             patch('app.src.services.webhook.send_signal.requests.post') as mock_post, \
             patch('app.src.services.webhook.send_signal.WEBHOOK_URLS', ['http://webhook.test']):
            
            # Mock Alpaca quote response
            mock_alpaca.quote = AsyncMock(return_value={
                "quote": {
                    "quotes": {
                        "AAPL": {"ap": 150.50, "bp": 150.45}
                    }
                }
            })
            
            # Mock successful webhook response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            technical_indicators = {
                "adx": 25.5,
                "rsi": 55.0,
                "volume": 1000000,
            }
            
            # Call webhook
            await send_signal_to_webhook(
                ticker="AAPL",
                action="buy_to_open",
                indicator="momentum_trading",
                enter_reason="Strong upward momentum",
                enter_price=150.50,
                technical_indicators=technical_indicators,
            )
            
            # Verify webhook was called
            assert mock_post.called
            call_args = mock_post.call_args
            payload = call_args[1]['json']
            
            # Verify required fields
            required_fields = [
                'ticker_symbol',
                'action',
                'indicator',
                'enter_reason',
                'technical_indicators',
            ]
            
            for field in required_fields:
                assert field in payload, f"Required field '{field}' missing from webhook payload"
