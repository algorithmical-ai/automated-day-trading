"""
Penny Stocks Trading Indicator
Trades stocks valued less than $5 USD using momentum-based entry and exit

IMPROVED ALGORITHM (Dec 2024):
- Accounts for bid-ask spread in breakeven calculations
- Uses ATR-based stop losses with sensible bounds (-1.5% to -4%)
- Tiered trailing stops that tighten as profit grows
- 60-second minimum holding period (up from 15s)
- Consecutive check requirement before stop loss exit
- Better momentum confirmation for entries
"""

import asyncio
from datetime import datetime, timezone
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
    RejectionCollector,
    InactiveTickerRepository
)
from app.src.services.trading.penny_stock_utils import (
    SpreadCalculator,
    ATRCalculator,
    TieredTrailingStop,
    ExitDecisionEngine,
    ExitDecision,
    DailyPerformanceMetrics,
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

    # Configuration - CONSERVATIVE PENNY STOCK TRADING (Dec 2024)
    # After massive losses, tightening all parameters significantly
    max_stock_price: float = 5.0  # Only trade stocks < $5
    min_stock_price: float = 0.50  # INCREASED: Avoid ultra-low penny stocks (was 0.01)
    
    # TIGHT STOPS - penny stocks are too volatile for wide stops
    trailing_stop_percent: float = 0.5  # Base trailing stop (used by tiered system)
    profit_threshold: float = 1.0  # Exit at 1% profit
    immediate_loss_exit_threshold: float = -1.5  # TIGHTENED: Emergency stop at -1.5% (was -3.0%)
    default_atr_stop_percent: float = -1.5  # TIGHTENED: Default ATR-based stop loss (was -2.0%)
    
    top_k: int = 1  # REDUCED: Only top 1 ticker to reduce exposure (was 2)
    min_momentum_threshold: float = 5.0  # INCREASED: Minimum 5% momentum to enter (was 3.0%)
    max_momentum_threshold: float = 15.0  # Maximum 15% momentum
    exceptional_momentum_threshold: float = 10.0  # INCREASED: Exceptional momentum for preemption (was 8.0%)
    
    min_volume: int = 1000  # INCREASED: Minimum daily volume (was 500)
    min_avg_volume: int = 2000  # INCREASED: Minimum average daily volume (was 1000)
    max_price_discrepancy_percent: float = 3.0  # TIGHTENED: Max % difference (was 5.0%)
    max_bid_ask_spread_percent: float = 1.5  # TIGHTENED: Max bid-ask spread (was 2.0%)
    
    # SAFETY: Disable shorting for penny stocks - too risky (can spike 100%+ in minutes)
    allow_short_positions: bool = False
    
    entry_cycle_seconds: int = 1  # Check for entries every 1 second
    exit_cycle_seconds: int = 1  # Check exits every 1 second
    max_active_trades: int = 3  # REDUCED: Max concurrent trades (was 10) - less exposure
    max_daily_trades: int = 10  # REDUCED: Max trades per day (was 30)
    
    # SHORTER holding period - exit faster on losses
    min_holding_period_seconds: int = 15  # REDUCED: from 60 to 15 seconds - exit faster
    recent_bars_for_trend: int = 5  # Use last 5 bars to determine trend
    
    # ATR configuration for volatility-based stops - TIGHTENED
    atr_period: int = 14  # Period for ATR calculation
    atr_multiplier: float = 1.0  # REDUCED: ATR multiplier (was 1.5)
    atr_stop_min: float = -1.0  # TIGHTENED: Minimum stop loss (was -1.5%)
    atr_stop_max: float = -2.0  # TIGHTENED: Maximum stop loss (was -4.0%)

    # Track losing tickers for the day (exclude from MAB)
    _losing_tickers_today: set = set()  # Tickers that showed loss today
    
    # Exit decision engine instance (shared across exit cycles)
    _exit_engine: Optional[ExitDecisionEngine] = None
    
    # Daily performance metrics
    _daily_metrics: Optional[DailyPerformanceMetrics] = None

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
        Validate ticker using SIMPLIFIED validation for penny stocks.
        
        PHILOSOPHY: Alpaca's gainers/most_actives ARE the momentum signal.
        We trust that signal and only do minimal validation:
        1. Have at least 3 bars (minimal data quality)
        2. Valid bid/ask spread (can actually trade)
        
        We DON'T over-filter with:
        - Complex momentum thresholds (Alpaca already screened for momentum)
        - Continuation scores (too restrictive for volatile penny stocks)
        - Price extreme rules (penny stocks are volatile by nature)
        
        Args:
            ticker: Stock ticker symbol
            bars: Historical price bars
            quote_data: Current quote data
            collector: RejectionCollector to accumulate rejections
            
        Returns:
            True if ticker passes validation, False otherwise
        """
        # Calculate trend metrics for logging purposes
        trend_metrics = TrendAnalyzer.calculate_trend_metrics(bars)
        
        # SIMPLIFIED VALIDATION - Only essential checks
        
        # 1. Minimal data quality - need at least 3 bars to calculate any trend
        MIN_BARS_REQUIRED = 3
        if not bars or len(bars) < MIN_BARS_REQUIRED:
            reason = f"Insufficient bars data (need {MIN_BARS_REQUIRED}, got {len(bars) if bars else 0})"
            collector.add_rejection(
                ticker=ticker,
                indicator=cls.indicator_name(),
                reason_long=reason,
                reason_short=reason,
                technical_indicators=trend_metrics.to_dict() if trend_metrics else None
            )
            return False
        
        # 2. Valid bid/ask - must be able to actually trade
        if quote_data.bid <= 0 or quote_data.ask <= 0:
            reason = f"Invalid bid/ask: bid={quote_data.bid}, ask={quote_data.ask}"
            collector.add_rejection(
                ticker=ticker,
                indicator=cls.indicator_name(),
                reason_long=reason,
                reason_short=reason,
                technical_indicators=trend_metrics.to_dict() if trend_metrics else None
            )
            return False
        
        # 3. Spread check - but be lenient for penny stocks (they're volatile)
        MAX_SPREAD_FOR_PENNY = 5.0  # Allow up to 5% spread for penny stocks
        if quote_data.spread_percent > MAX_SPREAD_FOR_PENNY:
            reason = f"Bid-ask spread too wide: {quote_data.spread_percent:.2f}% > {MAX_SPREAD_FOR_PENNY}%"
            collector.add_rejection(
                ticker=ticker,
                indicator=cls.indicator_name(),
                reason_long=reason,
                reason_short=reason,
                technical_indicators=trend_metrics.to_dict() if trend_metrics else None
            )
            return False
        
        # PASSED - Trust Alpaca's gainer/most_active signal
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
            
            # SIMPLIFIED: Accept any momentum - Alpaca already screened these as gainers/most_actives
            # Even if our calculated momentum is 0, Alpaca identified this as a mover
            # Use a small positive/negative value if momentum is exactly 0 to indicate direction
            if momentum_score == 0.0 and ticker_bars:
                # Determine direction from price change
                first_price = ticker_bars[0].get("c", 0)
                last_price = ticker_bars[-1].get("c", 0)
                if first_price > 0 and last_price > 0:
                    price_change = ((last_price - first_price) / first_price) * 100
                    momentum_score = price_change if price_change != 0 else 0.1  # Default to slight positive
                    reason = f"Price change: {price_change:.2f}% (Alpaca gainer signal)"
                else:
                    momentum_score = 0.1  # Default to slight positive for Alpaca gainers
                    reason = "Alpaca gainer signal (insufficient price data for momentum calc)"
            
            stats["passed"] += 1
            ticker_momentum_scores.append((ticker, momentum_score, reason))
            logger.debug(
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
                    logger.debug(f"Successfully wrote {len(records)} rejection records")
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
        # RESTORED: Require minimum momentum threshold to filter out weak signals
        # The 0.01% threshold was too permissive and led to many losing trades
        MIN_MOMENTUM_FOR_ENTRY = cls.min_momentum_threshold  # Use class config (3.0%)
        
        upward_tickers = [
            (t, score, reason)
            for t, score, reason in ticker_momentum_scores
            if score >= MIN_MOMENTUM_FOR_ENTRY  # Require meaningful upward momentum
        ]
        downward_tickers = [
            (t, score, reason)
            for t, score, reason in ticker_momentum_scores
            if score <= -MIN_MOMENTUM_FOR_ENTRY  # Require meaningful downward momentum
        ]
        
        logger.info(
            f"Momentum split: {len(upward_tickers)} upward, {len(downward_tickers)} downward "
            f"(from {len(ticker_momentum_scores)} total candidates)"
        )

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

        # Use MAB to select top tickers (don't filter out losing tickers - allow re-entry with good momentum)
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

        # Log MAB-rejected tickers (passed validation but not selected by MAB)
        selected_tickers_list = [t[0] for t in top_upward] + [t[0] for t in top_downward]
        
        # Get rejection reasons for all rejected tickers
        all_candidates = upward_tickers + downward_tickers
        rejected_info = await MABService.get_rejected_tickers_with_reasons(
            indicator=cls.indicator_name(),
            ticker_candidates=all_candidates,
            selected_tickers=selected_tickers_list
        )
        
        if rejected_info:
            logger.debug(f"Logging {len(rejected_info)} tickers rejected by MAB to InactiveTickersForDayTrading")
            for ticker, rejection_data in rejected_info.items():
                try:
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
                                "momentum_score": rejection_data.get('momentum_score', 0.0),
                            }
                    
                    reason_long = rejection_data.get('reason_long', '')
                    reason_short = rejection_data.get('reason_short', '')
                    
                    # Enhanced: If no MAB reasons, generate enhanced reasons using MAB rejection enhancer
                    if not reason_long and not reason_short:
                        logger.debug(f"No MAB rejection reason for {ticker}, generating enhanced reason")
                        from app.src.services.mab.mab_rejection_enhancer import MABRejectionEnhancer
                        
                        enhanced_reasons = await MABRejectionEnhancer.enhance_real_time_record(
                            ticker=ticker,
                            indicator=cls.indicator_name(),
                            technical_indicators=technical_indicators
                        )
                        
                        reason_long = enhanced_reasons.get('reason_long', '')
                        reason_short = enhanced_reasons.get('reason_short', '')
                        
                        if not reason_long and not reason_short:
                            # Fallback: create a basic reason based on momentum
                            momentum_score = rejection_data.get('momentum_score', 0.0)
                            if momentum_score >= 0:
                                reason_long = f"Not selected by MAB algorithm - ranked below top {cls.top_k} candidates (momentum: {momentum_score:.2f}%)"
                            else:
                                reason_short = f"Not selected by MAB algorithm - ranked below top {cls.top_k} candidates (momentum: {momentum_score:.2f}%)"
                    
                    # Ensure at least one reason is populated
                    if not reason_long and not reason_short:
                        logger.warning(f"Still no rejection reason for {ticker} after enhancement, skipping log")
                        continue
                    
                    result = await DynamoDBClient.log_inactive_ticker(
                        ticker=ticker,
                        indicator=cls.indicator_name(),
                        reason_not_to_enter_long=reason_long,
                        reason_not_to_enter_short=reason_short,
                        technical_indicators=technical_indicators
                    )
                    
                    if not result:
                        logger.warning(f"Failed to log MAB rejection for {ticker} to InactiveTickersForDayTrading")
                    else:
                        logger.debug(f"Logged MAB rejection for {ticker}: long={bool(reason_long)}, short={bool(reason_short)}")
                except Exception as e:
                    logger.warning(f"Error logging MAB rejection for {ticker}: {str(e)}")

        # Log MAB-selected tickers with positive selection reasons
        # This ensures we know which tickers were chosen by MAB (even if they later fail entry validation)
        logger.debug(f"Logging {len(selected_tickers_list)} tickers selected by MAB to InactiveTickersForDayTrading")
        for selected_ticker in selected_tickers_list:
            try:
                # Find the ticker in the original candidates to get momentum score
                ticker_data = None
                for ticker, momentum_score, reason in all_candidates:
                    if ticker == selected_ticker:
                        ticker_data = (ticker, momentum_score, reason)
                        break
                
                if not ticker_data:
                    continue
                
                ticker, momentum_score, reason = ticker_data
                
                # Get technical indicators
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
                            "momentum_score": momentum_score,
                        }
                
                # Create positive selection reason
                is_long = momentum_score >= 0
                direction = "long" if is_long else "short"
                
                # Get MAB stats to show why this ticker was selected
                mab_stats = await MABService._get_instance().get_stats(cls.indicator_name(), ticker)
                if mab_stats:
                    successes = mab_stats.get('successes', 0)
                    failures = mab_stats.get('failures', 0)
                    total = mab_stats.get('total_trades', 0)
                    success_rate = (successes / total * 100) if total > 0 else 0
                    selection_reason = f"✅ Selected by MAB for {direction} entry - ranked in top {cls.top_k} (success rate: {success_rate:.1f}%, momentum: {momentum_score:.2f}%)"
                else:
                    selection_reason = f"✅ Selected by MAB for {direction} entry - ranked in top {cls.top_k} (new ticker, momentum: {momentum_score:.2f}%)"
                
                # Log with positive reason in the appropriate direction
                reason_long = selection_reason if is_long else ""
                reason_short = selection_reason if not is_long else ""
                
                result = await DynamoDBClient.log_inactive_ticker(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    reason_not_to_enter_long=reason_long,
                    reason_not_to_enter_short=reason_short,
                    technical_indicators=technical_indicators
                )
                
                if result:
                    logger.debug(f"Logged MAB selection for {ticker}: {direction} - {selection_reason[:50]}...")
                else:
                    logger.warning(f"Failed to log MAB selection for {ticker}")
                    
            except Exception as e:
                logger.warning(f"Error logging MAB selection for {selected_ticker}: {str(e)}")

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

        # Process short entries (if enabled)
        # SAFETY: Shorting penny stocks is extremely risky - they can spike 100%+ in minutes
        if cls.allow_short_positions:
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
        else:
            if top_downward:
                logger.info(
                    f"⚠️ Skipping {len(top_downward)} short entries - shorting disabled for penny stocks (too risky)"
                )

        await asyncio.sleep(cls.entry_cycle_seconds)

    @classmethod
    async def _find_lowest_profitable_trade(
        cls, active_trades: List[Dict[str, Any]]
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Find the lowest profitable trade from active trades for preemption.
        
        CONSERVATIVE: Only preempt trades that are already profitable.
        This ensures we lock in gains rather than locking in losses.
        """
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

            # Only consider profitable trades for preemption (>= 0.5% profit)
            # This ensures we don't lock in losses
            if profit_percent >= 0.5:
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
        Preempt the lowest profitable trade to make room for exceptional momentum trade.
        
        CONSERVATIVE: Only preempt trades that are already profitable (>= 0.5%).
        This ensures we lock in gains rather than locking in losses.
        """
        active_trades = await cls._get_active_trades()

        if len(active_trades) < cls.max_active_trades:
            return False

        result = await cls._find_lowest_profitable_trade(active_trades)
        if not result:
            logger.debug("No profitable trades to preempt (all trades are losing or below 0.5%)")
            return False

        lowest_trade, lowest_profit = result
        ticker_to_exit = lowest_trade.get("ticker")

        logger.info(
            f"Preempting {ticker_to_exit} 💰 (profit: {lowest_profit:.2f}%) "
            f"to make room for {new_ticker} (momentum: {new_momentum_score:.2f}%)"
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
        """Process entry for a single ticker with improved validation."""
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
                    await cls._log_selected_ticker_entry_failure(
                        ticker, momentum_score, action, 
                        f"Could not preempt existing trade for exceptional momentum {momentum_score:.2f}%"
                    )
                    return False

                # Re-check after preemption
                active_trades = await cls._get_active_trades()
                active_count = len(active_trades)
                if active_count >= cls.max_active_trades:
                    logger.warning(
                        f"Still at max capacity ({active_count}/{cls.max_active_trades}) after preemption for {ticker}. "
                        f"This may indicate a race condition or concurrent entry."
                    )
            else:
                logger.info(
                    f"At max capacity ({active_count}/{cls.max_active_trades}), "
                    f"skipping {ticker} (momentum: {momentum_score:.2f} < "
                    f"exceptional threshold: {cls.exceptional_momentum_threshold})"
                )
                await cls._log_selected_ticker_entry_failure(
                    ticker, momentum_score, action, 
                    f"At max capacity ({active_count}/{cls.max_active_trades}), momentum {momentum_score:.2f}% < exceptional threshold {cls.exceptional_momentum_threshold}%"
                )
                return False

        # Get entry price using Alpaca API
        quote_response = await AlpacaClient.quote(ticker)
        if not quote_response:
            logger.warning(f"Failed to get quote for {ticker}, skipping")
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, "Failed to get quote data"
            )
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
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, f"Invalid bid/ask: bid={bid}, ask={ask}"
            )
            return False

        # IMPROVED: Calculate and validate bid-ask spread
        spread_percent = SpreadCalculator.calculate_spread_percent(bid, ask)
        if spread_percent > cls.max_bid_ask_spread_percent:
            logger.info(
                f"Skipping {ticker}: bid-ask spread {spread_percent:.2f}% > max {cls.max_bid_ask_spread_percent}%"
            )
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, 
                f"Bid-ask spread too wide: {spread_percent:.2f}% > max {cls.max_bid_ask_spread_percent}%"
            )
            return False

        is_long = action == "buy_to_open"
        enter_price = ask if is_long else bid

        if enter_price <= 0:
            logger.warning(f"Invalid entry price for {ticker}, skipping")
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, f"Invalid entry price: ${enter_price:.4f}"
            )
            return False

        logger.debug(
            f"Entry price for {ticker}: ${enter_price:.4f} (bid=${bid:.4f}, ask=${ask:.4f}, spread={spread_percent:.2f}%)"
        )

        # Verify price is still in valid range
        if enter_price < cls.min_stock_price:
            logger.info(
                f"Skipping {ticker}: entry price ${enter_price:.2f} < ${cls.min_stock_price:.2f}"
            )
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, 
                f"Entry price too low: ${enter_price:.2f} < ${cls.min_stock_price:.2f}"
            )
            return False
        if enter_price >= cls.max_stock_price:
            logger.info(
                f"Skipping {ticker}: entry price ${enter_price:.2f} >= ${cls.max_stock_price:.2f}"
            )
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, 
                f"Entry price too high: ${enter_price:.2f} >= ${cls.max_stock_price:.2f}"
            )
            return False

        # Get bars data for validation and technical indicators
        bars_data = market_data_dict.get(ticker)
        ticker_bars = []
        if bars_data:
            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])

        # Validate entry price matches latest bar close price
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
                    await cls._log_selected_ticker_entry_failure(
                        ticker, momentum_score, action, 
                        f"Price discrepancy too large: quote=${enter_price:.4f} vs close=${close_price:.4f} ({price_discrepancy:.2f}%)"
                    )
                    return False

        # RESTORED: Momentum confirmation check - verify trend is continuing
        # Without this, we were entering trades that immediately reversed
        from app.src.services.trading.penny_stock_utils import MomentumConfirmation
        
        is_confirmed, confirm_reason = MomentumConfirmation.is_momentum_confirmed(
            ticker_bars, is_long
        )
        if not is_confirmed:
            logger.info(f"Skipping {ticker}: momentum not confirmed - {confirm_reason}")
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action,
                f"Momentum not confirmed: {confirm_reason}"
            )
            return False
        
        logger.debug(f"{ticker} momentum confirmed: {confirm_reason}")

        # IMPROVED: Calculate breakeven price accounting for spread
        breakeven_price = SpreadCalculator.calculate_breakeven_price(
            enter_price, spread_percent, is_long
        )

        # IMPROVED: Calculate ATR-based stop loss
        atr = ATRCalculator.calculate_atr(ticker_bars, period=cls.atr_period) if ticker_bars else None
        atr_stop_percent = ATRCalculator.calculate_stop_loss_percent(
            atr, enter_price, cls.atr_multiplier, cls.atr_stop_min, cls.atr_stop_max
        )

        # Prepare entry data
        direction = "upward" if is_long else "downward"
        ranked_reason = f"{reason} (ranked #{rank} {direction} momentum)"

        # Build technical indicators
        technical_indicators = {}
        if ticker_bars:
            latest_bar = ticker_bars[-1]
            technical_indicators = {
                "close_price": latest_bar.get("c", 0.0),
                "volume": latest_bar.get("v", 0),
                "high": latest_bar.get("h", 0.0),
                "low": latest_bar.get("l", 0.0),
                "open": latest_bar.get("o", 0.0),
                # IMPROVED: Store spread and ATR info for exit logic
                "spread_percent": spread_percent,
                "breakeven_price": breakeven_price,
                "atr_stop_percent": atr_stop_percent,
                "atr": atr if atr else 0.0,
            }

        await send_signal_to_webhook(
            ticker=ticker,
            action=action,
            indicator=cls.indicator_name(),
            enter_reason=ranked_reason,
            enter_price=enter_price,
            technical_indicators=technical_indicators,
        )

        # IMPROVED: Enter trade with ATR-based stop loss instead of fixed tight stop
        entry_success = await cls._enter_trade(
            ticker=ticker,
            action=action,
            enter_price=enter_price,
            enter_reason=ranked_reason,
            technical_indicators=technical_indicators,
            dynamic_stop_loss=atr_stop_percent,  # Use ATR-based stop
        )

        if not entry_success:
            logger.error(f"Failed to enter trade for {ticker}")
            await cls._log_selected_ticker_entry_failure(
                ticker, momentum_score, action, 
                "Failed to enter trade (database or API error)"
            )
            return False

        # Update trailing stop to 0.5% after entry (TIGHT for quick exits)
        await DynamoDBClient.update_momentum_trade_trailing_stop(
            ticker=ticker,
            indicator=cls.indicator_name(),
            trailing_stop=cls.trailing_stop_percent,
            peak_profit_percent=0.0,
            skipped_exit_reason="",
        )

        logger.info(
            f"✅ Entered {ticker} {action} at ${enter_price:.4f} "
            f"(quick exit: {cls.profit_threshold:.2f}% profit, "
            f"immediate loss exit: {cls.immediate_loss_exit_threshold:.2f}%)"
        )

        return True

    @classmethod
    async def _log_selected_ticker_entry_failure(
        cls,
        ticker: str,
        momentum_score: float,
        action: str,
        failure_reason: str
    ) -> None:
        """
        Log when a MAB-selected ticker fails to enter a trade.
        
        This provides transparency about why selected tickers didn't result in trades.
        """
        try:
            is_long = action == "buy_to_open"
            direction = "long" if is_long else "short"
            
            # Create a comprehensive failure reason that shows the ticker was selected but failed entry
            full_reason = f"⚠️ Selected by MAB for {direction} entry (momentum: {momentum_score:.2f}%) but failed validation: {failure_reason}"
            
            # Get technical indicators if available
            technical_indicators = {
                "momentum_score": momentum_score,
                "selected_by_mab": True,
                "entry_failure": True,
                "failure_reason": failure_reason
            }
            
            # Log with failure reason in the appropriate direction
            reason_long = full_reason if is_long else ""
            reason_short = full_reason if not is_long else ""
            
            result = await DynamoDBClient.log_inactive_ticker(
                ticker=ticker,
                indicator=cls.indicator_name(),
                reason_not_to_enter_long=reason_long,
                reason_not_to_enter_short=reason_short,
                technical_indicators=technical_indicators
            )
            
            if result:
                logger.debug(f"Logged entry failure for MAB-selected {ticker}: {failure_reason}")
            else:
                logger.warning(f"Failed to log entry failure for {ticker}")
                
        except Exception as e:
            logger.warning(f"Error logging entry failure for {ticker}: {str(e)}")

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
        """
        IMPROVED exit monitoring cycle using ExitDecisionEngine.
        
        Key improvements:
        - Uses breakeven price accounting for bid-ask spread
        - ATR-based stop losses with sensible bounds
        - Tiered trailing stops that tighten as profit grows
        - 60-second minimum holding period (only emergency exits during this time)
        - Consecutive check requirement before stop loss exit
        - Tracks spread-induced vs genuine losses
        """
        if not await AlpacaClient.is_market_open():
            logger.debug("Market is closed, skipping penny stocks exit logic")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_trades = await cls._get_active_trades()
        if not active_trades:
            logger.debug("No active penny stocks trades to monitor")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        # Initialize exit engine and daily metrics if needed
        if cls._exit_engine is None:
            cls._exit_engine = ExitDecisionEngine()
        if cls._daily_metrics is None:
            cls._daily_metrics = DailyPerformanceMetrics()
        
        # Check if we need to reset daily metrics
        today = datetime.now().strftime("%Y-%m-%d")
        if cls._daily_metrics.date != today:
            logger.info(f"📊 End of day metrics: {cls._daily_metrics.to_dict()}")
            cls._daily_metrics.reset()

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
            
            # Convert Decimal to float if needed (DynamoDB returns Decimal)
            if enter_price is not None:
                enter_price = float(enter_price)
            
            peak_profit_percent = float(trade.get("peak_profit_percent", 0.0))

            if not ticker or enter_price is None or enter_price <= 0:
                logger.warning(f"Invalid penny stocks trade data: {trade}")
                continue

            # Get technical indicators from entry (contains spread and ATR info)
            # Handle case where tech_indicators might be a JSON string instead of dict
            tech_indicators_enter = trade.get("technical_indicators_for_enter", {})
            if isinstance(tech_indicators_enter, str):
                try:
                    import json
                    tech_indicators_enter = json.loads(tech_indicators_enter)
                except (json.JSONDecodeError, TypeError):
                    tech_indicators_enter = {}
            if not isinstance(tech_indicators_enter, dict):
                tech_indicators_enter = {}
            
            spread_percent = float(tech_indicators_enter.get("spread_percent", 1.0))  # Default 1%
            breakeven_price = float(tech_indicators_enter.get("breakeven_price", enter_price))
            atr_stop_percent = float(tech_indicators_enter.get("atr_stop_percent", cls.default_atr_stop_percent))

            # Calculate holding period
            holding_seconds = 0.0
            created_at = trade.get("created_at")
            if created_at:
                try:
                    enter_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if enter_time.tzinfo is None:
                        enter_time = enter_time.replace(tzinfo=timezone.utc)
                    current_time = datetime.now(timezone.utc)
                    holding_seconds = (current_time - enter_time).total_seconds()
                except Exception as e:
                    logger.debug(f"Error calculating holding period: {str(e)}")

            # Get current price using Alpaca API
            current_price = await cls._get_current_price(ticker, original_action)
            if current_price is None or current_price <= 0:
                logger.warning(f"Failed to get quote for {ticker} - will retry in next cycle")
                continue

            is_long = original_action == "buy_to_open"

            # Track peak price for trailing stop
            if is_long:
                peak_price = max(enter_price, current_price, peak_profit_percent * enter_price / 100 + enter_price if peak_profit_percent > 0 else enter_price)
            else:
                # For shorts, "peak" is actually the lowest price (best for shorts)
                peak_price = min(enter_price, current_price, enter_price - peak_profit_percent * enter_price / 100 if peak_profit_percent > 0 else enter_price)

            # Use ExitDecisionEngine for exit decision
            exit_decision: ExitDecision = cls._exit_engine.evaluate_exit(
                ticker=ticker,
                entry_price=enter_price,
                breakeven_price=breakeven_price,
                current_price=current_price,
                peak_price=peak_price,
                atr_stop_percent=atr_stop_percent,
                holding_seconds=holding_seconds,
                is_long=is_long,
                spread_percent=spread_percent
            )

            # Calculate current profit for logging and tracking
            profit_percent = cls._calculate_profit_percent(enter_price, current_price, original_action)

            if not exit_decision.should_exit:
                # Update peak profit in database
                new_peak = max(peak_profit_percent, profit_percent)
                await DynamoDBClient.update_momentum_trade_trailing_stop(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    trailing_stop=cls.trailing_stop_percent,
                    peak_profit_percent=new_peak,
                    skipped_exit_reason=exit_decision.reason,
                )
                logger.debug(f"{ticker}: {exit_decision.reason} (profit: {profit_percent:.2f}%)")
                continue

            # Exit triggered
            exit_emoji = "💰" if profit_percent >= 0 else "🚨"
            logger.info(
                f"{exit_emoji} Exit signal for {ticker}: {exit_decision.reason} "
                f"(enter: ${enter_price:.4f}, current: ${current_price:.4f}, profit: {profit_percent:.2f}%)"
            )

            # Get latest quote right before exit
            exit_price = await cls._get_current_price(ticker, original_action)
            if exit_price is None or exit_price <= 0:
                exit_price = current_price
                logger.warning(f"Failed to get exit quote for {ticker}, using current price ${current_price:.4f}")

            # Calculate final profit
            final_profit_percent = cls._calculate_profit_percent(enter_price, exit_price, original_action)

            # Record metrics
            cls._daily_metrics.record_trade(final_profit_percent, exit_decision.is_spread_induced)

            # If trade ended in loss, mark ticker as losing for today
            if final_profit_percent < 0:
                cls._losing_tickers_today.add(ticker)
                loss_type = "spread-induced" if exit_decision.is_spread_induced else "price movement"
                logger.warning(
                    f"📛 Marked {ticker} as losing ticker ({loss_type} loss: {final_profit_percent:.2f}%) - "
                    f"excluded from MAB selection for rest of day"
                )

            # Get technical indicators for exit
            bars_data = await AlpacaClient.get_market_data(ticker, limit=cls.recent_bars_for_trend + 5)
            technical_indicators_exit = {}
            if bars_data:
                bars_dict = bars_data.get("bars", {})
                ticker_bars = bars_dict.get(ticker, [])
                if ticker_bars:
                    latest_bar = ticker_bars[-1]
                    technical_indicators_exit = {
                        "close_price": latest_bar.get("c", 0.0),
                        "volume": latest_bar.get("v", 0),
                        "exit_type": exit_decision.exit_type,
                        "is_spread_induced": exit_decision.is_spread_induced,
                        "holding_seconds": holding_seconds,
                    }

            # Reset exit engine state for this ticker
            cls._exit_engine.reset_ticker(ticker)

            await cls._exit_trade(
                ticker=ticker,
                original_action=original_action,
                enter_price=enter_price,
                exit_price=exit_price,
                exit_reason=exit_decision.reason,
                technical_indicators_enter=tech_indicators_enter,
                technical_indicators_exit=technical_indicators_exit,
            )

        await asyncio.sleep(cls.exit_cycle_seconds)
