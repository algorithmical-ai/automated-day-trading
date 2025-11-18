"""
Momentum Trading Service with entry and exit logic based on price momentum
"""
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from loguru_logger import logger
from mcp_client import MCPClient
from dynamodb_client import DynamoDBClient
from tool_discovery import ToolDiscoveryService


class MomentumTradingService:
    """Momentum-based trading service with entry and exit logic"""
    
    def __init__(self, tool_discovery: Optional[ToolDiscoveryService] = None):
        self.tool_discovery = tool_discovery
        self.mcp_client = MCPClient(tool_discovery=tool_discovery)
        self.db_client = DynamoDBClient()
        self.running = True
        # Threshold for profitability (percentage)
        self.profit_threshold = 0.5  # 0.5% profit threshold
    
    def stop(self):
        """Stop the trading service"""
        self.running = False
    
    def _calculate_momentum(self, datetime_price: List[List]) -> Tuple[bool, bool, str]:
        """
        Calculate price momentum from datetime_price array
        Returns: (has_upward_momentum, has_downward_momentum, reason)
        """
        if not datetime_price or len(datetime_price) < 3:
            return False, False, "Insufficient price data"
        
        # Extract prices (datetime_price is list of [datetime, price])
        prices = [float(entry[1]) for entry in datetime_price if len(entry) >= 2]
        
        if len(prices) < 3:
            return False, False, "Insufficient price data"
        
        # Look at recent prices vs earlier prices
        # Use first 30% and last 30% of data points for comparison
        n = len(prices)
        early_count = max(1, n // 3)
        recent_count = max(1, n // 3)
        
        early_prices = prices[:early_count]
        recent_prices = prices[-recent_count:]
        
        early_avg = sum(early_prices) / len(early_prices)
        recent_avg = sum(recent_prices) / len(recent_prices)
        
        # Calculate percentage change
        change_percent = ((recent_avg - early_avg) / early_avg) * 100
        
        # Also check if recent trend is consistent
        recent_trend = sum(
            (recent_prices[i] - recent_prices[i-1]) 
            for i in range(1, len(recent_prices))
        ) / max(1, len(recent_prices) - 1)
        
        upward_momentum = change_percent > 0.1 and recent_trend > 0  # At least 0.1% up with positive recent trend
        downward_momentum = change_percent < -0.1 and recent_trend < 0  # At least 0.1% down with negative recent trend
        
        reason = f"Momentum: {change_percent:.2f}% change (early_avg: {early_avg:.2f}, recent_avg: {recent_avg:.2f})"
        
        return upward_momentum, downward_momentum, reason
    
    def _is_profitable(self, enter_price: float, current_price: float, action: str) -> bool:
        """
        Check if trade is profitable based on enter price, current price, and action
        For buy_to_open (long): profitable if current_price > enter_price
        For sell_to_open (short): profitable if current_price < enter_price
        """
        if action == "buy_to_open":
            # Long trade: profitable if current price is higher
            profit_percent = ((current_price - enter_price) / enter_price) * 100
            return profit_percent >= self.profit_threshold
        elif action == "sell_to_open":
            # Short trade: profitable if current price is lower
            profit_percent = ((enter_price - current_price) / enter_price) * 100
            return profit_percent >= self.profit_threshold
        return False
    
    async def entry_service(self):
        """Entry service that runs every 10 seconds - analyzes momentum and enters trades"""
        logger.info("Momentum entry service started")
        while self.running:
            try:
                # Step 1a: Get market clock
                clock_response = await self.mcp_client.get_market_clock()
                if not clock_response:
                    logger.warning("Failed to get market clock, skipping this cycle")
                    await asyncio.sleep(10)
                    continue
                
                clock = clock_response.get("clock", {})
                is_open = clock.get("is_open", False)
                
                # Step 1b: Check if market is open
                if not is_open:
                    logger.info("Market is closed, skipping momentum entry logic")
                    await asyncio.sleep(10)
                    continue
                
                logger.info("Market is open, proceeding with momentum entry logic")
                
                # Step 1c: Get screened tickers
                tickers_response = await self.mcp_client.get_alpaca_screened_tickers()
                if not tickers_response:
                    logger.warning("Failed to get screened tickers, skipping this cycle")
                    await asyncio.sleep(10)
                    continue
                
                gainers = tickers_response.get("gainers", [])
                losers = tickers_response.get("losers", [])
                most_actives = tickers_response.get("most_actives", [])
                
                # Combine all tickers to analyze
                all_tickers = list(set(gainers + losers + most_actives))
                
                # Step 1c.1: Get blacklisted tickers and filter them out
                blacklisted_tickers = await self.db_client.get_blacklisted_tickers()
                blacklisted_set = set(blacklisted_tickers)
                
                # Filter out blacklisted tickers
                filtered_tickers = [ticker for ticker in all_tickers if ticker not in blacklisted_set]
                
                if blacklisted_set:
                    logger.info(
                        f"Filtered out {len(all_tickers) - len(filtered_tickers)} blacklisted tickers. "
                        f"Analyzing {len(filtered_tickers)} tickers for momentum"
                    )
                else:
                    logger.info(f"Analyzing {len(filtered_tickers)} tickers for momentum")
                
                for ticker in filtered_tickers:
                    if not self.running:
                        break
                    
                    # Double-check ticker is not blacklisted before processing
                    if await self.db_client.is_ticker_blacklisted(ticker):
                        logger.debug(f"Ticker {ticker} is blacklisted, skipping")
                        continue
                    
                    # Check if ticker already has an active trade
                    active_trades = await self.db_client.get_all_momentum_trades()
                    if any(trade.get("ticker") == ticker for trade in active_trades):
                        logger.debug(f"Ticker {ticker} already has an active momentum trade, skipping")
                        continue
                    
                    # Step 1d: Get market data for ticker
                    market_data_response = await self.mcp_client.get_market_data(ticker)
                    if not market_data_response:
                        logger.warning(f"Failed to get market data for {ticker}")
                        continue
                    
                    technical_analysis = market_data_response.get("technical_analysis", {})
                    datetime_price = technical_analysis.get("datetime_price", [])
                    
                    if not datetime_price:
                        logger.debug(f"No datetime_price data for {ticker}")
                        continue
                    
                    # Step 1e: Calculate momentum
                    upward_momentum, downward_momentum, reason = self._calculate_momentum(datetime_price)
                    
                    # Determine action and enter price based on momentum
                    action = None
                    enter_price = 0.0
                    
                    if upward_momentum:
                        # Upward momentum -> long trade (buy_to_open)
                        action = "buy_to_open"
                        # Get quote for ask price (buy price)
                        quote_response = await self.mcp_client.get_quote(ticker)
                        if quote_response:
                            quote_data = quote_response.get("quote", {})
                            quotes = quote_data.get("quotes", {})
                            ticker_quote = quotes.get(ticker, {})
                            enter_price = ticker_quote.get("ap", 0.0)  # Ask price for buy
                        
                        if enter_price <= 0:
                            logger.warning(f"Failed to get valid quote price for {ticker}, skipping")
                            continue
                        
                    elif downward_momentum:
                        # Downward momentum -> short trade (sell_to_open)
                        action = "sell_to_open"
                        # Get quote for bid price (sell price)
                        quote_response = await self.mcp_client.get_quote(ticker)
                        if quote_response:
                            quote_data = quote_response.get("quote", {})
                            quotes = quote_data.get("quotes", {})
                            ticker_quote = quotes.get(ticker, {})
                            enter_price = ticker_quote.get("bp", 0.0)  # Bid price for sell
                        
                        if enter_price <= 0:
                            logger.warning(f"Failed to get valid quote price for {ticker}, skipping")
                            continue
                    else:
                        # No clear momentum, skip
                        logger.debug(f"No clear momentum for {ticker}: {reason}")
                        continue
                    
                    # Step 1f: Send webhook signal
                    indicator = "Momentum Trading"
                    webhook_response = await self.mcp_client.send_webhook_signal(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_reason=reason
                    )
                    
                    if webhook_response:
                        logger.info(f"Webhook signal sent for {ticker} - {action} (momentum: {reason})")
                    else:
                        logger.warning(f"Failed to send webhook signal for {ticker}")
                    
                    # Step 1g: Add to DynamoDB (ActiveTickersForAutomatedDayTrader table)
                    await self.db_client.add_momentum_trade(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_price=enter_price,
                        enter_reason=reason
                    )
                    
                    logger.info(f"Entered momentum trade for {ticker} - {action} at {enter_price}")
                
                # Wait 10 seconds before next cycle
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.exception(f"Error in momentum entry service: {str(e)}")
                await asyncio.sleep(10)
    
    async def exit_service(self):
        """Exit service that runs every 5 seconds - checks profitability and exits trades"""
        logger.info("Momentum exit service started")
        while self.running:
            try:
                # Step 2a: Check if market is open - don't do momentum trading when market is closed
                clock_response = await self.mcp_client.get_market_clock()
                if not clock_response:
                    logger.warning("Failed to get market clock, skipping momentum exit check")
                    await asyncio.sleep(5)
                    continue
                
                clock = clock_response.get("clock", {})
                is_open = clock.get("is_open", False)
                
                if not is_open:
                    logger.info("Market is closed, skipping momentum exit logic")
                    await asyncio.sleep(5)
                    continue
                
                # Step 2: Get all active momentum trades from DynamoDB
                active_trades = await self.db_client.get_all_momentum_trades()
                
                if not active_trades:
                    logger.debug("No active momentum trades to monitor")
                    await asyncio.sleep(5)
                    continue
                
                logger.info(f"Monitoring {len(active_trades)} active momentum trades")
                
                for trade in active_trades:
                    if not self.running:
                        break
                    
                    ticker = trade.get("ticker")
                    original_action = trade.get("action")
                    enter_price = trade.get("enter_price")
                    indicator = trade.get("indicator", "Momentum Trading")
                    
                    if not ticker or enter_price is None or enter_price <= 0:
                        logger.warning(f"Invalid momentum trade data: {trade}")
                        continue
                    
                    # Determine exit action based on original action
                    if original_action == "buy_to_open":
                        exit_action = "sell_to_close"
                    elif original_action == "sell_to_open":
                        exit_action = "buy_to_close"
                    else:
                        logger.warning(f"Unknown action: {original_action} for {ticker}")
                        continue
                    
                    # Step 2.1: Get current market data to check profitability
                    market_data_response = await self.mcp_client.get_market_data(ticker)
                    if not market_data_response:
                        logger.warning(f"Failed to get market data for {ticker} for exit check")
                        continue
                    
                    technical_analysis = market_data_response.get("technical_analysis", {})
                    current_price = technical_analysis.get("close_price", 0.0)
                    
                    if current_price <= 0:
                        logger.warning(f"Failed to get valid current price for {ticker}")
                        continue
                    
                    # Step 2.2: Check if trade is profitable
                    is_profitable = self._is_profitable(enter_price, current_price, original_action)
                    
                    if is_profitable:
                        logger.info(
                            f"Profitable exit signal for {ticker} - {exit_action} "
                            f"(enter: {enter_price}, current: {current_price})"
                        )
                        
                        # Calculate profit for reason
                        if original_action == "buy_to_open":
                            profit_percent = ((current_price - enter_price) / enter_price) * 100
                        else:
                            profit_percent = ((enter_price - current_price) / enter_price) * 100
                        
                        reason = f"Profit target reached: {profit_percent:.2f}% profit"
                        
                        # Step 2.3: Send webhook signal
                        webhook_response = await self.mcp_client.send_webhook_signal(
                            ticker=ticker,
                            action=exit_action,
                            indicator=indicator,
                            enter_reason=reason
                        )
                        
                        if webhook_response:
                            logger.info(f"Webhook signal sent for {ticker} - {exit_action}")
                        else:
                            logger.warning(f"Failed to send webhook signal for {ticker}")
                        
                        # Step 2.4: Delete from DynamoDB
                        await self.db_client.delete_momentum_trade(ticker)
                        logger.info(f"Exited momentum trade for {ticker}")
                    else:
                        # Not profitable yet, continue monitoring
                        if original_action == "buy_to_open":
                            profit_percent = ((current_price - enter_price) / enter_price) * 100
                        else:
                            profit_percent = ((enter_price - current_price) / enter_price) * 100
                        logger.debug(
                            f"{ticker} not yet profitable: {profit_percent:.2f}% "
                            f"(threshold: {self.profit_threshold}%)"
                        )
                
                # Wait 5 seconds before next cycle
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.exception(f"Error in momentum exit service: {str(e)}")
                await asyncio.sleep(5)
    
    async def run(self):
        """Run both entry and exit services concurrently"""
        logger.info("Starting momentum trading service...")
        
        # Run both services concurrently
        await asyncio.gather(
            self.entry_service(),
            self.exit_service()
        )

