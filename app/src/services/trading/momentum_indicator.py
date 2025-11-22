"""
Momentum Trading Indicator
Uses price momentum to identify entry and exit signals
"""

import asyncio
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, date, timezone

from app.src.common.loguru_logger import logger
from app.src.services.mcp.mcp_client import MCPClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator


class MomentumIndicator(BaseTradingIndicator):
    """Momentum-based trading indicator"""

    # Momentum-specific configuration
    profit_threshold: float = 1.5
    top_k: int = 2
    exceptional_momentum_threshold: float = 5.0
    min_momentum_threshold: float = 3.0
    min_daily_volume: int = 1000
    stop_loss_threshold: float = -1.5
    trailing_stop_percent: float = 1.5
    min_adx_threshold: float = 20.0
    rsi_oversold_for_long: float = 35.0
    rsi_overbought_for_short: float = 65.0
    profit_target_strong_momentum: float = 5.0

    @classmethod
    def indicator_name(cls) -> str:
        return "Momentum Trading"

    @classmethod
    def _is_warrant_or_option(cls, ticker: str) -> bool:
        """Check if ticker is a warrant or option"""
        ticker_upper = ticker.upper()
        warrant_suffixes = ["W", "WS", "WT", "WTS", "R", "RT"]

        for suffix in warrant_suffixes:
            if ticker_upper.endswith(suffix):
                if len(ticker_upper) > len(suffix) + 2:
                    return True
        return False

    @classmethod
    async def _passes_stock_quality_filters(
        cls, ticker: str, market_data: Dict[str, Any], momentum_score: float = 0.0
    ) -> Tuple[bool, str]:
        """Check if ticker passes stock quality filters"""
        if cls._is_warrant_or_option(ticker):
            return (
                False,
                f"Excluded: {ticker} is a warrant/option (ends with W/R/RT/etc)",
            )

        technical_analysis = market_data.get("technical_analysis", {})
        current_price = technical_analysis.get("close_price", 0.0)

        volume = technical_analysis.get("volume", 0)
        volume_sma = technical_analysis.get("volume_sma", 0)
        avg_volume = volume_sma if volume_sma > 0 else volume

        if avg_volume < cls.min_daily_volume:
            return (
                False,
                f"Volume too low: {avg_volume:,} < {cls.min_daily_volume:,} minimum",
            )

        adx = technical_analysis.get("adx", 0.0)
        if adx < cls.min_adx_threshold:
            return (
                False,
                f"ADX too low: {adx:.2f} < {cls.min_adx_threshold} (no strong trend)",
            )

        rsi = technical_analysis.get("rsi", 50.0)
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
        """Calculate price momentum score from datetime_price array"""
        if not datetime_price or len(datetime_price) < 3:
            return 0.0, "Insufficient price data"

        prices = []
        for entry in datetime_price:
            try:
                if isinstance(entry, list):
                    if len(entry) >= 2:
                        prices.append(float(entry[1]))
                elif isinstance(entry, dict):
                    price = (
                        entry.get("price")
                        or entry.get("close")
                        or entry.get("close_price")
                    )
                    if price is not None:
                        prices.append(float(price))
            except (ValueError, TypeError, KeyError, IndexError):
                continue

        if len(prices) < 3:
            return 0.0, "Insufficient price data"

        n = len(prices)
        early_count = max(1, n // 3)
        recent_count = max(1, n // 3)

        early_prices = prices[:early_count]
        recent_prices = prices[-recent_count:]

        early_avg = sum(early_prices) / len(early_prices)
        recent_avg = sum(recent_prices) / len(recent_prices)

        change_percent = ((recent_avg - early_avg) / early_avg) * 100

        recent_trend = sum(
            (recent_prices[i] - recent_prices[i - 1])
            for i in range(1, len(recent_prices))
        ) / max(1, len(recent_prices) - 1)

        trend_percent = (recent_trend / early_avg) * 100 if early_avg > 0 else 0
        momentum_score = (0.7 * change_percent) + (0.3 * trend_percent)

        reason = f"Momentum: {change_percent:.2f}% change, {trend_percent:.2f}% trend (early_avg: {early_avg:.2f}, recent_avg: {recent_avg:.2f})"

        return momentum_score, reason

    @classmethod
    async def _find_lowest_profitable_trade(
        cls, active_trades: List[Dict[str, Any]]
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        """Find the lowest profitable trade from active trades"""
        lowest_profit = None
        lowest_trade = None

        for trade in active_trades:
            ticker = trade.get("ticker")
            enter_price = trade.get("enter_price")
            action = trade.get("action")

            if not ticker or enter_price is None or enter_price <= 0:
                continue

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
        """Preempt a low profitable trade to make room for exceptional trade"""
        active_trades = await cls._get_active_trades()

        if len(active_trades) < cls.max_active_trades:
            return False

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

        original_action = lowest_trade.get("action")
        enter_price = lowest_trade.get("enter_price")

        if original_action == "buy_to_open":
            exit_action = "sell_to_close"
        elif original_action == "sell_to_open":
            exit_action = "buy_to_close"
        else:
            logger.warning(f"Unknown action: {original_action} for {ticker_to_exit}")
            return False

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

        reason = f"Preempted for exceptional trade: {lowest_profit:.2f}% profit"

        technical_indicators_for_enter = lowest_trade.get(
            "technical_indicators_for_enter"
        )
        technical_indicators_for_exit = technical_analysis.copy()
        if "datetime_price" in technical_indicators_for_exit:
            technical_indicators_for_exit = {
                k: v
                for k, v in technical_indicators_for_exit.items()
                if k != "datetime_price"
            }

        await cls._exit_trade(
            ticker=ticker_to_exit,
            original_action=original_action,
            enter_price=enter_price,
            exit_price=exit_price,
            exit_reason=reason,
            technical_indicators_enter=technical_indicators_for_enter,
            technical_indicators_exit=technical_indicators_for_exit,
        )

        return True

    @classmethod
    async def entry_service(cls):
        """Entry service - analyze momentum and enter trades"""
        logger.info("Momentum entry service started (HIGHLY SELECTIVE MODE)")
        while cls.running:
            try:
                # Check market open
                if not await cls._check_market_open():
                    logger.debug("Market is closed, skipping momentum entry logic")
                    await asyncio.sleep(cls.entry_cycle_seconds)
                    continue

                logger.info(
                    "Market is open, proceeding with momentum entry logic (HIGHLY SELECTIVE)"
                )

                # Reset daily stats if needed
                await cls._reset_daily_stats_if_needed()

                # Check daily trade limit
                if cls._has_reached_daily_trade_limit():
                    logger.info(
                        f"Daily trade limit reached: {cls.daily_trades_count}/{cls.max_daily_trades}. "
                        "Skipping entry logic this cycle."
                    )
                    await asyncio.sleep(cls.entry_cycle_seconds)
                    continue

                # Get screened tickers
                all_tickers = await cls._get_screened_tickers()
                if not all_tickers:
                    logger.warning("Failed to get screened tickers, skipping this cycle")
                    await asyncio.sleep(10)
                    continue

                # Filter blacklisted tickers
                filtered_tickers = await cls._filter_blacklisted_tickers(all_tickers)

                # Get active trades
                active_trades = await cls._get_active_trades()
                active_count = len(active_trades)
                active_ticker_set = await cls._get_active_ticker_set()

                logger.info(
                    f"Current active trades: {active_count}/{cls.max_active_trades}"
                )

                # Collect momentum scores
                ticker_momentum_scores = []
                market_data_dict = {}

                for ticker in filtered_tickers:
                    if not cls.running:
                        break

                    if ticker in active_ticker_set:
                        logger.debug(
                            f"Ticker {ticker} already has an active momentum trade, skipping"
                        )
                        continue

                    market_data_response = await MCPClient.get_market_data(ticker)
                    if not market_data_response:
                        logger.debug(f"Failed to get market data for {ticker}")
                        continue

                    market_data_dict[ticker] = market_data_response

                    technical_analysis = market_data_response.get(
                        "technical_analysis", {}
                    )
                    datetime_price = technical_analysis.get("datetime_price", [])

                    if not datetime_price:
                        logger.debug(f"No datetime_price data for {ticker}")
                        continue

                    momentum_score, reason = cls._calculate_momentum(datetime_price)

                    abs_momentum = abs(momentum_score)
                    if abs_momentum < cls.min_momentum_threshold:
                        logger.debug(
                            f"Skipping {ticker}: momentum {momentum_score:.2f}% < "
                            f"minimum threshold {cls.min_momentum_threshold}%"
                        )
                        continue

                    passes_filter, filter_reason = (
                        await cls._passes_stock_quality_filters(
                            ticker, market_data_response, momentum_score
                        )
                    )
                    if not passes_filter:
                        logger.debug(f"Skipping {ticker}: {filter_reason}")
                        continue

                    if cls._is_ticker_in_cooldown(ticker):
                        logger.debug(
                            f"Skipping {ticker}: still in cooldown period "
                            f"({cls.ticker_cooldown_minutes} minutes after exit)"
                        )
                        continue

                    ticker_momentum_scores.append((ticker, momentum_score, reason))
                    logger.info(
                        f"{ticker} passed all filters: momentum={momentum_score:.2f}%, "
                        f"{filter_reason}"
                    )

                logger.info(
                    f"Calculated momentum scores for {len(ticker_momentum_scores)} tickers"
                )

                # Separate upward and downward momentum
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

                # Use MAB to select top-k tickers
                top_upward = await MABService.select_tickers_with_mab(
                    cls.indicator_name(),
                    ticker_candidates=upward_tickers,
                    market_data_dict=market_data_dict,
                    top_k=cls.top_k,
                )
                top_downward = await MABService.select_tickers_with_mab(
                    cls.indicator_name(),
                    ticker_candidates=downward_tickers,
                    market_data_dict=market_data_dict,
                    top_k=cls.top_k,
                )

                logger.info(
                    f"MAB selected {len(top_upward)} upward momentum tickers and "
                    f"{len(top_downward)} downward momentum tickers (top_k={cls.top_k})"
                )

                # Enter trades for upward momentum (long)
                for rank, (ticker, momentum_score, reason) in enumerate(
                    top_upward, start=1
                ):
                    if not cls.running:
                        break

                    if cls._has_reached_daily_trade_limit():
                        logger.info(
                            f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                            f"Skipping remaining candidates."
                        )
                        break

                    active_trades = await cls._get_active_trades()
                    active_count = len(active_trades)

                    if active_count >= cls.max_active_trades:
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

                    action = "buy_to_open"

                    quote_response = await MCPClient.get_quote(ticker)
                    if not quote_response:
                        logger.warning(f"Failed to get quote for {ticker}, skipping")
                        continue

                    quote_data = quote_response.get("quote", {})
                    quotes = quote_data.get("quotes", {})
                    ticker_quote = quotes.get(ticker, {})
                    enter_price = ticker_quote.get("ap", 0.0)

                    if enter_price <= 0:
                        logger.warning(
                            f"Failed to get valid quote price for {ticker}, skipping"
                        )
                        continue

                    ranked_reason = f"{reason} (ranked #{rank} upward momentum)"
                    await send_signal_to_webhook(
                        ticker=ticker,
                        action=action,
                        indicator=cls.indicator_name(),
                        enter_reason=ranked_reason,
                    )

                    technical_indicators = market_data_dict.get(ticker, {}).get(
                        "technical_analysis", {}
                    )
                    technical_indicators_for_enter = technical_indicators.copy()
                    if "datetime_price" in technical_indicators_for_enter:
                        technical_indicators_for_enter = {
                            k: v
                            for k, v in technical_indicators_for_enter.items()
                            if k != "datetime_price"
                        }

                    await cls._enter_trade(
                        ticker=ticker,
                        action=action,
                        enter_price=enter_price,
                        enter_reason=ranked_reason,
                        technical_indicators=technical_indicators_for_enter,
                    )

                # Enter trades for downward momentum (short)
                for rank, (ticker, momentum_score, reason) in enumerate(
                    top_downward, start=1
                ):
                    if not cls.running:
                        break

                    if cls._has_reached_daily_trade_limit():
                        logger.info(
                            f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                            f"Skipping remaining candidates."
                        )
                        break

                    active_trades = await cls._get_active_trades()
                    active_count = len(active_trades)

                    if active_count >= cls.max_active_trades:
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

                    action = "sell_to_open"

                    quote_response = await MCPClient.get_quote(ticker)
                    if not quote_response:
                        logger.warning(f"Failed to get quote for {ticker}, skipping")
                        continue

                    quote_data = quote_response.get("quote", {})
                    quotes = quote_data.get("quotes", {})
                    ticker_quote = quotes.get(ticker, {})
                    enter_price = ticker_quote.get("bp", 0.0)

                    if enter_price <= 0:
                        logger.warning(
                            f"Failed to get valid quote price for {ticker}, skipping"
                        )
                        continue

                    ranked_reason = f"{reason} (ranked #{rank} downward momentum)"
                    await send_signal_to_webhook(
                        ticker=ticker,
                        action=action,
                        indicator=cls.indicator_name(),
                        enter_reason=ranked_reason,
                    )

                    technical_indicators = market_data_dict.get(ticker, {}).get(
                        "technical_analysis", {}
                    )
                    technical_indicators_for_enter = technical_indicators.copy()
                    if "datetime_price" in technical_indicators_for_enter:
                        technical_indicators_for_enter = {
                            k: v
                            for k, v in technical_indicators_for_enter.items()
                            if k != "datetime_price"
                        }

                    await cls._enter_trade(
                        ticker=ticker,
                        action=action,
                        enter_price=enter_price,
                        enter_reason=ranked_reason,
                        technical_indicators=technical_indicators_for_enter,
                    )

                await asyncio.sleep(cls.entry_cycle_seconds)

            except Exception as e:
                logger.exception(f"Error in momentum entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    async def exit_service(cls):
        """Exit service - monitor trades and exit based on profitability"""
        logger.info("Momentum exit service started")
        while cls.running:
            try:
                if not await cls._check_market_open():
                    logger.debug("Market is closed, skipping momentum exit logic")
                    await asyncio.sleep(cls.exit_cycle_seconds)
                    continue

                active_trades = await cls._get_active_trades()

                if not active_trades:
                    logger.debug("No active momentum trades to monitor")
                    await asyncio.sleep(cls.exit_cycle_seconds)
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
                    trailing_stop = float(trade.get("trailing_stop", 0.5))
                    peak_profit_percent = float(trade.get("peak_profit_percent", 0.0))

                    if not ticker or enter_price is None or enter_price <= 0:
                        logger.warning(f"Invalid momentum trade data: {trade}")
                        continue

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

                    profit_percent = cls._calculate_profit_percent(
                        enter_price, current_price, original_action
                    )

                    should_exit = False
                    exit_reason = None

                    if profit_percent < cls.stop_loss_threshold:
                        should_exit = True
                        exit_reason = (
                            f"Trailing stop loss triggered: {profit_percent:.2f}% "
                            f"(below {cls.stop_loss_threshold}% stop loss threshold)"
                        )
                        logger.info(
                            f"Exit signal for {ticker} - losing trade: {profit_percent:.2f}%"
                        )

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

                    if not should_exit:
                        profit_target_to_exit = cls.profit_target_strong_momentum

                        is_profitable = profit_percent >= profit_target_to_exit
                        if is_profitable:
                            should_exit = True
                            exit_reason = (
                                f"Profit target reached: {profit_percent:.2f}% profit "
                                f"(target: {profit_target_to_exit:.2f}%)"
                            )

                    if not should_exit:
                        if profit_percent > peak_profit_percent:
                            peak_profit_percent = profit_percent
                            trailing_stop = cls.trailing_stop_percent

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
                            indicator=cls.indicator_name(),
                            trailing_stop=trailing_stop,
                            peak_profit_percent=peak_profit_percent,
                            skipped_exit_reason=skipped_reason,
                        )

                    if should_exit:
                        logger.info(
                            f"Exit signal for {ticker} "
                            f"(enter: {enter_price}, current: {current_price}, "
                            f"profit: {profit_percent:.2f}%)"
                        )

                        technical_indicators_for_enter = trade.get(
                            "technical_indicators_for_enter"
                        )
                        technical_indicators_for_exit = technical_analysis.copy()
                        if "datetime_price" in technical_indicators_for_exit:
                            technical_indicators_for_exit = {
                                k: v
                                for k, v in technical_indicators_for_exit.items()
                                if k != "datetime_price"
                            }

                        await cls._exit_trade(
                            ticker=ticker,
                            original_action=original_action,
                            enter_price=enter_price,
                            exit_price=current_price,
                            exit_reason=exit_reason,
                            technical_indicators_enter=technical_indicators_for_enter,
                            technical_indicators_exit=technical_indicators_for_exit,
                        )

                await asyncio.sleep(cls.exit_cycle_seconds)

            except Exception as e:
                logger.exception(f"Error in momentum exit service: {str(e)}")
                await asyncio.sleep(5)

