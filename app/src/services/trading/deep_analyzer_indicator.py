"""
Deep Analyzer Trading Indicator
Uses MarketDataService for deep technical analysis to identify entry and exit signals
"""

import asyncio
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, date, timezone

from app.src.common.loguru_logger import logger
from app.src.common.utils import measure_latency
from app.src.services.mcp.mcp_client import MCPClient
from app.src.services.market_data.market_data_service import MarketDataService
from app.src.services.mab.mab_service import MABService
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator


class DeepAnalyzerIndicator(BaseTradingIndicator):
    """Deep Analyzer trading indicator using MarketDataService"""

    # Deep Analyzer specific configuration
    top_k: int = 2
    min_entry_score: float = 0.70  # Minimum entry score from MarketDataService

    @classmethod
    def indicator_name(cls) -> str:
        return "Deep Analyzer"

    @classmethod
    async def _evaluate_ticker_for_entry(
        cls, ticker: str, market_data: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        """
        Evaluate ticker for entry using MarketDataService
        Returns: (action, signal_data, reason) or (None, None, reason) if no entry
        """
        try:
            # Evaluate for long entry (buy_to_open)
            long_result = await MarketDataService.enter_trade(
                ticker=ticker,
                action="buy_to_open",
                market_data=market_data,
            )

            # Evaluate for short entry (sell_to_open)
            short_result = await MarketDataService.enter_trade(
                ticker=ticker,
                action="sell_to_open",
                market_data=market_data,
            )

            long_enter = long_result.get("enter", False)
            short_enter = short_result.get("enter", False)

            long_score = (
                long_result.get("signal", {}).get("entry_score", 0.0)
                if long_enter
                else 0.0
            )
            short_score = (
                short_result.get("signal", {}).get("entry_score", 0.0)
                if short_enter
                else 0.0
            )

            # Choose the better signal
            if long_enter and short_enter:
                if long_score >= short_score:
                    return (
                        "buy_to_open",
                        long_result.get("signal"),
                        f"Long entry (score: {long_score:.2f})",
                    )
                else:
                    return (
                        "sell_to_open",
                        short_result.get("signal"),
                        f"Short entry (score: {short_score:.2f})",
                    )
            elif long_enter:
                return (
                    "buy_to_open",
                    long_result.get("signal"),
                    f"Long entry (score: {long_score:.2f})",
                )
            elif short_enter:
                return (
                    "sell_to_open",
                    short_result.get("signal"),
                    f"Short entry (score: {short_score:.2f})",
                )
            else:
                # Check which one had a higher score even if not entering
                long_analysis = long_result.get("analysis", {})
                short_analysis = short_result.get("analysis", {})
                long_analysis_score = long_analysis.get("entry_score", 0.0)
                short_analysis_score = short_analysis.get("entry_score", 0.0)

                if long_analysis_score > short_analysis_score:
                    reason = long_result.get("message", "No entry signal")
                    logger.debug(
                        f"{ticker} no entry: long_score={long_analysis_score:.2f}, "
                        f"short_score={short_analysis_score:.2f}, reason={reason}"
                    )
                else:
                    reason = short_result.get("message", "No entry signal")
                    logger.debug(
                        f"{ticker} no entry: long_score={long_analysis_score:.2f}, "
                        f"short_score={short_analysis_score:.2f}, reason={reason}"
                    )

                return None, None, reason

        except Exception as e:
            logger.error(f"Error evaluating {ticker} for entry: {str(e)}")
            return None, None, f"Error: {str(e)}"

    @classmethod
    async def _evaluate_ticker_for_exit(
        cls,
        ticker: str,
        enter_price: float,
        action: str,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Evaluate ticker for exit using MarketDataService
        Returns: (should_exit, exit_reason, exit_data)
        """
        try:
            # Convert action to exit action
            if action == "buy_to_open":
                exit_action = "SELL_TO_CLOSE"
            elif action == "sell_to_open":
                exit_action = "BUY_TO_CLOSE"
            else:
                return False, None, None

            exit_result = await MarketDataService.exit_trade(
                ticker=ticker,
                enter_price=enter_price,
                action=exit_action,
            )

            if exit_result.get("error", False):
                logger.warning(
                    f"Error in exit evaluation for {ticker}: {exit_result.get('reason', 'Unknown error')}"
                )
                return False, None, None

            exit_decision = exit_result.get("exit_decision", False)
            exit_reason = exit_result.get("reason", "")

            return exit_decision, exit_reason, exit_result

        except Exception as e:
            logger.error(f"Error evaluating {ticker} for exit: {str(e)}")
            return False, None, None

    @classmethod
    async def entry_service(cls):
        """Entry service - analyze using MarketDataService and enter trades"""
        logger.info("Deep Analyzer entry service started")
        while cls.running:
            try:
                await cls._run_entry_cycle()
            except Exception as e:
                logger.exception(f"Error in Deep Analyzer entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    @measure_latency
    async def _run_entry_cycle(cls):
        """Execute a single Deep Analyzer entry cycle."""
        logger.debug("Starting Deep Analyzer entry cycle")
        # Check market open
        if not await cls._check_market_open():
            logger.debug("Market is closed, skipping Deep Analyzer entry logic")
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        logger.info("Market is open, proceeding with Deep Analyzer entry logic")

        # Reset daily stats if needed
        await cls._reset_daily_stats_if_needed()

        # Check daily trade limit
        if cls._has_reached_daily_trade_limit():
            logger.info(
                f"Daily trade limit reached: {cls.daily_trades_count}/{cls.max_daily_trades}. "
                "Skipping entry logic this cycle."
            )
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        # Get screened tickers
        all_tickers = await cls._get_screened_tickers()
        if not all_tickers:
            logger.warning("Failed to get screened tickers, skipping this cycle")
            await asyncio.sleep(2)
            return

        # Get active trades
        active_trades = await cls._get_active_trades()
        active_count = len(active_trades)
        active_ticker_set = await cls._get_active_ticker_set()

        logger.info(f"Current active trades: {active_count}/{cls.max_active_trades}")

        # Filter out tickers that are already active or in cooldown before fetching market data
        candidates_to_fetch = [
            ticker
            for ticker in all_tickers
            if ticker not in active_ticker_set
            and not cls._is_ticker_in_cooldown(ticker)
        ]

        logger.info(
            f"Fetching market data for {len(candidates_to_fetch)} tickers in parallel batches"
        )

        # Fetch market data in parallel batches
        market_data_dict = await cls._fetch_market_data_batch(
            candidates_to_fetch, max_concurrent=10
        )

        # Evaluate all tickers for entry
        ticker_candidates = (
            []
        )  # List of (ticker, entry_score, action, signal_data, reason)

        stats = {
            "no_market_data": 0,
            "no_entry_signal": 0,
            "low_entry_score": 0,
            "passed": 0,
        }

        for ticker in candidates_to_fetch:
            if not cls.running:
                break

            market_data_response = market_data_dict.get(ticker)
            if not market_data_response:
                stats["no_market_data"] += 1
                await DynamoDBClient.log_inactive_ticker_reason(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    reason_not_to_enter_long="No market data response",
                    reason_not_to_enter_short="No market data response",
                )
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})

            # Evaluate for entry
            action, signal_data, reason = await cls._evaluate_ticker_for_entry(
                ticker, market_data_response
            )

            if action and signal_data:
                entry_score = signal_data.get("entry_score", 0.0)
                if entry_score >= cls.min_entry_score:
                    stats["passed"] += 1
                    ticker_candidates.append(
                        (ticker, entry_score, action, signal_data, reason)
                    )
                    logger.info(
                        f"{ticker} passed Deep Analyzer filters: {action} "
                        f"(score: {entry_score:.2f}, {reason})"
                    )
                else:
                    stats["low_entry_score"] += 1
                    logger.debug(
                        f"Skipping {ticker}: entry score {entry_score:.2f} < "
                        f"minimum {cls.min_entry_score}"
                    )
                    # Log reason based on action
                    if action == "buy_to_open":
                        reason_long = f"Entry score {entry_score:.2f} < minimum {cls.min_entry_score}"
                        reason_short = None
                    else:  # sell_to_open
                        reason_long = None
                        reason_short = f"Entry score {entry_score:.2f} < minimum {cls.min_entry_score}"
                    
                    await DynamoDBClient.log_inactive_ticker_reason(
                        ticker=ticker,
                        indicator=cls.indicator_name(),
                        reason_not_to_enter_long=reason_long,
                        reason_not_to_enter_short=reason_short,
                        technical_indicators=technical_analysis,
                    )
            else:
                stats["no_entry_signal"] += 1
                logger.debug(f"Skipping {ticker}: {reason}")
                
                # Get detailed reasons for both long and short
                long_result = await MarketDataService.enter_trade(
                    ticker=ticker,
                    action="buy_to_open",
                    market_data=market_data_response,
                )
                short_result = await MarketDataService.enter_trade(
                    ticker=ticker,
                    action="sell_to_open",
                    market_data=market_data_response,
                )
                
                long_enter = long_result.get("enter", False)
                short_enter = short_result.get("enter", False)
                
                reason_long = None
                reason_short = None
                
                if not long_enter:
                    reason_long = long_result.get("message", "No entry signal")
                if not short_enter:
                    reason_short = short_result.get("message", "No entry signal")
                
                await DynamoDBClient.log_inactive_ticker_reason(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    reason_not_to_enter_long=reason_long,
                    reason_not_to_enter_short=reason_short,
                    technical_indicators=technical_analysis,
                )

        logger.info(
            f"Evaluated {len(ticker_candidates)} tickers with valid entry signals "
            f"(filtered: {stats['no_market_data']} no data, "
            f"{stats['no_entry_signal']} no entry signal, "
            f"{stats['low_entry_score']} low entry score < {cls.min_entry_score})"
        )

        # Separate long and short candidates
        long_candidates = [
            (t, score, action, signal, reason)
            for t, score, action, signal, reason in ticker_candidates
            if action == "buy_to_open"
        ]
        short_candidates = [
            (t, score, action, signal, reason)
            for t, score, action, signal, reason in ticker_candidates
            if action == "sell_to_open"
        ]

        # Use MAB to select top-k tickers from each direction
        # Convert to format expected by MAB: (ticker, score, reason)
        long_mab_candidates = [
            (t, score, reason) for t, score, _, _, reason in long_candidates
        ]
        short_mab_candidates = [
            (t, score, reason) for t, score, _, _, reason in short_candidates
        ]

        top_long = await MABService.select_tickers_with_mab(
            cls.indicator_name(),
            ticker_candidates=long_mab_candidates,
            market_data_dict=market_data_dict,
            top_k=cls.top_k,
        )
        top_short = await MABService.select_tickers_with_mab(
            cls.indicator_name(),
            ticker_candidates=short_mab_candidates,
            market_data_dict=market_data_dict,
            top_k=cls.top_k,
        )

        logger.info(
            f"MAB selected {len(top_long)} long Deep Analyzer tickers and "
            f"{len(top_short)} short Deep Analyzer tickers (top_k={cls.top_k})"
        )

        # Create lookup for signal data
        long_signal_lookup = {
            t: (signal, reason) for t, _, _, signal, reason in long_candidates
        }
        short_signal_lookup = {
            t: (signal, reason) for t, _, _, signal, reason in short_candidates
        }

        # Enter trades for long candidates
        for rank, (ticker, entry_score, _) in enumerate(top_long, start=1):
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
                logger.info(
                    f"At max capacity ({active_count}/{cls.max_active_trades}), "
                    f"skipping {ticker} (entry score: {entry_score:.2f})"
                )
                continue

            action = "buy_to_open"
            signal_data, reason = long_signal_lookup.get(ticker, (None, ""))

            # Get quote for ask price (buy price)
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

            ranked_reason = (
                f"{reason} (ranked #{rank} long, entry_score: {entry_score:.2f})"
            )
            is_golden = signal_data.get("is_golden", False) if signal_data else False
            portfolio_allocation = (
                signal_data.get("portfolio_allocation", None) if signal_data else None
            )

            from app.src.services.webhook.send_signal import send_signal_to_webhook

            await send_signal_to_webhook(
                ticker=ticker,
                action=action,
                indicator=cls.indicator_name(),
                enter_reason=ranked_reason,
                is_golden_exception=is_golden,
                portfolio_allocation_percent=portfolio_allocation,
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

        # Enter trades for short candidates
        for rank, (ticker, entry_score, _) in enumerate(top_short, start=1):
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
                logger.info(
                    f"At max capacity ({active_count}/{cls.max_active_trades}), "
                    f"skipping {ticker} (entry score: {entry_score:.2f})"
                )
                continue

            action = "sell_to_open"
            signal_data, reason = short_signal_lookup.get(ticker, (None, ""))

            # Get quote for bid price (sell price)
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

            ranked_reason = (
                f"{reason} (ranked #{rank} short, entry_score: {entry_score:.2f})"
            )
            is_golden = signal_data.get("is_golden", False) if signal_data else False
            portfolio_allocation = (
                signal_data.get("portfolio_allocation", None) if signal_data else None
            )

            from app.src.services.webhook.send_signal import send_signal_to_webhook

            await send_signal_to_webhook(
                ticker=ticker,
                action=action,
                indicator=cls.indicator_name(),
                enter_reason=ranked_reason,
                is_golden_exception=is_golden,
                portfolio_allocation_percent=portfolio_allocation,
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

    @classmethod
    async def exit_service(cls):
        """Exit service - monitor trades and exit using MarketDataService"""
        logger.info("Deep Analyzer exit service started")
        while cls.running:
            try:
                await cls._run_exit_cycle()
            except Exception as e:
                logger.exception(f"Error in Deep Analyzer exit service: {str(e)}")
                await asyncio.sleep(5)

    @classmethod
    @measure_latency
    async def _run_exit_cycle(cls):
        """Execute a single Deep Analyzer exit monitoring cycle."""
        if not await cls._check_market_open():
            logger.debug("Market is closed, skipping Deep Analyzer exit logic")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_trades = await cls._get_active_trades()

        if not active_trades:
            logger.debug("No active Deep Analyzer trades to monitor")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_count = len(active_trades)
        logger.info(
            f"Monitoring {active_count}/{cls.max_active_trades} active Deep Analyzer trades"
        )

        for trade in active_trades:
            if not cls.running:
                break

            ticker = trade.get("ticker")
            original_action = trade.get("action")
            enter_price = trade.get("enter_price")

            if not ticker or enter_price is None or enter_price <= 0:
                logger.warning(f"Invalid Deep Analyzer trade data: {trade}")
                continue

            # Evaluate for exit using MarketDataService
            should_exit, exit_reason, exit_data = await cls._evaluate_ticker_for_exit(
                ticker=ticker,
                enter_price=enter_price,
                action=original_action,
            )

            if should_exit:
                # Get current price from exit_data
                exit_price = exit_data.get("current_price", 0.0) if exit_data else 0.0

                if exit_price <= 0:
                    # Fallback: get current price from market data
                    market_data_response = await MCPClient.get_market_data(ticker)
                    if market_data_response:
                        technical_analysis = market_data_response.get(
                            "technical_analysis", {}
                        )
                        exit_price = technical_analysis.get("close_price", 0.0)

                if exit_price <= 0:
                    logger.warning(f"Failed to get valid exit price for {ticker}")
                    continue

                logger.info(
                    f"Exit signal for {ticker} - {exit_reason} "
                    f"(enter: {enter_price}, exit: {exit_price})"
                )

                # Get technical indicators for exit
                technical_indicators_for_enter = trade.get(
                    "technical_indicators_for_enter"
                )

                technical_indicators_for_exit = None
                if exit_data:
                    # Extract indicators from exit_data if available
                    indicators = exit_data.get("indicators", {})
                    if indicators:
                        technical_indicators_for_exit = indicators

                if not technical_indicators_for_exit:
                    # Fallback: get from market data
                    market_data_response = await MCPClient.get_market_data(ticker)
                    if market_data_response:
                        technical_analysis = market_data_response.get(
                            "technical_analysis", {}
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
                    exit_price=exit_price,
                    exit_reason=exit_reason or "MarketDataService exit signal",
                    technical_indicators_enter=technical_indicators_for_enter,
                    technical_indicators_exit=technical_indicators_for_exit,
                )

        await asyncio.sleep(cls.exit_cycle_seconds)
