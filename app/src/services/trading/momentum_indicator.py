"""
Momentum Trading Indicator
Uses price momentum to identify entry and exit signals
"""

import asyncio
import os
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, timezone, time
import pytz

from app.src.common.loguru_logger import logger
from app.src.common.utils import measure_latency
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
    max_momentum_threshold: float = (
        50.0  # Avoid entering on extreme momentum (likely at peak)
    )
    min_daily_volume: int = 1000
    stop_loss_threshold: float = -2.5  # Increased from -1.5% to give trades more room
    trailing_stop_percent: float = 2.5  # Increased from 1.5% to reduce premature exits
    min_adx_threshold: float = 20.0
    rsi_oversold_for_long: float = 40.0  # Increased from 35.0 - require more oversold for longs
    rsi_overbought_for_short: float = 70.0  # Increased from 65.0 - require truly overbought for shorts
    profit_target_strong_momentum: float = 5.0
    min_holding_period_seconds: int = (
        60  # Minimum 60 seconds before allowing exit (prevent instant exits)
    )

    # Volatility and low-priced stock filters
    min_stock_price: float = (
        0.10  # Minimum stock price to trade (avoid extreme penny stocks)
    )
    max_stock_price_for_penny_treatment: float = (
        3.0  # Stocks under this price get special handling
    )
    max_atr_percent_for_entry: float = (
        5.0  # Maximum ATR% to allow entry (5% = very volatile)
    )
    max_volatility_for_low_price: float = 4.0  # Max ATR% for stocks under $3
    min_price_for_standard_entry: float = 2.0  # Stocks above this use standard filters
    max_bid_ask_spread_percent: float = 2.0  # Maximum bid-ask spread % for entry
    trailing_stop_penny_stock_multiplier: float = (
        1.5  # Wider trailing stop for penny stocks
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
        180  # 3 minutes - don't activate trailing stop until this time has passed (for penny stocks)
    )
    min_trailing_stop_cooldown_seconds: int = (
        120  # 2 minutes minimum cooldown for ALL stocks to prevent whipsaw exits
    )
    force_close_before_market_close: bool = True  # Force close all positions before market close
    minutes_before_close_to_exit: int = 15  # Exit positions 15 minutes before market close

    # Dynamic stop loss configuration
    _alpaca_api_key = os.environ.get("REAL_TRADE_API_KEY", "")
    _alpaca_api_secret = os.environ.get("REAL_TRADE_SECRET_KEY", "")
    _alpaca_base_url = "https://data.alpaca.markets/v2/stocks/bars"

    @classmethod
    def indicator_name(cls) -> str:
        return "Momentum Trading"

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
        current_time_only = current_time_est.time()
        
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
    def _calculate_atr_percent(cls, atr: float, current_price: float) -> float:
        """Calculate ATR as percentage of current price"""
        if current_price <= 0 or atr <= 0:
            return 0.0
        return (atr / current_price) * 100

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
        if enter_price <= 0 or atr <= 0 or current_price <= 0:
            return cls.trailing_stop_percent

        # Calculate ATR as percentage of price
        atr_percent = cls._calculate_atr_percent(atr, current_price)

        # Use 2.5x ATR for trailing stop, with min/max bounds
        trailing_stop = atr_percent * 2.5

        # Bounds: minimum 2%, maximum 8% for penny stocks
        if enter_price < 5.0:  # Penny stock threshold
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
            quote_response = await MCPClient.get_quote(ticker)
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
    ) -> float:
        """
        Calculate dynamic stop loss based on ATR and intraday volatility.

        Args:
            ticker: Stock ticker symbol
            enter_price: Entry price for the trade
            technical_analysis: Technical indicators including ATR

        Returns:
            Dynamic stop loss percentage (negative value, e.g., -3.5 for -3.5%)
        """
        # Default stop loss if we can't calculate dynamic one
        default_stop_loss = cls.stop_loss_threshold

        # Use ATR if available (preferred method)
        if technical_analysis:
            atr = technical_analysis.get("atr", 0.0)
            if atr > 0 and enter_price > 0:
                atr_percent = cls._calculate_atr_percent(atr, enter_price)

                # For low-priced stocks, use wider stop loss based on ATR
                is_low_price = enter_price < cls.max_stock_price_for_penny_treatment

                if is_low_price:
                    # Use 2x ATR for penny stocks, but cap at reasonable levels
                    stop_loss_atr_multiple = 2.0
                    dynamic_stop_loss = -(atr_percent * stop_loss_atr_multiple)
                    # Cap between -3.5% and -7.0% for penny stocks
                    dynamic_stop_loss = max(-7.0, min(-3.5, dynamic_stop_loss))

                    logger.info(
                        f"ATR-based stop loss for {ticker}: {dynamic_stop_loss:.2f}% "
                        f"(ATR: {atr_percent:.2f}%, enter_price: ${enter_price:.2f})"
                    )
                    return dynamic_stop_loss
                else:
                    # For higher-priced stocks, use 1.5x ATR
                    stop_loss_atr_multiple = 1.5
                    dynamic_stop_loss = -(atr_percent * stop_loss_atr_multiple)
                    # Cap between -2.5% and -5.0% for regular stocks
                    dynamic_stop_loss = max(-5.0, min(-2.5, dynamic_stop_loss))

                    logger.info(
                        f"ATR-based stop loss for {ticker}: {dynamic_stop_loss:.2f}% "
                        f"(ATR: {atr_percent:.2f}%, enter_price: ${enter_price:.2f})"
                    )
                    return dynamic_stop_loss

        # Fallback to Alpaca API for stocks under $3 if ATR not available
        if enter_price >= cls.max_stock_price_for_penny_treatment:
            return default_stop_loss

        # Check if we have API credentials
        if not cls._alpaca_api_key or not cls._alpaca_api_secret:
            logger.debug(
                f"No Alpaca API credentials, using default stop loss for {ticker}"
            )
            return default_stop_loss

        try:
            # Get today's date in UTC
            today = datetime.now(timezone.utc).date()
            start_time = datetime.combine(today, datetime.min.time()).replace(
                tzinfo=timezone.utc
            )
            start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Fetch intraday bars (1-minute) for today
            url = f"{cls._alpaca_base_url}"
            params = {
                "symbols": ticker,
                "timeframe": "1Min",
                "start": start_iso,
                "limit": 1000,
                "adjustment": "raw",
                "feed": "sip",
                "sort": "asc",
            }
            headers = {
                "accept": "application/json",
                "APCA-API-KEY-ID": cls._alpaca_api_key,
                "APCA-API-SECRET-KEY": cls._alpaca_api_secret,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params={k: str(v) for k, v in params.items()},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status != 200:
                        logger.debug(
                            f"Alpaca API returned status {response.status} for {ticker}, using default stop loss"
                        )
                        return default_stop_loss

                    try:
                        data = await response.json()
                    except Exception as json_error:
                        logger.warning(
                            f"Failed to parse JSON response for {ticker}: {str(json_error)}, using default stop loss"
                        )
                        return default_stop_loss

                    # Validate response structure
                    if not isinstance(data, dict):
                        logger.warning(
                            f"Invalid response format for {ticker}: expected dict, got {type(data)}, using default stop loss"
                        )
                        return default_stop_loss

                    bars_dict = data.get("bars", {})
                    if not isinstance(bars_dict, dict):
                        logger.warning(
                            f"Invalid bars format for {ticker}: expected dict, got {type(bars_dict)}, using default stop loss"
                        )
                        return default_stop_loss

                    bars = bars_dict.get(ticker, [])
                    if not isinstance(bars, list):
                        logger.warning(
                            f"Invalid bars list for {ticker}: expected list, got {type(bars)}, using default stop loss"
                        )
                        return default_stop_loss

                    if not bars or len(bars) < 5:
                        logger.debug(
                            f"Insufficient bars data for {ticker} ({len(bars) if bars else 0} bars), using default stop loss"
                        )
                        return default_stop_loss

                    # Extract prices from bars
                    prices = []
                    for bar in bars:
                        if not isinstance(bar, dict):
                            logger.debug(
                                f"Skipping invalid bar entry for {ticker}: not a dict"
                            )
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
                    price_range_pct = (
                        (price_range / min_price) * 100 if min_price > 0 else 0
                    )

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
                        sum(high_low_ranges) / len(high_low_ranges)
                        if high_low_ranges
                        else 0
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
                                    recent_high_low_ranges.append(
                                        (high - low) / low * 100
                                    )
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
                    dynamic_stop_loss = (
                        -2.5 - (price_range_pct * 0.5) - (volatility * 0.5)
                    )
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
        technical_analysis = market_data.get("technical_analysis", {})
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
        """
        technical_analysis = market_data.get("technical_analysis", {})
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

        technical_analysis = market_data.get("technical_analysis", {})
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
            # Stricter volatility filter for low-priced stocks
            if volatility_score > cls.max_volatility_for_low_price:
                return (
                    False,
                    f"Too volatile for low-priced stock: {volatility_reason} "
                    f"(exceeds {cls.max_volatility_for_low_price:.2f}% limit for stocks < ${cls.max_stock_price_for_penny_treatment})",
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

        adx = technical_analysis.get("adx")
        if adx is None:
            return False, "Missing ADX data"

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

        # Check stochastic confirmation for shorts (prevent shorting during bullish momentum)
        if is_short:
            stoch = technical_analysis.get("stoch", {})
            stoch_k = stoch.get("k", 50.0) if isinstance(stoch, dict) else 50.0
            stoch_d = stoch.get("d", 50.0) if isinstance(stoch, dict) else 50.0
            
            # Don't short if stochastic is still bullish (K > D and K > 60)
            # This indicates upward momentum is still present
            if stoch_k > stoch_d and stoch_k > 60:
                return (
                    False,
                    f"Stochastic still bullish for short: K={stoch_k:.2f} > D={stoch_d:.2f} and K > 60 (upward momentum present)",
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
                await cls._run_entry_cycle()
            except Exception as e:
                logger.exception(f"Error in momentum entry service: {str(e)}")
                await asyncio.sleep(10)

    @classmethod
    @measure_latency
    async def _run_entry_cycle(cls):
        """Execute a single momentum entry cycle."""
        logger.debug("Starting momentum entry cycle")
        if not await cls._check_market_open():
            logger.debug("Market is closed, skipping momentum entry logic")
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        logger.info(
            "Market is open, proceeding with momentum entry logic (HIGHLY SELECTIVE)"
        )

        await cls._reset_daily_stats_if_needed()

        # Check daily limit (will be bypassed for golden tickers later)
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

        # Fetch market data in parallel batches (increased concurrency for speed)
        market_data_dict = await cls._fetch_market_data_batch(
            candidates_to_fetch, max_concurrent=25
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
                        "reason_not_to_enter_long": "No market data response",
                        "reason_not_to_enter_short": "No market data response",
                        "technical_indicators": None,
                    }
                )
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            datetime_price = technical_analysis.get("datetime_price", [])

            if not datetime_price:
                stats["no_datetime_price"] += 1
                logger.debug(f"No datetime_price data for {ticker}")
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": "No datetime_price data",
                        "reason_not_to_enter_short": "No datetime_price data",
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            momentum_score, reason = cls._calculate_momentum(datetime_price)

            abs_momentum = abs(momentum_score)
            if abs_momentum < cls.min_momentum_threshold:
                stats["low_momentum"] += 1
                logger.debug(
                    f"Skipping {ticker}: momentum {momentum_score:.2f}% < "
                    f"minimum threshold {cls.min_momentum_threshold}%"
                )
                # Determine long/short based on momentum sign
                if momentum_score > 0:
                    reason_long = f"Momentum {momentum_score:.2f}% < minimum threshold {cls.min_momentum_threshold}%"
                    reason_short = None
                else:
                    reason_long = None
                    reason_short = f"Momentum {momentum_score:.2f}% < minimum threshold {cls.min_momentum_threshold}%"

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
                # Determine long/short based on momentum sign
                if momentum_score > 0:
                    reason_long = f"Momentum {momentum_score:.2f}% > maximum threshold {cls.max_momentum_threshold}% (likely at peak)"
                    reason_short = None
                else:
                    reason_long = None
                    reason_short = f"Momentum {momentum_score:.2f}% > maximum threshold {cls.max_momentum_threshold}% (likely at peak)"

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
                # Determine long/short based on momentum sign
                if momentum_score > 0:
                    reason_long = filter_reason
                    reason_short = None
                else:
                    reason_long = None
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
            logger.info(
                f"{ticker} passed all filters: momentum={momentum_score:.2f}%, "
                f"{filter_reason}"
            )

        # Batch write all inactive ticker reasons in parallel
        if inactive_ticker_logs:

            async def log_one(log_data):
                await DynamoDBClient.log_inactive_ticker_reason(**log_data)

            # Write in batches of 20 to avoid overwhelming DynamoDB
            batch_size = 20
            for i in range(0, len(inactive_ticker_logs), batch_size):
                batch = inactive_ticker_logs[i : i + batch_size]
                await asyncio.gather(
                    *[log_one(log_data) for log_data in batch], return_exceptions=True
                )

        logger.info(
            f"Calculated momentum scores for {len(ticker_momentum_scores)} tickers "
            f"(filtered: {stats['no_market_data']} no data, "
            f"{stats['no_datetime_price']} no datetime_price, "
            f"{stats['low_momentum']} low momentum, "
            f"{stats['failed_quality_filters']} failed quality filters)"
        )

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

        for rank, (ticker, momentum_score, reason) in enumerate(top_upward, start=1):
            if not cls.running:
                break

            # Check if daily limit reached (allow golden tickers to bypass)
            daily_limit_reached = await cls._has_reached_daily_trade_limit()
            is_golden = False

            if daily_limit_reached:
                market_data_response = market_data_dict.get(ticker)
                if market_data_response:
                    is_golden = cls._is_golden_ticker(
                        momentum_score, market_data_response
                    )
                    if not is_golden:
                        logger.info(
                            f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                            f"Skipping {ticker} (not golden/exceptional)."
                        )
                        break
                    else:
                        logger.info(
                            f"Daily trade limit reached, but {ticker} is GOLDEN "
                            f"(momentum: {momentum_score:.2f}%) - allowing entry"
                        )
                else:
                    logger.info(
                        f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                        f"Skipping {ticker} (no market data to verify golden status)."
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

            # Check bid-ask spread before entry
            spread_acceptable, spread_percent, spread_reason = (
                await cls._check_bid_ask_spread(ticker, enter_price)
            )
            if not spread_acceptable:
                logger.info(
                    f"Skipping {ticker}: {spread_reason} (enter_price: ${enter_price:.2f})"
                )
                continue

            golden_prefix = "🟡 GOLDEN: " if is_golden else ""
            ranked_reason = f"{golden_prefix}{reason} (ranked #{rank} upward momentum)"
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

            # Calculate dynamic stop loss for penny stocks
            dynamic_stop_loss = await cls._calculate_dynamic_stop_loss(
                ticker, enter_price, technical_indicators_for_enter
            )

            await cls._enter_trade(
                ticker=ticker,
                action=action,
                enter_price=enter_price,
                enter_reason=ranked_reason,
                technical_indicators=technical_indicators_for_enter,
                dynamic_stop_loss=dynamic_stop_loss,
            )

        for rank, (ticker, momentum_score, reason) in enumerate(top_downward, start=1):
            if not cls.running:
                break

            # Check if daily limit reached (allow golden tickers to bypass)
            daily_limit_reached = await cls._has_reached_daily_trade_limit()
            is_golden = False

            if daily_limit_reached:
                market_data_response = market_data_dict.get(ticker)
                if market_data_response:
                    is_golden = cls._is_golden_ticker(
                        momentum_score, market_data_response
                    )
                    if not is_golden:
                        logger.info(
                            f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                            f"Skipping {ticker} (not golden/exceptional)."
                        )
                        break
                    else:
                        logger.info(
                            f"Daily trade limit reached, but {ticker} is GOLDEN "
                            f"(momentum: {momentum_score:.2f}%) - allowing entry"
                        )
                else:
                    logger.info(
                        f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                        f"Skipping {ticker} (no market data to verify golden status)."
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

            # Check bid-ask spread before entry
            spread_acceptable, spread_percent, spread_reason = (
                await cls._check_bid_ask_spread(ticker, enter_price)
            )
            if not spread_acceptable:
                logger.info(
                    f"Skipping {ticker}: {spread_reason} (enter_price: ${enter_price:.2f})"
                )
                continue

            golden_prefix = "🟡 GOLDEN: " if is_golden else ""
            ranked_reason = (
                f"{golden_prefix}{reason} (ranked #{rank} downward momentum)"
            )
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

            # Calculate dynamic stop loss for penny stocks
            dynamic_stop_loss = await cls._calculate_dynamic_stop_loss(
                ticker, enter_price, technical_indicators_for_enter
            )

            await cls._enter_trade(
                ticker=ticker,
                action=action,
                enter_price=enter_price,
                enter_reason=ranked_reason,
                technical_indicators=technical_indicators_for_enter,
                dynamic_stop_loss=dynamic_stop_loss,
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
    @measure_latency
    async def _run_exit_cycle(cls):
        """Execute a single momentum exit monitoring cycle."""
        if not await cls._check_market_open():
            logger.debug("Market is closed, skipping momentum exit logic")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_trades = await cls._get_active_trades()

        if not active_trades:
            logger.debug("No active momentum trades to monitor")
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_count = len(active_trades)
        logger.info(
            f"Monitoring {active_count}/{cls.max_active_trades} active momentum trades"
        )

        # Check if we need to force close positions before market close
        is_near_close = cls._is_near_market_close()
        if is_near_close:
            logger.info(
                f"Near market close - forcing exit of all {active_count} active positions "
                f"({cls.minutes_before_close_to_exit} minutes before close)"
            )

        for trade in active_trades:
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

            # Check minimum holding period
            holding_period_minutes = 0
            if created_at:
                try:
                    enter_time = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    if enter_time.tzinfo is None:
                        enter_time = enter_time.replace(tzinfo=timezone.utc)
                    current_time = datetime.now(timezone.utc)
                    holding_period_seconds = (current_time - enter_time).total_seconds()
                    holding_period_minutes = holding_period_seconds / 60.0

                    if holding_period_seconds < cls.min_holding_period_seconds:
                        logger.debug(
                            f"Skipping exit check for {ticker}: "
                            f"holding period {holding_period_seconds:.1f}s < "
                            f"minimum {cls.min_holding_period_seconds}s"
                        )
                        continue
                except Exception as e:
                    logger.warning(
                        f"Error calculating holding period for {ticker}: {str(e)}"
                    )

            market_data_response = await MCPClient.get_market_data(ticker)
            if not market_data_response:
                logger.warning(
                    f"Failed to get market data for {ticker} for exit check - will retry in next cycle"
                )
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            current_price = technical_analysis.get("close_price", 0.0)

            if current_price <= 0:
                logger.warning(f"Failed to get valid current price for {ticker}")
                continue

            profit_percent = cls._calculate_profit_percent(
                enter_price, current_price, original_action
            )

            should_exit = False
            exit_reason = None

            # Force exit before market close
            if is_near_close:
                should_exit = True
                exit_reason = (
                    f"End-of-day closure: exiting {cls.minutes_before_close_to_exit} minutes before market close "
                    f"(current profit: {profit_percent:.2f}%)"
                )
                logger.info(
                    f"Force exit for {ticker} before market close: {exit_reason}"
                )

            # Time-based exit for volatile/low-priced stocks (check after getting market data)
            if holding_period_minutes > 0:
                is_low_price = enter_price < cls.max_stock_price_for_penny_treatment
                atr = technical_analysis.get("atr", 0.0)
                atr_percent = (
                    cls._calculate_atr_percent(atr, current_price)
                    if atr > 0 and current_price > 0
                    else 0.0
                )
                is_volatile = atr_percent > 3.0

                max_holding_minutes = None
                if is_low_price:
                    max_holding_minutes = cls.max_holding_time_penny_stocks_minutes
                elif is_volatile:
                    max_holding_minutes = cls.max_holding_time_volatile_stocks_minutes

                if (
                    max_holding_minutes
                    and holding_period_minutes >= max_holding_minutes
                ):
                    should_exit = True
                    exit_reason = (
                        f"Time-based exit: held for {holding_period_minutes:.1f} minutes "
                        f"(max: {max_holding_minutes} min for {'penny' if is_low_price else 'volatile'} stock, "
                        f"profit: {profit_percent:.2f}%)"
                    )
                    logger.info(
                        f"Exit signal for {ticker} - time-based exit: "
                        f"held {holding_period_minutes:.1f} min, profit: {profit_percent:.2f}%"
                    )

            if profit_percent < stop_loss_threshold:
                should_exit = True
                exit_reason = (
                    f"Trailing stop loss triggered: {profit_percent:.2f}% "
                    f"(below {stop_loss_threshold:.2f}% stop loss threshold"
                    f"{' (dynamic)' if dynamic_stop_loss is not None else ''})"
                )
                logger.info(
                    f"Exit signal for {ticker} - losing trade: {profit_percent:.2f}%"
                )

            elif peak_profit_percent > 0:
                # Check if trailing stop should be active (cooling-off period)
                trailing_stop_active = True
                if created_at:
                    try:
                        enter_time = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                        if enter_time.tzinfo is None:
                            enter_time = enter_time.replace(tzinfo=timezone.utc)
                        elapsed_seconds = (
                            datetime.now(timezone.utc) - enter_time
                        ).total_seconds()

                        # Apply minimum cooldown for ALL stocks to prevent whipsaw exits
                        # For penny stocks, use longer cooldown
                        is_low_price = (
                            enter_price < cls.max_stock_price_for_penny_treatment
                        )
                        required_cooldown = (
                            cls.trailing_stop_cooldown_seconds
                            if is_low_price
                            else cls.min_trailing_stop_cooldown_seconds
                        )
                        if elapsed_seconds < required_cooldown:
                            trailing_stop_active = False
                            logger.debug(
                                f"Trailing stop not active for {ticker}: "
                                f"cooling period ({elapsed_seconds:.0f}s < {required_cooldown}s) "
                                f"{'(penny stock)' if is_low_price else '(standard)'}"
                            )
                    except Exception as e:
                        logger.debug(
                            f"Error checking trailing stop cooldown for {ticker}: {str(e)}"
                        )

                if trailing_stop_active:
                    # Calculate ATR-based trailing stop
                    atr = technical_analysis.get("atr", 0.0)
                    if atr > 0:
                        # Use ATR-based trailing stop (more sophisticated)
                        dynamic_trailing_stop = (
                            cls._calculate_volatility_adjusted_trailing_stop(
                                enter_price, atr, current_price
                            )
                        )
                    else:
                        # Fallback to multiplier-based approach if no ATR
                        is_low_price = (
                            enter_price < cls.max_stock_price_for_penny_treatment
                        )
                        atr_percent = (
                            cls._calculate_atr_percent(atr, current_price)
                            if atr > 0 and current_price > 0
                            else 0.0
                        )

                        base_trailing_stop = cls.trailing_stop_percent
                        if is_low_price:
                            dynamic_trailing_stop = (
                                base_trailing_stop
                                * cls.trailing_stop_penny_stock_multiplier
                            )
                        elif atr_percent > 3.0:  # High volatility
                            dynamic_trailing_stop = (
                                base_trailing_stop
                                * cls.trailing_stop_volatile_multiplier
                            )
                        else:
                            dynamic_trailing_stop = base_trailing_stop

                    # Trailing stop should only protect profits, not trigger on losses
                    # Only apply trailing stop if current profit is still positive
                    if profit_percent > 0:
                        drop_from_peak = peak_profit_percent - profit_percent
                        if drop_from_peak >= dynamic_trailing_stop:
                            should_exit = True
                            exit_reason = (
                                f"Trailing stop triggered: profit dropped {drop_from_peak:.2f}% "
                                f"from peak of {peak_profit_percent:.2f}% (current: {profit_percent:.2f}%, "
                                f"trailing stop: {dynamic_trailing_stop:.2f}%)"
                            )
                            logger.info(
                                f"Exit signal for {ticker} - trailing stop: "
                                f"peak {peak_profit_percent:.2f}%, current {profit_percent:.2f}%, "
                                f"trailing stop: {dynamic_trailing_stop:.2f}%"
                            )
                    else:
                        # Trade is already negative - trailing stop doesn't apply
                        # The hard stop loss will handle it if it gets worse
                        logger.debug(
                            f"Trailing stop not applicable for {ticker}: "
                            f"current profit {profit_percent:.2f}% is negative "
                            f"(peak was {peak_profit_percent:.2f}%)"
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
                    # Calculate dynamic trailing stop for updating (use ATR-based if available)
                    atr = technical_analysis.get("atr", 0.0)
                    if atr > 0:
                        trailing_stop = (
                            cls._calculate_volatility_adjusted_trailing_stop(
                                enter_price, atr, current_price
                            )
                        )
                    else:
                        # Fallback to multiplier-based approach
                        is_low_price = (
                            enter_price < cls.max_stock_price_for_penny_treatment
                        )
                        atr_percent = (
                            cls._calculate_atr_percent(atr, current_price)
                            if atr > 0 and current_price > 0
                            else 0.0
                        )

                        if is_low_price:
                            trailing_stop = (
                                cls.trailing_stop_percent
                                * cls.trailing_stop_penny_stock_multiplier
                            )
                        elif atr_percent > 3.0:
                            trailing_stop = (
                                cls.trailing_stop_percent
                                * cls.trailing_stop_volatile_multiplier
                            )
                        else:
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
