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
from app.src.services.trading.validation import (
    TrendAnalyzer,
    QuoteData,
    DataQualityRule,
    LiquidityRule,
    TrendDirectionRule,
    ContinuationRule,
    PriceExtremeRule,
    MomentumThresholdRule,
    RejectionCollector,
    InactiveTickerRepository
)


class PennyStocksIndicator(BaseTradingIndicator):
    """
    Penny stocks trading indicator for stocks < $5 USD

    TREND-FOLLOWING STRATEGY - Profit at any cost:
    - Enter LONG only if last few bars show clear UPWARD trend
    - Enter SHORT only if last few bars show clear DOWNWARD trend
    - Hold LONG until dip from peak (trend reversal) - then exit immediately
    - Hold SHORT until rise from bottom (trend reversal) - then exit immediately
    - Exit immediately if trade becomes unprofitable (enter_price > current_price for long, enter_price < current_price for short)
    - Losing tickers excluded from MAB for rest of day
    - Max 30 trades per day
    """

    # Configuration - HIGHLY SELECTIVE PENNY STOCK TRADING
    max_stock_price: float = 5.0  # Only trade stocks < $5
    min_stock_price: float = 0.01  # Minimum stock price (avoid extreme penny stocks)
    trailing_stop_percent: float = 0.5  # 0.5% trailing stop (TIGHT - exit quickly)
    profit_threshold: float = 0.5  # Exit at 0.5% profit (QUICK CASH IN)
    immediate_loss_exit_threshold: float = (
        -0.25
    )  # Exit immediately on -0.25% loss (CUT LOSSES FAST)
    top_k: int = 2  # Top K tickers to select
    min_momentum_threshold: float = 3.0  # INCREASED: Minimum 3% momentum to enter (STRONG TREND REQUIRED)
    max_momentum_threshold: float = 10.0  # DECREASED: Maximum 10% momentum (avoid entering near peaks/bottoms)
    exceptional_momentum_threshold: float = (
        8.0  # Exceptional momentum to trigger preemption
    )
    min_volume: int = 500  # Minimum daily volume (increased for liquidity)
    min_avg_volume: int = 1000  # Minimum average daily volume
    max_price_discrepancy_percent: float = (
        10.0  # Max % difference between quote and close price
    )
    max_bid_ask_spread_percent: float = 2.0  # Max bid-ask spread as % of price
    entry_cycle_seconds: int = 1  # Check for entries every 1 second (VERY FAST)
    exit_cycle_seconds: int = 1  # Check exits every 1 second (VERY FAST)
    max_active_trades: int = 10  # Increased for more concurrent trades
    max_daily_trades: int = 30  # Increased to 30 for quick profit trades
    min_holding_period_seconds: int = (
        15  # Minimum 15 seconds to avoid garbage trades (trend needs time to develop)
    )
    recent_bars_for_trend: int = 5  # Use last 5 bars to determine trend

    # Track losing tickers for the day (exclude from MAB)
    _losing_tickers_today: set = set()  # Tickers that showed loss today

    @classmethod
    def indicator_name(cls) -> str:
        return "Penny Stocks"

    @classmethod
    def _calculate_recent_trend(
        cls, bars: List[Dict[str, Any]]
    ) -> Tuple[float, str, Optional[float], Optional[float], float]:
        """
        Calculate trend from recent few bars only (simple and fast).
        Returns: (trend_score, reason, peak_price, bottom_price, recent_continuation)
        - trend_score > 0: trending up (for long entry)
        - trend_score < 0: trending down (for short entry)
        - peak_price: highest price in recent bars (for long exit)
        - bottom_price: lowest price in recent bars (for short exit)
        - recent_continuation: 0.0-1.0, how much the trend is continuing in most recent bars
        """
        if not bars or len(bars) < 3:
            return 0.0, "Insufficient bars data", None, None, 0.0

        # Extract close prices from recent bars only
        recent_bars = (
            bars[-cls.recent_bars_for_trend :]
            if len(bars) >= cls.recent_bars_for_trend
            else bars
        )
        prices = []
        for bar in recent_bars:
            try:
                close_price = bar.get("c")
                if close_price is not None:
                    prices.append(float(close_price))
            except (ValueError, TypeError):
                continue

        if len(prices) < 3:
            return 0.0, "Insufficient valid prices", None, None, 0.0

        # Find peak and bottom in recent bars
        peak_price = max(prices)
        bottom_price = min(prices)

        # Simple trend: compare first vs last price in recent bars
        first_price = prices[0]
        last_price = prices[-1]

        # Check if trend is consistent (most bars moving in same direction)
        price_changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        up_moves = sum(1 for change in price_changes if change > 0)
        down_moves = sum(1 for change in price_changes if change < 0)

        # Calculate momentum: 70% from overall change, 30% from consistency
        overall_change_percent = (
            ((last_price - first_price) / first_price) * 100 if first_price > 0 else 0
        )
        consistency_score = (
            ((up_moves - down_moves) / len(price_changes)) * 100 if price_changes else 0
        )

        # Only consider it a clear trend if most bars move in same direction
        momentum_score = (0.7 * overall_change_percent) + (0.3 * consistency_score)

        # Require STRONG clear trend: at least 70% of moves in same direction (INCREASED from 60%)
        trend_strength = (
            max(up_moves, down_moves) / len(price_changes) if price_changes else 0
        )
        if trend_strength < 0.7:
            momentum_score *= 0.3  # Heavily reduce score if trend is not clear (INCREASED penalty from 0.5)

        # Check if trend is still continuing (most recent bars should continue the trend)
        # For entry validation: we want to see the trend continuing, not ending
        recent_continuation = 0.0
        if len(prices) >= 3:
            # Check last 2-3 bars to see if trend is continuing
            last_3_prices = prices[-3:]
            if len(last_3_prices) >= 2:
                recent_changes = [
                    last_3_prices[i] - last_3_prices[i - 1]
                    for i in range(1, len(last_3_prices))
                ]
                if momentum_score > 0:  # Upward trend
                    # For upward trend, recent changes should be positive or at least not strongly negative
                    recent_continuation = (
                        sum(1 for c in recent_changes if c > 0) / len(recent_changes)
                        if recent_changes
                        else 0
                    )
                else:  # Downward trend
                    # For downward trend, recent changes should be negative or at least not strongly positive
                    recent_continuation = (
                        sum(1 for c in recent_changes if c < 0) / len(recent_changes)
                        if recent_changes
                        else 0
                    )

        reason = f"Recent trend ({len(recent_bars)} bars): {overall_change_percent:.2f}% change, {up_moves} up/{down_moves} down moves, peak=${peak_price:.4f}, bottom=${bottom_price:.4f}, continuation={recent_continuation:.2f}"
        return momentum_score, reason, peak_price, bottom_price, recent_continuation

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
    def _is_special_security(cls, ticker: str) -> bool:
        """Check if ticker is a special security (warrants, rights, units, etc.)"""
        special_suffixes = [".WS", ".RT", ".U", ".W", ".R", ".V"]
        return any(ticker.upper().endswith(suffix) for suffix in special_suffixes)

    @classmethod
    async def _validate_ticker_with_pipeline(
        cls,
        ticker: str,
        bars: List[Dict[str, Any]],
        quote_data: QuoteData,
        collector: RejectionCollector
    ) -> bool:
        """
        Validate ticker using the validation pipeline.
        
        Args:
            ticker: Stock ticker symbol
            bars: Historical price bars
            quote_data: Current quote data
            collector: RejectionCollector to accumulate rejections
            
        Returns:
            True if ticker passes all validation rules, False otherwise
        """
        # Calculate trend metrics
        trend_metrics = TrendAnalyzer.calculate_trend_metrics(bars)
        
        # Create validation rules
        rules = [
            DataQualityRule(required_bars=cls.recent_bars_for_trend),
            LiquidityRule(max_spread_percent=cls.max_bid_ask_spread_percent),
            TrendDirectionRule(),
            ContinuationRule(min_continuation=0.7),
            PriceExtremeRule(extreme_threshold_percent=1.0),
            MomentumThresholdRule(
                min_momentum=cls.min_momentum_threshold,
                max_momentum=cls.max_momentum_threshold
            )
        ]
        
        # Apply validation rules sequentially (early termination on first failure)
        for rule in rules:
            result = rule.validate(ticker, trend_metrics, quote_data, bars)
            
            if not result.passed:
                # Add rejection to collector
                technical_indicators = trend_metrics.to_dict() if trend_metrics else None
                
                collector.add_rejection(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    reason_long=result.reason_long,
                    reason_short=result.reason_short,
                    technical_indicators=technical_indicators
                )
                
                return False
        
        # All rules passed
        return True

    @classmethod
    async def _passes_filters(
        cls,
        ticker: str,
        bars_data: Optional[Dict[str, Any]],
        momentum_score: float,  # noqa: ARG002
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Check if ticker passes filters for entry.
        SIMPLIFIED - No complex technical analysis, just basic checks.
        Returns (passes, reason, reason_for_direction)
        - reason_for_direction is None for universal filters (apply to both long/short)
        - reason_for_direction is set for direction-specific filters (momentum-related)
        Note: momentum_score parameter kept for API compatibility but momentum is checked before calling this method
        """
        if not bars_data:
            return False, "No market data", None

        # Filter out special securities (warrants, rights, etc.)
        if cls._is_special_security(ticker):
            return False, f"Special security (warrants/rights): {ticker}", None

        bars_dict = bars_data.get("bars", {})
        ticker_bars = bars_dict.get(ticker, [])
        if not ticker_bars or len(ticker_bars) < cls.recent_bars_for_trend:
            return (
                False,
                f"Insufficient bars data (need {cls.recent_bars_for_trend}, got {len(ticker_bars)})",
                None,
            )

        # Get current price from quote
        quote_response = await AlpacaClient.quote(ticker)
        if not quote_response:
            return False, "Unable to get quote", None

        quote_data = quote_response.get("quote", {})
        quotes = quote_data.get("quotes", {})
        ticker_quote = quotes.get(ticker, {})

        bid = ticker_quote.get("bp", 0.0)
        ask = ticker_quote.get("ap", 0.0)

        if bid <= 0 or ask <= 0:
            return False, f"Invalid bid/ask: bid={bid}, ask={ask}", None

        # Use mid price
        current_price = (bid + ask) / 2.0

        # Check bid-ask spread
        spread = ask - bid
        spread_percent = (spread / current_price) * 100 if current_price > 0 else 100
        if spread_percent > cls.max_bid_ask_spread_percent:
            return (
                False,
                f"Bid-ask spread too wide: {spread_percent:.2f}% > {cls.max_bid_ask_spread_percent}%",
                None,
            )

        # Check price range
        if current_price < cls.min_stock_price:
            return (
                False,
                f"Price too low: ${current_price:.2f} < ${cls.min_stock_price:.2f}",
                None,
            )
        if current_price >= cls.max_stock_price:
            return (
                False,
                f"Price too high: ${current_price:.2f} >= ${cls.max_stock_price:.2f}",
                None,
            )

        # Validate quote price vs close price from bars
        latest_bar = ticker_bars[-1]
        close_price = latest_bar.get("c", 0.0)
        if close_price > 0:
            price_discrepancy = abs(current_price - close_price) / close_price * 100
            if price_discrepancy > cls.max_price_discrepancy_percent:
                return (
                    False,
                    f"Price discrepancy too large: quote=${current_price:.4f} vs close=${close_price:.4f} ({price_discrepancy:.2f}%)",
                    None,
                )

        # Note: Momentum is already checked before calling this method, so we skip it here
        # to avoid redundant checks and ensure consistent direction-specific logging

        # Check volume - use recent bars only (simplified)
        recent_volumes = [
            bar.get("v", 0) for bar in ticker_bars[-cls.recent_bars_for_trend :]
        ]
        total_volume = sum(recent_volumes)
        avg_volume = total_volume / len(recent_volumes) if recent_volumes else 0

        # More lenient volume check for penny stocks (they're volatile, we want to trade them)
        if total_volume < cls.min_volume * 0.5:  # 50% of normal requirement
            return (
                False,
                f"Volume too low: {total_volume} < {cls.min_volume * 0.5}",
                None,
            )

        # Skip avg_volume check - penny stocks are volatile, we bank on that

        return True, "Passed all filters (trend-based strategy)", None

    @classmethod
    async def entry_service(cls):
        """Entry service - analyze momentum and enter trades (runs every 1 second)"""
        logger.info("Penny Stocks entry service started (FAST MODE: 1 second cycles)")
        while cls.running:
            try:
                await cls._run_entry_cycle()
            except Exception as e:
                logger.exception(f"Error in penny stocks entry service: {str(e)}")
                await asyncio.sleep(1)  # Fast retry on error

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

        # Reset losing tickers list at start of new day (when daily stats reset)
        # Check if we're in a new day by checking if daily_trades_date changed
        from datetime import date

        today = date.today().isoformat()
        if (
            not hasattr(cls, "_losing_tickers_date")
            or cls._losing_tickers_date != today
        ):
            cls._losing_tickers_today = set()
            cls._losing_tickers_date = today
            logger.info("🔄 Reset losing tickers list for new trading day")

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
            await asyncio.sleep(cls.entry_cycle_seconds)  # Use configured cycle time
            return

        active_trades = await cls._get_active_trades()
        active_count = len(active_trades)
        active_ticker_set = await cls._get_active_ticker_set()

        logger.info(f"Current active trades: {active_count}/{cls.max_active_trades}")

        # Filter out active tickers, those in cooldown, special securities, and losing tickers from today
        candidates_to_fetch = [
            ticker
            for ticker in all_tickers
            if ticker not in active_ticker_set
            and not cls._is_ticker_in_cooldown(ticker)
            and not cls._is_special_security(ticker)
            and ticker
            not in cls._losing_tickers_today  # Exclude tickers that showed loss today
        ]

        if cls._losing_tickers_today:
            logger.info(
                f"Excluding {len(cls._losing_tickers_today)} losing tickers from today's selection: "
                f"{list(cls._losing_tickers_today)[:10]}"  # Show first 10
            )

        special_securities_count = sum(
            1 for ticker in all_tickers if cls._is_special_security(ticker)
        )
        if special_securities_count > 0:
            logger.debug(
                f"Filtered out {special_securities_count} special securities (warrants/rights)"
            )

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

        logger.debug(
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

        # Process results using validation pipeline
        ticker_momentum_scores = []
        stats = {
            "no_market_data": 0,
            "insufficient_bars": 0,
            "low_momentum": 0,
            "failed_filters": 0,
            "passed": 0,
        }

        # Initialize rejection collector for batch writing
        rejection_collector = RejectionCollector()

        for ticker in candidates_to_fetch:
            if not cls.running:
                break

            bars_data = market_data_dict.get(ticker)
            if not bars_data:
                stats["no_market_data"] += 1
                continue

            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])
            
            # Get current quote for validation
            current_quote = await AlpacaClient.quote(ticker)
            if not current_quote:
                stats["no_market_data"] += 1
                continue
                
            quote_data_obj = current_quote.get("quote", {})
            quotes = quote_data_obj.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})
            bid = ticker_quote.get("bp", 0.0)
            ask = ticker_quote.get("ap", 0.0)
            
            # Create QuoteData object
            quote = QuoteData.from_bid_ask(ticker, bid, ask)
            
            # Validate using pipeline
            passed = await cls._validate_ticker_with_pipeline(
                ticker, ticker_bars, quote, rejection_collector
            )
            
            if not passed:
                stats["failed_filters"] += 1
                continue
            
            # Calculate trend metrics for passing tickers
            trend_metrics = TrendAnalyzer.calculate_trend_metrics(ticker_bars)
            momentum_score = trend_metrics.momentum_score
            reason = trend_metrics.reason
            
            stats["passed"] += 1
            ticker_momentum_scores.append((ticker, momentum_score, reason))
            logger.info(
                f"{ticker} passed all filters: momentum={momentum_score:.2f}%"
            )

        # Batch write all rejection records using repository
        if rejection_collector.has_records():
            logger.debug(f"Writing {rejection_collector.count()} rejection records to DynamoDB")
            
            repository = InactiveTickerRepository()
            records = rejection_collector.get_records()
            
            try:
                success = await repository.batch_write_rejections(records)
                if success:
                    logger.info(f"Successfully wrote {len(records)} rejection records")
                else:
                    logger.warning(f"Some rejection records failed to write")
            except Exception as e:
                logger.error(f"Error writing rejection records: {str(e)}")

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

        # Filter out losing tickers from MAB candidates
        upward_tickers_filtered = [
            (t, s, r)
            for t, s, r in upward_tickers
            if t not in cls._losing_tickers_today
        ]
        downward_tickers_filtered = [
            (t, s, r)
            for t, s, r in downward_tickers
            if t not in cls._losing_tickers_today
        ]

        if len(upward_tickers) != len(upward_tickers_filtered) or len(
            downward_tickers
        ) != len(downward_tickers_filtered):
            excluded_count = (len(upward_tickers) - len(upward_tickers_filtered)) + (
                len(downward_tickers) - len(downward_tickers_filtered)
            )
            logger.info(
                f"Excluded {excluded_count} losing tickers from MAB selection "
                f"(upward: {len(upward_tickers_filtered)}/{len(upward_tickers)}, "
                f"downward: {len(downward_tickers_filtered)}/{len(downward_tickers)})"
            )

        top_upward = await MABService.select_tickers_with_mab(
            cls.indicator_name(),
            ticker_candidates=upward_tickers_filtered,
            market_data_dict=market_data_for_mab,
            top_k=cls.top_k,
        )
        top_downward = await MABService.select_tickers_with_mab(
            cls.indicator_name(),
            ticker_candidates=downward_tickers_filtered,
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
            
            # Convert Decimal to float if needed (DynamoDB returns Decimal)
            if enter_price is not None:
                enter_price = float(enter_price)

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
        
        # Convert Decimal to float if needed (DynamoDB returns Decimal)
        if enter_price is not None:
            enter_price = float(enter_price)

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

        bid = ticker_quote.get("bp", 0.0)
        ask = ticker_quote.get("ap", 0.0)

        if bid <= 0 or ask <= 0:
            logger.warning(
                f"Invalid bid/ask for {ticker}: bid={bid}, ask={ask}, skipping"
            )
            return False

        # Check bid-ask spread before entry
        mid_price = (bid + ask) / 2.0
        spread = ask - bid
        spread_percent = (spread / mid_price) * 100 if mid_price > 0 else 100
        if spread_percent > cls.max_bid_ask_spread_percent:
            logger.warning(
                f"Skipping {ticker}: bid-ask spread too wide: {spread_percent:.2f}% > {cls.max_bid_ask_spread_percent}%"
            )
            return False

        is_long = action == "buy_to_open"
        enter_price = ask if is_long else bid

        if enter_price <= 0:
            logger.warning(f"Invalid entry price for {ticker}, skipping")
            return False

        logger.debug(
            f"Entry price for {ticker}: ${enter_price:.4f} (bid=${bid:.4f}, ask=${ask:.4f}, spread={spread_percent:.2f}%)"
        )

        # Verify price is still in valid range
        if enter_price < cls.min_stock_price:
            logger.info(
                f"Skipping {ticker}: entry price ${enter_price:.2f} < ${cls.min_stock_price:.2f}"
            )
            return False
        if enter_price >= cls.max_stock_price:
            logger.info(
                f"Skipping {ticker}: entry price ${enter_price:.2f} >= ${cls.max_stock_price:.2f}"
            )
            return False

        # Validate entry price matches latest bar close price
        bars_data = market_data_dict.get(ticker)
        if bars_data:
            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])
            if ticker_bars:
                latest_bar = ticker_bars[-1]
                close_price = latest_bar.get("c", 0.0)
                if close_price > 0:
                    price_discrepancy = (
                        abs(enter_price - close_price) / close_price * 100
                    )
                    if price_discrepancy > cls.max_price_discrepancy_percent:
                        logger.warning(
                            f"Skipping {ticker}: entry price ${enter_price:.4f} differs from close ${close_price:.4f} "
                            f"by {price_discrepancy:.2f}% (max: {cls.max_price_discrepancy_percent}%)"
                        )
                        return False

        # Prepare entry data
        direction = "upward" if is_long else "downward"
        ranked_reason = f"{reason} (ranked #{rank} {direction} momentum)"

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

        await send_signal_to_webhook(
            ticker=ticker,
            action=action,
            indicator=cls.indicator_name(),
            enter_reason=ranked_reason,
            enter_price=enter_price,
            technical_indicators=technical_indicators,
        )

        # Enter trade with tight 0.5% trailing stop (AGGRESSIVE)
        entry_success = await cls._enter_trade(
            ticker=ticker,
            action=action,
            enter_price=enter_price,
            enter_reason=ranked_reason,
            technical_indicators=technical_indicators,
            dynamic_stop_loss=-cls.trailing_stop_percent,  # 0.5% stop loss (tight)
        )

        if not entry_success:
            logger.error(f"Failed to enter trade for {ticker}")
            return False

        # Update trailing stop to 0.5% after entry (TIGHT for quick exits)
        await DynamoDBClient.update_momentum_trade_trailing_stop(
            ticker=ticker,
            indicator=cls.indicator_name(),
            trailing_stop=cls.trailing_stop_percent,
            peak_profit_percent=0.0,
            current_profit_percent=0.0,
        )

        logger.info(
            f"✅ Entered {ticker} {action} at ${enter_price:.4f} "
            f"(quick exit: {cls.profit_threshold:.2f}% profit, "
            f"immediate loss exit: {cls.immediate_loss_exit_threshold:.2f}%)"
        )

        return True

    @classmethod
    async def exit_service(cls):
        """Exit service - monitor trades and exit based on profitability (runs every 1 second)"""
        logger.info("Penny Stocks exit service started (FAST MODE: 1 second cycles)")
        while cls.running:
            try:
                await cls._run_exit_cycle()
            except Exception as e:
                logger.exception(f"Error in penny stocks exit service: {str(e)}")
                await asyncio.sleep(1)  # Fast retry on error

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

        # Filter trades that haven't passed minimum holding period
        trades_to_process = []
        for trade in active_trades:
            created_at = trade.get("created_at")
            if created_at:
                try:
                    from datetime import datetime, timezone

                    enter_time = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    if enter_time.tzinfo is None:
                        enter_time = enter_time.replace(tzinfo=timezone.utc)
                    current_time = datetime.now(timezone.utc)
                    holding_period_seconds = (current_time - enter_time).total_seconds()

                    if holding_period_seconds < cls.min_holding_period_seconds:
                        ticker = trade.get("ticker")
                        logger.debug(
                            f"Skipping {ticker}: holding period {holding_period_seconds:.1f}s < "
                            f"minimum {cls.min_holding_period_seconds}s"
                        )
                        continue
                except Exception as e:
                    logger.debug(f"Error checking holding period: {str(e)}")
                    # Continue on error
            trades_to_process.append(trade)

        if not trades_to_process:
            logger.debug("No trades passed minimum holding period")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        for trade in trades_to_process:
            if not cls.running:
                break

            ticker = trade.get("ticker")
            original_action = trade.get("action")
            enter_price = trade.get("enter_price")
            
            # Convert Decimal to float if needed (DynamoDB returns Decimal)
            if enter_price is not None:
                enter_price = float(enter_price)
            
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

            # Get latest bars for trend check (simple - no complex technical analysis)
            bars_data = await AlpacaClient.get_market_data(
                ticker, limit=cls.recent_bars_for_trend + 5
            )
            technical_indicators = {}
            if bars_data:
                bars_dict = bars_data.get("bars", {})
                ticker_bars = bars_dict.get(ticker, [])
                if ticker_bars:
                    latest_bar = ticker_bars[-1]
                    # Simple indicators - just price and volume
                    technical_indicators = {
                        "close_price": latest_bar.get("c", 0.0),
                        "volume": latest_bar.get("v", 0),
                    }

            profit_percent = cls._calculate_profit_percent(
                enter_price, current_price, original_action
            )

            should_exit = False
            exit_reason = None
            is_long = original_action == "buy_to_open"

            # Get recent bars for peak/bottom tracking
            bars_data_for_exit = await AlpacaClient.get_market_data(
                ticker, limit=cls.recent_bars_for_trend + 10
            )
            
            # Track peak price (for long) and bottom price (for short) since entry
            peak_price_since_entry = None
            bottom_price_since_entry = None
            
            if bars_data_for_exit:
                bars_dict = bars_data_for_exit.get("bars", {})
                ticker_bars = bars_dict.get(ticker, [])
                if ticker_bars:
                    # Get all prices since entry to find peak/bottom
                    prices_since_entry = [bar.get("c", 0.0) for bar in ticker_bars if bar.get("c", 0.0) > 0]
                    if prices_since_entry:
                        peak_price_since_entry = max(prices_since_entry)
                        bottom_price_since_entry = min(prices_since_entry)

            # PRIORITY 1: Exit on profitable trend reversal (BOOK PROFIT QUICKLY)
            # This is the PRIMARY exit strategy - get in and out with profit
            if is_long:
                # For LONG: Exit if price starts dipping from peak
                # Strategy: Enter on upward momentum, exit as soon as it dips from peak
                if peak_price_since_entry and peak_price_since_entry > enter_price:
                    # We have a peak above entry price (we're in profit territory)
                    # Check if current price is dipping from that peak
                    dip_from_peak_percent = ((current_price - peak_price_since_entry) / peak_price_since_entry) * 100
                    
                    # Exit if price has dipped by 0.3% or more from peak
                    if dip_from_peak_percent <= -0.3:
                        should_exit = True
                        profit_from_entry = ((current_price - enter_price) / enter_price) * 100
                        exit_reason = (
                            f"Dip from peak (LONG): peak ${peak_price_since_entry:.4f} → current ${current_price:.4f} "
                            f"(dip: {dip_from_peak_percent:.2f}%, profit from entry: {profit_from_entry:.2f}%)"
                        )
                        logger.info(f"💰 PROFIT EXIT for {ticker} - {exit_reason}")
            else:
                # For SHORT: Exit if price starts rising from bottom
                # Strategy: Enter on downward momentum, exit as soon as it rises from bottom
                if bottom_price_since_entry and bottom_price_since_entry < enter_price:
                    # We have a bottom below entry price (we're in profit territory)
                    # Check if current price is rising from that bottom
                    rise_from_bottom_percent = ((current_price - bottom_price_since_entry) / bottom_price_since_entry) * 100
                    
                    # Exit if price has risen by 0.3% or more from bottom
                    if rise_from_bottom_percent >= 0.3:
                        should_exit = True
                        profit_from_entry = ((enter_price - current_price) / enter_price) * 100
                        exit_reason = (
                            f"Rise from bottom (SHORT): bottom ${bottom_price_since_entry:.4f} → current ${current_price:.4f} "
                            f"(rise: {rise_from_bottom_percent:.2f}%, profit from entry: {profit_from_entry:.2f}%)"
                        )
                        logger.info(f"💰 PROFIT EXIT for {ticker} - {exit_reason}")

            # PRIORITY 2: Exit if trade becomes unprofitable (CUT LOSSES)
            if not should_exit:
                if is_long:
                    # For long: exit if current_price < enter_price (unprofitable)
                    if current_price < enter_price:
                        should_exit = True
                        exit_reason = (
                            f"Unprofitable exit (LONG): current ${current_price:.4f} < enter ${enter_price:.4f} "
                            f"(loss: {profit_percent:.2f}%)"
                        )
                        logger.warning(
                            f"🚨 LOSS EXIT for {ticker} LONG - unprofitable: {profit_percent:.2f}%"
                        )
                        cls._losing_tickers_today.add(ticker)
                else:
                    # For short: exit if current_price > enter_price (unprofitable)
                    if current_price > enter_price:
                        should_exit = True
                        exit_reason = (
                            f"Unprofitable exit (SHORT): current ${current_price:.4f} > enter ${enter_price:.4f} "
                            f"(loss: {profit_percent:.2f}%)"
                        )
                        logger.warning(
                            f"🚨 LOSS EXIT for {ticker} SHORT - unprofitable: {profit_percent:.2f}%"
                        )
                        cls._losing_tickers_today.add(ticker)

            # PRIORITY 3: Exit on significant loss (SAFETY NET)
            if not should_exit and profit_percent < cls.immediate_loss_exit_threshold:
                should_exit = True
                exit_reason = (
                    f"Significant loss exit: {profit_percent:.2f}% loss "
                    f"(below {cls.immediate_loss_exit_threshold:.2f}% threshold)"
                )
                logger.warning(
                    f"🚨 LOSS EXIT for {ticker} - loss: {profit_percent:.2f}%"
                )
                cls._losing_tickers_today.add(ticker)

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

                # Record trade outcome for MAB
                final_profit_percent = cls._calculate_profit_percent(
                    enter_price, exit_price, original_action
                )

                # If trade ended in loss, mark ticker as losing for today
                if final_profit_percent < 0:
                    cls._losing_tickers_today.add(ticker)
                    logger.warning(
                        f"📛 Marked {ticker} as losing ticker (final profit: {final_profit_percent:.2f}%) - "
                        f"excluded from MAB selection for rest of day"
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
