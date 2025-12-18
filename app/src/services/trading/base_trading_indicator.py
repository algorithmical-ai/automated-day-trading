"""
Base Trading Indicator
Abstract base class for trading indicators with shared infrastructure
"""

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional, ClassVar
from datetime import datetime, date, timezone, time
import pytz

import gc
from app.src.common.alpaca import AlpacaClient
from app.src.common.loguru_logger import logger
from app.src.common.memory_monitor import MemoryMonitor
from app.src.services.technical_analysis.technical_analysis_lib import (
    TechnicalAnalysisLib,
)
from app.src.services.candidate_generator.alpaca_screener import AlpacaScreenerService
from app.src.db.dynamodb_client import DynamoDBClient, _get_est_timestamp
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService


# Memory optimization: Limit max tickers to process per cycle
# This prevents OOM on Heroku Basic/Standard dynos (512MB-1GB)
# Reduced from 50 to 25 after continued OOM issues
MAX_TICKERS_PER_CYCLE = int(os.getenv("MAX_TICKERS_PER_CYCLE", "25"))


class BaseTradingIndicator(ABC):
    """Base class for trading indicators with shared infrastructure"""

    # Class-level configuration
    running: bool = True
    max_active_trades: int = 5
    max_daily_trades: int = 20
    ticker_cooldown_minutes: int = 60
    entry_cycle_seconds: int = 5
    exit_cycle_seconds: int = 5
    position_size_dollars: float = 2000.0  # Fixed position size in dollars
    
    # Memory optimization: max tickers to process per entry cycle
    max_tickers_per_cycle: int = MAX_TICKERS_PER_CYCLE

    # Daily tracking
    daily_trades_count: int = 0
    daily_trades_date: Optional[str] = None
    ticker_exit_timestamps: ClassVar[Optional[Dict[str, datetime]]] = (
        None  # Per-subclass dict, initialized on first use
    )
    mab_reset_date: Optional[str] = None
    mab_reset_timestamp: Optional[datetime] = None  # Track when reset happened (EST)
    _daily_count_lock: ClassVar[Optional[asyncio.Lock]] = (
        None  # Lock for thread-safe daily count updates
    )

    @classmethod
    @abstractmethod
    def indicator_name(cls) -> str:
        """Return the name of this indicator"""
        pass

    @classmethod
    def configure(cls):
        """Configure dependencies"""
        # MCPClient is no longer used - all calls now go directly to AlpacaClient and TechnicalAnalysisLib
        DynamoDBClient.configure()
        MABService.configure()
        cls.running = True
        cls.mab_reset_date = None
        cls.mab_reset_timestamp = None
        cls.daily_trades_count = 0
        cls.daily_trades_date = None
        # Initialize class-level mutable state properly for each subclass
        cls.ticker_exit_timestamps = {}
        # Always initialize lock for thread-safe daily count updates
        cls._daily_count_lock = asyncio.Lock()

    @classmethod
    def stop(cls):
        """Stop the trading indicator"""
        cls.running = False

    @classmethod
    def _get_ticker_exit_timestamps(cls) -> Dict[str, datetime]:
        """Get or initialize ticker_exit_timestamps dict for this class"""
        if (
            not hasattr(cls, "ticker_exit_timestamps")
            or cls.ticker_exit_timestamps is None
        ):
            cls.ticker_exit_timestamps = {}
        return cls.ticker_exit_timestamps

    @classmethod
    def _is_ticker_in_cooldown(cls, ticker: str) -> bool:
        """Check if ticker is in cooldown period"""
        exit_timestamps = cls._get_ticker_exit_timestamps()
        if ticker not in exit_timestamps:
            return False

        exit_time = exit_timestamps[ticker]
        elapsed_minutes = (
            datetime.now(timezone.utc) - exit_time
        ).total_seconds() / 60.0

        if elapsed_minutes >= cls.ticker_cooldown_minutes:
            exit_timestamps = cls._get_ticker_exit_timestamps()
            del exit_timestamps[ticker]
            return False

        return True

    @classmethod
    async def _has_reached_daily_trade_limit(cls) -> bool:
        """Check if daily trade limit has been reached by querying DynamoDB"""
        today = date.today().isoformat()

        # Query DynamoDB for actual completed trade count
        cls.daily_trades_count = await DynamoDBClient.get_completed_trade_count(
            date=today, indicator=cls.indicator_name()
        )

        return cls.daily_trades_count >= cls.max_daily_trades

    @classmethod
    async def _increment_daily_trade_count(cls):
        """Increment daily trade counter (thread-safe)"""
        async with cls._daily_count_lock:
            today = date.today().isoformat()

            if cls.daily_trades_date != today:
                cls.daily_trades_count = 0
                cls.daily_trades_date = today

            cls.daily_trades_count += 1

    @classmethod
    async def _reset_daily_stats_if_needed(cls):
        """Reset daily stats only once per day at 9:30 AM EST (market open)

        Uses EST only for market-hour logic, stores timestamps in UTC internally.
        """
        # Use UTC internally
        current_time_utc = datetime.now(timezone.utc)

        # Convert to EST only for market-hour logic
        est_tz = pytz.timezone("America/New_York")
        current_time_est = current_time_utc.astimezone(est_tz)
        today = current_time_est.date().isoformat()  # Use EST date for market day

        # Check if we've already reset today (using EST date for market day)
        already_reset_today = (
            cls.mab_reset_timestamp is not None
            and cls.mab_reset_timestamp.astimezone(est_tz).date().isoformat() == today
        )

        # Only reset if:
        # 1. It's after 9:30 AM EST
        # 2. We haven't reset today yet
        # 3. The date has changed (safety check)
        if (
            await AlpacaClient.is_market_open()
            and not already_reset_today
            and cls.mab_reset_date != today
        ):
            logger.info(
                f"Resetting daily MAB statistics for {cls.indicator_name()} "
                f"(market open: {current_time_est.strftime('%Y-%m-%d %H:%M:%S %Z')})"
            )
            await MABService.reset_daily_stats(cls.indicator_name())
            cls.mab_reset_date = today
            # Store UTC timestamp internally (convert EST datetime to UTC)
            cls.mab_reset_timestamp = current_time_est.astimezone(timezone.utc)
            cls.daily_trades_count = 0
            cls.daily_trades_date = today
            cls._get_ticker_exit_timestamps().clear()
        elif not await AlpacaClient.is_market_open():
            # Log if we're before market open (only once to avoid spam)
            if cls.mab_reset_date != today:
                logger.debug(
                    f"Waiting for market open (9:30 AM EST) before resetting MAB stats "
                    f"for {cls.indicator_name()}. Current time: {current_time_est.strftime('%H:%M:%S %Z')}"
                )

    @classmethod
    async def _get_screened_tickers(cls) -> List[str]:
        """Get screened tickers from Alpaca screener service directly"""
        try:
            screened_data = await AlpacaScreenerService().get_all_screened_tickers()
            if not screened_data:
                return []

            # Extract sets and convert to lists, then combine
            most_actives = list(screened_data.get("most_actives", set()))
            gainers = list(screened_data.get("gainers", set()))
            losers = list(screened_data.get("losers", set()))

            # Combine all unique tickers
            return list(set(most_actives + gainers + losers))
        except Exception as e:
            logger.error(f"Error getting screened tickers: {e}", exc_info=True)
            return []

    @classmethod
    async def _fetch_market_data_batch(
        cls, tickers: List[str], max_concurrent: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Fetch market data for multiple tickers in parallel batches.
        Uses memory-optimized batch sizes and caching.

        Args:
            tickers: List of ticker symbols to fetch
            max_concurrent: Maximum number of concurrent API calls (uses config if None)

        Returns:
            Dictionary mapping ticker -> market_data_response (or None if failed)
        """
        if not tickers:
            return {}

        # MEMORY OPTIMIZATION: Limit number of tickers to prevent OOM
        original_count = len(tickers)
        if len(tickers) > cls.max_tickers_per_cycle:
            logger.debug(
                f"{cls.indicator_name()}: Limiting tickers from {len(tickers)} to {cls.max_tickers_per_cycle}"
            )
            tickers = tickers[:cls.max_tickers_per_cycle]

        # Get memory-optimized configuration
        if max_concurrent is None:
            try:
                memory_config = MemoryMonitor.get_memory_config()
                max_concurrent = memory_config.get("market_data_batch_size", 5)
            except Exception as e:
                logger.warning(f"Failed to get memory config, using default: {e}")
                max_concurrent = 5
        
        # Ensure max_concurrent is a valid integer (reduced default for memory)
        if max_concurrent is None or not isinstance(max_concurrent, int) or max_concurrent <= 0:
            logger.warning(f"Invalid max_concurrent value: {max_concurrent}, using default 5")
            max_concurrent = 5
        
        # Cap max_concurrent to prevent too many concurrent requests
        max_concurrent = min(max_concurrent, 10)

        # Check memory before starting - abort if too high
        # AGGRESSIVE THRESHOLDS: Reduced from 700/800 to 500/600 MB
        current_mem = MemoryMonitor.get_current_memory_mb()
        if current_mem > 500:  # 500MB threshold for 1GB dyno (was 700)
            logger.warning(
                f"⚠️ Memory high ({current_mem:.0f}MB), running GC before batch fetch"
            )
            gc.collect()
            await TechnicalAnalysisLib.cleanup_cache()
            current_mem = MemoryMonitor.get_current_memory_mb()
            if current_mem > 600:  # 600MB abort threshold (was 800)
                logger.error(
                    f"🚨 Memory still too high ({current_mem:.0f}MB) after GC, skipping batch fetch"
                )
                return {}

        async def fetch_one(ticker: str) -> Tuple[str, Any]:
            """Fetch market data for a single ticker using caching"""
            try:
                # Use TechnicalAnalysisLib with caching enabled
                market_data = await TechnicalAnalysisLib.calculate_all_indicators(
                    ticker, use_cache=True
                )
                return (ticker, market_data)
            except Exception as e:
                logger.debug(f"Failed to get market data for {ticker}: {str(e)}")
                return (ticker, None)

        # Process in batches to avoid overwhelming memory
        results: Dict[str, Any] = {}
        total_batches = (len(tickers) + max_concurrent - 1) // max_concurrent

        for batch_num, i in enumerate(range(0, len(tickers), max_concurrent), 1):
            batch = tickers[i : i + max_concurrent]

            # Check memory threshold before processing batch - AGGRESSIVE
            current_mem = MemoryMonitor.get_current_memory_mb()
            if current_mem > 400:  # Warn and GC at 400MB (was 600)
                logger.warning(
                    f"⚠️ Memory at {current_mem:.0f}MB in batch {batch_num}, running GC"
                )
                gc.collect()
                await TechnicalAnalysisLib.cleanup_cache()
                
            if current_mem > 550:  # Stop at 550MB (was 750)
                logger.warning(
                    f"🚨 Memory too high ({current_mem:.0f}MB), stopping batch processing early"
                )
                break

            batch_results = await asyncio.gather(
                *[fetch_one(ticker) for ticker in batch], return_exceptions=True
            )

            for result in batch_results:
                if isinstance(result, Exception):
                    logger.debug(f"Exception in batch fetch: {str(result)}")
                    continue
                if isinstance(result, tuple) and len(result) == 2:
                    ticker, market_data = result
                    results[ticker] = market_data

            # Small delay between batches to allow memory cleanup
            if batch_num < total_batches:
                await asyncio.sleep(0.05)

            # Periodic garbage collection every 5 batches to free memory
            if batch_num % 5 == 0:
                gc.collect()

        # Final garbage collection
        gc.collect()

        if original_count > len(tickers):
            logger.debug(
                f"{cls.indicator_name()}: Processed {len(results)}/{original_count} tickers "
                f"(limited to {cls.max_tickers_per_cycle})"
            )

        return results

    @classmethod
    async def _get_active_trades(cls) -> List[Dict[str, Any]]:
        """Get active trades for this indicator"""
        return await DynamoDBClient.get_all_momentum_trades(cls.indicator_name())

    @classmethod
    async def _get_active_ticker_set(cls) -> set:
        """Get set of active tickers for this indicator"""
        active_trades = await cls._get_active_trades()
        return {trade.get("ticker") for trade in active_trades if trade.get("ticker")}

    @classmethod
    async def _enter_trade(
        cls,
        ticker: str,
        action: str,
        enter_price: float,
        enter_reason: str,
        technical_indicators: Optional[Dict[str, Any]] = None,
        dynamic_stop_loss: Optional[float] = None,
        entry_score: Optional[float] = None,
    ) -> bool:
        """Enter a trade and save to DynamoDB"""
        try:
            await DynamoDBClient.add_momentum_trade(
                ticker=ticker,
                action=action,
                indicator=cls.indicator_name(),
                enter_price=enter_price,
                enter_reason=enter_reason,
                technical_indicators_for_enter=technical_indicators,
                dynamic_stop_loss=dynamic_stop_loss,
                entry_score=entry_score,
            )

            await cls._increment_daily_trade_count()

            logger.info(
                f"Entered {cls.indicator_name()} trade for {ticker} - {action} at {enter_price} "
                f"(daily trades: {cls.daily_trades_count}/{cls.max_daily_trades})"
            )
            return True
        except Exception as e:
            logger.error(f"Error entering trade for {ticker}: {str(e)}")
            return False

    @classmethod
    async def _exit_trade(
        cls,
        ticker: str,
        original_action: str,
        enter_price: float,
        exit_price: float,
        exit_reason: str,
        technical_indicators_enter: Optional[Dict[str, Any]] = None,
        technical_indicators_exit: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Exit a trade and record completion"""
        try:
            # Determine exit action
            if original_action == "buy_to_open":
                exit_action = "sell_to_close"
            elif original_action == "sell_to_open":
                exit_action = "buy_to_close"
            else:
                logger.warning(f"Unknown action: {original_action} for {ticker}")
                return False

            # Calculate profit/loss using $2000 position size
            # Buy $2000 worth of shares at enter_price, sell all at exit_price
            if enter_price <= 0:
                logger.warning(
                    f"Invalid enter_price ({enter_price}) for {ticker}, setting profit_or_loss to 0"
                )
                profit_or_loss = 0.0
            else:
                # Convert Decimal to float if needed (DynamoDB returns Decimal)
                enter_price = float(enter_price)
                exit_price = float(exit_price)

                # Calculate number of shares bought with $2000
                number_of_shares = cls.position_size_dollars / enter_price

                if original_action == "buy_to_open":
                    # Long trade: buy at enter_price, sell at exit_price
                    # Profit = (exit_price - enter_price) * number_of_shares
                    profit_or_loss = (exit_price - enter_price) * number_of_shares
                elif original_action == "sell_to_open":
                    # Short trade: sell at enter_price, buy back at exit_price
                    # Profit = (enter_price - exit_price) * number_of_shares
                    profit_or_loss = (enter_price - exit_price) * number_of_shares
                else:
                    profit_or_loss = 0.0

                logger.debug(
                    f"Profit/loss calculation for {ticker}: "
                    f"position_size=${cls.position_size_dollars:.2f}, "
                    f"shares={number_of_shares:.4f}, "
                    f"enter=${enter_price:.4f}, exit=${exit_price:.4f}, "
                    f"profit/loss=${profit_or_loss:.2f}"
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
                "indicator": cls.indicator_name(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await MABService.record_trade_outcome(
                indicator=cls.indicator_name(),
                ticker=ticker,
                enter_price=enter_price,
                exit_price=exit_price,
                action=original_action,
                context=context,
            )

            # Get trade data for completed trades record
            active_trades = await cls._get_active_trades()
            trade_data = next(
                (t for t in active_trades if t.get("ticker") == ticker), None
            )

            enter_reason = trade_data.get("enter_reason", "") if trade_data else ""
            enter_timestamp = (
                trade_data.get("created_at", _get_est_timestamp())
                if trade_data
                else _get_est_timestamp()
            )

            if not technical_indicators_enter and trade_data:
                technical_indicators_enter = trade_data.get(
                    "technical_indicators_for_enter"
                )

            # Add completed trade
            current_date = date.today().isoformat()
            exit_timestamp = _get_est_timestamp()

            await DynamoDBClient.add_completed_trade(
                date=current_date,
                indicator=cls.indicator_name(),
                ticker=ticker,
                action=original_action,
                enter_price=enter_price,
                enter_reason=enter_reason,
                enter_timestamp=enter_timestamp,
                exit_price=exit_price,
                exit_timestamp=exit_timestamp,
                exit_reason=exit_reason,
                profit_or_loss=profit_or_loss,
                technical_indicators_for_enter=technical_indicators_enter,
                technical_indicators_for_exit=technical_indicators_exit,
            )

            # Delete from active trades
            await DynamoDBClient.delete_momentum_trade(ticker, cls.indicator_name())

            # Send webhook signal with profit/loss
            await send_signal_to_webhook(
                ticker=ticker,
                action=exit_action,
                indicator=cls.indicator_name(),
                enter_reason=exit_reason,
                profit_loss=profit_or_loss,
                enter_price=enter_price,
                exit_price=exit_price,
                technical_indicators=technical_indicators_exit,
            )

            # Track exit timestamp for cooldown
            cls._get_ticker_exit_timestamps()[ticker] = datetime.now(timezone.utc)

            logger.info(
                f"Exited {cls.indicator_name()} trade for {ticker}. "
                f"Cooldown period: {cls.ticker_cooldown_minutes} minutes."
            )
            return True
        except Exception as e:
            logger.error(f"Error exiting trade for {ticker}: {str(e)}")
            return False

    @classmethod
    def _calculate_profit_percent(
        cls, enter_price: float, current_price: float, action: str
    ) -> float:
        """Calculate profit percentage for a trade"""
        # Convert Decimal to float if needed (DynamoDB returns Decimal)
        enter_price = float(enter_price) if enter_price is not None else 0.0
        current_price = float(current_price) if current_price is not None else 0.0

        if action == "buy_to_open":
            return ((current_price - enter_price) / enter_price) * 100
        elif action == "sell_to_open":
            return ((enter_price - current_price) / enter_price) * 100
        return 0.0

    @classmethod
    async def _get_current_price_for_exit(
        cls, ticker: str, action: str
    ) -> Optional[float]:
        """
        Get current price for exit decision using Alpaca API.

        Args:
            ticker: Stock ticker symbol
            action: "buy_to_open" (long) or "sell_to_open" (short)

        Returns:
            Current price (bid for long, ask for short) or None if unavailable
        """
        try:
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
        except Exception as e:
            logger.error(f"Error getting current price for {ticker}: {str(e)}")
            return None

    @classmethod
    def _check_holding_period(
        cls, created_at: Optional[str], min_holding_seconds: Optional[int] = None
    ) -> Tuple[bool, float]:
        """
        Check if trade has passed minimum holding period.

        Args:
            created_at: ISO timestamp string when trade was created
            min_holding_seconds: Optional minimum holding period in seconds

        Returns:
            Tuple of (passed_minimum: bool, holding_period_minutes: float)
        """
        if not created_at:
            return True, 0.0  # No created_at means we can't check, allow processing

        if min_holding_seconds is None:
            min_holding_seconds = getattr(cls, "min_holding_period_seconds", 30)

        try:
            enter_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if enter_time.tzinfo is None:
                enter_time = enter_time.replace(tzinfo=timezone.utc)
            current_time = datetime.now(timezone.utc)
            holding_period_seconds = (current_time - enter_time).total_seconds()
            holding_period_minutes = holding_period_seconds / 60.0

            passed = holding_period_seconds >= min_holding_seconds
            return passed, holding_period_minutes
        except Exception as e:
            logger.warning(f"Error calculating holding period: {str(e)}")
            return True, 0.0  # On error, allow processing

    @classmethod
    def _is_near_market_close(cls) -> bool:
        """
        Check if we're within the specified minutes before market close.
        Market close is 4:00 PM ET (16:00).

        Returns:
            True if within minutes_before_close_to_exit of market close
        """
        minutes_before_close = getattr(cls, "minutes_before_close_to_exit", 15)

        est_tz = pytz.timezone("America/New_York")
        current_time_est = datetime.now(est_tz)
        market_close_time = time(16, 0)  # 4:00 PM ET

        # Calculate minutes until market close
        close_datetime = datetime.combine(current_time_est.date(), market_close_time)
        close_datetime = est_tz.localize(close_datetime)
        current_datetime = current_time_est

        if current_datetime >= close_datetime:
            # Already past market close
            return True

        minutes_until_close = (close_datetime - current_datetime).total_seconds() / 60.0
        return minutes_until_close <= minutes_before_close

    @classmethod
    async def _check_hard_stop_loss(
        cls,
        ticker: str,
        enter_price: float,
        current_price: float,
        action: str,
        dynamic_stop_loss: Optional[float] = None,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Check if hard stop loss should trigger an exit.

        Args:
            ticker: Stock ticker symbol
            enter_price: Entry price
            current_price: Current price
            action: Trade action ("buy_to_open" or "sell_to_open")
            dynamic_stop_loss: Dynamic stop loss percentage (negative value)

        Returns:
            Tuple of (should_exit: bool, exit_reason: Optional[str], profit_percent: float)
        """
        profit_percent = cls._calculate_profit_percent(
            enter_price, current_price, action
        )

        # Use dynamic stop loss if available, otherwise use default
        stop_loss_threshold = (
            float(dynamic_stop_loss)
            if dynamic_stop_loss is not None
            else getattr(cls, "stop_loss_threshold", -2.5)
        )

        if profit_percent < stop_loss_threshold:
            exit_reason = (
                f"Hard stop loss triggered: {profit_percent:.2f}% "
                f"(below {stop_loss_threshold:.2f}% threshold"
                f"{' (dynamic)' if dynamic_stop_loss is not None else ''})"
            )
            return True, exit_reason, profit_percent

        return False, None, profit_percent

    @classmethod
    async def _check_end_of_day_closure(
        cls,
        ticker: str,
        profit_percent: float,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if end-of-day forced closure should trigger.
        Only exits profitable trades; losing trades are held until next day.

        Args:
            ticker: Stock ticker symbol
            profit_percent: Current profit percentage

        Returns:
            Tuple of (should_exit: bool, exit_reason: Optional[str])
        """
        if not cls._is_near_market_close():
            return False, None

        minutes_before_close = getattr(cls, "minutes_before_close_to_exit", 15)

        # Only exit if profitable
        if profit_percent > 0:
            exit_reason = (
                f"End-of-day closure: exiting {minutes_before_close} minutes before market close "
                f"(current profit: {profit_percent:.2f}%)"
            )
            return True, exit_reason
        else:
            logger.info(
                f"Holding {ticker} at end of day (current loss: {profit_percent:.2f}%) - "
                f"will exit when profitable or stop loss triggered"
            )
            return False, None

    @classmethod
    async def _check_trailing_stop_exit(
        cls,
        ticker: str,
        enter_price: float,
        current_price: float,
        action: str,
        peak_profit_percent: float,
        created_at: Optional[str],
        technical_indicators: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Check if trailing stop should trigger an exit.

        Args:
            ticker: Stock ticker symbol
            enter_price: Entry price
            current_price: Current price
            action: Trade action ("buy_to_open" or "sell_to_open")
            peak_profit_percent: Peak profit percentage achieved
            created_at: ISO timestamp when trade was created
            technical_indicators: Technical indicators for the ticker

        Returns:
            Tuple of (should_exit: bool, exit_reason: Optional[str], profit_percent: float)
        """
        profit_percent = cls._calculate_profit_percent(
            enter_price, current_price, action
        )

        # Get activation threshold
        trailing_stop_activation_profit = getattr(
            cls, "trailing_stop_activation_profit", 0.5
        )

        # Check if trailing stop is activated
        if peak_profit_percent < trailing_stop_activation_profit:
            return False, None, profit_percent

        # Check cooldown period if specified
        trailing_stop_cooldown_seconds = getattr(
            cls, "trailing_stop_cooldown_seconds", 30
        )
        if created_at and trailing_stop_cooldown_seconds > 0:
            try:
                enter_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if enter_time.tzinfo is None:
                    enter_time = enter_time.replace(tzinfo=timezone.utc)
                elapsed_seconds = (
                    datetime.now(timezone.utc) - enter_time
                ).total_seconds()

                if elapsed_seconds < trailing_stop_cooldown_seconds:
                    return False, None, profit_percent
            except Exception:
                pass  # Continue if cooldown check fails

        # Calculate trailing stop distance
        from app.src.services.trading.trading_config import (
            ATR_TRAILING_STOP_MULTIPLIER,
            BASE_TRAILING_STOP_PERCENT,
            TRAILING_STOP_SHORT_MULTIPLIER,
            MAX_TRAILING_STOP_SHORT,
        )

        is_short = action == "sell_to_open"
        trailing_stop_percent = getattr(cls, "trailing_stop_percent", 2.5)

        # Use ATR-based trailing stop if available
        if technical_indicators:
            atr = technical_indicators.get("atr", 0.0)
            if atr and atr > 0 and current_price > 0:
                atr_percent = (atr / current_price) * 100
                dynamic_trailing_stop = max(
                    BASE_TRAILING_STOP_PERCENT,
                    ATR_TRAILING_STOP_MULTIPLIER * atr_percent,
                )
                if is_short:
                    dynamic_trailing_stop = min(
                        MAX_TRAILING_STOP_SHORT,
                        dynamic_trailing_stop * TRAILING_STOP_SHORT_MULTIPLIER,
                    )
            else:
                dynamic_trailing_stop = trailing_stop_percent
                if is_short:
                    trailing_stop_short_multiplier = getattr(
                        cls, "trailing_stop_short_multiplier", 1.5
                    )
                    dynamic_trailing_stop *= trailing_stop_short_multiplier
        else:
            dynamic_trailing_stop = trailing_stop_percent
            if is_short:
                trailing_stop_short_multiplier = getattr(
                    cls, "trailing_stop_short_multiplier", 1.5
                )
                dynamic_trailing_stop *= trailing_stop_short_multiplier

        # Check if trailing stop should trigger
        drop_from_peak = peak_profit_percent - profit_percent
        should_trigger = drop_from_peak >= dynamic_trailing_stop and profit_percent > 0

        if should_trigger:
            exit_reason = (
                f"Trailing stop triggered: profit dropped {drop_from_peak:.2f}% "
                f"from peak of {peak_profit_percent:.2f}% (current: {profit_percent:.2f}%, "
                f"trailing stop: {dynamic_trailing_stop:.2f}%)"
            )
            return True, exit_reason, profit_percent

        return False, None, profit_percent

    @classmethod
    async def _should_exit_trade(
        cls,
        trade: Dict[str, Any],
        technical_indicators: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], float, float]:
        """
        Comprehensive exit logic check for a trade.
        Checks all exit conditions in priority order:
        1. Hard stop loss (highest priority)
        2. End-of-day forced closure (only for profitable trades)
        3. Trailing stop (if activated)

        Args:
            trade: Trade dictionary with ticker, action, enter_price, etc.
            technical_indicators: Optional technical indicators for the ticker

        Returns:
            Tuple of (should_exit: bool, exit_reason: Optional[str],
                     current_price: float, profit_percent: float)
        """
        ticker = trade.get("ticker")
        action = trade.get("action")
        enter_price = trade.get("enter_price")
        peak_profit_percent = float(trade.get("peak_profit_percent", 0.0))
        created_at = trade.get("created_at")
        dynamic_stop_loss = trade.get("dynamic_stop_loss")

        if not ticker or enter_price is None or enter_price <= 0:
            logger.warning(f"Invalid trade data: {trade}")
            return False, None, 0.0, 0.0

        # Check minimum holding period
        min_holding_seconds = getattr(cls, "min_holding_period_seconds", 30)
        passed_holding, holding_minutes = cls._check_holding_period(
            created_at, min_holding_seconds
        )

        if not passed_holding:
            logger.debug(
                f"Skipping {ticker}: holding period {holding_minutes:.1f} min < "
                f"minimum {min_holding_seconds/60:.2f} min"
            )
            return False, None, 0.0, 0.0

        # Get current price
        current_price = await cls._get_current_price_for_exit(ticker, action)
        if current_price is None or current_price <= 0:
            logger.warning(
                f"Failed to get quote for {ticker} - will retry in next cycle"
            )
            return False, None, 0.0, 0.0

        # 1. Check hard stop loss (highest priority)
        should_exit, exit_reason, profit_percent = await cls._check_hard_stop_loss(
            ticker, enter_price, current_price, action, dynamic_stop_loss
        )
        if should_exit:
            return True, exit_reason, current_price, profit_percent

        # 2. Check end-of-day forced closure (only for profitable trades)
        should_exit, exit_reason = await cls._check_end_of_day_closure(
            ticker, profit_percent
        )
        if should_exit:
            return True, exit_reason, current_price, profit_percent

        # 3. Check trailing stop (if activated)
        should_exit, exit_reason, profit_percent = await cls._check_trailing_stop_exit(
            ticker,
            enter_price,
            current_price,
            action,
            peak_profit_percent,
            created_at,
            technical_indicators,
        )
        if should_exit:
            return True, exit_reason, current_price, profit_percent

        return False, None, current_price, profit_percent

    @classmethod
    async def _log_inactive_ticker(
        cls,
        ticker: str,
        reason_not_to_enter_long: str,
        reason_not_to_enter_short: str,
        technical_indicators: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Log an inactive ticker (evaluated but not traded).

        Args:
            ticker: Stock ticker symbol
            reason_not_to_enter_long: Reason for not entering long position
            reason_not_to_enter_short: Reason for not entering short position
            technical_indicators: Technical indicators at evaluation time

        Returns:
            True if successful, False otherwise
        """
        try:
            await DynamoDBClient.log_inactive_ticker(
                ticker=ticker,
                indicator=cls.indicator_name(),
                reason_not_to_enter_long=reason_not_to_enter_long,
                reason_not_to_enter_short=reason_not_to_enter_short,
                technical_indicators=technical_indicators,
            )

            logger.debug(
                f"Logged inactive ticker {ticker} for {cls.indicator_name()}: "
                f"long={reason_not_to_enter_long}, short={reason_not_to_enter_short}"
            )
            return True
        except Exception as e:
            logger.error(f"Error logging inactive ticker {ticker}: {str(e)}")
            return False

    @classmethod
    @abstractmethod
    async def entry_service(cls):
        """Entry service - analyze and enter trades"""
        pass

    @classmethod
    @abstractmethod
    async def exit_service(cls):
        """Exit service - monitor and exit trades"""
        pass

    @classmethod
    async def run(cls):
        """Run both entry and exit services concurrently with staggered startup"""
        logger.info(f"Starting {cls.indicator_name()} trading service...")
        
        # MEMORY OPTIMIZATION: Add startup delay to let the app stabilize
        # This prevents all indicators from hammering the API simultaneously at startup
        startup_delay = int(os.getenv("INDICATOR_STARTUP_DELAY_SECONDS", "5"))
        if startup_delay > 0:
            logger.info(f"{cls.indicator_name()}: Waiting {startup_delay}s before starting...")
            await asyncio.sleep(startup_delay)
        
        # Stagger entry and exit services to reduce memory spikes
        async def delayed_entry_service():
            # Entry service starts 3 seconds after exit service
            await asyncio.sleep(3)
            await cls.entry_service()
        
        await asyncio.gather(cls.exit_service(), delayed_entry_service())
