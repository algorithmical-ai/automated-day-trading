"""
Trading Service with entry and exit logic
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, date
from app.src.common.loguru_logger import logger
from app.src.services.mcp.mcp_client import MCPClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.tool_discovery.tool_discovery import ToolDiscoveryService
from app.src.config.constants import (
    MCP_SERVER_TRANSPORT,
    MCP_TOOL_DISCOVERY_INTERVAL_SECONDS,
)
from app.src.services.mab.mab_service import MABService
from app.src.services.mcp.server import market_client

class TradingService:
    """Main trading service with entry and exit logic"""

    running: bool = True
    mab_reset_date: Optional[str] = None
    INDICATOR_AUTOMATED_TRADING = "Automated Trading"
    INDICATOR_AUTOMATED_WORKFLOW = "Automated workflow"
    tool_discovery_cls: Optional[type] = ToolDiscoveryService

    @classmethod
    def configure(cls, tool_discovery_cls: Optional[type] = ToolDiscoveryService):
        """Configure dependencies for class-based usage"""
        if tool_discovery_cls is not None:
            cls.tool_discovery_cls = tool_discovery_cls
        MCPClient.configure(tool_discovery_cls=tool_discovery_cls)
        DynamoDBClient.configure()
        MABService.configure()
        cls.running = True
        cls.mab_reset_date = None
    
    @classmethod
    def stop(cls):
        """Stop the trading service"""
        cls.running = False

    @classmethod
    async def entry_service(cls):
        """Entry service that runs every 10 seconds"""
        logger.info("Entry service started")
        while cls.running:
            try:
                # Step 1a: Get market clock
                clock_response = await MCPClient.get_market_clock()
                if not clock_response:
                    logger.warning("Failed to get market clock, skipping this cycle")
                    await asyncio.sleep(10)
                    continue

                clock = clock_response.get("clock", {})
                is_open = clock.get("is_open", False)

                # Step 1b: Check if market is open
                if not is_open:
                    logger.info("Market is closed, skipping entry logic")
                    await asyncio.sleep(10)
                    continue

                logger.info("Market is open, proceeding with entry logic")

                # Step 1b.1: Reset MAB daily stats if needed (at market open)
                today = date.today().isoformat()
                if cls.mab_reset_date != today:
                    logger.info("Resetting daily MAB statistics for new trading day")
                    await MABService.reset_daily_stats(cls.INDICATOR_AUTOMATED_TRADING)
                    await MABService.reset_daily_stats(cls.INDICATOR_AUTOMATED_WORKFLOW)
                    cls.mab_reset_date = today

                # Step 1c: Get screened tickers
                tickers_response = await MCPClient.get_alpaca_screened_tickers()
                if not tickers_response:
                    logger.warning(
                        "Failed to get screened tickers, skipping this cycle"
                    )
                    await asyncio.sleep(10)
                    continue

                gainers = tickers_response.get("gainers", [])
                losers = tickers_response.get("losers", [])
                most_actives = tickers_response.get("most_actives", [])

                # Step 1d: Get blacklisted tickers and filter them out
                blacklisted_tickers = await DynamoDBClient.get_blacklisted_tickers()
                blacklisted_set = set(blacklisted_tickers)

                # Step 1e: Process gainers and most_actives with buy_to_open
                buy_tickers = list(set(gainers + most_actives))

                # Filter out blacklisted tickers
                buy_tickers = [
                    ticker for ticker in buy_tickers if ticker not in blacklisted_set
                ]

                if blacklisted_set:
                    logger.info(
                        f"Processing {len(buy_tickers)} buy candidates "
                        f"(filtered out {len(list(set(gainers + most_actives))) - len(buy_tickers)} blacklisted tickers)"
                    )
                else:
                    logger.info(f"Processing {len(buy_tickers)} buy candidates")

                for ticker in buy_tickers:
                    if not cls.running:
                        break

                    # Double-check ticker is not blacklisted before processing
                    if await DynamoDBClient.is_ticker_blacklisted(ticker):
                        logger.debug(f"Ticker {ticker} is blacklisted, skipping")
                        continue

                    # Retry logic for enter() calls with exponential backoff for 503 errors
                    # Note: enter() API typically takes 5-10 seconds, so retries use longer delays
                    enter_response = None
                    max_retries = 2  # Reduced to 2 since API is slow (5-10s per call)
                    for attempt in range(max_retries):
                        enter_response = await MCPClient.enter(ticker, "buy_to_open")
                        if enter_response:
                            break
                        # If we get None (likely 503 error), wait and retry
                        # Use longer delays since API normally takes 5-10 seconds
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt) * 2.0  # 2s, 4s
                            logger.debug(
                                f"Retrying enter() for {ticker} (attempt {attempt + 1}/{max_retries}) "
                                f"after {wait_time}s delay (API typically takes 5-10s)"
                            )
                            await asyncio.sleep(wait_time)
                    
                    if not enter_response:
                        logger.warning(
                            f"Failed to get enter response for {ticker} after {max_retries} attempts "
                            f"(API may be temporarily unavailable)"
                        )
                        continue

                    enter = enter_response.get("enter", False)

                    if enter:
                        logger.info(f"Enter signal for {ticker} - buy_to_open")

                        analysis = enter_response.get("analysis", {})
                        reason = enter_response.get("reason", "")

                        # Get quote to extract enter_price (ask price for buy_to_open)
                        quote_response = await MCPClient.get_quote(ticker)
                        enter_price = 0.0

                        if quote_response:
                            quote_data = quote_response.get("quote", {})
                            quotes = quote_data.get("quotes", {})
                            ticker_quote = quotes.get(ticker, {})
                            # Use ask price (ap) for buy_to_open
                            enter_price = ticker_quote.get("ap", 0.0)

                        if enter_price <= 0:
                            logger.warning(
                                f"Failed to get valid quote price for {ticker}, skipping"
                            )
                            continue

                        # Step 1e.1: Check MAB before entering trade
                        # Get market data for MAB context
                        market_data_response = await MCPClient.get_market_data(ticker)
                        momentum_score = 0.0  # Default momentum for non-momentum trading
                        if market_data_response:
                            technical_analysis = market_data_response.get(
                                "technical_analysis", {}
                            )
                            # Try to extract a simple momentum signal if available
                            datetime_price = technical_analysis.get("datetime_price", [])
                            if datetime_price and len(datetime_price) >= 2:
                                prices = [
                                    float(entry[1])
                                    for entry in datetime_price
                                    if len(entry) >= 2
                                ]
                                if len(prices) >= 2:
                                    # Simple momentum: recent vs earlier price
                                    momentum_score = (
                                        (prices[-1] - prices[0]) / prices[0] * 100
                                        if prices[0] > 0
                                        else 0.0
                                    )

                        should_trade, mab_score, mab_reason = (
                            await MABService.should_trade_ticker(
                                indicator=cls.INDICATOR_AUTOMATED_TRADING,
                                ticker=ticker,
                                momentum_score=momentum_score,
                                market_data=market_data_response,
                            )
                        )

                        if not should_trade:
                            logger.info(
                                f"Skipping {ticker} - MAB filter: {mab_reason} "
                                f"(MAB score: {mab_score:.3f} below threshold)"
                            )
                            continue

                        logger.info(
                            f"MAB approved {ticker} for entry: {mab_reason} "
                            f"(MAB score: {mab_score:.3f})"
                        )

                        # Step 1f: Send webhook signal
                        webhook_response = await MCPClient.send_webhook_signal(
                            ticker=ticker,
                            action="buy_to_open",
                            indicator="Automated Trading",
                            enter_reason=reason,
                        )

                        if webhook_response:
                            logger.info(
                                f"Webhook signal sent for {ticker} - buy_to_open"
                            )
                        else:
                            logger.warning(
                                f"Failed to send webhook signal for {ticker}"
                            )

                        # Step 1g: Add to DynamoDB
                        await DynamoDBClient.add_trade(
                            ticker=ticker,
                            action="buy_to_open",
                            indicator="Automated Trading",
                            enter_price=enter_price,
                            enter_reason=reason,
                            enter_response=enter_response,
                        )

                # Step 1h: Process losers and most_actives with sell_to_open
                sell_tickers = list(set(losers + most_actives))

                # Filter out blacklisted tickers
                sell_tickers = [
                    ticker for ticker in sell_tickers if ticker not in blacklisted_set
                ]

                if blacklisted_set:
                    logger.info(
                        f"Processing {len(sell_tickers)} sell candidates "
                        f"(filtered out {len(list(set(losers + most_actives))) - len(sell_tickers)} blacklisted tickers)"
                    )
                else:
                    logger.info(f"Processing {len(sell_tickers)} sell candidates")

                for ticker in sell_tickers:
                    if not cls.running:
                        break

                    # Double-check ticker is not blacklisted before processing
                    if await DynamoDBClient.is_ticker_blacklisted(ticker):
                        logger.debug(f"Ticker {ticker} is blacklisted, skipping")
                        continue

                    # Retry logic for enter() calls with exponential backoff for 503 errors
                    # Note: enter() API typically takes 5-10 seconds, so retries use longer delays
                    enter_response = None
                    max_retries = 2  # Reduced to 2 since API is slow (5-10s per call)
                    for attempt in range(max_retries):
                        enter_response = await MCPClient.enter(ticker, "sell_to_open")
                        if enter_response:
                            break
                        # If we get None (likely 503 error), wait and retry
                        # Use longer delays since API normally takes 5-10 seconds
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt) * 2.0  # 2s, 4s
                            logger.debug(
                                f"Retrying enter() for {ticker} (attempt {attempt + 1}/{max_retries}) "
                                f"after {wait_time}s delay (API typically takes 5-10s)"
                            )
                            await asyncio.sleep(wait_time)
                    
                    if not enter_response:
                        logger.warning(
                            f"Failed to get enter response for {ticker} after {max_retries} attempts "
                            f"(API may be temporarily unavailable)"
                        )
                        continue

                    enter = enter_response.get("enter", False)

                    if enter:
                        logger.info(f"Enter signal for {ticker} - sell_to_open")

                        analysis = enter_response.get("analysis", {})
                        reason = enter_response.get("reason", "")

                        # Get quote to extract enter_price (bid price for sell_to_open)
                        quote_response = await MCPClient.get_quote(ticker)
                        enter_price = 0.0

                        if quote_response:
                            quote_data = quote_response.get("quote", {})
                            quotes = quote_data.get("quotes", {})
                            ticker_quote = quotes.get(ticker, {})
                            # Use bid price (bp) for sell_to_open (shorting)
                            enter_price = ticker_quote.get("bp", 0.0)

                        if enter_price <= 0:
                            logger.warning(
                                f"Failed to get valid quote price for {ticker}, skipping"
                            )
                            continue

                        # Step 1h.1: Check MAB before entering trade
                        # Get market data for MAB context
                        market_data_response = await MCPClient.get_market_data(ticker)
                        momentum_score = 0.0  # Default momentum for non-momentum trading
                        if market_data_response:
                            technical_analysis = market_data_response.get(
                                "technical_analysis", {}
                            )
                            # Try to extract a simple momentum signal if available
                            datetime_price = technical_analysis.get("datetime_price", [])
                            if datetime_price and len(datetime_price) >= 2:
                                prices = [
                                    float(entry[1])
                                    for entry in datetime_price
                                    if len(entry) >= 2
                                ]
                                if len(prices) >= 2:
                                    # Simple momentum: recent vs earlier price
                                    momentum_score = (
                                        (prices[-1] - prices[0]) / prices[0] * 100
                                        if prices[0] > 0
                                        else 0.0
                                    )

                        should_trade, mab_score, mab_reason = (
                            await MABService.should_trade_ticker(
                                indicator=cls.INDICATOR_AUTOMATED_WORKFLOW,
                                ticker=ticker,
                                momentum_score=momentum_score,
                                market_data=market_data_response,
                            )
                        )

                        if not should_trade:
                            logger.info(
                                f"Skipping {ticker} - MAB filter: {mab_reason} "
                                f"(MAB score: {mab_score:.3f} below threshold)"
                            )
                            continue

                        logger.info(
                            f"MAB approved {ticker} for entry: {mab_reason} "
                            f"(MAB score: {mab_score:.3f})"
                        )

                        # Step 1i: Send webhook signal
                        webhook_response = await MCPClient.send_webhook_signal(
                            ticker=ticker,
                            action="sell_to_open",
                            indicator="Automated workflow",
                            enter_reason=reason,
                        )

                        if webhook_response:
                            logger.info(
                                f"Webhook signal sent for {ticker} - sell_to_open"
                            )
                        else:
                            logger.warning(
                                f"Failed to send webhook signal for {ticker}"
                            )

                        # Step 1j: Add to DynamoDB
                        await DynamoDBClient.add_trade(
                            ticker=ticker,
                            action="sell_to_open",
                            indicator="Automated workflow",
                            enter_price=enter_price,
                            enter_reason=reason,
                            enter_response=enter_response,
                        )

                # Wait 10 seconds before next cycle
                await asyncio.sleep(10)

            except Exception as e:
                logger.exception(f"Error in entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    async def exit_service(cls):
        """Exit service that runs every 5 seconds"""
        logger.info("Exit service started")
        while cls.running:
            try:
                # Step 2: Get all active trades from DynamoDB
                active_trades = await DynamoDBClient.get_all_active_trades()

                if not active_trades:
                    logger.debug("No active trades to monitor")
                    await asyncio.sleep(5)
                    continue

                logger.info(f"Monitoring {len(active_trades)} active trades")

                for trade in active_trades:
                    if not cls.running:
                        break

                    ticker = trade.get("ticker")
                    original_action = trade.get("action")
                    enter_price = trade.get("enter_price")

                    if not ticker or enter_price is None or enter_price <= 0:
                        logger.warning(f"Invalid trade data: {trade}")
                        continue

                    # Skip blacklisted tickers - don't call exit() for them
                    if await DynamoDBClient.is_ticker_blacklisted(ticker):
                        logger.debug(
                            f"Ticker {ticker} is blacklisted, skipping exit check"
                        )
                        continue

                    # Determine exit action based on original action
                    if original_action == "buy_to_open":
                        exit_action = "sell_to_close"
                    elif original_action == "sell_to_open":
                        exit_action = "buy_to_close"
                    else:
                        logger.warning(
                            f"Unknown action: {original_action} for {ticker}"
                        )
                        continue

                    # Step 2.1: Call exit() MCP tool with retry logic
                    # Note: exit() API typically takes 5-10 seconds, so retries use longer delays
                    exit_response = None
                    max_retries = 2  # Reduced to 2 since API is slow (5-10s per call)
                    for attempt in range(max_retries):
                        exit_response = await MCPClient.exit(
                            ticker=ticker, enter_price=enter_price, action=exit_action
                        )
                        if exit_response:
                            break
                        # If we get None (likely 503 error), wait and retry
                        # Use longer delays since API normally takes 5-10 seconds
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt) * 2.0  # 2s, 4s
                            logger.debug(
                                f"Retrying exit() for {ticker} (attempt {attempt + 1}/{max_retries}) "
                                f"after {wait_time}s delay (API typically takes 5-10s)"
                            )
                            await asyncio.sleep(wait_time)
                    
                    if not exit_response:
                        logger.warning(
                            f"Failed to get exit response for {ticker} after {max_retries} attempts "
                            f"(API may be temporarily unavailable)"
                        )
                        continue

                    exit_decision = exit_response.get("exit_decision", False)

                    if exit_decision:
                        logger.info(f"Exit signal for {ticker} - {exit_action}")

                        reason = exit_response.get("reason", "")
                        indicator = trade.get("indicator", "Automated Trading")

                        # Step 2.1.1: Get current price for profit/loss calculation
                        # Get market data to extract exit price
                        market_data_response = await MCPClient.get_market_data(ticker)
                        exit_price = enter_price  # Default to enter_price if we can't get current price
                        
                        if market_data_response:
                            technical_analysis = market_data_response.get(
                                "technical_analysis", {}
                            )
                            current_price = technical_analysis.get("close_price", 0.0)
                            if current_price > 0:
                                exit_price = current_price
                            else:
                                # Fallback: try to get quote
                                quote_response = await MCPClient.get_quote(ticker)
                                if quote_response:
                                    quote_data = quote_response.get("quote", {})
                                    quotes = quote_data.get("quotes", {})
                                    ticker_quote = quotes.get(ticker, {})
                                    if exit_action == "sell_to_close":
                                        exit_price = ticker_quote.get("bp", enter_price)  # Bid price for sell
                                    else:
                                        exit_price = ticker_quote.get("ap", enter_price)  # Ask price for buy

                        # Step 2.2: Send webhook signal
                        webhook_response = await MCPClient.send_webhook_signal(
                            ticker=ticker,
                            action=exit_action,
                            indicator=indicator,
                            enter_reason=reason,
                        )

                        if webhook_response:
                            logger.info(
                                f"Webhook signal sent for {ticker} - {exit_action}"
                            )
                        else:
                            logger.warning(
                                f"Failed to send webhook signal for {ticker}"
                            )

                        # Step 2.2.1: Record MAB reward (profit/loss)
                        # Calculate profit percentage
                        if original_action == "buy_to_open":
                            profit_percent = (
                                (exit_price - enter_price) / enter_price * 100
                                if enter_price > 0
                                else 0.0
                            )
                        elif original_action == "sell_to_open":
                            profit_percent = (
                                (enter_price - exit_price) / enter_price * 100
                                if enter_price > 0
                                else 0.0
                            )
                        else:
                            profit_percent = 0.0

                        context = {
                            "profit_percent": profit_percent,
                            "enter_price": enter_price,
                            "exit_price": exit_price,
                            "action": original_action,
                            "indicator": indicator,
                            "timestamp": datetime.utcnow().isoformat(),
                        }

                        indicator_name = (
                            cls.INDICATOR_AUTOMATED_WORKFLOW
                            if indicator == "Automated workflow"
                            else cls.INDICATOR_AUTOMATED_TRADING
                        )

                        await MABService.record_trade_outcome(
                            indicator=indicator_name,
                            ticker=ticker,
                            enter_price=enter_price,
                            exit_price=exit_price,
                            action=original_action,
                            context=context,
                        )

                        logger.info(
                            f"Recorded MAB reward for {ticker}: {profit_percent:.2f}% profit/loss "
                            f"(enter: {enter_price}, exit: {exit_price})"
                        )

                        # Step 2.3: Delete from DynamoDB
                        await DynamoDBClient.delete_trade(ticker)

                # Wait 5 seconds before next cycle
                await asyncio.sleep(5)

            except Exception as e:
                logger.exception(f"Error in exit service: {str(e)}")
                await asyncio.sleep(5)

    @classmethod
    async def run(cls):
        """Run both entry and exit services concurrently"""
        logger.info("Starting trading service...")

        # Run both services concurrently
        await asyncio.gather(cls.entry_service(), cls.exit_service())
