"""
Base Trading Indicator
Abstract base class for trading indicators with shared infrastructure
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional, ClassVar
from datetime import datetime, date, timezone, time
import pytz

from app.src.common.loguru_logger import logger
from app.src.services.mcp.mcp_client import MCPClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService


class BaseTradingIndicator(ABC):
    """Base class for trading indicators with shared infrastructure"""

    # Class-level configuration
    running: bool = True
    max_active_trades: int = 5
    max_daily_trades: int = 5
    ticker_cooldown_minutes: int = 60
    entry_cycle_seconds: int = 5
    exit_cycle_seconds: int = 5
    position_size_dollars: float = 2000.0  # Fixed position size in dollars

    # Daily tracking
    daily_trades_count: int = 0
    daily_trades_date: Optional[str] = None
    ticker_exit_timestamps: ClassVar[Optional[Dict[str, datetime]]] = None  # Per-subclass dict, initialized on first use
    mab_reset_date: Optional[str] = None
    mab_reset_timestamp: Optional[datetime] = None  # Track when reset happened (EST)
    _daily_count_lock: ClassVar[Optional[asyncio.Lock]] = None  # Lock for thread-safe daily count updates

    @classmethod
    @abstractmethod
    def indicator_name(cls) -> str:
        """Return the name of this indicator"""
        pass

    @classmethod
    def configure(cls):
        """Configure dependencies"""
        MCPClient.configure()
        DynamoDBClient.configure()
        MABService.configure()
        cls.running = True
        cls.mab_reset_date = None
        cls.mab_reset_timestamp = None
        cls.daily_trades_count = 0
        cls.daily_trades_date = None
        # Initialize class-level mutable state properly for each subclass
        cls.ticker_exit_timestamps = {}
        # Initialize lock for thread-safe daily count updates
        if cls._daily_count_lock is None:
            cls._daily_count_lock = asyncio.Lock()

    @classmethod
    def stop(cls):
        """Stop the trading indicator"""
        cls.running = False

    @classmethod
    def _get_ticker_exit_timestamps(cls) -> Dict[str, datetime]:
        """Get or initialize ticker_exit_timestamps dict for this class"""
        if not hasattr(cls, 'ticker_exit_timestamps') or cls.ticker_exit_timestamps is None:
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
        # Ensure lock is initialized
        if cls._daily_count_lock is None:
            cls._daily_count_lock = asyncio.Lock()
        
        async with cls._daily_count_lock:
            today = date.today().isoformat()

            if cls.daily_trades_date != today:
                cls.daily_trades_count = 0
                cls.daily_trades_date = today

            cls.daily_trades_count += 1

    @classmethod
    async def _check_market_open(cls) -> bool:
        """Check if market is open"""
        clock_response = await MCPClient.get_market_clock()
        if not clock_response:
            return False

        clock = clock_response.get("clock", {})
        return clock.get("is_open", False)

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
        market_open_time = time(9, 30)  # 9:30 AM EST

        # Check if it's after 9:30 AM EST (market-hour logic)
        current_time_only = current_time_est.time()
        is_after_market_open = current_time_only >= market_open_time

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
            is_after_market_open
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
        elif not is_after_market_open:
            # Log if we're before market open (only once to avoid spam)
            if cls.mab_reset_date != today:
                logger.debug(
                    f"Waiting for market open (9:30 AM EST) before resetting MAB stats "
                    f"for {cls.indicator_name()}. Current time: {current_time_est.strftime('%H:%M:%S %Z')}"
                )

    @classmethod
    async def _get_screened_tickers(cls) -> List[str]:
        """Get screened tickers from MCP tool (proxied Alpaca screener)"""
        screened_data = await MCPClient.get_alpaca_screened_tickers()

        if not screened_data:
            return []

        # Extract sets and convert to lists, then combine
        most_actives = list(screened_data.get("most_actives", set()))
        gainers = list(screened_data.get("gainers", set()))
        losers = list(screened_data.get("losers", set()))

        # Combine all unique tickers
        return list(set(most_actives + gainers + losers))

    @classmethod
    async def _fetch_market_data_batch(
        cls, tickers: List[str], max_concurrent: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch market data for multiple tickers in parallel batches.

        Args:
            tickers: List of ticker symbols to fetch
            max_concurrent: Maximum number of concurrent API calls

        Returns:
            Dictionary mapping ticker -> market_data_response (or None if failed)
        """
        if not tickers:
            return {}

        async def fetch_one(ticker: str) -> Tuple[str, Any]:
            """Fetch market data for a single ticker"""
            try:
                market_data = await MCPClient.get_market_data(ticker)
                return (ticker, market_data)
            except Exception as e:
                logger.debug(f"Failed to get market data for {ticker}: {str(e)}")
                return (ticker, None)

        # Process in batches to avoid overwhelming the API
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
                    ticker, market_data = result
                    results[ticker] = market_data

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

            # Send webhook signal
            await send_signal_to_webhook(
                ticker=ticker,
                action=exit_action,
                indicator=cls.indicator_name(),
                enter_reason=exit_reason,
            )

            # Calculate profit/loss using $2000 position size
            # Buy $2000 worth of shares at enter_price, sell all at exit_price
            if enter_price <= 0:
                logger.warning(
                    f"Invalid enter_price ({enter_price}) for {ticker}, setting profit_or_loss to 0"
                )
                profit_or_loss = 0.0
            else:
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
                trade_data.get("created_at", datetime.now(timezone.utc).isoformat())
                if trade_data
                else datetime.now(timezone.utc).isoformat()
            )

            if not technical_indicators_enter and trade_data:
                technical_indicators_enter = trade_data.get(
                    "technical_indicators_for_enter"
                )

            # Add completed trade
            current_date = date.today().isoformat()
            exit_timestamp = datetime.now(timezone.utc).isoformat()

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
        if action == "buy_to_open":
            return ((current_price - enter_price) / enter_price) * 100
        elif action == "sell_to_open":
            return ((enter_price - current_price) / enter_price) * 100
        return 0.0

    @abstractmethod
    async def entry_service(cls):
        """Entry service - analyze and enter trades"""
        pass

    @abstractmethod
    async def exit_service(cls):
        """Exit service - monitor and exit trades"""
        pass

    @classmethod
    async def run(cls):
        """Run both entry and exit services concurrently"""
        logger.info(f"Starting {cls.indicator_name()} trading service...")
        await asyncio.gather(cls.entry_service(), cls.exit_service())
