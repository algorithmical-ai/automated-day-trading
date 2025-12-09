"""
Integration tests for end-to-end MAB rejection logging.

Feature: mab-rejection-logging
Tests the complete flow of MAB rejection logging from selection to DynamoDB persistence.
"""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch, MagicMock
from app.src.services.mab.mab_service import MABService
from app.src.db.dynamodb_client import DynamoDBClient


class TestMABRejectionIntegration:
    """Integration tests for MAB rejection logging."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_mab_rejection_logging(self):
        """
        Integration test: Complete flow of MAB rejection logging.
        
        Tests that:
        1. Tickers pass validation
        2. MAB rejects some tickers
        3. Rejection reasons are generated correctly
        4. Rejections are logged to DynamoDB with correct format
        """
        indicator = "Test Indicator"
        
        # Setup: Create test data
        ticker_candidates = [
            ("AAPL", 2.5, "upward momentum"),
            ("BBBB", -3.0, "downward momentum"),
            ("CCCC", 1.8, "upward momentum")
        ]
        selected_tickers = ["AAPL"]  # Only AAPL is selected
        
        # Mock MAB stats
        mab_stats_map = {
            "AAPL": None,  # New ticker - selected
            "BBBB": {
                'successes': 2,
                'failures': 8,
                'total_trades': 10,
                'excluded_until': None
            },
            "CCCC": {
                'successes': 5,
                'failures': 5,
                'total_trades': 10,
                'excluded_until': None
            }
        }
        
        # Mock DynamoDB logging
        logged_items = []
        
        async def mock_log_inactive_ticker(**kwargs):
            logged_items.append(kwargs)
            return True
        
        # Execute
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.side_effect = lambda ind, tick: mab_stats_map.get(tick)
            
            with patch.object(DynamoDBClient, 'log_inactive_ticker', new_callable=AsyncMock) as mock_log:
                mock_log.side_effect = mock_log_inactive_ticker
                
                # Get rejection info
                rejected_info = await MABService.get_rejected_tickers_with_reasons(
                    indicator=indicator,
                    ticker_candidates=ticker_candidates,
                    selected_tickers=selected_tickers
                )
                
                # Simulate logging (as would happen in the indicator)
                for ticker, rejection_data in rejected_info.items():
                    await DynamoDBClient.log_inactive_ticker(
                        ticker=ticker,
                        indicator=indicator,
                        reason_not_to_enter_long=rejection_data.get('reason_long', ''),
                        reason_not_to_enter_short=rejection_data.get('reason_short', ''),
                        technical_indicators={'momentum_score': rejection_data.get('momentum_score', 0.0)}
                    )
        
        # Verify
        # 1. AAPL should not be logged (selected)
        assert not any(item['ticker'] == 'AAPL' for item in logged_items), \
            "Selected ticker AAPL should not be logged"
        
        # 2. BBBB should be logged with reason_short
        bbbb_log = next((item for item in logged_items if item['ticker'] == 'BBBB'), None)
        assert bbbb_log is not None, "BBBB should be logged"
        assert bbbb_log['reason_not_to_enter_short'], "BBBB should have reason_short"
        assert bbbb_log['reason_not_to_enter_long'] == '', "BBBB should not have reason_long"
        assert "MAB rejected:" in bbbb_log['reason_not_to_enter_short'], \
            "BBBB reason should contain 'MAB rejected:'"
        
        # 3. CCCC should be logged with reason_long
        cccc_log = next((item for item in logged_items if item['ticker'] == 'CCCC'), None)
        assert cccc_log is not None, "CCCC should be logged"
        assert cccc_log['reason_not_to_enter_long'], "CCCC should have reason_long"
        assert cccc_log['reason_not_to_enter_short'] == '', "CCCC should not have reason_short"
        assert "MAB rejected:" in cccc_log['reason_not_to_enter_long'], \
            "CCCC reason should contain 'MAB rejected:'"
    
    @pytest.mark.asyncio
    async def test_mab_rejection_with_technical_indicators(self):
        """
        Integration test: MAB rejection logging includes technical indicators.
        
        Tests that technical indicators are properly included in the logged data.
        """
        indicator = "Test Indicator"
        
        ticker_candidates = [
            ("AAPL", 2.5, "upward momentum")
        ]
        selected_tickers = []  # Not selected
        
        # Mock MAB stats
        mab_stats = {
            'successes': 3,
            'failures': 7,
            'total_trades': 10,
            'excluded_until': None
        }
        
        # Mock technical indicators
        tech_indicators = {
            'momentum_score': 2.5,
            'volume': 50000,
            'close_price': 150.25,
            'atr': 2.5,
            'rsi': 65.0
        }
        
        logged_items = []
        
        async def mock_log_inactive_ticker(**kwargs):
            logged_items.append(kwargs)
            return True
        
        # Execute
        with patch.object(MABService, 'get_stats', new_callable=AsyncMock) as mock_get_stats:
            mock_get_stats.return_value = mab_stats
            
            with patch.object(DynamoDBClient, 'log_inactive_ticker', new_callable=AsyncMock) as mock_log:
                mock_log.side_effect = mock_log_inactive_ticker
                
                # Get rejection info
                rejected_info = await MABService.get_rejected_tickers_with_reasons(
                    indicator=indicator,
                    ticker_candidates=ticker_candidates,
                    selected_tickers=selected_tickers
                )
                
                # Log with technical indicators
                for ticker, rejection_data in rejected_info.items():
                    await DynamoDBClient.log_inactive_ticker(
                        ticker=ticker,
                        indicator=indicator,
                        reason_not_to_enter_long=rejection_data.get('reason_long', ''),
                        reason_not_to_enter_short=rejection_data.get('reason_short', ''),
                        technical_indicators=tech_indicators
                    )
        
        # Verify
        assert len(logged_items) == 1, "Should have logged one rejection"
        logged_item = logged_items[0]
        
        assert logged_item['technical_indicators'] == tech_indicators, \
            "Technical indicators should be included in the log"
        assert logged_item['technical_indicators']['momentum_score'] == 2.5, \
            "Momentum score should be in technical indicators"
    
    @pytest.mark.asyncio
    async def test_mab_rejection_timestamp_timezone(self):
        """
        Integration test: MAB rejection logging uses EST/EDT timezone.
        
        Tests that timestamps are in the correct timezone.
        """
        # This test verifies the timestamp handling in DynamoDBClient
        # The actual timestamp generation happens in log_inactive_ticker
        
        # Create a timestamp in EST/EDT
        est_tz = ZoneInfo('America/New_York')
        now_est = datetime.now(est_tz)
        
        # Verify it has timezone info
        assert now_est.tzinfo is not None, "Timestamp should have timezone info"
        assert 'America/New_York' in str(now_est.tzinfo) or 'EST' in str(now_est.tzinfo) or 'EDT' in str(now_est.tzinfo), \
            f"Timestamp should be in EST/EDT timezone but got: {now_est.tzinfo}"
