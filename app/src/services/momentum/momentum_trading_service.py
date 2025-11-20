"""
Momentum Trading Service with entry and exit logic based on price momentum
"""

import asyncio
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, date, timezone
from common.loguru_logger import logger
from services.mcp.mcp_client import MCPClient
from db.dynamodb_client import DynamoDBClient
from services.tool_discovery.tool_discovery import ToolDiscoveryService
from mab_service import MABService


class MomentumTradingService:
    """Momentum-based trading service with entry and exit logic"""

    def __init__(
        self, tool_discovery: Optional[ToolDiscoveryService] = None, top_k: int = 10
    ):
        self.tool_discovery = tool_discovery
        self.mcp_client = MCPClient(tool_discovery=tool_discovery)
        self.db_client = DynamoDBClient()
        self.running = True
        # Threshold for profitability (percentage)
        self.profit_threshold = 0.5  # 0.5% profit threshold
        # Number of top tickers to trade (configurable)
        self.top_k = top_k
        # Maximum number of active trades at any time
        self.max_active_trades = 30
        # Exceptional momentum threshold for preemption (higher = more selective)
        self.exceptional_momentum_threshold = 5.0  # 5.0% momentum score
        # Initialize MAB service for contextual bandit-based ticker selection
        self.mab_service = MABService(self.db_client, indicator="Momentum Trading")
        # Track if we've reset MAB stats today
        self.mab_reset_date = None

    def stop(self):
        """Stop the trading service"""
        self.running = False

    def _calculate_momentum(self, datetime_price: List[List]) -> Tuple[float, str]:
        """
        Calculate price momentum score from datetime_price array
        Returns: (momentum_score, reason)
        - Positive score indicates upward momentum
        - Negative score indicates downward momentum
        - Higher absolute value indicates stronger momentum
        """
        if not datetime_price or len(datetime_price) < 3:
            return 0.0, "Insufficient price data"

        # Extract prices (datetime_price is list of [datetime, price])
        prices = [float(entry[1]) for entry in datetime_price if len(entry) >= 2]

        if len(prices) < 3:
            return 0.0, "Insufficient price data"

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
            (recent_prices[i] - recent_prices[i - 1])
            for i in range(1, len(recent_prices))
        ) / max(1, len(recent_prices) - 1)

        # Calculate momentum score: combine change_percent and recent_trend
        # Weight change_percent more heavily (70%) and recent_trend (30%)
        # Normalize recent_trend to percentage by dividing by early_avg
        trend_percent = (recent_trend / early_avg) * 100 if early_avg > 0 else 0
        momentum_score = (0.7 * change_percent) + (0.3 * trend_percent)

        reason = f"Momentum: {change_percent:.2f}% change, {trend_percent:.2f}% trend (early_avg: {early_avg:.2f}, recent_avg: {recent_avg:.2f})"

        return momentum_score, reason

    def _is_profitable(
        self, enter_price: float, current_price: float, action: str
    ) -> bool:
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

    def _calculate_profit_percent(
        self, enter_price: float, current_price: float, action: str
    ) -> float:
        """
        Calculate profit percentage for a trade
        Returns positive for profit, negative for loss
        """
        if action == "buy_to_open":
            # Long trade: profit if current price is higher
            return ((current_price - enter_price) / enter_price) * 100
        elif action == "sell_to_open":
            # Short trade: profit if current price is lower
            return ((enter_price - current_price) / enter_price) * 100
        return 0.0

    async def _find_lowest_profitable_trade(
        self, active_trades: List[Dict[str, Any]]
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Find the lowest profitable trade from active trades
        Returns (trade_dict, profit_percent) or None if no profitable trades
        """
        lowest_profit = None
        lowest_trade = None

        for trade in active_trades:
            ticker = trade.get("ticker")
            enter_price = trade.get("enter_price")
            action = trade.get("action")

            if not ticker or enter_price is None or enter_price <= 0:
                continue

            # Get current price
            market_data_response = await self.mcp_client.get_market_data(ticker)
            if not market_data_response:
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            current_price = technical_analysis.get("close_price", 0.0)

            if current_price <= 0:
                continue

            profit_percent = self._calculate_profit_percent(
                enter_price, current_price, action
            )

            # Only consider profitable trades
            if profit_percent >= self.profit_threshold:
                if lowest_profit is None or profit_percent < lowest_profit:
                    lowest_profit = profit_percent
                    lowest_trade = trade

        if lowest_trade and lowest_profit is not None:
            return (lowest_trade, lowest_profit)
        return None

    async def _preempt_low_profit_trade(
        self, new_ticker: str, new_momentum_score: float
    ) -> bool:
        """
        Preempt (exit) a low profitable trade to make room for a new exceptional trade
        Returns True if preemption was successful, False otherwise
        """
        active_trades = await self.db_client.get_all_momentum_trades()

        if len(active_trades) < self.max_active_trades:
            return False  # No need to preempt

        # Find lowest profitable trade
        result = await self._find_lowest_profitable_trade(active_trades)
        if not result:
            logger.debug("No profitable trades to preempt")
            return False

        lowest_trade, lowest_profit = result
        ticker_to_exit = lowest_trade.get("ticker")

        logger.info(
            f"Preempting {ticker_to_exit} (profit: {lowest_profit:.2f}%) "
            f"to make room for {new_ticker} (momentum: {new_momentum_score:.2f})"
        )

        # Exit the low profit trade
        original_action = lowest_trade.get("action")
        enter_price = lowest_trade.get("enter_price")
        indicator = lowest_trade.get("indicator", "Momentum Trading")

        # Determine exit action
        if original_action == "buy_to_open":
            exit_action = "sell_to_close"
        elif original_action == "sell_to_open":
            exit_action = "buy_to_close"
        else:
            logger.warning(f"Unknown action: {original_action} for {ticker_to_exit}")
            return False

        # Get current price for exit
        market_data_response = await self.mcp_client.get_market_data(ticker_to_exit)
        if not market_data_response:
            logger.warning(
                f"Failed to get market data for {ticker_to_exit} for preemption"
            )
            return False

        technical_analysis = market_data_response.get("technical_analysis", {})
        exit_price = technical_analysis.get("close_price", 0.0)

        if exit_price <= 0:
            logger.warning(f"Invalid exit price for {ticker_to_exit}")
            return False

        # Send webhook signal
        reason = f"Preempted for exceptional trade: {lowest_profit:.2f}% profit"
        webhook_response = await self.mcp_client.send_webhook_signal(
            ticker=ticker_to_exit,
            action=exit_action,
            indicator=indicator,
            enter_reason=reason,
        )

        if webhook_response:
            logger.info(
                f"Webhook signal sent for preempted {ticker_to_exit} - {exit_action}"
            )
        else:
            logger.warning(f"Failed to send webhook signal for {ticker_to_exit}")

        # Record MAB reward
        profit_percent = self._calculate_profit_percent(
            enter_price, exit_price, original_action
        )
        context = {
            "profit_percent": profit_percent,
            "enter_price": enter_price,
            "exit_price": exit_price,
            "action": original_action,
            "indicator": indicator,
            "preempted": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.mab_service.record_trade_outcome(
            ticker=ticker_to_exit,
            enter_price=enter_price,
            exit_price=exit_price,
            action=original_action,
            context=context,
        )

        # Get trade data before deletion for completed trades record
        enter_reason = lowest_trade.get("enter_reason", "")
        enter_timestamp = lowest_trade.get(
            "created_at", datetime.now(timezone.utc).isoformat()
        )
        technical_indicators_for_enter = lowest_trade.get(
            "technical_indicators_for_enter"
        )

        # Calculate profit_or_loss in dollars (assuming 1 share for calculation)
        if original_action == "buy_to_open":
            profit_or_loss = exit_price - enter_price
        elif original_action == "sell_to_open":
            profit_or_loss = enter_price - exit_price
        else:
            profit_or_loss = 0.0

        # Get technical indicators for exit
        technical_indicators_for_exit = technical_analysis.copy()
        # Remove datetime_price if present (not needed for exit indicators)
        if "datetime_price" in technical_indicators_for_exit:
            technical_indicators_for_exit = {
                k: v
                for k, v in technical_indicators_for_exit.items()
                if k != "datetime_price"
            }

        # Get current date for partition key
        current_date = date.today().isoformat()
        exit_timestamp = datetime.now(timezone.utc).isoformat()
        exit_reason = reason

        # Add completed trade to CompletedTradesForAutomatedDayTrading
        await self.db_client.add_completed_trade(
            date=current_date,
            indicator=indicator,
            ticker=ticker_to_exit,
            action=original_action,
            enter_price=enter_price,
            enter_reason=enter_reason,
            enter_timestamp=enter_timestamp,
            exit_price=exit_price,
            exit_timestamp=exit_timestamp,
            exit_reason=exit_reason,
            profit_or_loss=profit_or_loss,
            technical_indicators_for_enter=technical_indicators_for_enter,
            technical_indicators_for_exit=technical_indicators_for_exit,
        )

        # Delete from DynamoDB
        await self.db_client.delete_momentum_trade(ticker_to_exit)
        logger.info(f"Preempted and exited trade for {ticker_to_exit}")
        return True

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

                # Step 1b.1: Reset MAB daily stats if needed (at market open)
                today = date.today().isoformat()
                if self.mab_reset_date != today:
                    logger.info("Resetting daily MAB statistics for new trading day")
                    await self.mab_service.reset_daily_stats()
                    self.mab_reset_date = today

                # Step 1c: Get screened tickers
                tickers_response = await self.mcp_client.get_alpaca_screened_tickers()
                if not tickers_response:
                    logger.warning(
                        "Failed to get screened tickers, skipping this cycle"
                    )
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
                filtered_tickers = [
                    ticker for ticker in all_tickers if ticker not in blacklisted_set
                ]

                if blacklisted_set:
                    logger.info(
                        f"Filtered out {len(all_tickers) - len(filtered_tickers)} blacklisted tickers. "
                        f"Analyzing {len(filtered_tickers)} tickers for momentum"
                    )
                else:
                    logger.info(
                        f"Analyzing {len(filtered_tickers)} tickers for momentum"
                    )

                # Step 1d: Get active trades to filter out tickers that already have trades
                active_trades = await self.db_client.get_all_momentum_trades()
                active_count = len(active_trades)
                active_ticker_set = {
                    trade.get("ticker")
                    for trade in active_trades
                    if trade.get("ticker")
                }

                logger.info(
                    f"Current active trades: {active_count}/{self.max_active_trades}"
                )

                # Step 1e: Collect momentum scores for all tickers and market data for MAB
                ticker_momentum_scores = []  # List of (ticker, momentum_score, reason)
                market_data_dict = {}  # Store market data for MAB context

                for ticker in filtered_tickers:
                    if not self.running:
                        break

                    # Double-check ticker is not blacklisted before processing
                    if await self.db_client.is_ticker_blacklisted(ticker):
                        logger.debug(f"Ticker {ticker} is blacklisted, skipping")
                        continue

                    # Skip tickers that already have an active trade
                    if ticker in active_ticker_set:
                        logger.debug(
                            f"Ticker {ticker} already has an active momentum trade, skipping"
                        )
                        continue

                    # Get market data for ticker
                    market_data_response = await self.mcp_client.get_market_data(ticker)
                    if not market_data_response:
                        logger.debug(f"Failed to get market data for {ticker}")
                        continue

                    # Store market data for MAB context
                    market_data_dict[ticker] = market_data_response

                    technical_analysis = market_data_response.get(
                        "technical_analysis", {}
                    )
                    datetime_price = technical_analysis.get("datetime_price", [])

                    if not datetime_price:
                        logger.debug(f"No datetime_price data for {ticker}")
                        continue

                    # Calculate momentum score
                    momentum_score, reason = self._calculate_momentum(datetime_price)

                    # Only include tickers with meaningful momentum (non-zero score)
                    if momentum_score != 0.0:
                        ticker_momentum_scores.append((ticker, momentum_score, reason))

                logger.info(
                    f"Calculated momentum scores for {len(ticker_momentum_scores)} tickers"
                )

                # Step 1f: Separate upward and downward momentum
                upward_tickers = [
                    (t, score, reason)
                    for t, score, reason in ticker_momentum_scores
                    if score > 0
                ]
                downward_tickers = [
                    (t, score, reason)
                    for t, score, reason in ticker_momentum_scores
                    if score < 0
                ]

                # Step 1f.1: Use MAB to select top-k tickers from each direction
                # MAB will boost high-profitability tickers and penalize low-profitability ones
                top_upward = await self.mab_service.select_tickers_with_mab(
                    ticker_candidates=upward_tickers,
                    market_data_dict=market_data_dict,
                    top_k=self.top_k,
                )
                top_downward = await self.mab_service.select_tickers_with_mab(
                    ticker_candidates=downward_tickers,
                    market_data_dict=market_data_dict,
                    top_k=self.top_k,
                )

                logger.info(
                    f"MAB selected {len(top_upward)} upward momentum tickers and "
                    f"{len(top_downward)} downward momentum tickers (top_k={self.top_k})"
                )

                # Step 1g: Enter trades for top-k tickers
                for rank, (ticker, momentum_score, reason) in enumerate(
                    top_upward, start=1
                ):
                    if not self.running:
                        break

                    # Check active trade count before entering
                    active_trades = await self.db_client.get_all_momentum_trades()
                    active_count = len(active_trades)

                    # If at max capacity, check if we can preempt
                    if active_count >= self.max_active_trades:
                        # Only preempt if momentum is exceptional
                        if abs(momentum_score) >= self.exceptional_momentum_threshold:
                            logger.info(
                                f"At max capacity ({active_count}/{self.max_active_trades}), "
                                f"attempting to preempt for exceptional trade {ticker} "
                                f"(momentum: {momentum_score:.2f})"
                            )
                            preempted = await self._preempt_low_profit_trade(
                                ticker, momentum_score
                            )
                            if not preempted:
                                logger.info(
                                    f"Could not preempt for {ticker}, skipping entry "
                                    f"(momentum: {momentum_score:.2f})"
                                )
                                continue
                        else:
                            logger.info(
                                f"At max capacity ({active_count}/{self.max_active_trades}), "
                                f"skipping {ticker} (momentum: {momentum_score:.2f} < "
                                f"exceptional threshold: {self.exceptional_momentum_threshold})"
                            )
                            continue

                    # Upward momentum -> long trade (buy_to_open)
                    action = "buy_to_open"

                    # Get quote for ask price (buy price)
                    quote_response = await self.mcp_client.get_quote(ticker)
                    if not quote_response:
                        logger.warning(f"Failed to get quote for {ticker}, skipping")
                        continue

                    quote_data = quote_response.get("quote", {})
                    quotes = quote_data.get("quotes", {})
                    ticker_quote = quotes.get(ticker, {})
                    enter_price = ticker_quote.get("ap", 0.0)  # Ask price for buy

                    if enter_price <= 0:
                        logger.warning(
                            f"Failed to get valid quote price for {ticker}, skipping"
                        )
                        continue

                    # Send webhook signal
                    indicator = "Momentum Trading"
                    ranked_reason = f"{reason} (ranked #{rank} upward momentum)"
                    webhook_response = await self.mcp_client.send_webhook_signal(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_reason=ranked_reason,
                    )

                    if webhook_response:
                        logger.info(
                            f"Webhook signal sent for {ticker} - {action} (momentum score: {momentum_score:.2f}, rank: #{rank})"
                        )
                    else:
                        logger.warning(f"Failed to send webhook signal for {ticker}")

                    # Add to DynamoDB
                    await self.db_client.add_momentum_trade(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_price=enter_price,
                        enter_reason=ranked_reason,
                    )

                    logger.info(
                        f"Entered momentum trade for {ticker} - {action} at {enter_price} (momentum score: {momentum_score:.2f}, rank: #{rank})"
                    )

                for rank, (ticker, momentum_score, reason) in enumerate(
                    top_downward, start=1
                ):
                    if not self.running:
                        break

                    # Check active trade count before entering
                    active_trades = await self.db_client.get_all_momentum_trades()
                    active_count = len(active_trades)

                    # If at max capacity, check if we can preempt
                    if active_count >= self.max_active_trades:
                        # Only preempt if momentum is exceptional (use absolute value for downward)
                        if abs(momentum_score) >= self.exceptional_momentum_threshold:
                            logger.info(
                                f"At max capacity ({active_count}/{self.max_active_trades}), "
                                f"attempting to preempt for exceptional trade {ticker} "
                                f"(momentum: {momentum_score:.2f})"
                            )
                            preempted = await self._preempt_low_profit_trade(
                                ticker, abs(momentum_score)
                            )
                            if not preempted:
                                logger.info(
                                    f"Could not preempt for {ticker}, skipping entry "
                                    f"(momentum: {momentum_score:.2f})"
                                )
                                continue
                        else:
                            logger.info(
                                f"At max capacity ({active_count}/{self.max_active_trades}), "
                                f"skipping {ticker} (momentum: {momentum_score:.2f} < "
                                f"exceptional threshold: {self.exceptional_momentum_threshold})"
                            )
                            continue

                    # Downward momentum -> short trade (sell_to_open)
                    action = "sell_to_open"

                    # Get quote for bid price (sell price)
                    quote_response = await self.mcp_client.get_quote(ticker)
                    if not quote_response:
                        logger.warning(f"Failed to get quote for {ticker}, skipping")
                        continue

                    quote_data = quote_response.get("quote", {})
                    quotes = quote_data.get("quotes", {})
                    ticker_quote = quotes.get(ticker, {})
                    enter_price = ticker_quote.get("bp", 0.0)  # Bid price for sell

                    if enter_price <= 0:
                        logger.warning(
                            f"Failed to get valid quote price for {ticker}, skipping"
                        )
                        continue

                    # Send webhook signal
                    indicator = "Momentum Trading"
                    ranked_reason = f"{reason} (ranked #{rank} downward momentum)"
                    webhook_response = await self.mcp_client.send_webhook_signal(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_reason=ranked_reason,
                    )

                    if webhook_response:
                        logger.info(
                            f"Webhook signal sent for {ticker} - {action} (momentum score: {momentum_score:.2f}, rank: #{rank})"
                        )
                    else:
                        logger.warning(f"Failed to send webhook signal for {ticker}")

                    # Add to DynamoDB
                    await self.db_client.add_momentum_trade(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_price=enter_price,
                        enter_reason=ranked_reason,
                    )

                    logger.info(
                        f"Entered momentum trade for {ticker} - {action} at {enter_price} (momentum score: {momentum_score:.2f}, rank: #{rank})"
                    )

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
                    logger.warning(
                        "Failed to get market clock, skipping momentum exit check"
                    )
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

                active_count = len(active_trades)
                logger.info(
                    f"Monitoring {active_count}/{self.max_active_trades} active momentum trades"
                )

                # When at capacity, be more aggressive about exiting trades
                at_capacity = active_count >= self.max_active_trades

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
                        logger.warning(
                            f"Unknown action: {original_action} for {ticker}"
                        )
                        continue

                    # Step 2.1: Get current market data to check profitability
                    market_data_response = await self.mcp_client.get_market_data(ticker)
                    if not market_data_response:
                        logger.warning(
                            f"Failed to get market data for {ticker} for exit check - will retry in next cycle"
                        )
                        continue

                    technical_analysis = market_data_response.get(
                        "technical_analysis", {}
                    )
                    current_price = technical_analysis.get("close_price", 0.0)

                    if current_price <= 0:
                        logger.warning(
                            f"Failed to get valid current price for {ticker}"
                        )
                        continue

                    # Step 2.2: Calculate profit percentage
                    profit_percent = self._calculate_profit_percent(
                        enter_price, current_price, original_action
                    )

                    # Step 2.2.1: Check if trade is profitable
                    is_profitable = profit_percent >= self.profit_threshold

                    # When at capacity, also consider exiting low profitable trades
                    # to make room for potentially better trades
                    should_exit = is_profitable
                    exit_reason = None

                    if is_profitable:
                        exit_reason = (
                            f"Profit target reached: {profit_percent:.2f}% profit"
                        )
                    elif at_capacity and profit_percent > 0:
                        # At capacity and trade has some profit (but below threshold)
                        # Exit to make room for potentially better trades
                        should_exit = True
                        exit_reason = (
                            f"Exiting low profit trade ({profit_percent:.2f}%) "
                            f"at capacity to make room for better opportunities"
                        )

                    if should_exit:
                        logger.info(
                            f"Exit signal for {ticker} - {exit_action} "
                            f"(enter: {enter_price}, current: {current_price}, "
                            f"profit: {profit_percent:.2f}%)"
                        )

                        reason = exit_reason

                        # Step 2.3: Send webhook signal
                        webhook_response = await self.mcp_client.send_webhook_signal(
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

                        # Step 2.4: Record MAB reward (profit/loss)
                        context = {
                            "profit_percent": profit_percent,
                            "enter_price": enter_price,
                            "exit_price": current_price,
                            "action": original_action,
                            "indicator": indicator,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        await self.mab_service.record_trade_outcome(
                            ticker=ticker,
                            enter_price=enter_price,
                            exit_price=current_price,
                            action=original_action,
                            context=context,
                        )

                        # Step 2.4.1: Get trade data before deletion for completed trades record
                        enter_reason = trade.get("enter_reason", "")
                        enter_timestamp = trade.get(
                            "created_at", datetime.now(timezone.utc).isoformat()
                        )
                        technical_indicators_for_enter = trade.get(
                            "technical_indicators_for_enter"
                        )

                        # Calculate profit_or_loss in dollars (assuming 1 share for calculation)
                        # For long: profit = exit_price - enter_price
                        # For short: profit = enter_price - exit_price
                        if original_action == "buy_to_open":
                            profit_or_loss = current_price - enter_price
                        elif original_action == "sell_to_open":
                            profit_or_loss = enter_price - current_price
                        else:
                            profit_or_loss = 0.0

                        # Get technical indicators for exit
                        technical_indicators_for_exit = technical_analysis.copy()
                        # Remove datetime_price if present (not needed for exit indicators)
                        if "datetime_price" in technical_indicators_for_exit:
                            technical_indicators_for_exit = {
                                k: v
                                for k, v in technical_indicators_for_exit.items()
                                if k != "datetime_price"
                            }

                        # Get current date for partition key
                        current_date = date.today().isoformat()
                        exit_timestamp = datetime.now(timezone.utc).isoformat()

                        # Step 2.4.2: Add completed trade to CompletedTradesForAutomatedDayTrading
                        await self.db_client.add_completed_trade(
                            date=current_date,
                            indicator=indicator,
                            ticker=ticker,
                            action=original_action,
                            enter_price=enter_price,
                            enter_reason=enter_reason,
                            enter_timestamp=enter_timestamp,
                            exit_price=current_price,
                            exit_timestamp=exit_timestamp,
                            exit_reason=exit_reason,
                            profit_or_loss=profit_or_loss,
                            technical_indicators_for_enter=technical_indicators_for_enter,
                            technical_indicators_for_exit=technical_indicators_for_exit,
                        )

                        # Step 2.5: Delete from DynamoDB
                        await self.db_client.delete_momentum_trade(ticker)
                        logger.info(f"Exited momentum trade for {ticker}")
                    else:
                        # Not profitable yet, continue monitoring
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
        await asyncio.gather(self.entry_service(), self.exit_service())
