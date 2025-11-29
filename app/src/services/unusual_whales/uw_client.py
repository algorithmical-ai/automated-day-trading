"""
Unusual Whales API Client

Provides access to options flow, dark pool data, and market sentiment
for enhanced trading signal validation.

Premium subscription required: https://unusualwhales.com
API Documentation: https://api.unusualwhales.com/docs
"""

import os
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import aiohttp
from app.src.common.loguru_logger import logger


class FlowSentiment(Enum):
    """Options flow sentiment classification"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class UnusualWhalesClient:
    """
    Client for Unusual Whales API
    
    Provides access to:
    - Options flow data (unusual activity, sweeps, blocks)
    - Dark pool transactions
    - Market sentiment (put/call ratios, flow sentiment)
    - Institutional activity signals
    
    Usage:
        client = UnusualWhalesClient()
        flow_data = await client.get_stock_flow("AAPL")
        sentiment = await client.get_flow_sentiment("AAPL")
    """
    
    BASE_URL = "https://api.unusualwhales.com"
    
    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize Unusual Whales client.
        
        Args:
            api_token: API token (or set UW_API_TOKEN env var)
        """
        self._api_token = api_token or os.environ.get("UW_API_TOKEN", "")
        self._timeout = aiohttp.ClientTimeout(total=15)
        self._rate_limit_delay = 0.2  # 200ms between requests
        self._last_request_time = 0.0
        
        if not self._api_token:
            logger.warning(
                "Unusual Whales API token not configured. "
                "Set UW_API_TOKEN environment variable."
            )
    
    @property
    def is_configured(self) -> bool:
        """Check if API token is configured"""
        return bool(self._api_token)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    
    async def _rate_limit(self):
        """Enforce rate limiting between requests"""
        import time
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - time_since_last)
        self._last_request_time = time.time()
    
    async def _make_request(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Make authenticated request to Unusual Whales API.
        
        Args:
            endpoint: API endpoint path (e.g., "/api/stock/AAPL/flow")
            params: Optional query parameters
            
        Returns:
            JSON response data or None on error
        """
        if not self.is_configured:
            logger.debug("Unusual Whales API not configured, skipping request")
            return None
        
        await self._rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(
                    url,
                    headers=self._get_headers(),
                    params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                        logger.error("Unusual Whales API: Unauthorized - check API token")
                    elif response.status == 429:
                        logger.warning("Unusual Whales API: Rate limited")
                        await asyncio.sleep(1.0)
                    elif response.status == 404:
                        logger.debug(f"Unusual Whales API: Endpoint not found: {endpoint}")
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"Unusual Whales API error {response.status}: {error_text[:200]}"
                        )
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"Unusual Whales API timeout: {endpoint}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Unusual Whales API client error: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unusual Whales API unexpected error: {e}")
            return None

    # =========================================================================
    # Options Flow Endpoints
    # =========================================================================
    
    async def get_stock_flow_recent(
        self,
        ticker: str,
        limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Get recent options flow for a specific ticker.
        
        This returns the most recent options trades including:
        - Trade size and premium
        - Put/Call type
        - Strike and expiration
        - Flags (sweep, block, unusual, etc.)
        
        Args:
            ticker: Stock ticker symbol
            limit: Maximum number of trades to return
            
        Returns:
            Dict with 'data' list of flow records
        """
        endpoint = f"/api/stock/{ticker.upper()}/flow"
        params = {"limit": limit}
        return await self._make_request(endpoint, params)
    
    async def get_flow_alerts(
        self,
        ticker: Optional[str] = None,
        limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Get options flow alerts (unusual activity).
        
        Flow alerts are filtered for likely "opener" trades
        with significant size and unusual characteristics.
        
        Args:
            ticker: Optional ticker to filter by
            limit: Maximum alerts to return
            
        Returns:
            Dict with alert data
        """
        endpoint = "/api/option-trades/flow-alerts"
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker.upper()
        return await self._make_request(endpoint, params)
    
    async def get_stock_flow_summary(
        self,
        ticker: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get aggregated flow summary for a ticker.
        
        Includes:
        - Total call vs put volume
        - Net premium (calls - puts)
        - Bullish/bearish flow ratio
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Dict with flow summary data
        """
        endpoint = f"/api/stock/{ticker.upper()}/flow-summary"
        return await self._make_request(endpoint)

    # =========================================================================
    # Dark Pool Endpoints
    # =========================================================================
    
    async def get_darkpool_recent(
        self,
        limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Get recent dark pool transactions across all tickers.
        
        Args:
            limit: Maximum transactions to return
            
        Returns:
            Dict with dark pool data
        """
        endpoint = "/api/darkpool/recent"
        params = {"limit": limit}
        return await self._make_request(endpoint, params)
    
    async def get_darkpool_ticker(
        self,
        ticker: str,
        date_str: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get dark pool data for a specific ticker.
        
        Args:
            ticker: Stock ticker symbol
            date_str: Optional date in YYYY-MM-DD format
            
        Returns:
            Dict with ticker's dark pool activity
        """
        endpoint = f"/api/darkpool/ticker/{ticker.upper()}"
        params = {}
        if date_str:
            params["date"] = date_str
        return await self._make_request(endpoint, params)
    
    async def get_volume_by_price_level(
        self,
        ticker: str,
        date_str: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get volume breakdown by price level (lit vs dark).
        
        Useful for identifying institutional support/resistance levels.
        
        Args:
            ticker: Stock ticker symbol
            date_str: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dict with volume by price level data
        """
        if date_str is None:
            date_str = date.today().isoformat()
        
        endpoint = f"/api/stock/{ticker.upper()}/volume-by-price"
        params = {"date": date_str}
        return await self._make_request(endpoint, params)

    # =========================================================================
    # Market Sentiment Endpoints
    # =========================================================================
    
    async def get_market_tide(self) -> Optional[Dict[str, Any]]:
        """
        Get overall market sentiment (market tide).
        
        Returns aggregate put/call ratios and flow sentiment
        for the overall market.
        
        Returns:
            Dict with market tide data
        """
        endpoint = "/api/market/tide"
        return await self._make_request(endpoint)
    
    async def get_sector_flow(
        self,
        sector: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get options flow aggregated by sector.
        
        Args:
            sector: Optional sector name to filter
            
        Returns:
            Dict with sector flow data
        """
        endpoint = "/api/market/sector-flow"
        params = {}
        if sector:
            params["sector"] = sector
        return await self._make_request(endpoint, params)

    # =========================================================================
    # Stock Information Endpoints
    # =========================================================================
    
    async def get_stock_info(
        self,
        ticker: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get general stock information.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Dict with stock info
        """
        endpoint = f"/api/stock/{ticker.upper()}"
        return await self._make_request(endpoint)
    
    async def get_stock_quote(
        self,
        ticker: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get current stock quote.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Dict with quote data
        """
        endpoint = f"/api/stock/{ticker.upper()}/quote"
        return await self._make_request(endpoint)

    # =========================================================================
    # Screener Endpoints
    # =========================================================================
    
    async def get_screener_stocks(
        self,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get stock screener results.
        
        Args:
            params: Screener filter parameters
            
        Returns:
            Dict with screener results
        """
        endpoint = "/api/screener/stocks"
        return await self._make_request(endpoint, params)
    
    async def get_hottest_chains(
        self,
        limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """
        Get the hottest options chains (highest activity).
        
        Args:
            limit: Number of chains to return
            
        Returns:
            Dict with hottest chains data
        """
        endpoint = "/api/screener/option-contracts"
        params = {"limit": limit}
        return await self._make_request(endpoint, params)

    # =========================================================================
    # Institutional Activity Endpoints
    # =========================================================================
    
    async def get_congress_trades(
        self,
        ticker: Optional[str] = None,
        limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Get recent congressional trading activity.
        
        Args:
            ticker: Optional ticker to filter
            limit: Maximum trades to return
            
        Returns:
            Dict with congressional trades
        """
        endpoint = "/api/congress/recent"
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker.upper()
        return await self._make_request(endpoint, params)

    # =========================================================================
    # High-Level Analysis Methods
    # =========================================================================
    
    async def analyze_flow_sentiment(
        self,
        ticker: str
    ) -> Tuple[FlowSentiment, Dict[str, Any]]:
        """
        Analyze options flow to determine sentiment.
        
        Combines flow data to determine if smart money
        is bullish, bearish, or neutral on a ticker.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Tuple of (sentiment enum, details dict)
        """
        details = {
            "ticker": ticker,
            "call_volume": 0,
            "put_volume": 0,
            "call_premium": 0.0,
            "put_premium": 0.0,
            "bullish_flow_count": 0,
            "bearish_flow_count": 0,
            "sweep_count": 0,
            "block_count": 0,
            "unusual_count": 0,
            "net_premium": 0.0,
            "put_call_ratio": 0.0,
            "sentiment_score": 0.0,
            "confidence": "low",
        }
        
        if not self.is_configured:
            return FlowSentiment.NEUTRAL, details
        
        # Get recent flow
        flow_data = await self.get_stock_flow_recent(ticker, limit=100)
        
        if not flow_data or "data" not in flow_data:
            return FlowSentiment.NEUTRAL, details
        
        trades = flow_data.get("data", [])
        if not trades:
            return FlowSentiment.NEUTRAL, details
        
        for trade in trades:
            try:
                option_type = trade.get("option_type", "").upper()
                premium = float(trade.get("premium", 0) or 0)
                volume = int(trade.get("volume", 0) or 0)
                side = trade.get("side", "").upper()
                flags = trade.get("flags", []) or []
                
                if isinstance(flags, str):
                    flags = [flags]
                
                # Track volume and premium by type
                if option_type == "CALL":
                    details["call_volume"] += volume
                    details["call_premium"] += premium
                elif option_type == "PUT":
                    details["put_volume"] += volume
                    details["put_premium"] += premium
                
                # Track trade characteristics
                if "SWEEP" in flags:
                    details["sweep_count"] += 1
                if "BLOCK" in flags:
                    details["block_count"] += 1
                if "UNUSUAL" in flags:
                    details["unusual_count"] += 1
                
                # Determine if bullish or bearish
                # Buying calls or selling puts = bullish
                # Buying puts or selling calls = bearish
                if option_type == "CALL":
                    if side in ["BUY", "ASK", "ABOVE_ASK"]:
                        details["bullish_flow_count"] += 1
                    elif side in ["SELL", "BID", "BELOW_BID"]:
                        details["bearish_flow_count"] += 1
                elif option_type == "PUT":
                    if side in ["BUY", "ASK", "ABOVE_ASK"]:
                        details["bearish_flow_count"] += 1
                    elif side in ["SELL", "BID", "BELOW_BID"]:
                        details["bullish_flow_count"] += 1
                        
            except (ValueError, TypeError, KeyError) as e:
                logger.debug(f"Error parsing flow trade: {e}")
                continue
        
        # Calculate metrics
        total_volume = details["call_volume"] + details["put_volume"]
        if details["put_volume"] > 0:
            details["put_call_ratio"] = details["call_volume"] / details["put_volume"]
        
        details["net_premium"] = details["call_premium"] - details["put_premium"]
        
        # Calculate sentiment score (-1 to 1)
        total_flow = details["bullish_flow_count"] + details["bearish_flow_count"]
        if total_flow > 0:
            flow_ratio = (
                (details["bullish_flow_count"] - details["bearish_flow_count"]) 
                / total_flow
            )
        else:
            flow_ratio = 0
        
        # Premium-weighted sentiment
        total_premium = details["call_premium"] + details["put_premium"]
        if total_premium > 0:
            premium_ratio = (
                (details["call_premium"] - details["put_premium"]) 
                / total_premium
            )
        else:
            premium_ratio = 0
        
        # Combine flow ratio (60%) and premium ratio (40%)
        details["sentiment_score"] = (flow_ratio * 0.6) + (premium_ratio * 0.4)
        
        # Determine confidence based on volume and trade count
        if total_volume > 10000 and total_flow > 20:
            details["confidence"] = "high"
        elif total_volume > 5000 and total_flow > 10:
            details["confidence"] = "medium"
        else:
            details["confidence"] = "low"
        
        # Determine sentiment
        score = details["sentiment_score"]
        if score > 0.3:
            sentiment = FlowSentiment.BULLISH
        elif score < -0.3:
            sentiment = FlowSentiment.BEARISH
        elif abs(score) < 0.1:
            sentiment = FlowSentiment.NEUTRAL
        else:
            sentiment = FlowSentiment.MIXED
        
        return sentiment, details
    
    async def get_institutional_bias(
        self,
        ticker: str
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Determine institutional bias from dark pool activity.
        
        Analyzes dark pool transactions to determine if
        institutions are accumulating or distributing.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Tuple of (bias: "accumulating"/"distributing"/"neutral", details)
        """
        details = {
            "ticker": ticker,
            "dark_pool_volume": 0,
            "lit_volume": 0,
            "dark_pool_percent": 0.0,
            "buy_side_estimate": 0.0,
            "large_blocks_count": 0,
            "avg_block_size": 0.0,
        }
        
        if not self.is_configured:
            return "neutral", details
        
        dp_data = await self.get_darkpool_ticker(ticker)
        
        if not dp_data or "data" not in dp_data:
            return "neutral", details
        
        transactions = dp_data.get("data", [])
        if not transactions:
            return "neutral", details
        
        total_volume = 0
        total_dark = 0
        block_sizes = []
        
        for tx in transactions:
            try:
                volume = int(tx.get("volume", 0) or 0)
                is_dark = tx.get("is_darkpool", False)
                
                total_volume += volume
                if is_dark:
                    total_dark += volume
                    if volume > 10000:  # Large block threshold
                        details["large_blocks_count"] += 1
                        block_sizes.append(volume)
                        
            except (ValueError, TypeError):
                continue
        
        details["dark_pool_volume"] = total_dark
        details["lit_volume"] = total_volume - total_dark
        
        if total_volume > 0:
            details["dark_pool_percent"] = (total_dark / total_volume) * 100
        
        if block_sizes:
            details["avg_block_size"] = sum(block_sizes) / len(block_sizes)
        
        # Determine bias
        # High dark pool % with large blocks suggests institutional activity
        if details["dark_pool_percent"] > 40 and details["large_blocks_count"] > 5:
            # Check if premium flow is bullish or bearish
            flow_sentiment, flow_details = await self.analyze_flow_sentiment(ticker)
            if flow_sentiment == FlowSentiment.BULLISH:
                return "accumulating", details
            elif flow_sentiment == FlowSentiment.BEARISH:
                return "distributing", details
        
        return "neutral", details
    
    async def should_trade_ticker(
        self,
        ticker: str,
        intended_direction: str  # "long" or "short"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Determine if a trade should be taken based on Unusual Whales data.
        
        Combines options flow sentiment and dark pool analysis to
        validate if the intended trade direction aligns with
        institutional activity.
        
        Args:
            ticker: Stock ticker symbol
            intended_direction: "long" or "short"
            
        Returns:
            Tuple of (should_trade, reason, details)
        """
        if not self.is_configured:
            return True, "UW not configured - proceeding without flow validation", {}
        
        try:
            # Get flow sentiment
            sentiment, flow_details = await self.analyze_flow_sentiment(ticker)
            
            details = {
                "flow_sentiment": sentiment.value,
                "flow_details": flow_details,
                "intended_direction": intended_direction,
            }
            
            # Check alignment
            if intended_direction == "long":
                if sentiment == FlowSentiment.BEARISH:
                    if flow_details.get("confidence") == "high":
                        return False, (
                            f"Strong bearish flow detected: "
                            f"sentiment_score={flow_details['sentiment_score']:.2f}, "
                            f"put/call={flow_details['put_call_ratio']:.2f}"
                        ), details
                    else:
                        return True, (
                            f"Weak bearish flow (low confidence), proceeding with caution"
                        ), details
                elif sentiment == FlowSentiment.BULLISH:
                    return True, (
                        f"Bullish flow confirms long direction: "
                        f"sentiment_score={flow_details['sentiment_score']:.2f}"
                    ), details
                else:
                    return True, "Neutral/mixed flow - no strong signal", details
                    
            elif intended_direction == "short":
                if sentiment == FlowSentiment.BULLISH:
                    if flow_details.get("confidence") == "high":
                        return False, (
                            f"Strong bullish flow detected: "
                            f"sentiment_score={flow_details['sentiment_score']:.2f}, "
                            f"put/call={flow_details['put_call_ratio']:.2f}"
                        ), details
                    else:
                        return True, (
                            f"Weak bullish flow (low confidence), proceeding with caution"
                        ), details
                elif sentiment == FlowSentiment.BEARISH:
                    return True, (
                        f"Bearish flow confirms short direction: "
                        f"sentiment_score={flow_details['sentiment_score']:.2f}"
                    ), details
                else:
                    return True, "Neutral/mixed flow - no strong signal", details
            
            return True, "Unknown direction", details
            
        except Exception as e:
            logger.warning(f"Error checking UW trade validation for {ticker}: {e}")
            return True, f"UW validation error: {e}", {}
    
    async def get_penny_stock_risk_score(
        self,
        ticker: str,
        current_price: float
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate a risk score for penny stocks based on flow data.
        
        Higher score = higher risk of adverse price movement.
        
        Args:
            ticker: Stock ticker symbol
            current_price: Current stock price
            
        Returns:
            Tuple of (risk_score 0-100, details)
        """
        risk_score = 50.0  # Default medium risk
        details = {
            "ticker": ticker,
            "price": current_price,
            "risk_factors": [],
            "flow_available": False,
        }
        
        if not self.is_configured:
            details["risk_factors"].append("UW not configured")
            return risk_score, details
        
        if current_price >= 5.0:
            # Not a penny stock
            details["risk_factors"].append("Not a penny stock")
            return 30.0, details
        
        try:
            sentiment, flow_details = await self.analyze_flow_sentiment(ticker)
            details["flow_available"] = True
            details["flow_details"] = flow_details
            
            # Risk factors for penny stocks
            
            # 1. Low volume/activity = higher risk (less institutional interest)
            total_volume = flow_details.get("call_volume", 0) + flow_details.get("put_volume", 0)
            if total_volume < 1000:
                risk_score += 20
                details["risk_factors"].append(f"Low options volume: {total_volume}")
            elif total_volume < 5000:
                risk_score += 10
                details["risk_factors"].append(f"Moderate options volume: {total_volume}")
            else:
                risk_score -= 10
                details["risk_factors"].append(f"Good options volume: {total_volume}")
            
            # 2. High put/call ratio = bearish sentiment = higher risk for longs
            pcr = flow_details.get("put_call_ratio", 1.0)
            if pcr < 0.5:  # Very bullish
                risk_score -= 15
                details["risk_factors"].append(f"Bullish P/C ratio: {pcr:.2f}")
            elif pcr > 2.0:  # Very bearish
                risk_score += 20
                details["risk_factors"].append(f"Bearish P/C ratio: {pcr:.2f}")
            
            # 3. No sweeps or unusual activity = less institutional interest
            if flow_details.get("sweep_count", 0) == 0 and flow_details.get("unusual_count", 0) == 0:
                risk_score += 15
                details["risk_factors"].append("No sweep/unusual activity")
            elif flow_details.get("sweep_count", 0) > 5:
                risk_score -= 10
                details["risk_factors"].append(f"Active sweeps: {flow_details['sweep_count']}")
            
            # 4. Mixed sentiment = uncertain direction = higher risk
            if sentiment == FlowSentiment.MIXED:
                risk_score += 10
                details["risk_factors"].append("Mixed flow sentiment")
            
            # Clamp to 0-100
            risk_score = max(0, min(100, risk_score))
            
        except Exception as e:
            logger.warning(f"Error calculating penny stock risk for {ticker}: {e}")
            details["risk_factors"].append(f"Error: {e}")
        
        return risk_score, details


# Singleton instance for convenience
_client_instance: Optional[UnusualWhalesClient] = None


class UWFlowCache:
    """Cache UW flow data to reduce API calls"""
    
    _cache: Dict[str, Tuple[datetime, Dict]] = {}
    _cache_ttl_seconds = 60  # 1 minute cache
    
    @classmethod
    async def get_flow_sentiment(cls, ticker: str) -> Tuple[FlowSentiment, Dict]:
        """Get flow sentiment with caching"""
        now = datetime.now(timezone.utc)
        
        if ticker in cls._cache:
            cached_time, cached_data = cls._cache[ticker]
            if (now - cached_time).total_seconds() < cls._cache_ttl_seconds:
                return cached_data["sentiment"], cached_data["details"]
        
        # Cache miss - fetch fresh
        client = get_unusual_whales_client()
        sentiment, details = await client.analyze_flow_sentiment(ticker)
        
        cls._cache[ticker] = (now, {"sentiment": sentiment, "details": details})
        return sentiment, details


def get_unusual_whales_client() -> UnusualWhalesClient:
    """Get or create the singleton Unusual Whales client"""
    global _client_instance
    if _client_instance is None:
        _client_instance = UnusualWhalesClient()
    return _client_instance

