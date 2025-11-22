"""
Momentum Trading Service with entry and exit logic based on price momentum
"""

import asyncio
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, date, timezone
from app.src.common.loguru_logger import logger
from app.src.services.mcp.mcp_client import MCPClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.tool_discovery.tool_discovery import ToolDiscoveryService
from app.src.services.mab.mab_service import MABService
from app.src.config.constants import (
    MCP_SERVER_TRANSPORT,
    MCP_TOOL_DISCOVERY_INTERVAL_SECONDS,
)


class MomentumTradingService:
    """Momentum-based trading service with entry and exit logic - HIGHLY SELECTIVE"""

    running: bool = True
    profit_threshold: float = 1.5  # 1.5% profit threshold (increased from 0.5%)
    top_k: int = 2  # Maximum 2 tickers per direction per cycle (reduced from 10)
    max_active_trades: int = 5  # Maximum 5 active trades (reduced from 30)
    exceptional_momentum_threshold: float = 5.0
    # New: Minimum momentum threshold - only trade strong momentum
    min_momentum_threshold: float = 3.0  # Only trade if |momentum| >= 3%
    # New: Stock quality filters
    # min_stock_price: float = 1.0  # Minimum stock price $1.00
    min_daily_volume: int = 1000  # Minimum daily volume (100k shares)
    # New: Daily trade limits
    max_daily_trades: int = 5  # Maximum 5 trades per day total
    # New: Cooldown periods
    ticker_cooldown_minutes: int = (
        60  # Don't re-enter same ticker for 60 minutes after exit
    )
    # New: Trailing stop loss (wider than before)
    stop_loss_threshold: float = -1.5  # Exit if losing 1.5% (increased from 0.5%)
    trailing_stop_percent: float = 1.5  # Trail 1.5% from peak (increased from 0.5%)
    # New: ADX filter - only trade when trend is strong
    min_adx_threshold: float = 20.0  # Only trade if ADX >= 20 (strong trend)
    # New: RSI filters - avoid overbought/oversold entries
    rsi_oversold_for_long: float = 35.0  # Longs only when RSI < 35 (oversold)
    rsi_overbought_for_short: float = 65.0  # Shorts only when RSI > 65 (overbought)
    # New: Let winners run - higher profit target for strong momentum
    profit_target_strong_momentum: float = 5.0  # 5% target for strong momentum (>5%)
    # New: Cycle time (check less frequently)
    entry_cycle_seconds: int = 5  # Check every 5 seconds

    tool_discovery_cls: Optional[type] = ToolDiscoveryService
    indicator_name: str = "Momentum Trading"
    mab_reset_date: Optional[str] = None
    daily_trades_count: int = 0  # Track daily trades
    daily_trades_date: Optional[str] = None  # Track which date
    ticker_exit_timestamps: Dict[str, datetime] = (
        {}
    )  # Track when tickers were exited for cooldown

    @classmethod
    def configure(
        cls,
        *,
        tool_discovery_cls: Optional[type] = ToolDiscoveryService,
        top_k: int = 10,
    ):
        """Configure dependencies and runtime parameters"""
        if tool_discovery_cls is not None:
            cls.tool_discovery_cls = tool_discovery_cls
        cls.top_k = top_k
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
    def _is_ticker_in_cooldown(cls, ticker: str) -> bool:
        """
        Check if ticker is in cooldown period (recently exited)
        Returns True if ticker should not be traded yet
        """
        if ticker not in cls.ticker_exit_timestamps:
            return False

        exit_time = cls.ticker_exit_timestamps[ticker]
        elapsed_minutes = (
            datetime.now(timezone.utc) - exit_time
        ).total_seconds() / 60.0

        if elapsed_minutes >= cls.ticker_cooldown_minutes:
            # Cooldown expired, remove from dict
            del cls.ticker_exit_timestamps[ticker]
            return False

        return True  # Still in cooldown

    @classmethod
    def _has_reached_daily_trade_limit(cls) -> bool:
        """Check if daily trade limit has been reached"""
        today = date.today().isoformat()

        # Reset daily count if new day
        if cls.daily_trades_date != today:
            cls.daily_trades_count = 0
            cls.daily_trades_date = today

        return cls.daily_trades_count >= cls.max_daily_trades

    @classmethod
    def _increment_daily_trade_count(cls):
        """Increment daily trade counter"""
        today = date.today().isoformat()

        # Reset daily count if new day
        if cls.daily_trades_date != today:
            cls.daily_trades_count = 0
            cls.daily_trades_date = today

        cls.daily_trades_count += 1

    @classmethod
    def _is_warrant_or_option(cls, ticker: str) -> bool:
        """
        Check if ticker is a warrant or option based on suffix
        Warrants typically have suffixes like W, WS, WT, etc.
        Options are not typically traded directly in this system, but check anyway
        """
        ticker_upper = ticker.upper()
        # Common warrant/rights suffixes
        warrant_suffixes = ["W", "WS", "WT", "WTS", "R", "RT"]

        # Check if ticker ends with a warrant suffix (case insensitive)
        for suffix in warrant_suffixes:
            if ticker_upper.endswith(suffix):
                # Make sure it's actually a suffix (at least 3 chars before it)
                if len(ticker_upper) > len(suffix) + 2:
                    return True

        return False

    @classmethod
    async def _passes_stock_quality_filters(
        cls, ticker: str, market_data: Dict[str, Any], momentum_score: float = 0.0
    ) -> Tuple[bool, str]:
        """
        Check if ticker passes stock quality filters including ADX and RSI
        Returns: (passes_filter, reason)
        """
        # Filter 1: Exclude warrants and options
        if cls._is_warrant_or_option(ticker):
            return (
                False,
                f"Excluded: {ticker} is a warrant/option (ends with W/R/RT/etc)",
            )

        technical_analysis = market_data.get("technical_analysis", {})
        current_price = technical_analysis.get("close_price", 0.0)

        # # Filter 2: Minimum stock price
        # if current_price <= 0:
        #     return False, f"Invalid price data for {ticker}"

        # if current_price < cls.min_stock_price:
        #     return (
        #         False,
        #         f"Price too low: ${current_price:.2f} < ${cls.min_stock_price} minimum",
        #     )

        # Filter 3: Minimum volume
        volume = technical_analysis.get("volume", 0)
        volume_sma = technical_analysis.get("volume_sma", 0)
        avg_volume = volume_sma if volume_sma > 0 else volume

        if avg_volume < cls.min_daily_volume:
            return (
                False,
                f"Volume too low: {avg_volume:,} < {cls.min_daily_volume:,} minimum",
            )

        # Filter 4: ADX - require strong trend (ADX >= 20)
        adx = technical_analysis.get("adx", 0.0)
        if adx < cls.min_adx_threshold:
            return (
                False,
                f"ADX too low: {adx:.2f} < {cls.min_adx_threshold} (no strong trend)",
            )

        # Filter 5: RSI - avoid overbought/oversold entries
        rsi = technical_analysis.get("rsi", 50.0)  # Default to neutral if not available

        # Determine trade direction from momentum
        is_long = momentum_score > 0
        is_short = momentum_score < 0

        if is_long and rsi >= cls.rsi_oversold_for_long:
            return (
                False,
                f"RSI too high for long: {rsi:.2f} >= {cls.rsi_oversold_for_long} (not oversold enough)",
            )

        if is_short and rsi <= cls.rsi_overbought_for_short:
            return (
                False,
                f"RSI too low for short: {rsi:.2f} <= {cls.rsi_overbought_for_short} (not overbought enough)",
            )

        return True, f"Passed all quality filters (ADX: {adx:.2f}, RSI: {rsi:.2f})"

    @classmethod
    def _calculate_momentum(cls, datetime_price: List[Any]) -> Tuple[float, str]:
        """
        Calculate price momentum score from datetime_price array
        Returns: (momentum_score, reason)
        - Positive score indicates upward momentum
        - Negative score indicates downward momentum
        - Higher absolute value indicates stronger momentum
        """
        if not datetime_price or len(datetime_price) < 3:
            return 0.0, "Insufficient price data"

        # Extract prices (datetime_price can be list of [datetime, price] or list of dicts)
        prices = []
        for entry in datetime_price:
            try:
                if isinstance(entry, list):
                    # Handle list format: [datetime, price]
                    if len(entry) >= 2:
                        prices.append(float(entry[1]))
                elif isinstance(entry, dict):
                    # Handle dict format: try common price keys
                    price = (
                        entry.get("price")
                        or entry.get("close")
                        or entry.get("close_price")
                    )
                    if price is not None:
                        prices.append(float(price))
            except (ValueError, TypeError, KeyError, IndexError):
                # Skip invalid entries
                continue

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

    @classmethod
    def _is_profitable(
        cls, enter_price: float, current_price: float, action: str
    ) -> bool:
        """
        Check if trade is profitable based on enter price, current price, and action
        For buy_to_open (long): profitable if current_price > enter_price
        For sell_to_open (short): profitable if current_price < enter_price
        """
        if action == "buy_to_open":
            # Long trade: profitable if current price is higher
            profit_percent = ((current_price - enter_price) / enter_price) * 100
            return profit_percent >= cls.profit_threshold
        elif action == "sell_to_open":
            # Short trade: profitable if current price is lower
            profit_percent = ((enter_price - current_price) / enter_price) * 100
            return profit_percent >= cls.profit_threshold
        return False

    @classmethod
    def _calculate_profit_percent(
        cls, enter_price: float, current_price: float, action: str
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

    @classmethod
    async def _find_lowest_profitable_trade(
        cls, active_trades: List[Dict[str, Any]]
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
            market_data_response = await MCPClient.get_market_data(ticker)
            if not market_data_response:
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            current_price = technical_analysis.get("close_price", 0.0)

            if current_price <= 0:
                continue

            profit_percent = cls._calculate_profit_percent(
                enter_price, current_price, action
            )

            # Only consider profitable trades
            if profit_percent >= cls.profit_threshold:
                if lowest_profit is None or profit_percent < lowest_profit:
                    lowest_profit = profit_percent
                    lowest_trade = trade

        if lowest_trade and lowest_profit is not None:
            return (lowest_trade, lowest_profit)
        return None

    @classmethod
    async def _preempt_low_profit_trade(
        cls, new_ticker: str, new_momentum_score: float
    ) -> bool:
        """
        Preempt (exit) a low profitable trade to make room for a new exceptional trade
        Returns True if preemption was successful, False otherwise
        """
        active_trades = await DynamoDBClient.get_all_momentum_trades(cls.indicator_name)

        if len(active_trades) < cls.max_active_trades:
            return False  # No need to preempt

        # Find lowest profitable trade
        result = await cls._find_lowest_profitable_trade(active_trades)
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
        indicator = lowest_trade.get("indicator", cls.indicator_name)

        # Determine exit action
        if original_action == "buy_to_open":
            exit_action = "sell_to_close"
        elif original_action == "sell_to_open":
            exit_action = "buy_to_close"
        else:
            logger.warning(f"Unknown action: {original_action} for {ticker_to_exit}")
            return False

        # Get current price for exit
        market_data_response = await MCPClient.get_market_data(ticker_to_exit)
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
        await send_signal_to_webhook(
            ticker=ticker_to_exit,
            action=exit_action,
            indicator=indicator,
            enter_reason=reason,
        )

        # Record MAB reward
        profit_percent = cls._calculate_profit_percent(
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
        await MABService.record_trade_outcome(
            indicator=cls.indicator_name,
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
        await DynamoDBClient.add_completed_trade(
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
        await DynamoDBClient.delete_momentum_trade(ticker_to_exit, indicator)
        logger.info(f"Preempted and exited trade for {ticker_to_exit}")
        return True

    @classmethod
    async def entry_service(cls):
        """Entry service that runs every 60 seconds - analyzes momentum and enters trades (HIGHLY SELECTIVE)"""
        logger.info("Momentum entry service started (HIGHLY SELECTIVE MODE)")
        while cls.running:
            try:
                # Step 1a: Get market clock
                clock_response = await MCPClient.get_market_clock()
                if not clock_response:
                    logger.warning("Failed to get market clock, skipping this cycle")
                    await asyncio.sleep(cls.entry_cycle_seconds)
                    continue

                clock = clock_response.get("clock", {})
                is_open = clock.get("is_open", False)

                # Step 1b: Check if market is open
                if not is_open:
                    logger.debug("Market is closed, skipping momentum entry logic")
                    await asyncio.sleep(cls.entry_cycle_seconds)
                    continue

                logger.info(
                    "Market is open, proceeding with momentum entry logic (HIGHLY SELECTIVE)"
                )

                # Step 1b.1: Reset MAB daily stats and daily trade count if needed (at market open)
                today = date.today().isoformat()
                if cls.mab_reset_date != today:
                    logger.info("Resetting daily MAB statistics for new trading day")
                    await MABService.reset_daily_stats(cls.indicator_name)
                    cls.mab_reset_date = today
                    cls.daily_trades_count = 0
                    cls.daily_trades_date = today
                    cls.ticker_exit_timestamps.clear()  # Clear cooldown timestamps for new day

                # Step 1b.2: Check daily trade limit
                if cls._has_reached_daily_trade_limit():
                    logger.info(
                        f"Daily trade limit reached: {cls.daily_trades_count}/{cls.max_daily_trades}. "
                        "Skipping entry logic this cycle."
                    )
                    await asyncio.sleep(cls.entry_cycle_seconds)
                    continue

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

                # Combine all tickers to analyze
                all_tickers = list(set(gainers + losers + most_actives))

                # Step 1c.1: Get blacklisted tickers and filter them out
                blacklisted_tickers = await DynamoDBClient.get_blacklisted_tickers()
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
                active_trades = await DynamoDBClient.get_all_momentum_trades(cls.indicator_name)
                active_count = len(active_trades)
                active_ticker_set = {
                    trade.get("ticker")
                    for trade in active_trades
                    if trade.get("ticker")
                }

                logger.info(
                    f"Current active trades: {active_count}/{cls.max_active_trades}"
                )

                # Step 1e: Collect momentum scores for all tickers and market data for MAB
                ticker_momentum_scores = []  # List of (ticker, momentum_score, reason)
                market_data_dict = {}  # Store market data for MAB context

                for ticker in filtered_tickers:
                    if not cls.running:
                        break

                    # Double-check ticker is not blacklisted before processing
                    if await DynamoDBClient.is_ticker_blacklisted(ticker):
                        logger.debug(f"Ticker {ticker} is blacklisted, skipping")
                        continue

                    # Skip tickers that already have an active trade
                    if ticker in active_ticker_set:
                        logger.debug(
                            f"Ticker {ticker} already has an active momentum trade, skipping"
                        )
                        continue

                    # Get market data for ticker
                    market_data_response = await MCPClient.get_market_data(ticker)
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
                    momentum_score, reason = cls._calculate_momentum(datetime_price)

                    # Filter 1: Only include tickers with strong momentum (above minimum threshold)
                    abs_momentum = abs(momentum_score)
                    if abs_momentum < cls.min_momentum_threshold:
                        logger.debug(
                            f"Skipping {ticker}: momentum {momentum_score:.2f}% < "
                            f"minimum threshold {cls.min_momentum_threshold}%"
                        )
                        continue

                    # Filter 2: Check stock quality filters (including ADX and RSI)
                    passes_filter, filter_reason = (
                        await cls._passes_stock_quality_filters(
                            ticker, market_data_response, momentum_score
                        )
                    )
                    if not passes_filter:
                        logger.debug(f"Skipping {ticker}: {filter_reason}")
                        continue

                    # Filter 3: Check cooldown period
                    if cls._is_ticker_in_cooldown(ticker):
                        logger.debug(
                            f"Skipping {ticker}: still in cooldown period "
                            f"({cls.ticker_cooldown_minutes} minutes after exit)"
                        )
                        continue

                    # Passed all filters - add to candidates
                    ticker_momentum_scores.append((ticker, momentum_score, reason))
                    logger.info(
                        f"{ticker} passed all filters: momentum={momentum_score:.2f}%, "
                        f"{filter_reason}"
                    )

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
                top_upward = await MABService.select_tickers_with_mab(
                    cls.indicator_name,
                    ticker_candidates=upward_tickers,
                    market_data_dict=market_data_dict,
                    top_k=cls.top_k,
                )
                top_downward = await MABService.select_tickers_with_mab(
                    cls.indicator_name,
                    ticker_candidates=downward_tickers,
                    market_data_dict=market_data_dict,
                    top_k=cls.top_k,
                )

                logger.info(
                    f"MAB selected {len(top_upward)} upward momentum tickers and "
                    f"{len(top_downward)} downward momentum tickers (top_k={cls.top_k})"
                )

                # Step 1g: Enter trades for top-k tickers (HIGHLY SELECTIVE - max 2 per direction)
                for rank, (ticker, momentum_score, reason) in enumerate(
                    top_upward, start=1
                ):
                    if not cls.running:
                        break

                    # Check daily trade limit before entering
                    if cls._has_reached_daily_trade_limit():
                        logger.info(
                            f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                            f"Skipping remaining candidates."
                        )
                        break

                    # Check active trade count before entering
                    active_trades = await DynamoDBClient.get_all_momentum_trades(cls.indicator_name)
                    active_count = len(active_trades)

                    # If at max capacity, check if we can preempt
                    if active_count >= cls.max_active_trades:
                        # Only preempt if momentum is exceptional
                        if abs(momentum_score) >= cls.exceptional_momentum_threshold:
                            logger.info(
                                f"At max capacity ({active_count}/{cls.max_active_trades}), "
                                f"attempting to preempt for exceptional trade {ticker} "
                                f"(momentum: {momentum_score:.2f})"
                            )
                            preempted = await cls._preempt_low_profit_trade(
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
                                f"At max capacity ({active_count}/{cls.max_active_trades}), "
                                f"skipping {ticker} (momentum: {momentum_score:.2f} < "
                                f"exceptional threshold: {cls.exceptional_momentum_threshold})"
                            )
                            continue

                    # Upward momentum -> long trade (buy_to_open)
                    action = "buy_to_open"

                    # Get quote for ask price (buy price)
                    quote_response = await MCPClient.get_quote(ticker)
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
                    indicator = cls.indicator_name
                    ranked_reason = f"{reason} (ranked #{rank} upward momentum)"
                    await send_signal_to_webhook(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_reason=ranked_reason,
                    )

                    # Add to DynamoDB
                    await DynamoDBClient.add_momentum_trade(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_price=enter_price,
                        enter_reason=ranked_reason,
                    )

                    # Increment daily trade count
                    cls._increment_daily_trade_count()

                    logger.info(
                        f"Entered momentum trade for {ticker} - {action} at {enter_price} "
                        f"(momentum score: {momentum_score:.2f}, rank: #{rank}, "
                        f"daily trades: {cls.daily_trades_count}/{cls.max_daily_trades})"
                    )

                for rank, (ticker, momentum_score, reason) in enumerate(
                    top_downward, start=1
                ):
                    if not cls.running:
                        break

                    # Check daily trade limit before entering
                    if cls._has_reached_daily_trade_limit():
                        logger.info(
                            f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                            f"Skipping remaining candidates."
                        )
                        break
                    if not cls.running:
                        break

                    # Check active trade count before entering
                    active_trades = await DynamoDBClient.get_all_momentum_trades(cls.indicator_name)
                    active_count = len(active_trades)

                    # If at max capacity, check if we can preempt
                    if active_count >= cls.max_active_trades:
                        # Only preempt if momentum is exceptional (use absolute value for downward)
                        if abs(momentum_score) >= cls.exceptional_momentum_threshold:
                            logger.info(
                                f"At max capacity ({active_count}/{cls.max_active_trades}), "
                                f"attempting to preempt for exceptional trade {ticker} "
                                f"(momentum: {momentum_score:.2f})"
                            )
                            preempted = await cls._preempt_low_profit_trade(
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
                                f"At max capacity ({active_count}/{cls.max_active_trades}), "
                                f"skipping {ticker} (momentum: {momentum_score:.2f} < "
                                f"exceptional threshold: {cls.exceptional_momentum_threshold})"
                            )
                            continue

                    # Downward momentum -> short trade (sell_to_open)
                    action = "sell_to_open"

                    # Get quote for bid price (sell price)
                    quote_response = await MCPClient.get_quote(ticker)
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
                    indicator = cls.indicator_name
                    ranked_reason = f"{reason} (ranked #{rank} downward momentum)"
                    await send_signal_to_webhook(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_reason=ranked_reason,
                    )

                    # Add to DynamoDB
                    await DynamoDBClient.add_momentum_trade(
                        ticker=ticker,
                        action=action,
                        indicator=indicator,
                        enter_price=enter_price,
                        enter_reason=ranked_reason,
                    )

                    # Increment daily trade count
                    cls._increment_daily_trade_count()

                    logger.info(
                        f"Entered momentum trade for {ticker} - {action} at {enter_price} "
                        f"(momentum score: {momentum_score:.2f}, rank: #{rank}, "
                        f"daily trades: {cls.daily_trades_count}/{cls.max_daily_trades})"
                    )

                # Wait 60 seconds before next cycle (reduced frequency)
                await asyncio.sleep(cls.entry_cycle_seconds)

            except Exception as e:
                logger.exception(f"Error in momentum entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    async def exit_service(cls):
        """Exit service that runs every 5 seconds - checks profitability and exits trades"""
        logger.info("Momentum exit service started")
        while cls.running:
            try:
                # Step 2a: Check if market is open - don't do momentum trading when market is closed
                clock_response = await MCPClient.get_market_clock()
                if not clock_response:
                    logger.warning(
                        "Failed to get market clock, skipping momentum exit check"
                    )
                    await asyncio.sleep(5)
                    continue

                clock = clock_response.get("clock", {})
                is_open = clock.get("is_open", False)

                if not is_open:
                    logger.debug("Market is closed, skipping momentum exit logic")
                    await asyncio.sleep(5)
                    continue

                # Step 2: Get all active momentum trades from DynamoDB
                active_trades = await DynamoDBClient.get_all_momentum_trades(cls.indicator_name)

                if not active_trades:
                    logger.debug("No active momentum trades to monitor")
                    await asyncio.sleep(5)
                    continue

                active_count = len(active_trades)
                logger.info(
                    f"Monitoring {active_count}/{cls.max_active_trades} active momentum trades"
                )

                for trade in active_trades:
                    if not cls.running:
                        break

                    ticker = trade.get("ticker")
                    original_action = trade.get("action")
                    enter_price = trade.get("enter_price")
                    indicator = trade.get("indicator", "Momentum Trading")
                    # Get trailing stop and peak profit from trade (defaults if not present)
                    trailing_stop = float(trade.get("trailing_stop", 0.5))
                    peak_profit_percent = float(trade.get("peak_profit_percent", 0.0))

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
                    market_data_response = await MCPClient.get_market_data(ticker)
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
                    profit_percent = cls._calculate_profit_percent(
                        enter_price, current_price, original_action
                    )

                    # Step 2.2.1: Trailing stop loss logic (WIDER STOPS - 1.5% instead of 0.5%)
                    should_exit = False
                    exit_reason = None

                    # Check 1: Exit if losing more than 1.5% from enter_price (wider stop loss)
                    if profit_percent < cls.stop_loss_threshold:
                        should_exit = True
                        exit_reason = (
                            f"Trailing stop loss triggered: {profit_percent:.2f}% "
                            f"(below {cls.stop_loss_threshold}% stop loss threshold)"
                        )
                        logger.info(
                            f"Exit signal for {ticker} - losing trade: {profit_percent:.2f}%"
                        )

                    # Check 2: Exit if profit drops by 1.5% from peak (trailing stop - wider)
                    elif peak_profit_percent > 0:
                        drop_from_peak = peak_profit_percent - profit_percent
                        if drop_from_peak >= cls.trailing_stop_percent:
                            should_exit = True
                            exit_reason = (
                                f"Trailing stop triggered: profit dropped {drop_from_peak:.2f}% "
                                f"from peak of {peak_profit_percent:.2f}% (current: {profit_percent:.2f}%)"
                            )
                            logger.info(
                                f"Exit signal for {ticker} - trailing stop: "
                                f"peak {peak_profit_percent:.2f}%, current {profit_percent:.2f}%"
                            )

                    # Check 3: Dynamic profit target logic (if not already exiting)
                    # Use higher target to let winners run, avoid premature exits
                    if not should_exit:
                        # Use higher profit target - let winners run to 5% before fixed exit
                        # Primary exit mechanism is trailing stop (1.5% from peak), not fixed target
                        # Only exit at fixed target if we've already hit a good profit
                        profit_target_to_exit = cls.profit_target_strong_momentum  # 5%

                        is_profitable = profit_percent >= profit_target_to_exit
                        if is_profitable:
                            should_exit = True
                            exit_reason = (
                                f"Profit target reached: {profit_percent:.2f}% profit "
                                f"(target: {profit_target_to_exit:.2f}%)"
                            )
                        # REMOVED: Capacity-based low-profit exits - they're killing performance
                        # Let trailing stops handle exits instead of exiting at 0.06-0.19% to free capacity

                    # Update peak profit and trailing stop if trade is still active
                    if not should_exit:
                        # Update peak profit if current profit is higher
                        if profit_percent > peak_profit_percent:
                            peak_profit_percent = profit_percent
                            trailing_stop = (
                                cls.trailing_stop_percent
                            )  # Always maintain 1.5% trailing stop

                        # Update database with current trailing stop and peak profit
                        skipped_reason = None
                        if profit_percent < 0:
                            skipped_reason = (
                                f"Trade is losing: {profit_percent:.2f}% "
                                f"(trailing stop: {trailing_stop:.2f}%, peak: {peak_profit_percent:.2f}%)"
                            )
                        elif profit_percent < cls.profit_threshold:
                            skipped_reason = (
                                f"Trade not yet profitable: {profit_percent:.2f}% "
                                f"(trailing stop: {trailing_stop:.2f}%, peak: {peak_profit_percent:.2f}%)"
                            )
                        else:
                            skipped_reason = (
                                f"Trade profitable: {profit_percent:.2f}% "
                                f"(trailing stop: {trailing_stop:.2f}%, peak: {peak_profit_percent:.2f}%)"
                            )

                        await DynamoDBClient.update_momentum_trade_trailing_stop(
                            ticker=ticker,
                            indicator=indicator,
                            trailing_stop=trailing_stop,
                            peak_profit_percent=peak_profit_percent,
                            skipped_exit_reason=skipped_reason,
                        )

                    if should_exit:
                        logger.info(
                            f"Exit signal for {ticker} - {exit_action} "
                            f"(enter: {enter_price}, current: {current_price}, "
                            f"profit: {profit_percent:.2f}%)"
                        )

                        reason = exit_reason

                        # Step 2.3: Send webhook signal
                        await send_signal_to_webhook(
                            ticker=ticker,
                            action=exit_action,
                            indicator=indicator,
                            enter_reason=reason,
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
                        await MABService.record_trade_outcome(
                            indicator=cls.indicator_name,
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
                        await DynamoDBClient.add_completed_trade(
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
                        await DynamoDBClient.delete_momentum_trade(ticker, indicator)

                        # Track exit timestamp for cooldown period
                        cls.ticker_exit_timestamps[ticker] = datetime.now(timezone.utc)
                        logger.info(
                            f"Exited momentum trade for {ticker}. Cooldown period: {cls.ticker_cooldown_minutes} minutes."
                        )

                # Wait 5 seconds before next cycle
                await asyncio.sleep(5)

            except Exception as e:
                logger.exception(f"Error in momentum exit service: {str(e)}")
                await asyncio.sleep(5)

    @classmethod
    async def run(cls):
        """Run both entry and exit services concurrently"""
        logger.info("Starting momentum trading service...")

        # Run both services concurrently
        await asyncio.gather(cls.entry_service(), cls.exit_service())
