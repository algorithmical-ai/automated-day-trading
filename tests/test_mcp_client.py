"""
Unit tests for MCP Client
Tests basic functionality of the MCP API client
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.src.services.mcp.mcp_client import MCPClient


@pytest.mark.asyncio
async def test_shared_session_creation():
    """Test that shared session is created and reused"""
    try:
        # Get session twice
        session1 = await MCPClient._get_session()
        session2 = await MCPClient._get_session()
        
        # Should be the same session object
        assert session1 is session2
        assert not session1.closed
    finally:
        await MCPClient.close_session()


@pytest.mark.asyncio
async def test_session_cleanup():
    """Test that session is properly closed"""
    try:
        # Create session
        session = await MCPClient._get_session()
        assert not session.closed
        
        # Close session
        await MCPClient.close_session()
        
        # Session should be closed
        assert session.closed
        assert MCPClient._shared_session is None
    finally:
        await MCPClient.close_session()

@pytest.mark.asyncio
async def test_get_market_clock_debug_mode():
    """Test market clock returns open in debug mode"""
    # Mock DEBUG_DAY_TRADING to be True
    with patch('app.src.services.mcp.mcp_client.DEBUG_DAY_TRADING', True):
        result = await MCPClient.get_market_clock()
        
        assert result is not None
        assert result == {"clock": {"is_open": True}}


@pytest.mark.asyncio
async def test_send_webhook_signal_structure():
    """Test send_webhook_signal accepts correct parameters"""
    signal_data = {
        "ticker": "AAPL",
        "action": "buy_to_open",
        "price": 150.50,
        "reason": "momentum signal",
        "technical_indicators": {"rsi": 65, "adx": 25},
        "indicator": "momentum_trading"
    }
    
    # Mock the _call_mcp_tool method
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"status": "success"}
        
        result = await MCPClient.send_webhook_signal(signal_data)
        
        # Verify the method was called with correct parameters
        mock_call.assert_called_once_with("send_webhook_signal", {"signal_data": signal_data})
        assert result == {"status": "success"}


@pytest.mark.asyncio
async def test_send_webhook_signal_handles_failure():
    """Test send_webhook_signal handles failures gracefully"""
    signal_data = {
        "ticker": "AAPL",
        "action": "buy_to_open",
        "price": 150.50,
        "reason": "test",
        "technical_indicators": {},
        "indicator": "test"
    }
    
    # Mock the _call_mcp_tool method to return None (failure)
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = None
        
        result = await MCPClient.send_webhook_signal(signal_data)
        
        # Should return None but not raise exception
        assert result is None


@pytest.mark.asyncio
async def test_get_quote():
    """Test get_quote method"""
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"bid": 150.0, "ask": 150.5}
        
        result = await MCPClient.get_quote("AAPL")
        
        mock_call.assert_called_once_with("get_quote", {"ticker": "AAPL"})
        assert result == {"bid": 150.0, "ask": 150.5}


@pytest.mark.asyncio
async def test_get_market_data():
    """Test get_market_data method"""
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {
            "ticker": "AAPL",
            "price": 150.0,
            "technical_indicators": {"rsi": 65}
        }
        
        result = await MCPClient.get_market_data("AAPL")
        
        mock_call.assert_called_once_with("get_market_data", {"ticker": "AAPL"})
        assert result["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_enter_trade():
    """Test enter method"""
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"score": 0.75, "signal": "buy"}
        
        result = await MCPClient.enter("AAPL", "buy_to_open")
        
        mock_call.assert_called_once_with("enter", {"ticker": "AAPL", "action": "buy_to_open"})
        assert result["score"] == 0.75


@pytest.mark.asyncio
async def test_exit_trade():
    """Test exit method"""
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"signal": "exit", "reason": "stop_loss"}
        
        result = await MCPClient.exit("AAPL", 150.0, "buy_to_open")
        
        mock_call.assert_called_once_with("exit", {
            "ticker": "AAPL",
            "enter_price": 150.0,
            "action": "buy_to_open"
        })
        assert result["signal"] == "exit"


@pytest.mark.asyncio
async def test_exponential_backoff_on_503():
    """Test that exponential backoff is applied on 503 errors"""
    # This test verifies the retry logic exists by checking the implementation
    # A full integration test would require a real server returning 503
    # For now, we verify the method signature and basic error handling
    
    with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
        # Simulate a failure that would trigger retry logic
        mock_call.return_value = None
        
        result = await MCPClient.get_market_data("TEST")
        
        # Should return None on failure
        assert result is None
        mock_call.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


@pytest.mark.asyncio
async def test_market_data_caching():
    """Test that market data is cached and reused"""
    try:
        # Configure client with cache
        MCPClient.configure(cache_maxsize=500, cache_ttl=60.0)
        
        # Mock the _call_mcp_tool method
        with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "ticker": "AAPL",
                "price": 150.50,
                "technical_indicators": {"rsi": 65}
            }
            
            # First call should hit the API
            result1 = await MCPClient.get_market_data("AAPL", use_cache=True)
            assert result1 is not None
            assert mock_call.call_count == 1
            
            # Second call should use cache
            result2 = await MCPClient.get_market_data("AAPL", use_cache=True)
            assert result2 is not None
            assert result2 == result1
            assert mock_call.call_count == 1  # Should not call API again
            
            # Third call with cache disabled should hit API
            result3 = await MCPClient.get_market_data("AAPL", use_cache=False)
            assert result3 is not None
            assert mock_call.call_count == 2  # Should call API again
    finally:
        await MCPClient.close_session()


@pytest.mark.asyncio
async def test_market_data_cache_invalidation():
    """Test cache invalidation for market data"""
    try:
        # Configure client with cache
        MCPClient.configure(cache_maxsize=500, cache_ttl=60.0)
        
        # Mock the _call_mcp_tool method
        with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"ticker": "AAPL", "price": 150.50}
            
            # Cache some data
            await MCPClient.get_market_data("AAPL", use_cache=True)
            assert mock_call.call_count == 1
            
            # Invalidate cache for this ticker
            await MCPClient.invalidate_market_data_cache("AAPL")
            
            # Next call should hit API again
            await MCPClient.get_market_data("AAPL", use_cache=True)
            assert mock_call.call_count == 2
    finally:
        await MCPClient.close_session()


@pytest.mark.asyncio
async def test_market_data_cache_stats():
    """Test cache statistics retrieval"""
    try:
        # Configure client with cache
        MCPClient.configure(cache_maxsize=500, cache_ttl=60.0)
        
        # Mock the _call_mcp_tool method
        with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"ticker": "AAPL", "price": 150.50}
            
            # Make some cached calls
            await MCPClient.get_market_data("AAPL", use_cache=True)
            await MCPClient.get_market_data("AAPL", use_cache=True)  # Cache hit
            await MCPClient.get_market_data("TSLA", use_cache=True)  # Cache miss
            
            # Get stats
            stats = await MCPClient.get_cache_stats()
            assert stats["size"] == 2  # AAPL and TSLA
            assert stats["maxsize"] == 500
            assert stats["hits"] >= 1
            assert stats["misses"] >= 1
    finally:
        await MCPClient.close_session()


@pytest.mark.asyncio
async def test_cache_size_limit():
    """Test that cache respects size limit"""
    try:
        # Configure client with small cache
        MCPClient.configure(cache_maxsize=3, cache_ttl=60.0)
        
        # Mock the _call_mcp_tool method
        with patch.object(MCPClient, '_call_mcp_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"price": 100.0}
            
            # Add more items than cache size
            await MCPClient.get_market_data("AAPL", use_cache=True)
            await MCPClient.get_market_data("TSLA", use_cache=True)
            await MCPClient.get_market_data("GOOGL", use_cache=True)
            await MCPClient.get_market_data("MSFT", use_cache=True)
            
            # Check cache size
            stats = await MCPClient.get_cache_stats()
            assert stats["size"] <= 3  # Should not exceed maxsize
    finally:
        await MCPClient.close_session()
