"""
Integration test to verify momentum indicator works with TechnicalAnalysisLib
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from app.src.services.trading.momentum_indicator import MomentumIndicator


@pytest.mark.asyncio
async def test_momentum_indicator_with_technical_analysis_dict():
    """
    Test that momentum indicator correctly processes the dict returned by
    TechnicalAnalysisLib.calculate_all_indicators()
    """
    
    # Create a mock technical analysis response (as returned by TechnicalAnalysisLib)
    base_time = datetime(2024, 12, 8, 9, 30, 0)
    base_price = 100.0
    
    # Create datetime_price as dict (current format from TechnicalAnalysisLib)
    datetime_price_dict = {}
    for i in range(50):
        timestamp = base_time + timedelta(minutes=i)
        price = base_price + (i * 0.2)  # Gradual upward trend
        datetime_price_dict[timestamp.isoformat()] = price
    
    mock_technical_analysis = {
        "rsi": 55.0,
        "macd": (0.5, 0.3, 0.2),
        "bollinger": (105.0, 100.0, 95.0),
        "adx": 25.0,
        "ema_fast": 100.5,
        "ema_slow": 100.2,
        "volume_sma": 50000.0,
        "obv": 1000000.0,
        "mfi": 60.0,
        "ad": 500000.0,
        "stoch": (60.0, 55.0),
        "cci": 50.0,
        "atr": 2.0,
        "willr": -40.0,
        "roc": 1.5,
        "vwap": 100.3,
        "vwma": 100.2,
        "wma": 100.1,
        "volume": 60000.0,
        "close_price": 109.8,
        "datetime_price": datetime_price_dict,  # Dict format!
    }
    
    # Mock _fetch_market_data_batch to return our mock data
    with patch.object(
        MomentumIndicator,
        '_fetch_market_data_batch',
        new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = {
            "AAPL": mock_technical_analysis
        }
        
        # Call the method that processes market data
        market_data_dict = await MomentumIndicator._fetch_market_data_batch(["AAPL"])
        
        # Verify we got the data
        assert "AAPL" in market_data_dict
        market_data_response = market_data_dict["AAPL"]
        
        # Extract datetime_price (this is what the momentum indicator does)
        technical_analysis = market_data_response if isinstance(market_data_response, dict) else {}
        datetime_price_for_momentum = technical_analysis.get("datetime_price", [])
        
        # Verify datetime_price is a dict
        assert isinstance(datetime_price_for_momentum, dict), \
            f"Expected dict, got {type(datetime_price_for_momentum)}"
        assert len(datetime_price_for_momentum) == 50
        
        # Calculate momentum (this is what the momentum indicator does)
        momentum_score, reason = MomentumIndicator._calculate_momentum(
            datetime_price_for_momentum
        )
        
        # Verify momentum is calculated correctly
        assert momentum_score > 0, f"Expected positive momentum for upward trend, got {momentum_score}"
        assert "Momentum:" in reason
        
        print(f"✓ Integration test passed!")
        print(f"  - datetime_price format: {type(datetime_price_for_momentum).__name__}")
        print(f"  - Number of price points: {len(datetime_price_for_momentum)}")
        print(f"  - Calculated momentum: {momentum_score:.2f}%")
        print(f"  - Reason: {reason}")


@pytest.mark.asyncio
async def test_momentum_indicator_handles_empty_datetime_price():
    """Test that momentum indicator handles empty datetime_price gracefully"""
    
    mock_technical_analysis = {
        "rsi": 55.0,
        "close_price": 100.0,
        "datetime_price": {},  # Empty dict!
    }
    
    with patch.object(
        MomentumIndicator,
        '_fetch_market_data_batch',
        new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = {
            "AAPL": mock_technical_analysis
        }
        
        market_data_dict = await MomentumIndicator._fetch_market_data_batch(["AAPL"])
        market_data_response = market_data_dict["AAPL"]
        
        technical_analysis = market_data_response if isinstance(market_data_response, dict) else {}
        datetime_price_for_momentum = technical_analysis.get("datetime_price", [])
        
        # Calculate momentum
        momentum_score, reason = MomentumIndicator._calculate_momentum(
            datetime_price_for_momentum
        )
        
        # Should return 0.0 for empty data
        assert momentum_score == 0.0
        assert "Insufficient price data" in reason
        
        print(f"✓ Empty datetime_price handled correctly: {reason}")


if __name__ == "__main__":
    import asyncio
    
    print("\n=== Testing Momentum Indicator Integration ===\n")
    
    asyncio.run(test_momentum_indicator_with_technical_analysis_dict())
    asyncio.run(test_momentum_indicator_handles_empty_datetime_price())
    
    print("\n=== All integration tests passed! ===\n")
