"""
Momentum Trading Indicator
Uses price momentum to identify entry and exit signals

IMPROVED ALGORITHM (Dec 2024):
- Accounts for bid-ask spread in breakeven calculations
- Uses ExitDecisionEngine for consistent exit logic
- 60-second minimum holding period
- Consecutive check requirement before stop loss exit
- Tiered trailing stops that tighten as profit grows
"""

import asyncio
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, timezone, time
import pytz

from app.src.common.loguru_logger import logger
from app.src.common.utils import measure_latency
from app.src.common.memory_monitor import MemoryMonitor
from app.src.common.alpaca import AlpacaClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator
from app.src.services.technical_analysis.technical_analysis_lib import (
    TechnicalAnalysisLib,
)
from app.src.services.trading.trading_config import (
    ATR_STOP_LOSS_MULTIPLIER,
    ATR_TRAILING_STOP_MULTIPLIER,
    ATR_TRAILING_STOP_MULTIPLIER_LEGACY,
    BASE_TRAILING_STOP_PERCENT,
    TRAILING_STOP_SHORT_MULTIPLIER,
    MAX_TRAILING_STOP_SHORT,
    PENNY_STOCK_STOP_LOSS_MIN,
    PENNY_STOCK_STOP_LOSS_MAX,
    STANDARD_STOCK_STOP_LOSS_MIN,
    STANDARD_STOCK_STOP_LOSS_MAX,
)
from app.src.services.trading.penny_stock_utils import (
    SpreadCalculator,
    ATRCalculator,
    TieredTrailingStop,
    ExitDecisionEngine,
    ExitDecision,
    DailyPerformanceMetrics,
)
from app.src.services.trading.market_direction_filter import MarketDirectionFilter


