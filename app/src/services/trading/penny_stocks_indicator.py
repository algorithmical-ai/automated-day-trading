"""
Penny Stocks Trading Indicator
Trades stocks valued less than $5 USD using momentum-based entry and exit
"""

import asyncio
from typing import List, Tuple, Dict, Any, Optional

from app.src.common.loguru_logger import logger
from app.src.common.utils import measure_latency
from app.src.common.alpaca import AlpacaClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator


class PennyStocksIndicator(BaseTradingIndicator):
    """Penny stocks trading indicator for stocks < $5 USD"""

    # Configuration
    max_stock_price: float = 5.0  # Only trade stocks < $5
    min_stock_price: float = 0.10  # Minimum stock price
    trailing_stop_percent: float = 4.0  # 4% trailing stop loss
    profit_threshold: float = 1.0  # Minimum profit to exit
    top_k: int = 2  # Top K tickers to select
    min_momentum_threshold: float = 1.5  # Minimum momentum to enter
    max_momentum_threshold: float = 15.0  # Maximum momentum (avoid peaks)
    exceptional_momentum_threshold: float = (
        8.0  # Exceptional momentum to trigger preemption
    )
    min_volume: int = 1000  # Minimum daily volume
    entry_cycle_seconds: int = 5
    exit_cycle_seconds: int = 5
    max_active_trades: int = 5
    max_daily_trades: int = 10

    @classmethod
    def indicator_name(cls) -> str:
        return "Penny Stocks"

    @classmethod
    def _calculate_momentum(cls, bars: List[Dict[str, Any]]) -> Tuple[float, str]:
        """Calculate price momentum score from bars data"""
        if not bars or len(bars) < 3:
            return 0.0, "Insufficient bars data"

        # Extract close prices
        prices = []
        for bar in bars:
            try:
                close_price = bar.get("c")
                if close_price is not None:
                    prices.append(float(close_price))
            except (ValueError, TypeError):
                continue

        if len(prices) < 3:
            return 0.0, "Insufficient valid prices"

        n = len(prices)
        early_count = max(1, n // 3)
        recent_count = max(1, n // 3)

        early_prices = prices[:early_count]
        recent_prices = prices[-recent_count:]

        early_avg = sum(early_prices) / len(early_prices)
        recent_avg = sum(recent_prices) / len(recent_prices)

        change_percent = (
            ((recent_avg - early_avg) / early_avg) * 100 if early_avg > 0 else 0
        )

        recent_trend = sum(
            (recent_prices[i] - recent_prices[i - 1])
            for i in range(1, len(recent_prices))
        ) / max(1, len(recent_prices) - 1)

        trend_percent = (recent_trend / early_avg) * 100 if early_avg > 0 else 0
        momentum_score = (0.7 * change_percent) + (0.3 * trend_percent)

        reason = f"Momentum: {change_percent:.2f}% change, {trend_percent:.2f}% trend"
        return momentum_score, reason

    @classmethod
    async def _get_ticker_price(cls, ticker: str) -> Optional[float]:
        """Get current price for a ticker"""
        quote_response = await AlpacaClient.quote(ticker)
        if not quote_response:
            return None

        quote_data = quote_response.get("quote", {})
        quotes = quote_data.get("quotes", {})
        ticker_quote = quotes.get(ticker, {})

        # Use mid price (average of bid and ask)
        bid = ticker_quote.get("bp", 0.0)
        ask = ticker_quote.get("ap", 0.0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        elif ask > 0:
            return ask
        elif bid > 0:
            return bid
        return None

    @classmethod
    async def _fetch_market_data_batch(
        cls, tickers: List[str], max_concurrent: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch market data for multiple tickers using Alpaca API.
        Returns dict mapping ticker -> bars data
        """
        if not tickers:
            return {}

        async def fetch_one(ticker: str) -> Tuple[str, Any]:
            """Fetch market data for a single ticker"""
            try:
                bars_data = await AlpacaClient.get_market_data(ticker, limit=200)
                return (ticker, bars_data)
            except Exception as e:
                logger.debug(f"Failed to get market data for {ticker}: {str(e)}")
                return (ticker, None)

        # Process in batches
        results: Dict[str, Any] = {}
        for i in range(0, len(tickers), max_concurrent):
            batch = tickers[i : i + max_concurrent]
            batch_results = await asyncio.gather(
                *[fetch_one(ticker) for ticker in batch], return_exceptions=True
            )
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.debug(f"Exception in batch fetch: {str(result)}")
                    continue
                if isinstance(result, tuple) and len(result) == 2:
                    ticker, bars_data = result
                    results[ticker] = bars_data

        return results

    @classmethod
    async def _passes_filters(
        cls, ticker: str, bars_data: Optional[Dict[str, Any]], momentum_score: float
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Check if ticker passes filters for entry.
        Returns (passes, reason, reason_for_long/short)
        """
        if not bars_data:
            return False, "No market data", None

        bars_dict = bars_data.get("bars", {})
        ticker_bars = bars_dict.get(ticker, [])
        if not ticker_bars or len(ticker_bars) < 10:
            return False, "Insufficient bars data", None

        # Get current price
        current_price = await cls._get_ticker_price(ticker)
        if current_price is None or current_price <= 0:
            return False, "Unable to get current price", None

        # Check price range
        if current_price < cls.min_stock_price:
            return False, f"Price too low: ${current_price:.2f}", None
        if current_price >= cls.max_stock_price:
            return (
                False,
                f"Price too high: ${current_price:.2f} >= ${cls.max_stock_price:.2f}",
                None,
            )

        # Check momentum
        abs_momentum = abs(momentum_score)
        if abs_momentum < cls.min_momentum_threshold:
            reason = f"Momentum {momentum_score:.2f}% < minimum {cls.min_momentum_threshold}%"
            if momentum_score > 0:
                return False, reason, reason
            else:
                return False, reason, None
        if abs_momentum > cls.max_momentum_threshold:
            reason = f"Momentum {momentum_score:.2f}% > maximum {cls.max_momentum_threshold}% (likely at peak)"
            if momentum_score > 0:
                return False, reason, reason
            else:
                return False, reason, None

        # Check volume
        total_volume = sum(bar.get("v", 0) for bar in ticker_bars[-20:])  # Last 20 bars
        if total_volume < cls.min_volume:
            return False, f"Volume too low: {total_volume} < {cls.min_volume}", None

        return True, "Passed all filters", None

    @classmethod
    async def entry_service(cls):
        """Entry service - analyze momentum and enter trades"""
        logger.info("Penny Stocks entry service started")
        while cls.running:
            try:
                await cls._run_entry_cycle()
            except Exception as e:
                logger.exception(f"Error in penny stocks entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    @measure_latency
    async def _run_entry_cycle(cls):
        """Execute a single penny stocks entry cycle"""
        logger.debug("Starting penny stocks entry cycle")
        if not await AlpacaClient.is_market_open():
            logger.debug("Market is closed, skipping penny stocks entry logic")
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        logger.info("Market is open, proceeding with penny stocks entry logic")

        await cls._reset_daily_stats_if_needed()

        # Check daily limit
        daily_limit_reached = await cls._has_reached_daily_trade_limit()
        if daily_limit_reached:
            logger.info(
                f"Daily trade limit reached: {cls.daily_trades_count}/{cls.max_daily_trades}"
            )
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        # Get screened tickers
        all_tickers = await cls._get_screened_tickers()
        if not all_tickers:
            logger.warning("Failed to get screened tickers, skipping this cycle")
            await asyncio.sleep(2)
            return

        active_trades = await cls._get_active_trades()
        active_count = len(active_trades)
        active_ticker_set = await cls._get_active_ticker_set()

        logger.info(f"Current active trades: {active_count}/{cls.max_active_trades}")

        # Filter out active tickers and those in cooldown
        candidates_to_fetch = [
            ticker
            for ticker in all_tickers
            if ticker not in active_ticker_set
            and not cls._is_ticker_in_cooldown(ticker)
        ]

        # Filter out stocks >= $5 USD using quote() before fetching market data
        logger.info(
            f"Filtering {len(candidates_to_fetch)} candidates by price (< ${cls.max_stock_price:.2f})"
        )

        async def check_price(ticker: str) -> Tuple[str, Optional[float]]:
            """Get price for a ticker"""
            try:
                price = await cls._get_ticker_price(ticker)
                return (ticker, price)
            except Exception as e:
                logger.debug(f"Error getting price for {ticker}: {e}")
                return (ticker, None)

        # Get prices for all candidates in parallel
        price_results = await asyncio.gather(
            *[check_price(ticker) for ticker in candidates_to_fetch],
            return_exceptions=True,
        )

        # Filter to only include stocks < $5 USD
        penny_stock_candidates = []
        price_filtered_count = 0
        for result in price_results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, tuple) and len(result) == 2:
                ticker, price = result
                if price is None:
                    price_filtered_count += 1
                    continue
                if price < cls.max_stock_price:
                    penny_stock_candidates.append(ticker)
                else:
                    price_filtered_count += 1
                    logger.debug(
                        f"Filtered out {ticker}: price ${price:.2f} >= ${cls.max_stock_price:.2f}"
                    )

        candidates_to_fetch = penny_stock_candidates

        logger.info(
            f"Price filtering: {len(candidates_to_fetch)} penny stocks (< ${cls.max_stock_price:.2f}), "
            f"{price_filtered_count} filtered out (>= ${cls.max_stock_price:.2f} or no price data)"
        )

        logger.info(
            f"Fetching market data for {len(candidates_to_fetch)} penny stock tickers in parallel batches"
        )

        # Fetch market data using Alpaca API
        market_data_dict = await cls._fetch_market_data_batch(
            candidates_to_fetch, max_concurrent=25
        )

        # Process results
        ticker_momentum_scores = []
        stats = {
            "no_market_data": 0,
            "insufficient_bars": 0,
            "low_momentum": 0,
            "failed_filters": 0,
            "passed": 0,
        }

        # Collect inactive ticker reasons for batch writing
        inactive_ticker_logs = []

        for ticker in candidates_to_fetch:
            if not cls.running:
                break

            bars_data = market_data_dict.get(ticker)
            if not bars_data:
                stats["no_market_data"] += 1
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": "No market data response",
                        "reason_not_to_enter_short": "No market data response",
                        "technical_indicators": None,
                    }
                )
                continue

            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])
            if not ticker_bars or len(ticker_bars) < 10:
                stats["insufficient_bars"] += 1
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": "Insufficient bars data",
                        "reason_not_to_enter_short": "Insufficient bars data",
                        "technical_indicators": None,
                    }
                )
                continue

            # Calculate momentum
            momentum_score, reason = cls._calculate_momentum(ticker_bars)

            abs_momentum = abs(momentum_score)
            if abs_momentum < cls.min_momentum_threshold:
                stats["low_momentum"] += 1
                reason_text = f"Momentum {momentum_score:.2f}% < minimum threshold {cls.min_momentum_threshold}%"
                if momentum_score > 0:
                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": reason_text,
                            "reason_not_to_enter_short": None,
                            "technical_indicators": None,
                        }
                    )
                else:
                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": None,
                            "reason_not_to_enter_short": reason_text,
                            "technical_indicators": None,
                        }
                    )
                continue

            if abs_momentum > cls.max_momentum_threshold:
                stats["low_momentum"] += 1
                reason_text = f"Momentum {momentum_score:.2f}% > maximum threshold {cls.max_momentum_threshold}% (likely at peak)"
                if momentum_score > 0:
                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": reason_text,
                            "reason_not_to_enter_short": None,
                            "technical_indicators": None,
                        }
                    )
                else:
                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": None,
                            "reason_not_to_enter_short": reason_text,
                            "technical_indicators": None,
                        }
                    )
                continue

            # Check filters
            passes, filter_reason, reason_for_direction = await cls._passes_filters(
                ticker, bars_data, momentum_score
            )
            if not passes:
                stats["failed_filters"] += 1
                if momentum_score > 0:
                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": filter_reason,
                            "reason_not_to_enter_short": None,
                            "technical_indicators": None,
                        }
                    )
                else:
                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": None,
                            "reason_not_to_enter_short": filter_reason,
                            "technical_indicators": None,
                        }
                    )
                continue

            stats["passed"] += 1
            ticker_momentum_scores.append((ticker, momentum_score, reason))
            logger.info(
                f"{ticker} passed all filters: momentum={momentum_score:.2f}%, {filter_reason}"
            )

        # Batch write all inactive ticker reasons
        if inactive_ticker_logs:

            async def log_one(log_data):
                await DynamoDBClient.log_inactive_ticker_reason(**log_data)

            batch_size = 20
            for i in range(0, len(inactive_ticker_logs), batch_size):
                batch = inactive_ticker_logs[i : i + batch_size]
                await asyncio.gather(
                    *[log_one(log_data) for log_data in batch], return_exceptions=True
                )

        logger.info(
            f"Calculated momentum scores for {len(ticker_momentum_scores)} tickers "
            f"(filtered: {stats['no_market_data']} no data, "
            f"{stats['insufficient_bars']} insufficient bars, "
            f"{stats['low_momentum']} low momentum, "
            f"{stats['failed_filters']} failed filters)"
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

        # Use MAB to select top tickers
        # For penny stocks, we'll use a simplified market data dict
        market_data_for_mab = {}
        for ticker, _, _ in ticker_momentum_scores:
            bars_data = market_data_dict.get(ticker)
            if bars_data:
                # Create a simplified market_data structure for MAB
                bars_dict = bars_data.get("bars", {})
                ticker_bars = bars_dict.get(ticker, [])
                if ticker_bars:
                    latest_bar = ticker_bars[-1]
                    market_data_for_mab[ticker] = {
                        "technical_analysis": {
                            "close_price": latest_bar.get("c", 0.0),
                            "volume": latest_bar.get("v", 0),
                        }
                    }

        top_upward = await MABService.select_tickers_with_mab(
            cls.indicator_name(),
            ticker_candidates=upward_tickers,
            market_data_dict=market_data_for_mab,
            top_k=cls.top_k,
        )
        top_downward = await MABService.select_tickers_with_mab(
            cls.indicator_name(),
            ticker_candidates=downward_tickers,
            market_data_dict=market_data_for_mab,
            top_k=cls.top_k,
        )

        logger.info(
            f"MAB selected {len(top_upward)} upward momentum tickers and "
            f"{len(top_downward)} downward momentum tickers (top_k={cls.top_k})"
        )

        # Process long entries
        for rank, (ticker, momentum_score, reason) in enumerate(top_upward, start=1):
            if not cls.running:
                break

            await cls._process_ticker_entry(
                ticker=ticker,
                momentum_score=momentum_score,
                reason=reason,
                rank=rank,
                action="buy_to_open",
                market_data_dict=market_data_dict,
                daily_limit_reached=daily_limit_reached,
                is_golden=False,
            )

        # Process short entries
        for rank, (ticker, momentum_score, reason) in enumerate(top_downward, start=1):
            if not cls.running:
                break

            await cls._process_ticker_entry(
                ticker=ticker,
                momentum_score=momentum_score,
                reason=reason,
                rank=rank,
                action="sell_to_open",
                market_data_dict=market_data_dict,
                daily_limit_reached=daily_limit_reached,
                is_golden=False,
            )

        await asyncio.sleep(cls.entry_cycle_seconds)

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

            # Get current price using AlpacaClient.quote()
            current_price = await cls._get_current_price(ticker, action)
            if current_price is None or current_price <= 0:
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

        # Get latest bars for technical indicators
        bars_data = await AlpacaClient.get_market_data(ticker_to_exit, limit=200)
        technical_indicators = {}
        if bars_data:
            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker_to_exit, [])
            if ticker_bars:
                latest_bar = ticker_bars[-1]
                technical_indicators = {
                    "close_price": latest_bar.get("c", 0.0),
                    "volume": latest_bar.get("v", 0),
                }

        # Get latest quote right before exit using Alpaca API
        exit_price = await cls._get_current_price(ticker_to_exit, original_action)
        if exit_price is None or exit_price <= 0:
            logger.warning(
                f"Failed to get exit quote for {ticker_to_exit} for preemption"
            )
            return False

        reason = f"Preempted for exceptional trade: {lowest_profit:.2f}% profit"

        technical_indicators_for_enter = lowest_trade.get(
            "technical_indicators_for_enter"
        )

        await cls._exit_trade(
            ticker=ticker_to_exit,
            original_action=original_action,
            enter_price=enter_price,
            exit_price=exit_price,
            exit_reason=reason,
            technical_indicators_enter=technical_indicators_for_enter,
            technical_indicators_exit=technical_indicators,
        )

        return True

    @classmethod
    async def _process_ticker_entry(
        cls,
        ticker: str,
        momentum_score: float,
        reason: str,
        rank: int,
        action: str,
        market_data_dict: Dict[str, Any],
        daily_limit_reached: bool,
        is_golden: bool,
    ) -> bool:
        """Process entry for a single ticker"""
        if not cls.running:
            return False

        # Check active trades capacity
        active_trades = await cls._get_active_trades()
        active_count = len(active_trades)

        if active_count >= cls.max_active_trades:
            # Check if this is an exceptional momentum trade
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
                    logger.info(f"Could not preempt for {ticker}, skipping entry")
                    return False

                # Re-check after preemption
                active_trades = await cls._get_active_trades()
                active_count = len(active_trades)
                if active_count >= cls.max_active_trades:
                    logger.warning(
                        f"Still at max capacity ({active_count}/{cls.max_active_trades}) after preemption for {ticker}. "
                        f"This may indicate a race condition or concurrent entry."
                    )
                    # Still proceed with entry attempt - _enter_trade will handle duplicates
            else:
                logger.info(
                    f"At max capacity ({active_count}/{cls.max_active_trades}), "
                    f"skipping {ticker} (momentum: {momentum_score:.2f} < "
                    f"exceptional threshold: {cls.exceptional_momentum_threshold})"
                )
                return False

        # Get entry price using Alpaca API
        quote_response = await AlpacaClient.quote(ticker)
        if not quote_response:
            logger.warning(f"Failed to get quote for {ticker}, skipping")
            return False

        quote_data = quote_response.get("quote", {})
        quotes = quote_data.get("quotes", {})
        ticker_quote = quotes.get(ticker, {})

        is_long = action == "buy_to_open"
        enter_price = (
            ticker_quote.get("ap", 0.0) if is_long else ticker_quote.get("bp", 0.0)
        )

        if enter_price <= 0:
            logger.warning(f"Invalid entry price for {ticker}, skipping")
            return False

        logger.debug(f"Entry price for {ticker}: ${enter_price:.4f}")

        # Verify price is still < $5
        if enter_price >= cls.max_stock_price:
            logger.info(
                f"Skipping {ticker}: entry price ${enter_price:.2f} >= ${cls.max_stock_price:.2f}"
            )
            return False

        # Prepare entry data
        direction = "upward" if is_long else "downward"
        ranked_reason = f"{reason} (ranked #{rank} {direction} momentum)"

        await send_signal_to_webhook(
            ticker=ticker,
            action=action,
            indicator=cls.indicator_name(),
            enter_reason=ranked_reason,
        )

        # Get bars data for technical indicators
        bars_data = market_data_dict.get(ticker)
        technical_indicators = {}
        if bars_data:
            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])
            if ticker_bars:
                latest_bar = ticker_bars[-1]
                technical_indicators = {
                    "close_price": latest_bar.get("c", 0.0),
                    "volume": latest_bar.get("v", 0),
                    "high": latest_bar.get("h", 0.0),
                    "low": latest_bar.get("l", 0.0),
                    "open": latest_bar.get("o", 0.0),
                }

        # Enter trade with 4% trailing stop
        entry_success = await cls._enter_trade(
            ticker=ticker,
            action=action,
            enter_price=enter_price,
            enter_reason=ranked_reason,
            technical_indicators=technical_indicators,
            dynamic_stop_loss=-cls.trailing_stop_percent,  # 4% stop loss
        )

        if not entry_success:
            logger.error(f"Failed to enter trade for {ticker}")
            return False

        # Update trailing stop to 4% after entry (default is 0.5%)
        await DynamoDBClient.update_momentum_trade_trailing_stop(
            ticker=ticker,
            indicator=cls.indicator_name(),
            trailing_stop=cls.trailing_stop_percent,
            peak_profit_percent=0.0,
            current_profit_percent=0.0,
        )

        return True

    @classmethod
    async def exit_service(cls):
        """Exit service - monitor trades and exit based on profitability"""
        logger.info("Penny Stocks exit service started")
        while cls.running:
            try:
                await cls._run_exit_cycle()
            except Exception as e:
                logger.exception(f"Error in penny stocks exit service: {str(e)}")
                await asyncio.sleep(5)

    @classmethod
    async def _get_current_price(cls, ticker: str, action: str) -> Optional[float]:
        """Get current price for exit decision using Alpaca API"""
        quote_response = await AlpacaClient.quote(ticker)
        if not quote_response:
            return None

        quote_data = quote_response.get("quote", {})
        quotes = quote_data.get("quotes", {})
        ticker_quote = quotes.get(ticker, {})

        is_long = action == "buy_to_open"
        if is_long:
            return ticker_quote.get("bp", 0.0)  # Bid price for long exit
        else:
            return ticker_quote.get("ap", 0.0)  # Ask price for short exit

    @classmethod
    @measure_latency
    async def _run_exit_cycle(cls):
        """Execute a single penny stocks exit monitoring cycle"""
        if not await AlpacaClient.is_market_open():
            logger.debug("Market is closed, skipping penny stocks exit logic")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_trades = await cls._get_active_trades()
        if not active_trades:
            logger.debug("No active penny stocks trades to monitor")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_count = len(active_trades)
        logger.info(
            f"Monitoring {active_count}/{cls.max_active_trades} active penny stocks trades"
        )

        for trade in active_trades:
            if not cls.running:
                break

            ticker = trade.get("ticker")
            original_action = trade.get("action")
            enter_price = trade.get("enter_price")
            # Default to 4% trailing stop if not set
            trailing_stop = float(trade.get("trailing_stop", cls.trailing_stop_percent))
            if trailing_stop <= 0 or trailing_stop > 10:  # Sanity check
                trailing_stop = cls.trailing_stop_percent
            peak_profit_percent = float(trade.get("peak_profit_percent", 0.0))
            current_profit_percent = float(trade.get("current_profit_percent", 0.0))

            if not ticker or enter_price is None or enter_price <= 0:
                logger.warning(f"Invalid penny stocks trade data: {trade}")
                continue

            # Get current price using Alpaca API
            current_price = await cls._get_current_price(ticker, original_action)
            if current_price is None or current_price <= 0:
                logger.warning(
                    f"Failed to get quote for {ticker} - will retry in next cycle"
                )
                continue

            logger.debug(f"Current price for {ticker}: ${current_price:.4f}")

            # Get latest bars for momentum check
            bars_data = await AlpacaClient.get_market_data(ticker, limit=200)
            technical_indicators = {}
            if bars_data:
                bars_dict = bars_data.get("bars", {})
                ticker_bars = bars_dict.get(ticker, [])
                if ticker_bars:
                    latest_bar = ticker_bars[-1]
                    technical_indicators = {
                        "close_price": latest_bar.get("c", 0.0),
                        "volume": latest_bar.get("v", 0),
                    }

            profit_percent = cls._calculate_profit_percent(
                enter_price, current_price, original_action
            )

            should_exit = False
            exit_reason = None

            # Check stop loss (4% trailing stop)
            stop_loss_threshold = -trailing_stop
            if profit_percent < stop_loss_threshold:
                should_exit = True
                exit_reason = (
                    f"Stop loss triggered: {profit_percent:.2f}% "
                    f"(below {stop_loss_threshold:.2f}% stop loss threshold)"
                )
                logger.info(
                    f"Exit signal for {ticker} - stop loss: {profit_percent:.2f}%"
                )

            # Check trailing stop
            if not should_exit and peak_profit_percent > 0:
                drop_from_peak = peak_profit_percent - profit_percent
                if drop_from_peak >= trailing_stop and profit_percent > 0:
                    should_exit = True
                    exit_reason = (
                        f"Trailing stop triggered: profit dropped {drop_from_peak:.2f}% "
                        f"from peak of {peak_profit_percent:.2f}% (current: {profit_percent:.2f}%, "
                        f"trailing stop: {trailing_stop:.2f}%)"
                    )
                    logger.info(f"Exit signal for {ticker} - {exit_reason}")

            # Check profit target
            if not should_exit and profit_percent >= cls.profit_threshold:
                should_exit = True
                exit_reason = (
                    f"Profit target reached: {profit_percent:.2f}% profit "
                    f"(target: {cls.profit_threshold:.2f}%)"
                )
                logger.info(f"Exit signal for {ticker} - {exit_reason}")

            if not should_exit:
                # Update peak profit and current profit in database
                new_peak = max(peak_profit_percent, profit_percent)
                await DynamoDBClient.update_momentum_trade_trailing_stop(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    trailing_stop=trailing_stop,
                    peak_profit_percent=new_peak,
                    current_profit_percent=profit_percent,
                    skipped_exit_reason=f"Trade profitable: {profit_percent:.2f}%",
                )
                continue

            if should_exit:
                logger.info(
                    f"Exit signal for {ticker} "
                    f"(enter: {enter_price}, current: {current_price}, "
                    f"profit: {profit_percent:.2f}%)"
                )

                # Get latest quote right before exit
                exit_price = await cls._get_current_price(ticker, original_action)
                if exit_price is None or exit_price <= 0:
                    exit_price = current_price  # Fallback
                    logger.warning(
                        f"Failed to get exit quote for {ticker}, using current price ${current_price:.4f}"
                    )
                else:
                    logger.debug(f"Exit price for {ticker}: ${exit_price:.4f}")

                # Get technical indicators for enter (from trade data)
                technical_indicators_enter = trade.get(
                    "technical_indicators_for_enter", {}
                )

                await cls._exit_trade(
                    ticker=ticker,
                    original_action=original_action,
                    enter_price=enter_price,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    technical_indicators_enter=technical_indicators_enter,
                    technical_indicators_exit=technical_indicators,
                )

        await asyncio.sleep(cls.exit_cycle_seconds)
