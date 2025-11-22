"""
Base Trading Indicator
Abstract base class for trading indicators with shared infrastructure
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, date, timezone

from app.src.common.loguru_logger import logger
from app.src.services.mcp.mcp_client import MCPClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService
from app.src.services.candidate_generator.alpaca_screener import AlpacaScreenerService


class BaseTradingIndicator(ABC):
    """Base class for trading indicators with shared infrastructure"""

    # Class-level configuration
    running: bool = True
    max_active_trades: int = 5
    max_daily_trades: int = 5
    ticker_cooldown_minutes: int = 60
    entry_cycle_seconds: int = 5
    exit_cycle_seconds: int = 5

    # Daily tracking
    daily_trades_count: int = 0
    daily_trades_date: Optional[str] = None
    ticker_exit_timestamps: Dict[str, datetime] = {}
    mab_reset_date: Optional[str] = None

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
        cls.daily_trades_count = 0
        cls.daily_trades_date = None
        cls.ticker_exit_timestamps.clear()

    @classmethod
    def stop(cls):
        """Stop the trading indicator"""
        cls.running = False

    @classmethod
    def _is_ticker_in_cooldown(cls, ticker: str) -> bool:
        """Check if ticker is in cooldown period"""
        if ticker not in cls.ticker_exit_timestamps:
            return False

        exit_time = cls.ticker_exit_timestamps[ticker]
        elapsed_minutes = (
            datetime.now(timezone.utc) - exit_time
        ).total_seconds() / 60.0

        if elapsed_minutes >= cls.ticker_cooldown_minutes:
            del cls.ticker_exit_timestamps[ticker]
            return False

        return True

    @classmethod
    def _has_reached_daily_trade_limit(cls) -> bool:
        """Check if daily trade limit has been reached"""
        today = date.today().isoformat()

        if cls.daily_trades_date != today:
            cls.daily_trades_count = 0
            cls.daily_trades_date = today

        return cls.daily_trades_count >= cls.max_daily_trades

    @classmethod
    def _increment_daily_trade_count(cls):
        """Increment daily trade counter"""
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
        """Reset daily stats if new trading day"""
        today = date.today().isoformat()
        if cls.mab_reset_date != today:
            logger.info(f"Resetting daily MAB statistics for {cls.indicator_name()}")
            await MABService.reset_daily_stats(cls.indicator_name())
            cls.mab_reset_date = today
            cls.daily_trades_count = 0
            cls.daily_trades_date = today
            cls.ticker_exit_timestamps.clear()

    @classmethod
    async def _get_screened_tickers(cls) -> List[str]:
        """Get screened tickers from Alpaca Screener Service"""
        screener_service = AlpacaScreenerService()
        screened_data = await screener_service.get_all_screened_tickers()

        if not screened_data:
            return []

        # Extract sets and convert to lists, then combine
        most_actives = list(screened_data.get("most_actives", set()))
        gainers = list(screened_data.get("gainers", set()))
        losers = list(screened_data.get("losers", set()))

        # Combine all unique tickers
        return list(set(most_actives + gainers + losers))

    @classmethod
    async def _filter_blacklisted_tickers(cls, tickers: List[str]) -> List[str]:
        """Return all tickers without filtering (blacklist disabled)"""
        # Blacklist filtering is disabled - use all tickers from Alpaca
        logger.debug(
            f"Using all {len(tickers)} tickers from Alpaca for {cls.indicator_name()} "
            "(blacklist filtering disabled)"
        )
        return tickers

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
    ) -> bool:
        """Enter a trade and save to DynamoDB"""
        try:
            await DynamoDBClient.add_momentum_trade(
                ticker=ticker,
                action=action,
                indicator=cls.indicator_name(),
                enter_price=enter_price,
                enter_reason=enter_reason,
            )

            # Update with technical indicators if provided
            if technical_indicators:
                # Note: This would require adding a method to update technical_indicators_for_enter
                # For now, we'll store it in a separate field if needed
                pass

            cls._increment_daily_trade_count()

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

            # Calculate profit/loss
            if original_action == "buy_to_open":
                profit_or_loss = exit_price - enter_price
            elif original_action == "sell_to_open":
                profit_or_loss = enter_price - exit_price
            else:
                profit_or_loss = 0.0

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
            cls.ticker_exit_timestamps[ticker] = datetime.now(timezone.utc)

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