class MomentumIndicator(BaseTradingIndicator):
    """Momentum-based trading indicator with improved exit logic (Dec 2024)"""

    # Momentum-specific configuration - TIGHTENED for quality over quantity
    profit_threshold: float = 2.0  # RAISED: from 1.5% to 2.0% - need more profit to justify entry
    top_k: int = 1  # REDUCED: from 2 to 1 - be more selective
    exceptional_momentum_threshold: float = 7.0  # RAISED: from 5.0% to 7.0%
    min_momentum_threshold: float = 2.5  # RAISED: from 1.5% to 2.5% - require stronger signal
    max_momentum_threshold: float = 12.0  # TIGHTENED: from 15.0% to 12.0% - extreme = reversal risk
    min_daily_volume: int = 5000  # RAISED: from 1000 to 5000 - need real liquidity
    min_volume_ratio: float = 2.0  # RAISED: from 1.5x to 2.0x SMA - require stronger volume confirmation
    stop_loss_threshold: float = (
        -4.0
    )  # Keep at -4% - give trades room to breathe
    trailing_stop_percent: float = (
        2.5  # Base trailing stop, will be adjusted for shorts
    )
    trailing_stop_short_multiplier: float = 1.5  # Wider trailing stop for shorts (3-4%)
    min_adx_threshold: float = 25.0  # RAISED: from 20.0 to 25.0 - require stronger trend
    rsi_min_for_long: float = 45.0  # Not oversold (avoiding catching falling knives)

    # TIGHTENED: Max bid-ask spread for entry - wide spreads kill scalping profits
    max_bid_ask_spread_percent: float = 1.5  # TIGHTENED: from 3.0% to 1.5%

    # Exit decision engine instance (shared across exit cycles)
    _exit_engine: Optional[ExitDecisionEngine] = None

    # Daily performance metrics
    _daily_metrics: Optional[DailyPerformanceMetrics] = None
    rsi_max_for_long: float = 70.0  # Not overbought (avoiding tops)
    rsi_min_for_short: float = (
        50.0  # Minimum RSI to short (avoid oversold bounces, allow shorting stocks with negative momentum)
    )
    profit_target_strong_momentum: float = 5.0
    profit_target_multiplier: float = 2.0  # Profit target = 2x stop distance
    trailing_stop_activation_profit: float = (
        0.5  # Activate trailing stop after +0.5% profit (tiered system)
    )
    max_entry_hour_et: int = 15  # No entries after 3:00 PM ET (15:00)
    max_entry_minute_et: int = (
        55  # No entries after XX:55 (5 min buffer before cutoff hour ends)
    )

    # MFI (Money Flow Index) filters - avoid extreme conditions
    mfi_min_for_long: float = (
        20.0  # Don't buy into extreme selling pressure (MFI < 20 = oversold/falling knife)
    )
    mfi_max_for_long: float = 80.0  # Don't buy at extreme buying exhaustion
    mfi_min_for_short: float = 20.0  # Don't short already oversold stocks
    mfi_max_for_short: float = 80.0  # Don't short into extreme buying (squeeze)
    # IMPROVED: Longer holding periods to let trades develop
    min_holding_period_seconds: int = (
        90  # RAISED: from 60 to 90 seconds - give trades more room
    )
    min_holding_period_penny_stocks_seconds: int = (
        90  # RAISED: from 60 to 90 seconds - match regular stocks
    )

    # Volatility and low-priced stock filters
    min_stock_price: float = (
        5.0  # Minimum stock price to trade (penny stocks handled by PennyStocksIndicator)
    )
    max_stock_price_for_penny_treatment: float = (
        5.0  # Stocks under $5 get special handling (tight trailing stops)
    )
    max_atr_percent_for_entry: float = (
        5.0  # Maximum ATR% to allow entry (5% = very volatile)
    )
    max_volatility_for_low_price: float = (
        50.0  # Allow high volatility for penny stocks - we bank on it! (was 4.0)
    )
    # NOTE: max_bid_ask_spread_percent is defined above (3.0%) - removed duplicate here
    trailing_stop_penny_stock_multiplier: float = (
        1.5  # Wider trailing stop for penny stocks (legacy, now overridden)
    )
    # Tight trailing stop for penny stocks: exit when profit drops 0.5% from peak (QUICK EXITS)
    penny_stock_trailing_stop_percent: float = (
        0.5  # Exit penny stocks when profit drops 0.5% from peak (take profit VERY quickly)
    )
    penny_stock_trailing_stop_activation_profit: float = (
        0.25  # Activate trailing stop after +0.25% profit for penny stocks (very quick activation)
    )
    penny_stock_quick_profit_target: float = (
        1.5  # Quick profit target for penny stocks - exit at 1.5% profit (bank on volatility)
    )
    trailing_stop_volatile_multiplier: float = (
        1.3  # Wider trailing stop for volatile stocks
    )
    max_holding_time_penny_stocks_minutes: int = (
        30  # Maximum holding time for penny stocks (reduce risk)
    )
    max_holding_time_volatile_stocks_minutes: int = (
        60  # Maximum holding time for volatile stocks
    )
    trailing_stop_cooldown_seconds: int = (
        30  # 30 seconds - quick activation for penny stocks (was 180 seconds)
    )
    min_trailing_stop_cooldown_seconds: int = (
        30  # 30 seconds minimum cooldown for penny stocks to allow quick exits (was 120 seconds)
    )
    force_close_before_market_close: bool = (
        True  # Force close all positions before market close
    )
    minutes_before_close_to_exit: int = (
        15  # Exit positions 15 minutes before market close
    )

    # Profit-taking exit configuration (fixes for premature exits)
    min_profit_for_profit_taking_exit: float = (
        0.5  # Minimum 0.5% profit required before profit-taking exits can trigger
    )
    dip_rise_threshold_percent: float = (
        1.0  # 1.0% dip/rise threshold for profit-taking exits (was 0.5% - too tight)
    )
    min_holding_seconds_for_profit_taking: int = (
        60  # 60 seconds minimum hold time before profit-taking exits can trigger
    )

    @classmethod
    def indicator_name(cls) -> str:
        return "Momentum Trading"

    @classmethod
    def stop(cls):
        """Stop the trading indicator"""
        super().stop()

    @classmethod
    def _is_near_market_close(cls) -> bool:
        """
        Check if we're within the specified minutes before market close.
        Market close is 4:00 PM ET (16:00).
        """
        if not cls.force_close_before_market_close:
            return False

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
        return minutes_until_close <= cls.minutes_before_close_to_exit

    @classmethod
    def _is_after_entry_cutoff(cls) -> bool:
        """
        Check if current time is after the entry cutoff time.
        No new entries allowed after 3:55 PM ET to avoid late-day volatility
        and ensure trades have time to develop before market close.

        Returns:
            True if entries should be blocked, False if entries are allowed
        """
        est_tz = pytz.timezone("America/New_York")
        current_time_est = datetime.now(est_tz)
        current_hour = current_time_est.hour
        current_minute = current_time_est.minute

        # Block entries after max_entry_hour_et (e.g., after 3PM = hour 16+)
        if current_hour > cls.max_entry_hour_et:
            return True

        # Block entries in the last 5 minutes of the allowed hour (e.g., 3:55-3:59 PM)
        if (
            current_hour == cls.max_entry_hour_et
            and current_minute >= cls.max_entry_minute_et
        ):
            return True

        return False

    @classmethod
    def _filter_bars_after_entry(
        cls, bars: List[Dict[str, Any]], created_at: str
    ) -> List[Dict[str, Any]]:
        """
        Filter bars to only include those with timestamps after trade entry.

        Args:
            bars: List of bar dictionaries with 't' (timestamp) and 'c' (close) keys
            created_at: ISO timestamp string when trade was created

        Returns:
            List of bars with timestamps after created_at
        """
        if not bars or not created_at:
            return []

        try:
            # Parse the entry timestamp
            entry_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)

            filtered_bars = []
            for bar in bars:
                if not isinstance(bar, dict):
                    continue

                bar_timestamp_str = bar.get("t")
                if not bar_timestamp_str:
                    continue

                try:
                    # Parse bar timestamp
                    if isinstance(bar_timestamp_str, str):
                        bar_time = datetime.fromisoformat(
                            bar_timestamp_str.replace("Z", "+00:00")
                        )
                        if bar_time.tzinfo is None:
                            bar_time = bar_time.replace(tzinfo=timezone.utc)
                    else:
                        continue

                    # Only include bars AFTER entry time
                    if bar_time > entry_time:
                        filtered_bars.append(bar)
                except (ValueError, TypeError):
                    continue

            return filtered_bars
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing entry timestamp '{created_at}': {e}")
            return []

    @classmethod
    def _should_trigger_profit_taking_exit(
        cls,
        profit_from_entry: float,
        dip_or_rise_percent: float,
        holding_seconds: float,
        is_long: bool,
    ) -> Tuple[bool, str]:
        """
        Determine if profit-taking exit should trigger.

        This method implements the fixed exit logic that prevents premature exits:
        1. Requires positive profit (profit_from_entry > 0)
        2. Requires minimum profit threshold (>= 0.5%)
        3. Requires minimum holding time (>= 60 seconds)
        4. Uses wider dip/rise threshold (1.0% instead of 0.5%)

        Args:
            profit_from_entry: Current profit percentage from entry price
            dip_or_rise_percent: Percentage dip from peak (long) or rise from bottom (short)
                                 Should be positive for dip (long) and positive for rise (short)
            holding_seconds: Seconds since trade entry
            is_long: True for long trades, False for short trades

        Returns:
            Tuple of (should_exit: bool, reason: str)
        """
        direction = "long" if is_long else "short"
        exit_type = "dip from peak" if is_long else "rise from bottom"

        # Check 1: Must have positive profit
        if profit_from_entry <= 0:
            reason = (
                f"Skipping {exit_type} exit for {direction}: "
                f"profit {profit_from_entry:.2f}% is not positive (required > 0%)"
            )
            logger.debug(reason)
            return False, reason

        # Check 2: Must meet minimum profit threshold
        if profit_from_entry < cls.min_profit_for_profit_taking_exit:
            reason = (
                f"Skipping {exit_type} exit for {direction}: "
                f"profit {profit_from_entry:.2f}% below minimum threshold "
                f"{cls.min_profit_for_profit_taking_exit:.2f}%"
            )
            logger.debug(reason)
            return False, reason

        # Check 3: Must meet minimum holding time
        if holding_seconds < cls.min_holding_seconds_for_profit_taking:
            reason = (
                f"Skipping {exit_type} exit for {direction}: "
                f"holding time {holding_seconds:.0f}s below minimum "
                f"{cls.min_holding_seconds_for_profit_taking}s"
            )
            logger.debug(reason)
            return False, reason

        # Check 4: Dip/rise must exceed threshold (1.0%)
        if dip_or_rise_percent < cls.dip_rise_threshold_percent:
            reason = (
                f"Skipping {exit_type} exit for {direction}: "
                f"{exit_type} {dip_or_rise_percent:.2f}% below threshold "
                f"{cls.dip_rise_threshold_percent:.2f}%"
            )
            logger.debug(reason)
            return False, reason

        # All checks passed - trigger exit
        reason = (
            f"💰 PROFIT EXIT ({direction}): {exit_type} {dip_or_rise_percent:.2f}% "
            f"(threshold: {cls.dip_rise_threshold_percent:.2f}%), "
            f"profit from entry: {profit_from_entry:.2f}%, "
            f"held for {holding_seconds:.0f}s"
        )
        logger.info(reason)
        return True, reason

    @classmethod
    def _calculate_atr_percent(cls, atr: float, current_price: float) -> float:
        """Calculate ATR as percentage of current price"""
        if current_price <= 0 or atr is None or atr <= 0:
            return 0.0
        return (atr / current_price) * 100

    @classmethod
    def _calculate_trailing_stop_activation(
        cls, profit_percent: float, stop_loss: float
    ) -> Optional[float]:
        """Dynamic trailing stop that tightens as profit increases"""
        stop_distance = abs(stop_loss)

        if profit_percent < 0.5:
            return None  # No trailing stop yet
        elif profit_percent < stop_distance * 0.5:  # Less than 50% of target
            return stop_distance * 0.8  # Wide trailing (80% of stop distance)
        elif profit_percent < stop_distance:  # Less than 100% of target
            return stop_distance * 0.5  # Medium trailing
        else:  # Beyond stop distance in profit
            return stop_distance * 0.3  # Tight trailing to lock in gains

    @classmethod
    def _calculate_volatility_adjusted_trailing_stop(
        cls,
        enter_price: float,
        atr: float,
        current_price: float,
    ) -> float:
        """
        Calculate trailing stop based on ATR instead of fixed percentage.
        For penny stocks, use 2-3x ATR as trailing stop distance.
        This gives volatile stocks more room to breathe.
        """
        if enter_price <= 0 or atr is None or atr <= 0 or current_price <= 0:
            return cls.trailing_stop_percent

        # Calculate ATR as percentage of price
        atr_percent = cls._calculate_atr_percent(atr, current_price)

        # Use standardized ATR multiplier for trailing stop, with min/max bounds
        trailing_stop = atr_percent * ATR_TRAILING_STOP_MULTIPLIER_LEGACY

        # Bounds: minimum 2%, maximum 8% for penny stocks
        # Use consistent threshold with max_stock_price_for_penny_treatment
        if enter_price < cls.max_stock_price_for_penny_treatment:
            trailing_stop = max(3.0, min(8.0, trailing_stop))
        else:
            trailing_stop = max(2.0, min(5.0, trailing_stop))

        return trailing_stop

    @classmethod
    def _calculate_volatility_score(
        cls, technical_analysis: Dict[str, Any], current_price: float
    ) -> Tuple[float, str]:
        """
        Calculate volatility score based on ATR and other indicators.
        Returns (volatility_score, reason) where score is ATR% of price.
        """
        atr = technical_analysis.get("atr", 0.0)
        atr_percent = cls._calculate_atr_percent(atr, current_price)

        # Also consider Bollinger Band width as volatility indicator
        bollinger = technical_analysis.get("bollinger", {})
        if isinstance(bollinger, dict):
            upper = bollinger.get("upper", 0.0) or 0.0
            lower = bollinger.get("lower", 0.0) or 0.0
            middle = bollinger.get("middle", current_price) or current_price
            # Ensure all values are numbers and middle > 0 before using them
            if (
                isinstance(upper, (int, float))
                and isinstance(lower, (int, float))
                and isinstance(middle, (int, float))
                and middle > 0
            ):
                bb_width_percent = ((upper - lower) / middle) * 100
                # Use the higher of ATR% or BB width% as volatility measure
                volatility_score = max(atr_percent, bb_width_percent * 0.5)
            else:
                volatility_score = atr_percent
        else:
            volatility_score = atr_percent

        reason = f"ATR: {atr_percent:.2f}%"
        return volatility_score, reason

    @classmethod
    async def _check_bid_ask_spread(
        cls, ticker: str, enter_price: float
    ) -> Tuple[bool, float, str]:
        """
        Check if bid-ask spread is acceptable for entry.
        Returns (is_acceptable, spread_percent, reason)
        """
        try:
            quote_response = await AlpacaClient.quote(ticker)
            if not quote_response:
                return True, 0.0, "No quote data available, proceeding"

            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})

            bid = ticker_quote.get("bp", 0.0)  # Bid price
            ask = ticker_quote.get("ap", 0.0)  # Ask price

            if bid <= 0 or ask <= 0:
                return True, 0.0, "Invalid bid/ask data, proceeding"

            spread = ask - bid
            spread_percent = (spread / enter_price) * 100 if enter_price > 0 else 0.0

            # For low-priced stocks, be more lenient with spread
            max_spread = cls.max_bid_ask_spread_percent
            if enter_price < cls.max_stock_price_for_penny_treatment:
                max_spread = cls.max_bid_ask_spread_percent * 1.5  # 50% more lenient

            is_acceptable = spread_percent <= max_spread
            reason = (
                f"Spread: {spread_percent:.2f}% "
                f"{'acceptable' if is_acceptable else f'(exceeds {max_spread:.2f}% limit)'}"
            )

            return is_acceptable, spread_percent, reason
        except Exception as e:
            logger.debug(f"Error checking bid-ask spread for {ticker}: {str(e)}")
            return True, 0.0, f"Error checking spread: {str(e)}, proceeding"

    @classmethod
    async def _calculate_dynamic_stop_loss(
        cls,
        ticker: str,
        enter_price: float,
        technical_analysis: Optional[Dict[str, Any]] = None,
        action: Optional[str] = None,
    ) -> float:
        """
        Calculate dynamic stop loss based on 2x ATR as recommended by judge.
        Long: enter_price - 2*ATR
        Short: enter_price + 2*ATR

        Args:
            ticker: Stock ticker symbol
            enter_price: Entry price for the trade
            technical_analysis: Technical indicators including ATR
            action: Trade action ('buy_to_open' or 'sell_to_open') to determine direction

        Returns:
            Dynamic stop loss percentage (negative value, e.g., -3.5 for -3.5%)
        """
        # Default stop loss if we can't calculate dynamic one
        default_stop_loss = cls.stop_loss_threshold

        # Use ATR if available (preferred method) - use 2x ATR as recommended
        if technical_analysis:
            atr = technical_analysis.get("atr", 0.0)
            if atr is not None and atr > 0 and enter_price > 0:
                atr_percent = cls._calculate_atr_percent(atr, enter_price)

                # Use standardized ATR multiplier for stop loss
                dynamic_stop_loss = -(atr_percent * ATR_STOP_LOSS_MULTIPLIER)

                # Cap at reasonable levels to prevent excessive risk
                # Uses centralized bounds from trading_config.py
                is_low_price = enter_price < cls.max_stock_price_for_penny_treatment
                if is_low_price:
                    dynamic_stop_loss = max(PENNY_STOCK_STOP_LOSS_MIN, min(PENNY_STOCK_STOP_LOSS_MAX, dynamic_stop_loss))
                else:
                    dynamic_stop_loss = max(STANDARD_STOCK_STOP_LOSS_MIN, min(STANDARD_STOCK_STOP_LOSS_MAX, dynamic_stop_loss))

                logger.info(
                    f"ATR-based stop loss (2x ATR) for {ticker}: {dynamic_stop_loss:.2f}% "
                    f"(ATR: {atr_percent:.2f}%, enter_price: ${enter_price:.2f}, "
                    f"action: {action or 'unknown'})"
                )
                return dynamic_stop_loss

        # Fallback to Alpaca API for stocks under $5 if ATR not available
        if enter_price >= cls.max_stock_price_for_penny_treatment:
            return default_stop_loss

        try:
            # Fetch intraday bars using AlpacaClient.get_market_data()
            # This will get latest 200 bars (or up to 1000 if we need more)
            bars_data = await AlpacaClient.get_market_data(ticker, limit=1000)

            if not bars_data:
                logger.debug(
                    f"No bars data from AlpacaClient for {ticker}, using default stop loss"
                )
                return default_stop_loss

            bars_dict = bars_data.get("bars", {})
            bars = bars_dict.get(ticker, [])

            if not bars or len(bars) < 5:
                logger.debug(
                    f"Insufficient bars data for {ticker} ({len(bars) if bars else 0} bars), using default stop loss"
                )
                return default_stop_loss

            # Extract prices from bars
            prices = []
            for bar in bars:
                if not isinstance(bar, dict):
                    logger.debug(f"Skipping invalid bar entry for {ticker}: not a dict")
                    continue
                # Alpaca bars format: {"t": timestamp, "o": open, "h": high, "l": low, "c": close, "v": volume, "vw": vwap, "n": trades}
                try:
                    close_price = bar.get("c")
                    if close_price is not None:
                        close_price = float(close_price)
                        if close_price > 0:
                            prices.append(close_price)
                except (ValueError, TypeError) as price_error:
                    logger.debug(
                        f"Skipping bar with invalid close price for {ticker}: {str(price_error)}"
                    )
                    continue

            if len(prices) < 5:
                logger.debug(
                    f"Insufficient valid prices for {ticker}, using default stop loss"
                )
                return default_stop_loss

            # Calculate volatility metrics
            min_price = min(prices)
            max_price = max(prices)
            price_range = max_price - min_price
            price_range_pct = (price_range / min_price) * 100 if min_price > 0 else 0

            # Calculate average true range (ATR) approximation
            # Use high-low ranges for volatility
            high_low_ranges = []
            for bar in bars:
                if not isinstance(bar, dict):
                    continue
                try:
                    high = bar.get("h")
                    low = bar.get("l")
                    if high is not None and low is not None:
                        high = float(high)
                        low = float(low)
                        if high > 0 and low > 0:
                            high_low_ranges.append((high - low) / low * 100)
                except (ValueError, TypeError) as vol_error:
                    logger.debug(
                        f"Skipping bar for volatility calculation for {ticker}: {str(vol_error)}"
                    )
                    continue

            avg_volatility = (
                sum(high_low_ranges) / len(high_low_ranges) if high_low_ranges else 0
            )

            # Calculate recent volatility (last 30 minutes)
            recent_bars = bars[-30:] if len(bars) >= 30 else bars
            recent_high_low_ranges = []
            for bar in recent_bars:
                if not isinstance(bar, dict):
                    continue
                try:
                    high = bar.get("h")
                    low = bar.get("l")
                    if high is not None and low is not None:
                        high = float(high)
                        low = float(low)
                        if high > 0 and low > 0:
                            recent_high_low_ranges.append((high - low) / low * 100)
                except (ValueError, TypeError) as vol_error:
                    logger.debug(
                        f"Skipping recent bar for volatility calculation for {ticker}: {str(vol_error)}"
                    )
                    continue

            recent_volatility = (
                sum(recent_high_low_ranges) / len(recent_high_low_ranges)
                if recent_high_low_ranges
                else 0
            )

            # Use the higher of average or recent volatility
            volatility = max(avg_volatility, recent_volatility)

            # Calculate dynamic stop loss:
            # - Base: 2.5% (default)
            # - Add 50% of daily price range percentage
            # - Add 50% of volatility
            # - Cap at -7% maximum (to prevent excessive losses)
            # - Minimum of -3.5% for penny stocks (give them more room than default)
            dynamic_stop_loss = -2.5 - (price_range_pct * 0.5) - (volatility * 0.5)
            dynamic_stop_loss = max(-7.0, min(-3.5, dynamic_stop_loss))

            logger.info(
                f"Dynamic stop loss for {ticker}: {dynamic_stop_loss:.2f}% "
                f"(price_range: {price_range_pct:.2f}%, volatility: {volatility:.2f}%, "
                f"enter_price: ${enter_price:.2f})"
            )

            return dynamic_stop_loss

        except Exception as e:
            logger.warning(
                f"Error calculating dynamic stop loss for {ticker}: {str(e)}, using default"
            )
            return default_stop_loss

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
    def _is_golden_ticker(
        cls, momentum_score: float, market_data: Dict[str, Any]
    ) -> bool:
        """
        Check if ticker is a "golden" opportunity with exceptional momentum or technical indicators
        Golden tickers can bypass daily trade limits
        More stringent requirements for penny stocks to avoid false signals
        """
        # market_data IS the technical analysis dict (from calculate_all_indicators)
        technical_analysis = market_data if isinstance(market_data, dict) else {}
        current_price = technical_analysis.get("close_price", 0.0)
        abs_momentum = abs(momentum_score)

        # For penny stocks (< $3), require MUCH higher thresholds
        if current_price < cls.max_stock_price_for_penny_treatment:
            # Require exceptional momentum AND volume confirmation
            volume = technical_analysis.get("volume", 0)
            volume_sma = technical_analysis.get("volume_sma", 1)
            volume_ratio = volume / volume_sma if volume_sma > 0 else 0

            # Need 3x average volume AND >8% momentum for penny stock golden
            if abs_momentum >= 8.0 and volume_ratio >= 3.0:
                adx = technical_analysis.get("adx", 0)
                if adx >= 30:  # Strong trend confirmation
                    # Additional check: not at Bollinger Band extremes (avoid mean reversion)
                    bollinger = technical_analysis.get("bollinger", {})
                    if isinstance(bollinger, dict):
                        upper = bollinger.get("upper", 0)
                        lower = bollinger.get("lower", 0)
                        if upper > 0 and lower > 0 and current_price > 0:
                            band_width = upper - lower
                            if band_width > 0:
                                position_in_band = (current_price - lower) / band_width
                                # Don't mark as golden if at extreme (>90% for long, <10% for short)
                                is_long = momentum_score > 0
                                if is_long and position_in_band > 0.90:
                                    return False
                                if not is_long and position_in_band < 0.10:
                                    return False
                    return True
            return False

        # Original logic for non-penny stocks
        if abs_momentum >= cls.exceptional_momentum_threshold:
            return True

        # Exceptional technical indicators
        adx = technical_analysis.get("adx")
        rsi = technical_analysis.get("rsi", 50.0)

        # Very strong trend (ADX > 40) with perfect RSI conditions
        if adx and adx > 40:
            is_long = momentum_score > 0
            is_short = momentum_score < 0

            if is_long and rsi < 25:  # Very oversold
                return True
            if is_short and rsi > 75:  # Very overbought
                return True

        return False

    @classmethod
    def _is_likely_mean_reverting(
        cls,
        market_data: Dict[str, Any],
        momentum_score: float,
    ) -> Tuple[bool, str]:
        """
        Check if the stock is likely to mean-revert soon.
        Reject entries at Bollinger Band extremes to avoid entering at peaks/troughs.
        Also reject parabolic extensions (price far from EMAs).
        """
        # FIXED: market_data IS the technical analysis dict directly
        technical_analysis = market_data if isinstance(market_data, dict) else {}
        bollinger = technical_analysis.get("bollinger", {})
        current_price = technical_analysis.get("close_price", 0.0)

        if not isinstance(bollinger, dict):
            return False, "No Bollinger data"

        upper = bollinger.get("upper", 0)
        lower = bollinger.get("lower", 0)

        if upper <= 0 or lower <= 0 or current_price <= 0:
            return False, "Invalid Bollinger data"

        # Check if price is at Bollinger Band extremes
        band_width = upper - lower
        if band_width > 0:
            position_in_band = (current_price - lower) / band_width

            # For LONG entries, reject if price is already at upper band (>90%)
            if momentum_score > 0 and position_in_band > 0.90:
                return (
                    True,
                    f"Price at upper Bollinger ({position_in_band:.0%}), likely to revert",
                )

            # For SHORT entries, reject if price is already at lower band (<10%)
            if momentum_score < 0 and position_in_band < 0.10:
                return (
                    True,
                    f"Price at lower Bollinger ({position_in_band:.0%}), likely to revert",
                )

        # NEW: Check for parabolic extension from EMAs
        # Reject if price is too far from moving averages (likely to snap back)
        ema_fast = technical_analysis.get("ema_fast", 0.0)
        ema_slow = technical_analysis.get("ema_slow", 0.0)

        if ema_fast > 0 and current_price > 0:
            ema_deviation_percent = ((current_price - ema_fast) / ema_fast) * 100

            # For SHORTS: Reject if price is >10% ABOVE EMA (parabolic squeeze, will keep running)
            if momentum_score < 0 and ema_deviation_percent > 10.0:
                return (
                    True,
                    f"Parabolic extension for short: price ${current_price:.2f} is {ema_deviation_percent:.1f}% above EMA ${ema_fast:.2f} (squeeze in progress, don't short)",
                )

            # For LONGS: Reject if price is >10% ABOVE EMA (chasing extended move)
            if momentum_score > 0 and ema_deviation_percent > 10.0:
                return (
                    True,
                    f"Extended move for long: price ${current_price:.2f} is {ema_deviation_percent:.1f}% above EMA ${ema_fast:.2f} (too extended, wait for pullback)",
                )

            # For LONGS: Reject if price is >5% BELOW EMA (falling knife)
            if momentum_score > 0 and ema_deviation_percent < -5.0:
                return (
                    True,
                    f"Falling knife for long: price ${current_price:.2f} is {abs(ema_deviation_percent):.1f}% below EMA ${ema_fast:.2f} (wait for stabilization)",
                )

        return False, "Not at Bollinger extremes"

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

        # market_data IS the technical analysis dict (from calculate_all_indicators)
        technical_analysis = market_data if isinstance(market_data, dict) else {}
        current_price = technical_analysis.get("close_price", 0.0)

        # Check minimum price filter
        if current_price < cls.min_stock_price:
            return (
                False,
                f"Price too low: ${current_price:.2f} < ${cls.min_stock_price:.2f} minimum (too risky)",
            )

        # Check volatility for low-priced stocks
        is_low_price = current_price < cls.max_stock_price_for_penny_treatment
        volatility_score, volatility_reason = cls._calculate_volatility_score(
            technical_analysis, current_price
        )

        if is_low_price:
            # For penny stocks, we WANT high volatility - it's our edge! No filter here.
            # Only filter out extreme cases (>50% ATR) to avoid complete chaos
            if volatility_score > cls.max_volatility_for_low_price:
                return (
                    False,
                    f"Extreme volatility for penny stock: {volatility_reason} "
                    f"(exceeds {cls.max_volatility_for_low_price:.2f}% limit - too chaotic even for aggressive trading)",
                )
            # Log that we're allowing high volatility for penny stocks
            if volatility_score > 4.0:  # Log when volatility is above old threshold
                logger.info(
                    f"💰 Allowing high volatility penny stock {ticker}: {volatility_reason} "
                    f"(volatility: {volatility_score:.2f}% - banking on volatility for quick profits)"
                )
        else:
            # Standard volatility filter for higher-priced stocks
            if volatility_score > cls.max_atr_percent_for_entry:
                return (
                    False,
                    f"Too volatile: {volatility_reason} "
                    f"(exceeds {cls.max_atr_percent_for_entry:.2f}% limit)",
                )

        volume = technical_analysis.get("volume", 0)
        volume_sma = technical_analysis.get("volume_sma", 0)
        avg_volume = volume_sma if volume_sma > 0 else volume

        if avg_volume < cls.min_daily_volume:
            return (
                False,
                f"Volume too low: {avg_volume:,} < {cls.min_daily_volume:,} minimum",
            )

        # Check volume ratio (must be >1.5x SMA as recommended by judge)
        volume_ratio = volume / volume_sma if volume_sma > 0 else 0
        if volume_ratio < cls.min_volume_ratio:
            return (
                False,
                f"Volume ratio too low: {volume_ratio:.2f}x < {cls.min_volume_ratio}x SMA "
                f"(volume: {volume:,}, SMA: {volume_sma:,})",
            )

        # NEW: Validate indicator data quality - reject if data looks stale/broken
        stoch_data = technical_analysis.get("stoch", {})
        if isinstance(stoch_data, dict):
            stoch_k = stoch_data.get("k", 50.0)
            stoch_d = stoch_data.get("d", 50.0)
        elif isinstance(stoch_data, (list, tuple)) and len(stoch_data) >= 2:
            stoch_k = stoch_data[0] if stoch_data[0] is not None else 50.0
            stoch_d = stoch_data[1] if stoch_data[1] is not None else 50.0
        else:
            stoch_k = 50.0
            stoch_d = 50.0

        # Reject if stochastic is exactly 0 or 100 (likely broken data)
        if stoch_k == 0 and stoch_d == 0:
            return (
                False,
                f"Stochastic data appears broken (K={stoch_k}, D={stoch_d}) - skipping",
            )

        # Reject if Bollinger bands are flat (no volatility data)
        bollinger = technical_analysis.get("bollinger", {})
        if isinstance(bollinger, dict):
            bb_upper = bollinger.get("upper", 0)
            bb_lower = bollinger.get("lower", 0)
            bb_middle = bollinger.get("middle", 0)
        elif isinstance(bollinger, (list, tuple)) and len(bollinger) >= 3:
            bb_upper = bollinger[0] if bollinger[0] is not None else 0
            bb_middle = bollinger[1] if bollinger[1] is not None else 0
            bb_lower = bollinger[2] if bollinger[2] is not None else 0
        else:
            bb_upper = bb_lower = bb_middle = 0

        if bb_upper > 0 and bb_lower > 0 and abs(bb_upper - bb_lower) < 0.001:
            return (
                False,
                f"Bollinger bands are flat (upper={bb_upper:.4f}, lower={bb_lower:.4f}) - insufficient volatility data",
            )

        adx = technical_analysis.get("adx")
        if adx is None:
            return False, "Missing ADX data"

        if adx < cls.min_adx_threshold:
            return (
                False,
                f"ADX too low: {adx:.2f} < {cls.min_adx_threshold} (no strong trend)",
            )

        rsi = technical_analysis.get("rsi", 50.0)
        mfi = technical_analysis.get("mfi", 50.0)  # Money Flow Index
        is_long = momentum_score > 0
        is_short = momentum_score < 0

        # For momentum longs, you want RSI showing strength but not exhaustion
        if is_long and (rsi < cls.rsi_min_for_long or rsi > cls.rsi_max_for_long):
            return (
                False,
                f"RSI {rsi:.1f} outside acceptable range [{cls.rsi_min_for_long}-{cls.rsi_max_for_long}] for long entry",
            )

        # For shorts, we want to avoid shorting oversold stocks (RSI < 50) as they may bounce
        # But we allow shorting stocks with declining momentum even if RSI is moderate (50+)
        if is_short and rsi < cls.rsi_min_for_short:
            return (
                False,
                f"RSI too low for short: {rsi:.2f} < {cls.rsi_min_for_short} (may be oversold, risk of bounce)",
            )

        # MFI (Money Flow Index) filter - avoid extreme money flow conditions
        # MFI < 20 = extreme selling pressure (falling knife for longs)
        # MFI > 80 = extreme buying pressure (exhaustion for longs, squeeze for shorts)
        if is_long:
            if mfi < cls.mfi_min_for_long:
                return (
                    False,
                    f"MFI too low for long: {mfi:.1f} < {cls.mfi_min_for_long} (extreme selling pressure, falling knife)",
                )
            if mfi > cls.mfi_max_for_long:
                return (
                    False,
                    f"MFI too high for long: {mfi:.1f} > {cls.mfi_max_for_long} (buying exhaustion, likely reversal)",
                )

        if is_short:
            if mfi < cls.mfi_min_for_short:
                return (
                    False,
                    f"MFI too low for short: {mfi:.1f} < {cls.mfi_min_for_short} (already oversold, risk of bounce)",
                )
            if mfi > cls.mfi_max_for_short:
                return (
                    False,
                    f"MFI too high for short: {mfi:.1f} > {cls.mfi_max_for_short} (parabolic squeeze in progress)",
                )

        # NOTE: RSI > 75 filter for shorts removed — overbought stocks ARE good short candidates.
        # The MFI > 80 filter (above) already catches parabolic squeezes via money flow.
        # Rejecting RSI > 75 shorts was contradictory: high RSI means overbought = short opportunity.

        # Check stochastic confirmation (prevent entering during wrong momentum phase)
        stoch = technical_analysis.get("stoch", {})
        if isinstance(stoch, dict):
            # Handle dict format with "k" and "d" keys
            stoch_k_raw = stoch.get("k")
            stoch_d_raw = stoch.get("d")
            stoch_k = stoch_k_raw if stoch_k_raw is not None else 50.0
            stoch_d = stoch_d_raw if stoch_d_raw is not None else 50.0
        elif isinstance(stoch, (list, tuple)) and len(stoch) >= 2:
            # Handle list/tuple format [K, D] - this is the actual format from TechnicalAnalysisLib
            stoch_k = stoch[0] if stoch[0] is not None else 50.0
            stoch_d = stoch[1] if stoch[1] is not None else 50.0
        else:
            stoch_k = 50.0
            stoch_d = 50.0

        if is_short:
            # Don't short if stochastic is still bullish (K > D means upward momentum present)
            # This prevents shorting during active bullish momentum crossovers
            if stoch_k > stoch_d:
                return (
                    False,
                    f"Stochastic not bearish for short: K={stoch_k:.2f} > D={stoch_d:.2f} (upward momentum still present)",
                )

        if is_long:
            # Don't buy if stochastic is overbought (K > 80) - likely at a top
            # This prevents buying into exhausted rallies
            if stoch_k > 80.0:
                return (
                    False,
                    f"Stochastic overbought for long: K={stoch_k:.2f} > 80 (buying exhaustion, likely reversal)",
                )
            # Don't buy if stochastic is bearish (K < D means downward momentum present)
            if stoch_k < stoch_d and stoch_k < 30.0:
                return (
                    False,
                    f"Stochastic bearish for long: K={stoch_k:.2f} < D={stoch_d:.2f} with K < 30 (downward momentum present)",
                )

        # CCI (Commodity Channel Index) filter - avoid extreme readings
        # CCI > 200 = extremely overbought (don't buy), CCI < -200 = extremely oversold (don't short)
        # CCI > 100 with short = bullish momentum (don't short into strength)
        cci = technical_analysis.get("cci", 0.0)
        if cci is not None:
            if is_long and cci > 200.0:
                return (
                    False,
                    f"CCI extremely overbought for long: {cci:.1f} > 200 (price extended, likely reversal)",
                )
            if is_short and cci < -200.0:
                return (
                    False,
                    f"CCI extremely oversold for short: {cci:.1f} < -200 (price extended, likely bounce)",
                )
            # Don't short when CCI shows strong bullish momentum
            if is_short and cci > 100.0:
                return (
                    False,
                    f"CCI bullish for short: {cci:.1f} > 100 (strong upward momentum, don't short into strength)",
                )

        # Check for mean reversion risk (Bollinger Band extremes)
        is_mean_reverting, mean_revert_reason = cls._is_likely_mean_reverting(
            market_data, momentum_score
        )
        if is_mean_reverting:
            return False, mean_revert_reason

        return (
            True,
            f"Passed all quality filters (ADX: {adx:.2f}, RSI: {rsi:.2f}, {volatility_reason})",
        )

    @classmethod
    def _confirm_trend_structure(
        cls, prices: List[float], is_long: bool
    ) -> Tuple[bool, str]:
        """Confirm trend structure with swing highs/lows"""
        if len(prices) < 10:
            return True, "Insufficient data for structure check"

        # Find local peaks and troughs (simplified)
        recent_prices = prices[-20:] if len(prices) >= 20 else prices
        mid_idx = len(recent_prices) // 2

        first_half_high = max(recent_prices[:mid_idx])
        first_half_low = min(recent_prices[:mid_idx])
        second_half_high = max(recent_prices[mid_idx:])
        second_half_low = min(recent_prices[mid_idx:])

        if is_long:
            # Uptrend: higher highs AND higher lows
            if second_half_high > first_half_high and second_half_low > first_half_low:
                return True, "Uptrend confirmed: HH + HL"
            return False, "No clear uptrend structure"
        else:
            # Downtrend: lower highs AND lower lows
            if second_half_high < first_half_high and second_half_low < first_half_low:
                return True, "Downtrend confirmed: LH + LL"
            return False, "No clear downtrend structure"

    @classmethod
    def _calculate_momentum(cls, datetime_price: Any) -> Tuple[float, str]:
        """
        Calculate price momentum score from datetime_price.

        Args:
            datetime_price: Either a dict mapping timestamp strings to prices,
                          or a list of entries (legacy format)

        Returns:
            Tuple of (momentum_score, reason_string)
        """
        logger.debug(
            f"_calculate_momentum called with type: {type(datetime_price).__name__}, empty: {not datetime_price}"
        )

        if not datetime_price:
            return 0.0, "Insufficient price data"

        prices = []

        # Handle dictionary format (current format from TechnicalAnalysisLib)
        if isinstance(datetime_price, dict):
            logger.debug(
                f"Processing datetime_price as dictionary with {len(datetime_price)} entries"
            )
            try:
                # Extract (timestamp, price) pairs and sort by timestamp
                timestamp_price_pairs = []
                for timestamp_str, price in datetime_price.items():
                    try:
                        # Parse ISO timestamp
                        from datetime import datetime

                        if isinstance(timestamp_str, str):
                            # Handle various timestamp formats
                            if timestamp_str.endswith("Z"):
                                dt = datetime.fromisoformat(
                                    timestamp_str.replace("Z", "+00:00")
                                )
                            else:
                                dt = datetime.fromisoformat(timestamp_str)
                        else:
                            logger.debug(
                                f"Skipping non-string timestamp key: {type(timestamp_str)}"
                            )
                            continue

                        # Validate price
                        if (
                            price is not None
                            and isinstance(price, (int, float))
                            and price > 0
                        ):
                            timestamp_price_pairs.append((dt, float(price)))
                        else:
                            logger.debug(f"Skipping invalid price: {price}")
                    except (ValueError, TypeError) as e:
                        logger.debug(
                            f"Skipping invalid timestamp/price pair: {timestamp_str}={price}, error: {e}"
                        )
                        continue

                # Sort by timestamp (chronological order)
                timestamp_price_pairs.sort(key=lambda x: x[0])

                # Extract prices in chronological order
                prices = [price for _, price in timestamp_price_pairs]

                logger.debug(
                    f"Extracted {len(prices)} valid prices from dictionary in chronological order"
                )
                if prices:
                    logger.debug(f"Price range: {min(prices):.4f} to {max(prices):.4f}")

            except Exception as e:
                logger.warning(f"Error processing datetime_price dictionary: {e}")
                return 0.0, f"Error processing datetime_price dictionary: {str(e)}"

        # Handle list format (legacy format)
        elif isinstance(datetime_price, list):
            logger.debug(
                f"Processing datetime_price as list with {len(datetime_price)} entries"
            )
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

        # Handle tuple format (legacy or default indicators)
        elif isinstance(datetime_price, tuple):
            logger.debug(
                f"Processing datetime_price as tuple with {len(datetime_price)} entries"
            )
            for entry in datetime_price:
                try:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        price = entry[1]
                        if (
                            price is not None
                            and isinstance(price, (int, float))
                            and price > 0
                        ):
                            prices.append(float(price))
                except (ValueError, TypeError, IndexError):
                    continue

        # Handle unexpected format
        else:
            logger.warning(f"Unexpected datetime_price format: {type(datetime_price)}")
            return (
                0.0,
                f"Invalid datetime_price format: {type(datetime_price).__name__}",
            )

        # Check if we have enough data
        if len(prices) < 3:
            logger.debug(
                f"Insufficient price data: only {len(prices)} prices available (need at least 3)"
            )
            return 0.0, "Insufficient price data"

        # Calculate momentum using early vs recent average comparison
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

        reason = f"Momentum: {change_percent:.2f}% change, {trend_percent:.2f}% trend (early_avg: {early_avg:.2f}, recent_avg: {recent_avg:.2f}, n={n}, early_prices_count={len(early_prices)}, recent_prices_count={len(recent_prices)})"

        logger.debug(f"Momentum calculation: {reason}")
        logger.debug(
            f"Early prices sample: {early_prices[:3] if len(early_prices) > 0 else 'empty'}"
        )
        logger.debug(
            f"Recent prices sample: {recent_prices[-3:] if len(recent_prices) > 0 else 'empty'}"
        )

        return momentum_score, reason

    # Minimum holding time before a trade can be preempted (in seconds)
    min_holding_before_preempt_seconds: int = (
        60  # Don't preempt trades held less than 60 seconds
    )

    @classmethod
    async def _find_lowest_profitable_trade(
        cls, active_trades: List[Dict[str, Any]]
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        """Find the lowest profitable trade from active trades that can be preempted.

        Only considers trades that:
        1. Are currently profitable (>= profit_threshold)
        2. Have been held for at least min_holding_before_preempt_seconds
        """
        lowest_profit = None
        lowest_trade = None

        for trade in active_trades:
            ticker = trade.get("ticker")
            enter_price = trade.get("enter_price")
            action = trade.get("action")
            created_at = trade.get("created_at")

            if not ticker or enter_price is None or enter_price <= 0:
                continue

            # Check minimum holding time before allowing preemption
            # This prevents preempting trades that just entered (like ENVB after 2 seconds)
            passed_min_hold, holding_minutes = cls._check_holding_period(
                created_at, cls.min_holding_before_preempt_seconds
            )
            if not passed_min_hold:
                logger.debug(
                    f"Skipping {ticker} for preemption: held only {holding_minutes:.1f} min "
                    f"(need {cls.min_holding_before_preempt_seconds / 60:.1f} min)"
                )
                continue

            indicators = await TechnicalAnalysisLib.calculate_all_indicators(ticker)
            if not indicators:
                continue

            current_price = indicators.get("close_price", 0.0)

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

        indicators = await TechnicalAnalysisLib.calculate_all_indicators(ticker_to_exit)
        if not indicators:
            logger.warning(
                f"Failed to get technical indicators for {ticker_to_exit} for preemption"
            )
            return False

        initial_exit_price = indicators.get("close_price", 0.0)

        if initial_exit_price <= 0:
            logger.warning(f"Invalid exit price for {ticker_to_exit}")
            return False

        # Get latest quote right before exit using Alpaca API
        quote_response = await AlpacaClient.quote(ticker_to_exit)
        exit_price = None
        exit_quote_source = "none"

        if quote_response:
            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker_to_exit, {})
            is_long = original_action == "buy_to_open"
            if is_long:
                exit_price = ticker_quote.get("bp", 0.0)  # Bid price for long exit
            else:
                exit_price = ticker_quote.get("ap", 0.0)  # Ask price for short exit
            exit_quote_source = "alpaca"

        if exit_price is None or exit_price <= 0:
            # Fallback to initial_exit_price if quote fails
            exit_price = initial_exit_price
            logger.warning(
                f"Failed to get latest exit quote for {ticker_to_exit} from {exit_quote_source}, "
                f"using previously fetched price ${initial_exit_price:.4f}"
            )
        else:
            logger.debug(
                f"Using Alpaca quote for {ticker_to_exit} preempt exit: ${exit_price:.4f}"
            )

        reason = f"Preempted for exceptional trade: {lowest_profit:.2f}% profit"

        technical_indicators_for_enter = lowest_trade.get(
            "technical_indicators_for_enter"
        )
        technical_indicators_for_exit = indicators.copy()
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
                await cls._run_entry_cycle()
            except Exception as e:
                logger.exception(f"Error in momentum entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    def _extract_prices_from_datetime_price(
        cls, datetime_price: List[Any]
    ) -> List[float]:
        """Extract price values from datetime_price array."""
        prices = []
        for entry in datetime_price:
            try:
                if isinstance(entry, list) and len(entry) >= 2:
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
        return prices

    @classmethod
    def _extract_recent_avg_from_reason(cls, reason: str) -> Optional[float]:
        """
        Extract recent_avg price from reason string.
        Reason format: "Momentum: X% change, Y% trend (early_avg: A, recent_avg: B, ...)"
        """
        import re

        try:
            # Pattern to match "recent_avg: X.XX"
            match = re.search(r"recent_avg:\s*([\d.]+)", reason)
            if match:
                return float(match.group(1))
        except (ValueError, AttributeError):
            pass
        return None

    @classmethod
    def _check_immediate_momentum_for_entry(
        cls, bars: List[Dict[str, Any]], is_long: bool
    ) -> bool:
        """
        Check if the most recent 2-3 bars still show momentum in the correct direction.
        This catches reversals that happened between momentum calculation and entry.

        Args:
            bars: List of price bars with 'c' (close) key
            is_long: True for long positions (check upward momentum), False for short

        Returns:
            True if immediate momentum is valid, False if reversal detected
        """
        if not bars or len(bars) < 2:
            return True  # If insufficient data, don't block entry

        # Get last 2-3 bars for immediate check
        recent_bars = bars[-3:] if len(bars) >= 3 else bars[-2:]
        prices = []
        for bar in recent_bars:
            try:
                close_price = bar.get("c") or bar.get("close") or bar.get("close_price")
                if close_price is not None:
                    prices.append(float(close_price))
            except (ValueError, TypeError):
                continue

        if len(prices) < 2:
            return True  # Insufficient data, don't block

        # Check if recent bars show continuation of trend
        # For longs: recent prices should be generally flat or rising (not falling)
        # For shorts: recent prices should be generally flat or falling (not rising)
        if is_long:
            # For longs: count how many bars show upward movement
            up_moves = sum(
                1 for i in range(1, len(prices)) if prices[i] > prices[i - 1]
            )
            down_moves = sum(
                1 for i in range(1, len(prices)) if prices[i] < prices[i - 1]
            )

            # If we have more down moves than up moves in recent bars, momentum may be reversing
            # Allow if at least 50% are up moves or flat, or if net change is positive
            net_change = prices[-1] - prices[0]
            if net_change < 0 and down_moves > up_moves:
                return False  # Reversal detected
        else:
            # For shorts: count how many bars show downward movement
            up_moves = sum(
                1 for i in range(1, len(prices)) if prices[i] > prices[i - 1]
            )
            down_moves = sum(
                1 for i in range(1, len(prices)) if prices[i] < prices[i - 1]
            )

            # If we have more up moves than down moves in recent bars, momentum may be reversing
            net_change = prices[-1] - prices[0]
            if net_change > 0 and up_moves > down_moves:
                return False  # Reversal detected

        return True  # Momentum still valid

    @classmethod
    def _calculate_confidence_score(
        cls,
        momentum_score: float,
        recent_avg: Optional[float],
        enter_price: float,
        spread_percent: float,
        volume: int,
        rank: int,
        is_golden: bool,
        technical_indicators: Optional[dict] = None,
    ) -> float:
        """
        Calculate confidence score (0.0 to 1.0) for momentum trading entry.

        Factors considered:
        1. Momentum score (higher = higher confidence)
        2. Distance from recent_avg (further below = higher confidence)
        3. Spread (lower spread = higher confidence)
        4. Volume (higher volume = higher confidence)
        5. Rank (lower rank = higher confidence)
        6. Golden status (golden = higher confidence)
        7. RSI (for longs: 50-65 = optimal, overbought/oversold = lower confidence)

        Args:
            momentum_score: Momentum score from calculation
            recent_avg: Recent average price (None if unavailable)
            enter_price: Entry price
            spread_percent: Bid-ask spread percentage
            volume: Trading volume
            rank: Ranking of this ticker (1 = best)
            is_golden: Whether this is a golden/exceptional ticker
            technical_indicators: Optional technical indicators dict

        Returns:
            Confidence score between 0.0 and 1.0
        """
        # Base score from momentum (normalize to 0-1 range)
        # Momentum: min_momentum_threshold = 1.5%, max_momentum_threshold = 15.0%
        min_momentum = cls.min_momentum_threshold  # 1.5%
        max_momentum = cls.max_momentum_threshold  # 15.0%
        momentum_normalized = min(
            1.0,
            max(
                0.0,
                (abs(momentum_score) - min_momentum) / (max_momentum - min_momentum),
            ),
        )

        # Recent average distance factor (further below = higher confidence)
        recent_avg_factor = 1.0
        if recent_avg and recent_avg > 0:
            price_below_recent_avg_percent = (
                (recent_avg - enter_price) / recent_avg
            ) * 100
            # Optimal: 1-3% below recent_avg = high confidence (1.0)
            # Too close (< 0.5%) = lower confidence (0.7)
            # Far below (> 5%) = lower confidence (0.8)
            if price_below_recent_avg_percent < 0.5:
                recent_avg_factor = 0.7  # Too close to recent_avg
            elif price_below_recent_avg_percent < 1.0:
                recent_avg_factor = 0.85
            elif price_below_recent_avg_percent <= 3.0:
                recent_avg_factor = 1.0  # Optimal range
            elif price_below_recent_avg_percent <= 5.0:
                recent_avg_factor = 0.9
            else:
                recent_avg_factor = 0.8  # Too far below

        # Spread factor (lower spread = higher confidence)
        max_spread = cls.max_bid_ask_spread_percent  # 3.0%
        spread_factor = max(0.5, 1.0 - (spread_percent / max_spread))  # 0.5 to 1.0

        # Volume factor (normalize volume, higher = better)
        min_volume = cls.min_daily_volume  # 1000
        volume_factor = min(1.0, max(0.5, volume / (min_volume * 5)))  # 0.5 to 1.0

        # Rank factor (rank 1 = 1.0, rank 2 = 0.9)
        rank_factor = 1.0 if rank == 1 else 0.9

        # Golden factor (golden = bonus confidence, applied after weighted sum)
        golden_factor = 1.1 if is_golden else 1.0  # 10% bonus for golden

        # RSI factor (for longs: 50-65 = optimal)
        rsi_factor = 1.0
        if technical_indicators:
            rsi = technical_indicators.get("rsi")
            if rsi is not None:
                # Optimal RSI range: 50-65 for longs
                if 50 <= rsi <= 65:
                    rsi_factor = 1.0  # Optimal
                elif 45 <= rsi < 50 or 65 < rsi <= 70:
                    rsi_factor = 0.9  # Good
                elif 40 <= rsi < 45 or 70 < rsi <= 75:
                    rsi_factor = 0.8  # Acceptable
                else:
                    rsi_factor = 0.7  # Less ideal

        # Weighted combination
        confidence = (
            momentum_normalized * 0.30  # 30% weight on momentum
            + recent_avg_factor * 0.25  # 25% weight on recent_avg distance
            + spread_factor * 0.20  # 20% weight on spread
            + volume_factor * 0.15  # 15% weight on volume
            + rank_factor * 0.05  # 5% weight on rank
            + rsi_factor * 0.05  # 5% weight on RSI
        )

        # Apply golden bonus
        confidence = confidence * golden_factor

        # Ensure result is between 0.0 and 1.0
        return max(0.0, min(1.0, confidence))

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
        """
        Process entry for a single ticker (long or short).

        Returns:
            True if entry was successful, False otherwise
        """
        if not cls.running:
            return False

        market_data_response = market_data_dict.get(ticker)
        if not market_data_response:
            logger.warning(f"No market data for {ticker}, skipping entry")
            return False

        # Check daily limit (allow golden tickers to bypass)
        if daily_limit_reached and not is_golden:
            logger.info(
                f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                f"Skipping {ticker} (not golden/exceptional)."
            )
            return False

        # Check active trades capacity
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

        # For shorts, re-check quality filters at entry time
        if action == "sell_to_open":
            # Check if ticker is shortable via Alpaca API
            is_shortable = await AlpacaClient.is_shortable(ticker)
            if not is_shortable:
                logger.info(
                    f"Skipping {ticker} short entry: ticker is not shortable according to Alpaca API"
                )
                return False

            passes_filter, filter_reason = await cls._passes_stock_quality_filters(
                ticker, market_data_response, momentum_score
            )
            if not passes_filter:
                logger.info(
                    f"Skipping {ticker} short entry: {filter_reason} "
                    f"{'(was golden but failed filters at entry)' if is_golden else ''}"
                )
                return False

        # MARKET DIRECTION FILTER - Check QQQ trend before allowing trades
        should_allow, market_reason, trend_details = (
            await MarketDirectionFilter.should_allow_trade(
                action=action, indicator_name=cls.indicator_name()
            )
        )
        if not should_allow:
            logger.warning(
                f"Market direction filter blocked {ticker} {action}: {market_reason}"
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

        # CRITICAL FIX: Re-validate entry price against min_stock_price using actual quote
        # This catches stocks that dropped below $5 since screening (e.g., SUNE at $1.44)
        if enter_price < cls.min_stock_price:
            logger.warning(
                f"Skipping {ticker}: actual entry price ${enter_price:.2f} < ${cls.min_stock_price:.2f} "
                f"minimum (penny stock, should be handled by PennyStocksIndicator)"
            )
            return False

        logger.debug(f"Entry price for {ticker}: ${enter_price:.4f}")

        # Validate entry price vs technical analysis close price
        # Reject if there's significant divergence (stale data or bad quote)
        ta_close_price = (
            market_data_response.get("close_price", 0.0)
            if market_data_response
            else 0.0
        )
        if ta_close_price > 0 and enter_price > 0:
            price_divergence_percent = (
                abs((enter_price - ta_close_price) / ta_close_price) * 100
            )
            # Allow up to 5% divergence for penny stocks, 3% for regular stocks
            max_divergence = (
                5.0 if enter_price < cls.max_stock_price_for_penny_treatment else 3.0
            )
            if price_divergence_percent > max_divergence:
                logger.warning(
                    f"Skipping {ticker}: entry price ${enter_price:.4f} diverges {price_divergence_percent:.1f}% "
                    f"from TA close ${ta_close_price:.4f} (max allowed: {max_divergence}%) - possible stale data"
                )
                return False

        # Check bid-ask spread using SpreadCalculator
        bid = ticker_quote.get("bp", 0.0)
        ask = ticker_quote.get("ap", 0.0)
        spread_percent = SpreadCalculator.calculate_spread_percent(bid, ask)

        # NEW: Stricter validation for ultra-low price stocks (< $0.20)
        # These stocks have wider spreads and are more prone to manipulation
        # Check this FIRST before general spread check to apply stricter rules
        if enter_price < 0.20:
            # For ultra-low price stocks, require tighter spread (2.0% vs 3.0% default)
            ultra_low_price_max_spread = 2.0
            if spread_percent > ultra_low_price_max_spread:
                logger.info(
                    f"Skipping {ticker}: ultra-low price stock (${enter_price:.4f}) with spread {spread_percent:.2f}% > "
                    f"max {ultra_low_price_max_spread}% (stricter threshold for low-price stocks)"
                )
                return False
        elif spread_percent > cls.max_bid_ask_spread_percent:
            # General spread check for regular stocks
            logger.info(
                f"Skipping {ticker}: bid-ask spread {spread_percent:.2f}% > max {cls.max_bid_ask_spread_percent}%"
            )
            return False

        # NEW: Recent average peak validation - don't enter if current price is at, above, or too close to recent_avg
        # This prevents entering after momentum has already peaked
        # FIXED: Made stricter - reject entries at/above recent_avg or too close to recent_avg (like penny stocks)
        if is_long:
            recent_avg = cls._extract_recent_avg_from_reason(reason)
            if recent_avg and recent_avg > 0:
                # Calculate how much above/below recent_avg the current entry price is
                price_vs_recent_avg_percent = (
                    (enter_price - recent_avg) / recent_avg
                ) * 100

                # STRICT: Reject if entry is at or above recent_avg (within 0.5% tolerance for rounding)
                # This prevents entering when momentum has already peaked
                if price_vs_recent_avg_percent >= -0.5:
                    logger.info(
                        f"Skipping {ticker}: entry price ${enter_price:.4f} is at or above recent_avg ${recent_avg:.4f} "
                        f"({price_vs_recent_avg_percent:.2f}%) - momentum has already peaked"
                    )
                    return False

                # STRICT: Require entry to be meaningfully below recent_avg (at least 1% below)
                # This ensures we're entering during momentum build-up, not at the peak
                # Stricter for ultra-low price stocks (< $0.20)
                min_below_recent_avg = (
                    1.0 if enter_price < 0.20 else 1.0
                )  # 1% for all stocks
                if price_vs_recent_avg_percent > -min_below_recent_avg:
                    logger.info(
                        f"Skipping {ticker}: entry price ${enter_price:.4f} is only {abs(price_vs_recent_avg_percent):.2f}% below "
                        f"recent_avg ${recent_avg:.4f} (need at least {min_below_recent_avg}% below recent_avg) - too close to peak"
                    )
                    return False

        # NEW: Immediate momentum check - verify most recent bars still show momentum
        # This catches reversals that happened between momentum calculation and entry
        # Get bars data for immediate momentum validation
        bars_data = await AlpacaClient.get_market_data(ticker, limit=50)
        if bars_data:
            bars_dict = bars_data.get("bars", {})
            ticker_bars = bars_dict.get(ticker, [])
            if ticker_bars and len(ticker_bars) >= 3:
                recent_momentum_valid = cls._check_immediate_momentum_for_entry(
                    ticker_bars, is_long
                )
                if not recent_momentum_valid:
                    logger.info(
                        f"Skipping {ticker}: immediate momentum check failed - recent bars show reversal"
                    )
                    return False

        # IMPROVED: Calculate breakeven price accounting for spread
        breakeven_price = SpreadCalculator.calculate_breakeven_price(
            enter_price, spread_percent, is_long
        )

        # Prepare entry data
        direction = "upward" if is_long else "downward"
        golden_prefix = "🟡 GOLDEN: " if is_golden else ""
        ranked_reason = f"{golden_prefix}{reason} (ranked #{rank} {direction} momentum)"

        # market_data_response IS the technical analysis dict (from calculate_all_indicators)
        technical_indicators = (
            market_data_response if isinstance(market_data_response, dict) else {}
        )
        technical_indicators_for_enter = {
            k: v for k, v in technical_indicators.items() if k != "datetime_price"
        }

        # IMPROVED: Store spread and breakeven info for exit logic
        technical_indicators_for_enter["spread_percent"] = spread_percent
        technical_indicators_for_enter["breakeven_price"] = breakeven_price

        # Calculate confidence score (0.0 to 1.0)
        recent_avg = cls._extract_recent_avg_from_reason(reason)
        volume = technical_indicators_for_enter.get("volume", 0)
        confidence_score = cls._calculate_confidence_score(
            momentum_score=momentum_score,
            recent_avg=recent_avg,
            enter_price=enter_price,
            spread_percent=spread_percent,
            volume=volume,
            rank=rank,
            is_golden=is_golden,
            technical_indicators=technical_indicators_for_enter,
        )

        # Calculate dynamic stop loss
        dynamic_stop_loss = await cls._calculate_dynamic_stop_loss(
            ticker, enter_price, technical_indicators_for_enter, action=action
        )

        # Enter trade FIRST, then send webhook only on success
        entry_success = await cls._enter_trade(
            ticker=ticker,
            action=action,
            enter_price=enter_price,
            enter_reason=ranked_reason,
            technical_indicators=technical_indicators_for_enter,
            dynamic_stop_loss=dynamic_stop_loss,
        )

        if not entry_success:
            logger.error(f"Failed to enter trade for {ticker}")
            return False

        # Send webhook AFTER successful entry to prevent orphaned signals
        webhook_success = await send_signal_to_webhook(
            ticker=ticker,
            action=action,
            indicator=cls.indicator_name(),
            enter_reason=ranked_reason,
            enter_price=enter_price,
            technical_indicators=technical_indicators_for_enter,
            confidence_score=confidence_score,
        )
        if not webhook_success:
            logger.warning(
                f"Webhook failed for {ticker} {action} entry, but trade is tracked in DB"
            )

        return True

    @classmethod
    @measure_latency
    async def _run_entry_cycle(cls):
        """Execute a single momentum entry cycle."""
        logger.debug("Starting momentum entry cycle")
        if not await AlpacaClient.is_market_open():
            logger.debug("Market is closed, skipping momentum entry logic")
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        # Check entry cutoff time - no new entries after 3:55 PM ET
        # This prevents late-day entries that don't have time to develop
        if cls._is_after_entry_cutoff():
            est_tz = pytz.timezone("America/New_York")
            current_time_est = datetime.now(est_tz)
            logger.info(
                f"⏰ Entry cutoff reached ({current_time_est.strftime('%H:%M')} ET >= "
                f"{cls.max_entry_hour_et}:{cls.max_entry_minute_et:02d} ET). "
                "No new entries allowed - focusing on exit management only."
            )
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        logger.info(
            "Market is open, proceeding with momentum entry logic (HIGHLY SELECTIVE)"
        )

        await cls._reset_daily_stats_if_needed()

        # Check daily limit once (will be bypassed for golden tickers later)
        daily_limit_reached = await cls._has_reached_daily_trade_limit()
        if daily_limit_reached:
            logger.info(
                f"Daily trade limit reached: {cls.daily_trades_count}/{cls.max_daily_trades}. "
                "Will still check for golden/exceptional opportunities."
            )

        all_tickers = await cls._get_screened_tickers()
        if not all_tickers:
            logger.warning("Failed to get screened tickers, skipping this cycle")
            await asyncio.sleep(2)
            return

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

        # Fetch market data in parallel batches (using memory-optimized batch size)
        # max_concurrent=None will use memory-optimized config from MemoryMonitor
        market_data_dict = await cls._fetch_market_data_batch(
            candidates_to_fetch, max_concurrent=None
        )

        # Process results
        ticker_momentum_scores = []
        stats = {
            "no_market_data": 0,
            "no_datetime_price": 0,
            "low_momentum": 0,
            "failed_quality_filters": 0,
            "passed": 0,
        }

        # Collect inactive ticker reasons for batch writing
        inactive_ticker_logs = []

        for ticker in candidates_to_fetch:
            if not cls.running:
                break

            market_data_response = market_data_dict.get(ticker)
            if not market_data_response:
                stats["no_market_data"] += 1
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": "No market data response - cannot evaluate technical indicators or momentum for long entry",
                        "reason_not_to_enter_short": "No market data response - cannot evaluate technical indicators or momentum for short entry",
                        "technical_indicators": None,
                    }
                )
                continue

            # market_data_response IS the technical analysis dict (from calculate_all_indicators)
            technical_analysis = (
                market_data_response if isinstance(market_data_response, dict) else {}
            )

            # Use datetime_price for momentum calculation
            datetime_price_for_momentum = technical_analysis.get("datetime_price", {})

            # Check if datetime_price is empty (dict or list)
            is_empty = (
                (
                    isinstance(datetime_price_for_momentum, dict)
                    and len(datetime_price_for_momentum) == 0
                )
                or (
                    isinstance(datetime_price_for_momentum, list)
                    and len(datetime_price_for_momentum) == 0
                )
                or (
                    not datetime_price_for_momentum
                    and datetime_price_for_momentum is not None
                )
            )

            if is_empty:
                stats["no_datetime_price"] += 1
                logger.debug(
                    f"No datetime_price data for {ticker} (type: {type(datetime_price_for_momentum).__name__}, len: {len(datetime_price_for_momentum) if hasattr(datetime_price_for_momentum, '__len__') else 'N/A'})"
                )
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": "No datetime_price data - cannot calculate momentum for long entry evaluation",
                        "reason_not_to_enter_short": "No datetime_price data - cannot calculate momentum for short entry evaluation",
                        "technical_indicators": technical_analysis,
                    }
                )
                continue
            else:
                logger.debug(
                    f"Using MCP datetime_price for {ticker} momentum (type: {type(datetime_price_for_momentum).__name__}, len: {len(datetime_price_for_momentum) if hasattr(datetime_price_for_momentum, '__len__') else 'N/A'})"
                )

            momentum_score, reason = cls._calculate_momentum(
                datetime_price_for_momentum
            )

            abs_momentum = abs(momentum_score)
            # Dynamic momentum threshold based on price
            # For penny stocks, we need a much higher threshold to filter out noise/spread
            current_price = technical_analysis.get("close_price", 0.0)
            required_momentum = cls.min_momentum_threshold

            if (
                current_price > 0
                and current_price < cls.max_stock_price_for_penny_treatment
            ):
                required_momentum = 5.0  # Require 5% momentum for stocks under $5

            if abs_momentum < required_momentum:
                stats["low_momentum"] += 1
                logger.debug(
                    f"Skipping {ticker}: momentum {momentum_score:.2f}% < "
                    f"minimum threshold {required_momentum}% "
                    f"{'(adjusted for penny stock)' if required_momentum > cls.min_momentum_threshold else ''}"
                )
                # Momentum threshold applies to both directions
                # If positive momentum is too low, can't go long; if negative is too low, can't go short
                if momentum_score > 0:
                    reason_long = f"Momentum {momentum_score:.2f}% < minimum threshold {required_momentum}% (insufficient upward momentum for long entry)"
                    reason_short = f"Not evaluated for short entry (momentum is positive {momentum_score:.2f}%, would evaluate momentum threshold on negative momentum for short entry)"
                elif momentum_score < 0:
                    reason_long = f"Not evaluated for long entry (momentum is negative {momentum_score:.2f}%, would evaluate momentum threshold on positive momentum for long entry)"
                    reason_short = f"Momentum {abs(momentum_score):.2f}% < minimum threshold {required_momentum}% (insufficient downward momentum for short entry)"
                else:
                    # Zero momentum - applies to both
                    reason_long = f"Momentum {momentum_score:.2f}% < minimum threshold {required_momentum}% (insufficient momentum for long entry)"
                    reason_short = f"Momentum {momentum_score:.2f}% < minimum threshold {required_momentum}% (insufficient momentum for short entry)"

                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": reason_long,
                        "reason_not_to_enter_short": reason_short,
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            # Check for extreme momentum (likely entering at peak)
            if abs_momentum > cls.max_momentum_threshold:
                stats["low_momentum"] += 1  # Reuse this stat for high momentum
                logger.debug(
                    f"Skipping {ticker}: momentum {momentum_score:.2f}% > "
                    f"maximum threshold {cls.max_momentum_threshold}% (likely at peak)"
                )
                # Extreme momentum applies to both directions (entering at peak/trough)
                if momentum_score > 0:
                    reason_long = f"Momentum {momentum_score:.2f}% > maximum threshold {cls.max_momentum_threshold}% (likely at peak, risk of reversal)"
                    reason_short = f"Not evaluated for short entry (momentum is positive {momentum_score:.2f}%, would evaluate momentum threshold on negative momentum for short entry)"
                elif momentum_score < 0:
                    reason_long = f"Not evaluated for long entry (momentum is negative {momentum_score:.2f}%, would evaluate momentum threshold on positive momentum for long entry)"
                    reason_short = f"Momentum {abs(momentum_score):.2f}% > maximum threshold {cls.max_momentum_threshold}% (likely at trough, risk of reversal)"
                else:
                    # Zero momentum edge case
                    reason_long = f"Momentum {momentum_score:.2f}% exceeds maximum threshold {cls.max_momentum_threshold}% (applies to both directions)"
                    reason_short = f"Momentum {momentum_score:.2f}% exceeds maximum threshold {cls.max_momentum_threshold}% (applies to both directions)"

                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": reason_long,
                        "reason_not_to_enter_short": reason_short,
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            # Check price action confirmation (trend structure)
            datetime_price = technical_analysis.get("datetime_price", [])
            if datetime_price:
                prices = cls._extract_prices_from_datetime_price(datetime_price)
                if len(prices) >= 10:
                    is_long = momentum_score > 0
                    structure_confirmed, structure_reason = (
                        cls._confirm_trend_structure(prices, is_long)
                    )
                    if not structure_confirmed:
                        stats["failed_quality_filters"] += 1
                        logger.debug(f"Skipping {ticker}: {structure_reason}")
                        # Trend structure check is direction-specific
                        if is_long:
                            reason_long = f"Trend structure failed: {structure_reason}"
                            reason_short = f"Not evaluated (momentum is positive {momentum_score:.2f}%, would evaluate trend structure on negative momentum for short entry)"
                        else:
                            reason_long = f"Not evaluated (momentum is negative {momentum_score:.2f}%, would evaluate trend structure on positive momentum for long entry)"
                            reason_short = f"Trend structure failed: {structure_reason}"

                        inactive_ticker_logs.append(
                            {
                                "ticker": ticker,
                                "indicator": cls.indicator_name(),
                                "reason_not_to_enter_long": reason_long,
                                "reason_not_to_enter_short": reason_short,
                                "technical_indicators": technical_analysis,
                            }
                        )
                        continue

            passes_filter, filter_reason = await cls._passes_stock_quality_filters(
                ticker, market_data_response, momentum_score
            )
            if not passes_filter:
                stats["failed_quality_filters"] += 1
                logger.debug(f"Skipping {ticker}: {filter_reason}")
                # Log at Debug level for better visibility of why trades aren't happening
                logger.debug(
                    f"❌ {ticker} failed quality filter: {filter_reason} "
                    f"(momentum: {momentum_score:.2f}%)"
                )

                # Determine which direction(s) this filter applies to
                # Most filters apply to both directions, but some are direction-specific
                is_long = momentum_score > 0
                is_short = momentum_score < 0

                # Check if filter reason indicates direction-specific failure
                reason_lower = filter_reason.lower()
                is_direction_specific = (
                    (
                        "rsi" in reason_lower
                        and ("long" in reason_lower or "short" in reason_lower)
                    )
                    or ("stochastic" in reason_lower and "short" in reason_lower)
                    or (
                        "bollinger" in reason_lower
                        and ("long" in reason_lower or "short" in reason_lower)
                    )
                )

                if is_direction_specific:
                    # Direction-specific filter (RSI, Stochastic, Bollinger)
                    if is_long:
                        reason_long = filter_reason
                        reason_short = f"Not evaluated for short entry (momentum is positive {momentum_score:.2f}%, would evaluate quality filters on negative momentum for short entry)"
                    elif is_short:
                        reason_long = f"Not evaluated for long entry (momentum is negative {momentum_score:.2f}%, would evaluate quality filters on positive momentum for long entry)"
                        reason_short = filter_reason
                    else:
                        # Zero momentum - set both with clear explanation
                        reason_long = f"{filter_reason} (applies to both directions due to zero momentum)"
                        reason_short = f"{filter_reason} (applies to both directions due to zero momentum)"
                else:
                    # Universal filter (applies to both directions)
                    # Examples: price, volatility, volume, ADX, warrant/option
                    reason_long = filter_reason
                    reason_short = filter_reason

                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": reason_long,
                        "reason_not_to_enter_short": reason_short,
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            stats["passed"] += 1
            ticker_momentum_scores.append((ticker, momentum_score, reason))
            logger.debug(
                f"{ticker} passed all filters: momentum={momentum_score:.2f}%, "
                f"{filter_reason}"
            )

        # Batch write all inactive ticker reasons in parallel
        if inactive_ticker_logs:
            logger.debug(
                f"Logging {len(inactive_ticker_logs)} inactive tickers to DynamoDB"
            )

            async def log_one(log_data):
                try:
                    result = await DynamoDBClient.log_inactive_ticker_reason(**log_data)
                    if not result:
                        logger.debug(
                            f"Failed to log inactive ticker {log_data.get('ticker')}"
                        )
                    return result
                except Exception as e:
                    logger.error(
                        f"Error logging inactive ticker {log_data.get('ticker')}: {str(e)}"
                    )
                    return False

            # Write in batches using memory-optimized batch size
            memory_config = MemoryMonitor.get_memory_config()
            batch_size = memory_config["dynamodb_batch_size"]
            for i in range(0, len(inactive_ticker_logs), batch_size):
                batch = inactive_ticker_logs[i : i + batch_size]
                results = await asyncio.gather(
                    *[log_one(log_data) for log_data in batch], return_exceptions=True
                )
                successful = sum(1 for r in results if r is True)
                logger.debug(
                    f"Batch {i//batch_size + 1}: {successful}/{len(batch)} inactive tickers logged successfully"
                )

        logger.info(
            f"Calculated momentum scores for {len(ticker_momentum_scores)} tickers "
            f"(filtered: {stats['no_market_data']} no data, "
            f"{stats['no_datetime_price']} no datetime_price, "
            f"{stats['low_momentum']} low momentum, "
            f"{stats['failed_quality_filters']} failed quality filters)"
        )

        # Enhanced diagnostics: log if no tickers passed all filters
        if len(ticker_momentum_scores) == 0:
            logger.info(
                f"⚠️ ZERO tickers passed all filters! "
                f"Total candidates: {len(candidates_to_fetch)}, "
                f"No market data: {stats['no_market_data']}, "
                f"No datetime_price: {stats['no_datetime_price']}, "
                f"Low momentum: {stats['low_momentum']}, "
                f"Failed quality filters: {stats['failed_quality_filters']}"
            )

        # Separate upward and downward momentum
        # Note: tickers with score == 0 are treated as upward (neutral momentum)
        upward_tickers = [
            (t, score, reason, None)  # Add None for peak_price to match MAB service expectation
            for t, score, reason in ticker_momentum_scores
            if score >= 0
        ]
        downward_tickers = [
            (t, score, reason, None)  # Add None for peak_price to match MAB service expectation
            for t, score, reason in ticker_momentum_scores
            if score < 0
        ]

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

        # Log selected tickers for visibility
        if top_upward:
            logger.debug(
                f"Selected upward tickers: {[(t, f'{s:.2f}%', r[:50]) for t, s, r, _ in top_upward]}"
            )
        if top_downward:
            logger.debug(
                f"Selected downward tickers: {[(t, f'{s:.2f}%', r[:50]) for t, s, r, _ in top_downward]}"
            )

        # Enhanced diagnostic logging for zero trades
        if len(top_upward) == 0 and len(top_downward) == 0:
            logger.info(
                f"⚠️ MAB service returned zero tickers! "
                f"Upward candidates: {len(upward_tickers)}, "
                f"Downward candidates: {len(downward_tickers)}, "
                f"Total passed filters: {len(ticker_momentum_scores)}"
            )
            # Log sample of candidates that passed filters but weren't selected
            if upward_tickers:
                logger.info(
                    f"Sample upward candidates (top 5): "
                    f"{[(t, f'{s:.2f}%') for t, s, _ in upward_tickers[:5]]}"
                )
            if downward_tickers:
                logger.info(
                    f"Sample downward candidates (top 5): "
                    f"{[(t, f'{s:.2f}%') for t, s, _ in downward_tickers[:5]]}"
                )
        elif len(upward_tickers) > 0 and len(top_upward) == 0:
            logger.info(
                f"⚠️ MAB service returned zero upward tickers despite {len(upward_tickers)} candidates passing filters. "
                f"Top 3 candidates: {[(t, f'{s:.2f}%') for t, s, _ in upward_tickers[:3]]}"
            )
        elif len(downward_tickers) > 0 and len(top_downward) == 0:
            logger.info(
                f"⚠️ MAB service returned zero downward tickers despite {len(downward_tickers)} candidates passing filters. "
                f"Top 3 candidates: {[(t, f'{s:.2f}%') for t, s, _ in downward_tickers[:3]]}"
            )

        # Log MAB-rejected tickers (passed validation but not selected by MAB)
        selected_tickers_list = [t[0] for t in top_upward] + [
            t[0] for t in top_downward
        ]

        # Get rejection reasons for all rejected tickers
        all_candidates = upward_tickers + downward_tickers
        rejected_info = await MABService.get_rejected_tickers_with_reasons(
            indicator=cls.indicator_name(),
            ticker_candidates=all_candidates,
            selected_tickers=selected_tickers_list,
        )

        if rejected_info:
            logger.debug(
                f"Logging {len(rejected_info)} tickers rejected by MAB to InactiveTickersForDayTrading"
            )
            for ticker, rejection_data in rejected_info.items():
                try:
                    market_data_response = market_data_dict.get(ticker)
                    technical_indicators = {}
                    if market_data_response:
                        technical_indicators = market_data_response.get(
                            "technical_analysis", {}
                        )
                        technical_indicators["momentum_score"] = rejection_data.get(
                            "momentum_score", 0.0
                        )

                    reason_long = rejection_data.get("reason_long", "")
                    reason_short = rejection_data.get("reason_short", "")

                    # Ensure at least one reason is populated
                    if not reason_long and not reason_short:
                        logger.warning(
                            f"No rejection reason for {ticker}, skipping MAB rejection log"
                        )
                        continue

                    result = await DynamoDBClient.log_inactive_ticker(
                        ticker=ticker,
                        indicator=cls.indicator_name(),
                        reason_not_to_enter_long=reason_long,
                        reason_not_to_enter_short=reason_short,
                        technical_indicators=technical_indicators,
                    )

                    if not result:
                        logger.warning(
                            f"Failed to log MAB rejection for {ticker} to InactiveTickersForDayTrading"
                        )
                    else:
                        logger.debug(
                            f"Logged MAB rejection for {ticker}: long={bool(reason_long)}, short={bool(reason_short)}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Error logging MAB rejection for {ticker}: {str(e)}"
                    )

        # Process long entries
        for rank, (ticker, momentum_score, reason, _) in enumerate(top_upward, start=1):
            if not cls.running:
                break

            # Check if golden ticker (for daily limit bypass)
            market_data_response = market_data_dict.get(ticker)
            is_golden = False
            if daily_limit_reached and market_data_response:
                is_golden = cls._is_golden_ticker(momentum_score, market_data_response)
                if is_golden:
                    logger.info(
                        f"Daily trade limit reached, but {ticker} is GOLDEN "
                        f"(momentum: {momentum_score:.2f}%) - allowing entry"
                    )

            await cls._process_ticker_entry(
                ticker=ticker,
                momentum_score=momentum_score,
                reason=reason,
                rank=rank,
                action="buy_to_open",
                market_data_dict=market_data_dict,
                daily_limit_reached=daily_limit_reached,
                is_golden=is_golden,
            )

        # Process short entries
        for rank, (ticker, momentum_score, reason, _) in enumerate(top_downward, start=1):
            if not cls.running:
                break

            # Check if golden ticker (for daily limit bypass)
            market_data_response = market_data_dict.get(ticker)
            is_golden = False
            if daily_limit_reached and market_data_response:
                is_golden = cls._is_golden_ticker(momentum_score, market_data_response)
                if is_golden:
                    logger.info(
                        f"Daily trade limit reached, but {ticker} is GOLDEN "
                        f"(momentum: {momentum_score:.2f}%) - allowing entry"
                    )

            await cls._process_ticker_entry(
                ticker=ticker,
                momentum_score=momentum_score,
                reason=reason,
                rank=rank,
                action="sell_to_open",
                market_data_dict=market_data_dict,
                daily_limit_reached=daily_limit_reached,
                is_golden=is_golden,
            )

        # Summary log for entry cycle
        total_entries_attempted = len(top_upward) + len(top_downward)
        if total_entries_attempted == 0:
            logger.info(
                f"⚠️ Entry cycle completed with ZERO trade entries attempted. "
                f"Summary: {len(candidates_to_fetch)} candidates fetched, "
                f"{len(ticker_momentum_scores)} passed all filters, "
                f"{len(upward_tickers)} upward candidates, {len(downward_tickers)} downward candidates, "
                f"MAB selected {len(top_upward)} upward + {len(top_downward)} downward. "
                f"Active trades: {active_count}/{cls.max_active_trades}, "
                f"Daily trades: {cls.daily_trades_count}/{cls.max_daily_trades}"
            )
        else:
            logger.debug(
                f"Entry cycle completed: {total_entries_attempted} trade entries attempted "
                f"({len(top_upward)} long, {len(top_downward)} short)"
            )

        await asyncio.sleep(cls.entry_cycle_seconds)

    @classmethod
    async def exit_service(cls):
        """Exit service - monitor trades and exit based on profitability"""
        logger.info("Momentum exit service started")
        while cls.running:
            try:
                await cls._run_exit_cycle()
            except Exception as e:
                logger.exception(f"Error in momentum exit service: {str(e)}")
                await asyncio.sleep(5)

    @classmethod
    async def _get_current_price(cls, ticker: str, action: str) -> Optional[float]:
        """
        Get current price for exit decision using Alpaca API.

        Args:
            ticker: Stock ticker symbol
            action: "buy_to_open" (long) or "sell_to_open" (short)

        Returns:
            Current price (bid for long, ask for short) or None if unavailable
        """
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
    def _check_holding_period(
        cls, created_at: Optional[str], min_holding_seconds: Optional[int] = None
    ) -> Tuple[bool, float]:
        """
        Check if trade has passed minimum holding period.

        Args:
            created_at: ISO timestamp string when trade was created
            min_holding_seconds: Optional minimum holding period in seconds (defaults to cls.min_holding_period_seconds)

        Returns:
            Tuple of (passed_minimum: bool, holding_period_minutes: float)
        """
        if not created_at:
            return True, 0.0  # No created_at means we can't check, allow processing

        if min_holding_seconds is None:
            min_holding_seconds = cls.min_holding_period_seconds

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
    async def _check_trailing_stop(
        cls,
        ticker: str,
        enter_price: float,
        current_price: float,
        original_action: str,
        peak_profit_percent: float,
        stop_loss_threshold: float,
        technical_analysis: Dict[str, Any],
        created_at: Optional[str],
    ) -> Dict[str, Any]:
        """
        Check if trailing stop should trigger an exit.

        Returns:
            Dict with 'should_exit' (bool), 'exit_reason' (str), and 'profit_percent' (float)
        """
        # Get fresh price for trailing stop check
        fresh_price = await cls._get_current_price(ticker, original_action)
        if fresh_price and fresh_price > 0:
            current_price = fresh_price

        profit_percent = cls._calculate_profit_percent(
            enter_price, current_price, original_action
        )

        is_penny_stock = enter_price < cls.max_stock_price_for_penny_treatment
        is_short = original_action == "sell_to_open"

        # Check activation threshold
        activation_threshold = (
            cls.penny_stock_trailing_stop_activation_profit
            if is_penny_stock
            else cls.trailing_stop_activation_profit
        )

        if peak_profit_percent < activation_threshold:
            return {
                "should_exit": False,
                "exit_reason": None,
                "profit_percent": profit_percent,
            }

        # Check cooldown period
        if created_at:
            try:
                enter_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if enter_time.tzinfo is None:
                    enter_time = enter_time.replace(tzinfo=timezone.utc)
                elapsed_seconds = (
                    datetime.now(timezone.utc) - enter_time
                ).total_seconds()

                required_cooldown = (
                    cls.trailing_stop_cooldown_seconds
                    if is_penny_stock
                    else cls.min_trailing_stop_cooldown_seconds
                )

                if elapsed_seconds < required_cooldown:
                    return {
                        "should_exit": False,
                        "exit_reason": None,
                        "profit_percent": profit_percent,
                    }
            except Exception:
                pass  # Continue if cooldown check fails

        # Calculate trailing stop distance
        if is_penny_stock:
            dynamic_trailing_stop = cls.penny_stock_trailing_stop_percent
        else:
            # Calculate tiered trailing stop
            trailing_stop_distance = cls._calculate_trailing_stop_activation(
                peak_profit_percent, stop_loss_threshold
            )
            tiered_distance = (
                trailing_stop_distance
                if trailing_stop_distance is not None
                else abs(stop_loss_threshold) * 0.8
            )

            # Calculate ATR-based trailing stop
            atr = technical_analysis.get("atr", 0.0)
            if atr and atr > 0:
                atr_percent = cls._calculate_atr_percent(atr, current_price)
                atr_trailing = max(
                    BASE_TRAILING_STOP_PERCENT,
                    ATR_TRAILING_STOP_MULTIPLIER * atr_percent,
                )
                if is_short:
                    atr_trailing = min(
                        MAX_TRAILING_STOP_SHORT,
                        atr_trailing * TRAILING_STOP_SHORT_MULTIPLIER,
                    )
                dynamic_trailing_stop = min(tiered_distance, atr_trailing)
            else:
                dynamic_trailing_stop = tiered_distance
                if is_short:
                    dynamic_trailing_stop *= cls.trailing_stop_short_multiplier

        # Check if trailing stop should trigger
        drop_from_peak = peak_profit_percent - profit_percent
        should_trigger = (
            drop_from_peak >= dynamic_trailing_stop
            and profit_percent > 0  # Require profit for all stocks
        )

        if should_trigger:
            return {
                "should_exit": True,
                "exit_reason": (
                    f"Trailing stop triggered: profit dropped {drop_from_peak:.2f}% "
                    f"from peak of {peak_profit_percent:.2f}% (current: {profit_percent:.2f}%, "
                    f"trailing stop: {dynamic_trailing_stop:.2f}%)"
                ),
                "profit_percent": profit_percent,
            }

        return {
            "should_exit": False,
            "exit_reason": None,
            "profit_percent": profit_percent,
        }

    @classmethod
    @measure_latency
    async def _run_exit_cycle(cls):
        """Execute a single momentum exit monitoring cycle."""
        if not await AlpacaClient.is_market_open():
            logger.debug("Market is closed, skipping momentum exit logic")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_trades = await cls._get_active_trades()
        if not active_trades:
            logger.debug("No active momentum trades to monitor")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        # Filter trades that haven't passed minimum holding period
        trades_to_process = []
        for trade in active_trades:
            created_at = trade.get("created_at")
            enter_price = trade.get("enter_price", 0.0)
            is_penny_stock = (
                enter_price > 0
                and enter_price < cls.max_stock_price_for_penny_treatment
            )

            # Use shorter holding period for penny stocks
            min_holding = (
                cls.min_holding_period_penny_stocks_seconds
                if is_penny_stock
                else cls.min_holding_period_seconds
            )
            passed, holding_minutes = cls._check_holding_period(
                created_at, min_holding_seconds=min_holding
            )

            if not passed:
                ticker = trade.get("ticker")
                logger.debug(
                    f"Skipping {ticker}: holding period {holding_minutes:.1f} min < "
                    f"minimum {min_holding/60:.2f} min {'(penny stock)' if is_penny_stock else ''}"
                )
                continue
            trades_to_process.append(trade)

        if not trades_to_process:
            logger.debug("No trades passed minimum holding period")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_count = len(trades_to_process)
        logger.info(
            f"Monitoring {active_count}/{cls.max_active_trades} active momentum trades"
        )

        # Check if we need to force close positions before market close
        is_near_close = cls._is_near_market_close()
        if is_near_close:
            logger.debug(
                f"Near market close - forcing exit of all {active_count} active positions "
                f"({cls.minutes_before_close_to_exit} minutes before close)"
            )

        for trade in trades_to_process:
            if not cls.running:
                break

            ticker = trade.get("ticker")
            original_action = trade.get("action")
            enter_price = trade.get("enter_price")
            trailing_stop = float(trade.get("trailing_stop", 0.5))
            peak_profit_percent = float(trade.get("peak_profit_percent", 0.0))
            created_at = trade.get("created_at")
            # Get dynamic stop loss if available, otherwise use default
            dynamic_stop_loss = trade.get("dynamic_stop_loss")
            stop_loss_threshold = (
                float(dynamic_stop_loss)
                if dynamic_stop_loss is not None
                else cls.stop_loss_threshold
            )

            if not ticker or enter_price is None or enter_price <= 0:
                logger.warning(f"Invalid momentum trade data: {trade}")
                continue

            # Get current price for exit decision
            current_price = await cls._get_current_price(ticker, original_action)
            if current_price is None or current_price <= 0:
                logger.warning(
                    f"Failed to get quote for {ticker} - will retry in next cycle"
                )
                continue

            logger.debug(f"Current price for {ticker}: ${current_price:.4f}")

            # Get technical indicators (may be delayed, but don't block exit decisions)
            # Exit decisions are based on get_quote() which is more up-to-date
            indicators = await TechnicalAnalysisLib.calculate_all_indicators(ticker)
            technical_analysis = indicators if indicators else {}

            profit_percent = cls._calculate_profit_percent(
                enter_price, current_price, original_action
            )

            should_exit = False
            exit_reason = None
            is_long = original_action == "buy_to_open"

            # Get recent bars for peak/bottom tracking
            bars_data_for_exit = await AlpacaClient.get_market_data(ticker, limit=50)

            # Track peak price (for long) and bottom price (for short) since entry
            # FIXED: Only consider bars AFTER trade entry to avoid using pre-entry prices
            peak_price_since_entry = None
            bottom_price_since_entry = None

            if bars_data_for_exit:
                bars_dict = bars_data_for_exit.get("bars", {})
                ticker_bars = bars_dict.get(ticker, [])
                if ticker_bars:
                    # Filter bars to only include those AFTER trade entry
                    filtered_bars = cls._filter_bars_after_entry(
                        ticker_bars, created_at
                    )

                    if filtered_bars:
                        # Get prices from filtered (post-entry) bars only
                        prices_since_entry = [
                            bar.get("c", 0.0)
                            for bar in filtered_bars
                            if bar.get("c", 0.0) > 0
                        ]
                        if prices_since_entry:
                            peak_price_since_entry = max(prices_since_entry)
                            bottom_price_since_entry = min(prices_since_entry)
                    else:
                        # No post-entry bars yet - use entry price as initial peak/bottom
                        peak_price_since_entry = float(enter_price)
                        bottom_price_since_entry = float(enter_price)
                        logger.debug(
                            f"No post-entry bars for {ticker}, using entry price as initial peak/bottom"
                        )

            # Calculate holding time for profit-taking exit checks
            holding_seconds = 0.0
            if created_at:
                try:
                    entry_time = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    holding_seconds = (
                        datetime.now(timezone.utc) - entry_time
                    ).total_seconds()
                except (ValueError, TypeError):
                    holding_seconds = 0.0

            # PRIORITY 0: MAX HOLDING TIME - Force exit after 2 hours regardless of P/L
            # This prevents overnight holds like ABTC (-7.14% after 22 hours)
            MAX_HOLDING_MINUTES = 120  # 2 hours max
            holding_minutes = holding_seconds / 60.0
            if holding_minutes >= MAX_HOLDING_MINUTES:
                should_exit = True
                exit_reason = (
                    f"Max holding time exceeded: {holding_minutes:.0f} min "
                    f"(limit: {MAX_HOLDING_MINUTES} min, profit: {profit_percent:.2f}%)"
                )
                logger.warning(
                    f"⏰ Force exit for {ticker}: held too long - {exit_reason}"
                )

            # PRIORITY 1: Exit on profitable trend reversal (BOOK PROFIT QUICKLY)
            # FIXED: Now requires positive profit, minimum profit threshold, and minimum holding time
            # This prevents premature exits on normal market noise
            if is_long:
                # For LONG: Exit if price starts dipping from peak
                if peak_price_since_entry and peak_price_since_entry > 0:
                    # Calculate dip from peak (negative value means price dropped)
                    dip_from_peak_percent = (
                        (peak_price_since_entry - current_price)
                        / peak_price_since_entry
                    ) * 100
                    # Calculate profit from entry
                    profit_from_entry = (
                        (current_price - float(enter_price)) / float(enter_price)
                    ) * 100

                    # Use new helper method with all safety checks
                    should_trigger, trigger_reason = (
                        cls._should_trigger_profit_taking_exit(
                            profit_from_entry=profit_from_entry,
                            dip_or_rise_percent=dip_from_peak_percent,
                            holding_seconds=holding_seconds,
                            is_long=True,
                        )
                    )

                    if should_trigger:
                        should_exit = True
                        exit_reason = (
                            f"Dip from peak (LONG): peak ${peak_price_since_entry:.4f} → current ${current_price:.4f} "
                            f"(dip: {dip_from_peak_percent:.2f}%, profit from entry: {profit_from_entry:.2f}%)"
                        )
            else:
                # For SHORT: Exit if price starts rising from bottom
                if bottom_price_since_entry and bottom_price_since_entry > 0:
                    # Calculate rise from bottom (positive value means price rose)
                    rise_from_bottom_percent = (
                        (current_price - bottom_price_since_entry)
                        / bottom_price_since_entry
                    ) * 100
                    # Calculate profit from entry (for shorts, profit = entry - current)
                    profit_from_entry = (
                        (float(enter_price) - current_price) / float(enter_price)
                    ) * 100

                    # Use new helper method with all safety checks
                    should_trigger, trigger_reason = (
                        cls._should_trigger_profit_taking_exit(
                            profit_from_entry=profit_from_entry,
                            dip_or_rise_percent=rise_from_bottom_percent,
                            holding_seconds=holding_seconds,
                            is_long=False,
                        )
                    )

                    if should_trigger:
                        should_exit = True
                        exit_reason = (
                            f"Rise from bottom (SHORT): bottom ${bottom_price_since_entry:.4f} → current ${current_price:.4f} "
                            f"(rise: {rise_from_bottom_percent:.2f}%, profit from entry: {profit_from_entry:.2f}%)"
                        )

            # PRIORITY 2: Check stop loss (cut losses)
            # PATIENT EXIT STRATEGY: Give trades time to recover before exiting
            # Momentum stocks often dip before continuing - don't exit on noise
            if not should_exit and profit_percent < stop_loss_threshold:
                # Initialize exit engine if needed
                if cls._exit_engine is None:
                    cls._exit_engine = ExitDecisionEngine()

                # Track consecutive loss checks
                consecutive_checks = (
                    cls._exit_engine.consecutive_loss_checks.get(ticker, 0) + 1
                )
                cls._exit_engine.consecutive_loss_checks[ticker] = consecutive_checks

                # PATIENT: Require 12 consecutive checks (60 seconds at 5s intervals)
                # This gives the trade a full minute to recover from a dip
                # Only exit immediately on catastrophic loss
                CONSECUTIVE_CHECKS_REQUIRED = (
                    6  # 30 seconds of confirmation (reduced from 60s)
                )
                CATASTROPHIC_FLOOR = (
                    -8.0
                )  # HARD FLOOR: Never let a trade lose more than 8%

                # Catastrophic threshold is the HIGHER (less negative) of:
                # - 2x the dynamic stop loss
                # - Hard floor of -8%
                # This prevents situations like VELO where -15% loss occurred
                dynamic_catastrophic = stop_loss_threshold * 2.0
                catastrophic_threshold = max(dynamic_catastrophic, CATASTROPHIC_FLOOR)
                is_catastrophic = profit_percent < catastrophic_threshold

                if is_catastrophic:
                    # Catastrophic loss - exit immediately
                    should_exit = True
                    exit_reason = (
                        f"CATASTROPHIC stop loss: {profit_percent:.2f}% "
                        f"(below {catastrophic_threshold:.2f}% emergency threshold, "
                        f"original stop: {stop_loss_threshold:.2f}%)"
                    )
                    logger.warning(f"🚨 Emergency exit for {ticker}: {exit_reason}")
                    cls._exit_engine.consecutive_loss_checks[ticker] = 0
                elif consecutive_checks >= CONSECUTIVE_CHECKS_REQUIRED:
                    # Persistent loss after waiting - exit
                    should_exit = True
                    wait_seconds = consecutive_checks * cls.exit_cycle_seconds
                    exit_reason = (
                        f"Stop loss triggered: {profit_percent:.2f}% "
                        f"(below {stop_loss_threshold:.2f}% stop loss threshold"
                        f"{' (dynamic)' if dynamic_stop_loss is not None else ''}, "
                        f"confirmed after {wait_seconds}s of waiting)"
                    )
                    logger.info(
                        f"Exit signal for {ticker} - stop loss after patience: {profit_percent:.2f}%"
                    )
                    cls._exit_engine.consecutive_loss_checks[ticker] = 0
                else:
                    # Still waiting - log progress
                    wait_seconds = consecutive_checks * cls.exit_cycle_seconds
                    remaining_seconds = (
                        CONSECUTIVE_CHECKS_REQUIRED - consecutive_checks
                    ) * cls.exit_cycle_seconds
                    logger.debug(
                        f"Stop loss warning for {ticker}: {profit_percent:.2f}% "
                        f"(waited {wait_seconds}s, {remaining_seconds}s remaining before exit)"
                    )
            elif profit_percent >= stop_loss_threshold:
                # Reset consecutive loss counter if not in loss territory
                if (
                    cls._exit_engine is not None
                    and ticker in cls._exit_engine.consecutive_loss_checks
                ):
                    cls._exit_engine.consecutive_loss_checks[ticker] = 0

            # PRIORITY 3: Force exit before market close ONLY if trade is profitable
            # Hold losing trades until next day (unless stop loss is hit)
            if not should_exit and is_near_close:
                if profit_percent > 0:
                    should_exit = True
                    exit_reason = (
                        f"End-of-day closure: exiting {cls.minutes_before_close_to_exit} minutes before market close "
                        f"(current profit: {profit_percent:.2f}%)"
                    )
                    logger.info(
                        f"Force exit for {ticker} before market close: {exit_reason}"
                    )
                else:
                    logger.debug(
                        f"Holding {ticker} at end of day (current loss: {profit_percent:.2f}%) - "
                        f"will exit when profitable or stop loss triggered"
                    )

            if not should_exit:
                # For penny stocks: QUICK PROFIT EXIT - bank on volatility, get out fast!
                is_penny_stock = enter_price < cls.max_stock_price_for_penny_treatment
                if (
                    is_penny_stock
                    and profit_percent >= cls.penny_stock_quick_profit_target
                ):
                    should_exit = True
                    exit_reason = (
                        f"Penny stock quick profit target reached: {profit_percent:.2f}% profit "
                        f"(target: {cls.penny_stock_quick_profit_target:.2f}% - banking on volatility, quick exit)"
                    )
                    logger.info(
                        f"Quick profit exit for penny stock {ticker}: {exit_reason}"
                    )

                if not should_exit:
                    # Calculate dynamic profit target: 2x stop distance as recommended
                    # If stop loss is -3%, profit target should be +6%
                    stop_distance = abs(stop_loss_threshold)
                    profit_target_to_exit = stop_distance * cls.profit_target_multiplier

                    # Cap profit target at reasonable level (e.g., 10%)
                    profit_target_to_exit = min(10.0, profit_target_to_exit)

                    is_profitable = profit_percent >= profit_target_to_exit
                    if is_profitable:
                        should_exit = True
                        exit_reason = (
                            f"Profit target reached: {profit_percent:.2f}% profit "
                            f"(target: {profit_target_to_exit:.2f}% = {cls.profit_target_multiplier}x "
                            f"stop distance of {stop_distance:.2f}%)"
                        )

            if not should_exit:
                # Update peak profit if current profit is higher
                if profit_percent > peak_profit_percent:
                    peak_profit_percent = profit_percent

                # Calculate trailing stop for database update
                atr = technical_analysis.get("atr", 0.0)
                is_short = original_action == "sell_to_open"
                is_low_price = enter_price < cls.max_stock_price_for_penny_treatment

                if atr and atr > 0:
                    atr_percent = cls._calculate_atr_percent(atr, current_price)
                    trailing_stop = max(
                        BASE_TRAILING_STOP_PERCENT,
                        ATR_TRAILING_STOP_MULTIPLIER * atr_percent,
                    )
                    if is_short:
                        trailing_stop = min(
                            MAX_TRAILING_STOP_SHORT,
                            trailing_stop * TRAILING_STOP_SHORT_MULTIPLIER,
                        )
                else:
                    # Fallback to multiplier-based approach
                    if is_short:
                        trailing_stop = (
                            cls.trailing_stop_percent
                            * cls.trailing_stop_short_multiplier
                        )
                    elif is_low_price:
                        trailing_stop = (
                            cls.trailing_stop_percent
                            * cls.trailing_stop_penny_stock_multiplier
                        )
                    else:
                        trailing_stop = cls.trailing_stop_percent

                # Generate skipped reason for logging
                if profit_percent < 0:
                    skipped_reason = f"Trade is losing: {profit_percent:.2f}%"
                elif profit_percent < cls.profit_threshold:
                    skipped_reason = f"Trade not yet profitable: {profit_percent:.2f}%"
                else:
                    skipped_reason = f"Trade profitable: {profit_percent:.2f}%"

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

                # Get latest quote right before exit
                exit_price = await cls._get_current_price(ticker, original_action)
                if exit_price is None or exit_price <= 0:
                    exit_price = current_price  # Fallback to current price
                    logger.warning(
                        f"Failed to get exit quote for {ticker}, using current price ${current_price:.4f}"
                    )
                else:
                    logger.debug(f"Exit price for {ticker}: ${exit_price:.4f}")

                technical_indicators_for_enter = trade.get(
                    "technical_indicators_for_enter"
                )
                # technical_analysis IS the indicators dict (from calculate_all_indicators)
                technical_indicators_for_exit = (
                    technical_analysis.copy()
                    if isinstance(technical_analysis, dict)
                    else {}
                )
                if "datetime_price" in technical_indicators_for_exit:
                    technical_indicators_for_exit = {
                        k: v
                        for k, v in technical_indicators_for_exit.items()
                        if k != "datetime_price"
                    }

                # IMPROVED: Add exit metadata
                technical_indicators_for_exit["holding_seconds"] = holding_seconds

                # Calculate final profit for metrics
                final_profit_percent = cls._calculate_profit_percent(
                    enter_price, exit_price, original_action
                )

                # IMPROVED: Track daily performance metrics
                if cls._daily_metrics is None:
                    cls._daily_metrics = DailyPerformanceMetrics()

                # Check if we need to reset daily metrics
                today = datetime.now().strftime("%Y-%m-%d")
                if cls._daily_metrics.date != today:
                    logger.info(
                        f"📊 End of day metrics: {cls._daily_metrics.to_dict()}"
                    )
                    cls._daily_metrics.reset()

                # Determine if loss was spread-induced
                # Handle case where technical_indicators_for_enter might be a string or dict
                if isinstance(technical_indicators_for_enter, str):
                    import json

                    try:
                        technical_indicators_for_enter = json.loads(
                            technical_indicators_for_enter
                        )
                    except (json.JSONDecodeError, TypeError):
                        technical_indicators_for_enter = {}

                spread_percent = (
                    float(technical_indicators_for_enter.get("spread_percent", 1.0))
                    if isinstance(technical_indicators_for_enter, dict)
                    else 1.0
                )
                is_spread_induced = (
                    final_profit_percent < 0
                    and abs(final_profit_percent) <= spread_percent * 1.5
                )

                cls._daily_metrics.record_trade(final_profit_percent, is_spread_induced)

                if is_spread_induced:
                    logger.warning(
                        f"📛 Spread-induced loss for {ticker}: {final_profit_percent:.2f}% "
                        f"(spread was {spread_percent:.2f}%)"
                    )

                # Reset consecutive loss counter for this ticker
                if cls._exit_engine is not None:
                    cls._exit_engine.reset_ticker(ticker)

                await cls._exit_trade(
                    ticker=ticker,
                    original_action=original_action,
                    enter_price=enter_price,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    technical_indicators_enter=technical_indicators_for_enter,
                    technical_indicators_exit=technical_indicators_for_exit,
                )

        await asyncio.sleep(cls.exit_cycle_seconds)
