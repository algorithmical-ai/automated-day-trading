"""
MCP Client for interacting with Market Data Analyzer API
Uses MCP protocol with StreamableHTTP transport, with HTTP fallback
"""
import asyncio
import aiohttp
from typing import Optional, Dict, Any
from loguru_logger import logger
from constants import MARKET_DATA_MCP_URL, MCP_AUTH_HEADER_NAME, MARKET_DATA_MCP_TOKEN
from tool_discovery import ToolDiscoveryService
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Implementation


class MCPClient:
    """Client for interacting with MCP tools using MCP protocol"""
    
    def __init__(self, tool_discovery: Optional[ToolDiscoveryService] = None):
        self.base_url = MARKET_DATA_MCP_URL
        self.auth_header_name = MCP_AUTH_HEADER_NAME
        self.auth_token = MARKET_DATA_MCP_TOKEN
        self.tool_discovery = tool_discovery
    
    async def _call_mcp_tool_http(self, tool_name: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fallback method using direct HTTP POST requests"""
        try:
            headers = {
                "Content-Type": "application/json"
            }
            if self.auth_token:
                headers[self.auth_header_name] = self.auth_token
            
            # Try different endpoint structures
            # Method 1: POST to /mcp/{tool_name}
            url1 = f"{self.base_url}/{tool_name}"
            
            async with aiohttp.ClientSession() as session:
                # Try POST to /mcp/{tool_name} first
                async with session.post(url1, json=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    elif response.status == 404:
                        # If 404, try POST to /mcp with tool name in body
                        logger.debug(f"404 for {url1}, trying POST to {self.base_url} with tool in body")
                        # Try sending as MCP-style JSON-RPC request
                        jsonrpc_body = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {
                                "name": tool_name,
                                "arguments": params
                            }
                        }
                        async with session.post(self.base_url, json=jsonrpc_body, headers=headers) as response2:
                            if response2.status == 200:
                                data = await response2.json()
                                # Extract result from JSON-RPC response
                                if isinstance(data, dict):
                                    if "result" in data:
                                        return data["result"]
                                    return data
                                return data
                            else:
                                error_text = await response2.text()
                                logger.error(f"HTTP Error calling {tool_name} (method 2): {response2.status} - {error_text[:200]}")
                    else:
                        error_text = await response.text()
                        logger.error(f"HTTP Error calling {tool_name}: {response.status} - {error_text[:200]}")
                        return None
        except Exception as e:
            logger.exception(f"HTTP Exception calling {tool_name}: {str(e)}")
            return None
    
    async def _call_mcp_tool(self, tool_name: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generic method to call MCP tools - uses HTTP directly since MCP protocol fails with 500 errors"""
        # Check if tool is available via discovery service
        if self.tool_discovery:
            is_available = await self.tool_discovery.is_tool_available(tool_name)
            if not is_available:
                logger.debug(f"Tool {tool_name} not found in discovered tools list, trying anyway...")
        
        # Since MCP protocol is consistently failing with 500 errors, use HTTP directly
        # The server appears to not be handling our MCP protocol requests correctly
        # MCP Inspector might be using a different approach or version
        return await self._call_mcp_tool_http(tool_name, params)
    
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generic method to call any discovered MCP tool by name"""
        return await self._call_mcp_tool(tool_name, params)
    
    async def get_market_clock(self) -> Optional[Dict[str, Any]]:
        """Get market clock status"""
        return await self._call_mcp_tool("get_market_clock", {})
    
    async def get_alpaca_screened_tickers(self) -> Optional[Dict[str, Any]]:
        """Get screened tickers (gainers, losers, most_actives)"""
        return await self._call_mcp_tool("get_alpaca_screened_tickers", {})
    
    async def get_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get quote for a ticker"""
        params = {
            "ticker": ticker
        }
        return await self._call_mcp_tool("get_quote", params)
    
    async def enter(self, ticker: str, action: str) -> Optional[Dict[str, Any]]:
        """Call enter() MCP tool"""
        params = {
            "ticker": ticker,
            "action": action
        }
        return await self._call_mcp_tool("enter", params)
    
    async def exit(self, ticker: str, enter_price: float, action: str) -> Optional[Dict[str, Any]]:
        """Call exit() MCP tool"""
        params = {
            "ticker": ticker,
            "enter_price": enter_price,
            "action": action
        }
        return await self._call_mcp_tool("exit", params)
    
    async def send_webhook_signal(
        self, 
        ticker: str, 
        action: str, 
        indicator: str, 
        enter_reason: str
    ) -> Optional[Dict[str, Any]]:
        """Send webhook signal"""
        params = {
            "ticker": ticker,
            "action": action,
            "indicator": indicator,
            "enter_reason": enter_reason
        }
        return await self._call_mcp_tool("send_webhook_signal", params)
