"""
UW-Enhanced Momentum Trading Indicator

Uses price momentum with Unusual Whales API validation and volatility-aware risk management.
This is a new indicator that extends the base momentum logic with:
- Unusual Whales options flow validation
- Volatility-based stop losses and trailing stops
- Mean reversion detection
- Enhanced position sizing
"""

import asyncio
import os
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, timezone

import aiohttp

from app.src.common.loguru_logger import logger
from app.src.common.utils import measure_latency
from app.src.services.mcp.mcp_client import MCPClient
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.webhook.send_signal import send_signal_to_webhook
from app.src.services.mab.mab_service import MABService
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator
from app.src.services.market_data.market_data_service import MarketDataService
from app.src.services.trading.volatility_utils import VolatilityUtils
from app.src.services.unusual_whales.uw_client import (
    UnusualWhalesClient,
    FlowSentiment,
    get_unusual_whales_client,
)


class UWEnhancedMomentumIndicator(BaseTradingIndicator):
    """Momentum-based trading indicator with UW validation and volatility awareness"""

    # Momentum-specific configuration
    profit_threshold: float = 1.5
    top_k: int = 2
    exceptional_momentum_threshold: float = 5.0
    min_momentum_threshold: float = 3.0
    max_momentum_threshold: float = 50.0
    min_daily_volume: int = 1000
    stop_loss_threshold: float = -2.5
    trailing_stop_percent: float = 2.5
    min_adx_threshold: float = 20.0
    rsi_oversold_for_long: float = (
        40.0  # Increased from 35.0 - require more oversold for longs
    )
    rsi_overbought_for_short: float = (
        70.0  # Increased from 65.0 - require truly overbought for shorts
    )
    profit_target_strong_momentum: float = 5.0
    min_holding_period_seconds: int = 60

    # Unusual Whales integration
    use_unusual_whales: bool = True
    uw_reject_on_strong_opposing_flow: bool = True

    # Volatility and low-priced stock filters
    min_stock_price: float = 0.10
    max_stock_price_for_penny_treatment: float = 3.0
    max_bid_ask_spread_percent: float = 2.0

    # Dynamic stop loss configuration
    _alpaca_api_key = os.environ.get("REAL_TRADE_API_KEY", "")
    _alpaca_api_secret = os.environ.get("REAL_TRADE_SECRET_KEY", "")
    _alpaca_base_url = "https://data.alpaca.markets/v2/stocks/bars"

    @classmethod
    def indicator_name(cls) -> str:
        return "UW-Enhanced Momentum Trading"

    @classmethod
    def _calculate_atr_percent(cls, atr: float, current_price: float) -> float:
        """Calculate ATR as percentage of current price"""
        if current_price <= 0 or atr <= 0:
            return 0.0
        return (atr / current_price) * 100

    @classmethod
    async def _check_bid_ask_spread(
        cls, ticker: str, enter_price: float
    ) -> Tuple[bool, float, str]:
        """Check if bid-ask spread is acceptable for entry"""
        try:
            quote_response = await MCPClient.get_quote(ticker)
            if not quote_response:
                return True, 0.0, "No quote data available, proceeding"

            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})

            bid = ticker_quote.get("bp", 0.0)
            ask = ticker_quote.get("ap", 0.0)

            if bid <= 0 or ask <= 0:
                return True, 0.0, "Invalid bid/ask data, proceeding"

            spread = ask - bid
            spread_percent = (spread / enter_price) * 100 if enter_price > 0 else 0.0

            max_spread = cls.max_bid_ask_spread_percent
            if enter_price < cls.max_stock_price_for_penny_treatment:
                max_spread = cls.max_bid_ask_spread_percent * 1.5

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
        """Calculate dynamic stop loss based on ATR"""
        default_stop_loss = cls.stop_loss_threshold

        # Use ATR if available (preferred method via VolatilityUtils)
        if technical_analysis:
            atr = technical_analysis.get("atr", 0.0)
            if atr > 0 and enter_price > 0:
                return VolatilityUtils.calculate_volatility_adjusted_stop_loss(
                    enter_price, atr, default_stop_loss
                )

        # Fallback to Alpaca API for stocks under $3 if ATR not available
        if enter_price >= cls.max_stock_price_for_penny_treatment:
            return default_stop_loss

        if not cls._alpaca_api_key or not cls._alpaca_api_secret:
            return default_stop_loss

        try:
            today = datetime.now(timezone.utc).date()
            start_time = datetime.combine(today, datetime.min.time()).replace(
                tzinfo=timezone.utc
            )
            start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")

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
                        return default_stop_loss

                    data = await response.json()
                    bars_dict = data.get("bars", {})
                    bars = bars_dict.get(ticker, [])

                    if not bars or len(bars) < 5:
                        return default_stop_loss

                    high_low_ranges = []
                    for bar in bars:
                        if isinstance(bar, dict):
                            high = bar.get("h")
                            low = bar.get("l")
                            if high is not None and low is not None:
                                high, low = float(high), float(low)
                                if high > 0 and low > 0:
                                    high_low_ranges.append((high - low) / low * 100)

                    if not high_low_ranges:
                        return default_stop_loss

                    avg_volatility = sum(high_low_ranges) / len(high_low_ranges)
                    dynamic_stop_loss = -2.5 - (avg_volatility * 0.5)
                    dynamic_stop_loss = max(-7.0, min(-3.5, dynamic_stop_loss))

                    logger.info(
                        f"Dynamic stop loss for {ticker}: {dynamic_stop_loss:.2f}% "
                        f"(volatility: {avg_volatility:.2f}%, price: ${enter_price:.2f})"
                    )
                    return dynamic_stop_loss

        except Exception as e:
            logger.warning(f"Error calculating dynamic stop loss for {ticker}: {e}")
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
        """Check if ticker is a golden opportunity"""
        is_golden, reason = VolatilityUtils.is_golden_ticker_for_penny_stock(
            momentum_score, market_data, cls.exceptional_momentum_threshold
        )
        if is_golden:
            logger.info(f"Golden ticker detected: {reason}")
        return is_golden

    @classmethod
    async def _validate_with_unusual_whales(
        cls, ticker: str, intended_direction: str, enter_price: float
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate trade against Unusual Whales options flow data"""
        if not cls.use_unusual_whales:
            return True, "UW validation disabled", {}

        try:
            uw_client = get_unusual_whales_client()

            if not uw_client.is_configured:
                return True, "UW not configured", {}

            should_trade, reason, details = await uw_client.should_trade_ticker(
                ticker, intended_direction
            )

            # For penny stocks, also check risk score
            if enter_price < VolatilityUtils.PENNY_STOCK_THRESHOLD:
                risk_score, risk_details = await uw_client.get_penny_stock_risk_score(
                    ticker, enter_price
                )
                details["penny_stock_risk_score"] = risk_score
                details["penny_stock_risk_details"] = risk_details
                if risk_score >= 75:
                    return (
                        False,
                        (
                            f"Penny stock risk too high: {risk_score:.0f}/100 "
                            f"({risk_details.get('risk_factors', [])})"
                        ),
                        details,
                    )

            if not should_trade and cls.uw_reject_on_strong_opposing_flow:
                logger.info(
                    f"UW validation rejected {ticker} {intended_direction}: {reason}"
                )
                return False, reason, details

            return True, reason, details
        except Exception as e:
            logger.warning(f"UW validation error for {ticker}: {e}")
            return True, f"UW validation error: {e}", {}

    @classmethod
    async def _passes_volatility_and_mean_reversion_filters(
        cls,
        ticker: str,
        market_data: Dict[str, Any],
        momentum_score: float,
        enter_price: float,
    ) -> Tuple[bool, str]:
        """Check volatility filter and mean reversion detection"""
        technical_analysis = market_data.get("technical_analysis", {})
        atr = technical_analysis.get("atr", 0)

        # 1. Volatility filter
        passes_vol, vol_reason = VolatilityUtils.passes_volatility_filter(
            enter_price, atr
        )
        if not passes_vol:
            return False, vol_reason

        # 2. Mean reversion check
        bollinger = technical_analysis.get("bollinger", {})
        if isinstance(bollinger, dict):
            upper = bollinger.get("upper", 0)
            lower = bollinger.get("lower", 0)
        else:
            upper, lower = 0, 0

        current_price = technical_analysis.get("close_price", enter_price)
        is_reverting, revert_reason = VolatilityUtils.is_likely_mean_reverting(
            current_price, upper, lower, momentum_score
        )
        if is_reverting:
            return False, revert_reason

        return True, f"Passed volatility filters ({vol_reason})"

    @classmethod
    async def _passes_stock_quality_filters(
        cls, ticker: str, market_data: Dict[str, Any], momentum_score: float = 0.0
    ) -> Tuple[bool, str]:
        """Check if ticker passes stock quality filters"""
        if cls._is_warrant_or_option(ticker):
            return False, f"Excluded: {ticker} is a warrant/option"

        technical_analysis = market_data.get("technical_analysis", {})
        current_price = technical_analysis.get("close_price", 0.0)

        if current_price < cls.min_stock_price:
            return (
                False,
                f"Price too low: ${current_price:.2f} < ${cls.min_stock_price:.2f}",
            )

        # Check volatility filter using VolatilityUtils
        atr = technical_analysis.get("atr", 0)
        passes_vol, vol_reason = VolatilityUtils.passes_volatility_filter(
            current_price, atr
        )
        if not passes_vol:
            return False, vol_reason

        volume = technical_analysis.get("volume", 0)
        volume_sma = technical_analysis.get("volume_sma", 0)
        avg_volume = volume_sma if volume_sma > 0 else volume

        if avg_volume < cls.min_daily_volume:
            return False, f"Volume too low: {avg_volume:,} < {cls.min_daily_volume:,}"

        adx = technical_analysis.get("adx")
        if adx is None:
            return False, "Missing ADX data"

        if adx < cls.min_adx_threshold:
            return False, f"ADX too low: {adx:.2f} < {cls.min_adx_threshold}"

        rsi = technical_analysis.get("rsi", 50.0)
        is_long = momentum_score > 0
        is_short = momentum_score < 0

        if is_long and rsi >= cls.rsi_oversold_for_long:
            return (
                False,
                f"RSI too high for long: {rsi:.2f} >= {cls.rsi_oversold_for_long}",
            )

        if is_short and rsi <= cls.rsi_overbought_for_short:
            return (
                False,
                f"RSI too low for short: {rsi:.2f} <= {cls.rsi_overbought_for_short}",
            )

        # Check stochastic confirmation for shorts (prevent shorting during bullish momentum)
        if is_short:
            stoch = technical_analysis.get("stoch", {})
            stoch_k = stoch.get("k", 50.0) if isinstance(stoch, dict) else 50.0
            stoch_d = stoch.get("d", 50.0) if isinstance(stoch, dict) else 50.0

            # Don't short if stochastic is still bullish (K > D and K > 60)
            # OR if both K and D are extremely high (> 80), indicating strong upward momentum
            # This prevents shorting when stock is extremely overbought but still rising
            if (stoch_k > stoch_d and stoch_k > 60) or (stoch_k > 80 and stoch_d > 80):
                return (
                    False,
                    f"Stochastic still bullish for short: K={stoch_k:.2f}, D={stoch_d:.2f} "
                    f"(upward momentum present or extremely overbought)",
                )

        # Check for mean reversion risk
        bollinger = technical_analysis.get("bollinger", {})
        if isinstance(bollinger, dict):
            upper = bollinger.get("upper", 0)
            lower = bollinger.get("lower", 0)
        else:
            upper, lower = 0, 0

        is_reverting, revert_reason = VolatilityUtils.is_likely_mean_reverting(
            current_price, upper, lower, momentum_score
        )
        if is_reverting:
            return False, revert_reason

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
    async def _send_trade_event(
        cls,
        event_type: str,  # "enter_long", "enter_short", "exit_long", "exit_short"
        ticker: str,
        price: float,
        action: str,
        reason: str,
        technical_indicators: Optional[Dict[str, Any]] = None,
    ):
        """Send trade event via webhook"""
        try:
            await send_signal_to_webhook(
                ticker=ticker,
                action=action,
                indicator=cls.indicator_name(),
                enter_reason=reason,
            )
            logger.info(
                f"📡 Trade event sent: {event_type} for {ticker} at ${price:.2f} - {reason}"
            )
        except Exception as e:
            logger.warning(f"Error sending trade event for {ticker}: {e}")

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
            return False

        lowest_trade, lowest_profit = result
        ticker_to_exit = lowest_trade.get("ticker")

        logger.info(
            f"Preempting {ticker_to_exit} (profit: {lowest_profit:.2f}%) "
            f"for {new_ticker} (momentum: {new_momentum_score:.2f})"
        )

        original_action = lowest_trade.get("action")
        enter_price = lowest_trade.get("enter_price")

        if original_action == "buy_to_open":
            exit_action = "sell_to_close"
        elif original_action == "sell_to_open":
            exit_action = "buy_to_close"
        else:
            return False

        market_data_response = await MCPClient.get_market_data(ticker_to_exit)
        if not market_data_response:
            return False

        technical_analysis = market_data_response.get("technical_analysis", {})
        exit_price = technical_analysis.get("close_price", 0.0)

        if exit_price <= 0:
            return False

        reason = f"Preempted for exceptional trade: {lowest_profit:.2f}% profit"

        technical_indicators_for_enter = lowest_trade.get(
            "technical_indicators_for_enter"
        )
        technical_indicators_for_exit = {
            k: v for k, v in technical_analysis.items() if k != "datetime_price"
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
        logger.info("UW-Enhanced Momentum entry service started")
        while cls.running:
            try:
                await cls._run_entry_cycle()
            except Exception as e:
                logger.exception(
                    f"Error in UW-Enhanced Momentum entry service: {str(e)}"
                )
                await asyncio.sleep(10)

    @classmethod
    @measure_latency
    async def _run_entry_cycle(cls):
        """Execute a single momentum entry cycle with enhanced filtering"""
        logger.debug("Starting UW-Enhanced Momentum entry cycle")
        if not await cls._check_market_open():
            logger.debug("Market is closed, skipping entry logic")
            await asyncio.sleep(cls.entry_cycle_seconds)
            return

        logger.info("Market is open, proceeding with UW-Enhanced Momentum entry logic")

        await cls._reset_daily_stats_if_needed()

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

        candidates_to_fetch = [
            ticker
            for ticker in all_tickers
            if ticker not in active_ticker_set
            and not cls._is_ticker_in_cooldown(ticker)
        ]

        logger.info(f"Fetching market data for {len(candidates_to_fetch)} tickers")

        market_data_dict = await cls._fetch_market_data_batch(
            candidates_to_fetch, max_concurrent=25
        )

        ticker_momentum_scores = []
        stats = {
            "no_market_data": 0,
            "no_datetime_price": 0,
            "low_momentum": 0,
            "failed_quality_filters": 0,
            "failed_volatility_filters": 0,
            "failed_uw_validation": 0,
            "passed": 0,
        }

        inactive_ticker_logs = []

        for ticker in candidates_to_fetch:
            if not cls.running:
                break

            market_data_response = market_data_dict.get(ticker)
            if not market_data_response:
                stats["no_market_data"] += 1
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            datetime_price = technical_analysis.get("datetime_price", [])
            current_price = technical_analysis.get("close_price", 0.0)
            atr = technical_analysis.get("atr", 0)

            if not datetime_price:
                stats["no_datetime_price"] += 1
                continue

            momentum_score, reason = cls._calculate_momentum(datetime_price)
            abs_momentum = abs(momentum_score)

            if abs_momentum < cls.min_momentum_threshold:
                stats["low_momentum"] += 1
                continue

            if abs_momentum > cls.max_momentum_threshold:
                stats["low_momentum"] += 1
                continue

            # Stock quality filters
            passes_filter, filter_reason = await cls._passes_stock_quality_filters(
                ticker, market_data_response, momentum_score
            )
            if not passes_filter:
                stats["failed_quality_filters"] += 1
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": (
                            filter_reason if momentum_score > 0 else None
                        ),
                        "reason_not_to_enter_short": (
                            filter_reason if momentum_score < 0 else None
                        ),
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            # Volatility and mean reversion filters
            passes_vol, vol_reason = (
                await cls._passes_volatility_and_mean_reversion_filters(
                    ticker, market_data_response, momentum_score, current_price
                )
            )
            if not passes_vol:
                stats["failed_volatility_filters"] += 1
                logger.debug(f"Skipping {ticker}: {vol_reason}")
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": (
                            vol_reason if momentum_score > 0 else None
                        ),
                        "reason_not_to_enter_short": (
                            vol_reason if momentum_score < 0 else None
                        ),
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            # Unusual Whales validation
            intended_direction = "long" if momentum_score > 0 else "short"
            passes_uw, uw_reason, uw_details = await cls._validate_with_unusual_whales(
                ticker, intended_direction, current_price
            )
            if not passes_uw:
                stats["failed_uw_validation"] += 1
                logger.info(f"UW rejected {ticker}: {uw_reason}")
                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": (
                            uw_reason if momentum_score > 0 else None
                        ),
                        "reason_not_to_enter_short": (
                            uw_reason if momentum_score < 0 else None
                        ),
                        "technical_indicators": technical_analysis,
                    }
                )
                continue

            stats["passed"] += 1
            ticker_momentum_scores.append((ticker, momentum_score, reason))

            logger.info(
                f"{ticker} passed all filters: momentum={momentum_score:.2f}%, "
                f"ATR%={VolatilityUtils.calculate_atr_percent(atr, current_price):.2f}%, "
                f"UW={uw_reason[:50]}"
            )

        # Batch write inactive ticker logs
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
            f"{stats['no_datetime_price']} no datetime_price, "
            f"{stats['low_momentum']} low momentum, "
            f"{stats['failed_quality_filters']} failed quality, "
            f"{stats['failed_volatility_filters']} failed volatility, "
            f"{stats['failed_uw_validation']} failed UW validation)"
        )

        # Separate upward and downward momentum
        upward_tickers = [(t, s, r) for t, s, r in ticker_momentum_scores if s > 0]
        downward_tickers = [(t, s, r) for t, s, r in ticker_momentum_scores if s < 0]

        # MAB selection
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
            f"MAB selected {len(top_upward)} upward and {len(top_downward)} downward tickers"
        )

        # Process upward momentum (long) trades
        for rank, (ticker, momentum_score, reason) in enumerate(top_upward, start=1):
            if not cls.running:
                break

            daily_limit_reached = await cls._has_reached_daily_trade_limit()
            is_golden = False
            market_data_response = market_data_dict.get(ticker, {})

            if daily_limit_reached:
                is_golden = cls._is_golden_ticker(momentum_score, market_data_response)
                if not is_golden:
                    logger.info(f"Daily limit reached, skipping {ticker} (not golden)")
                    break
                logger.info(
                    f"Daily limit reached, but {ticker} is GOLDEN - allowing entry"
                )

            active_trades = await cls._get_active_trades()
            active_count = len(active_trades)

            if active_count >= cls.max_active_trades:
                if abs(momentum_score) >= cls.exceptional_momentum_threshold:
                    preempted = await cls._preempt_low_profit_trade(
                        ticker, momentum_score
                    )
                    if not preempted:
                        continue
                else:
                    continue

            action = "buy_to_open"
            quote_response = await MCPClient.get_quote(ticker)
            if not quote_response:
                continue

            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})
            enter_price = ticker_quote.get("ap", 0.0)

            if enter_price <= 0:
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            atr = technical_analysis.get("atr", 0)

            # Calculate volatility-adjusted settings
            dynamic_stop_loss = await cls._calculate_dynamic_stop_loss(
                ticker, enter_price, technical_analysis
            )
            if atr > 0:
                dynamic_stop_loss = (
                    VolatilityUtils.calculate_volatility_adjusted_stop_loss(
                        enter_price, atr, cls.stop_loss_threshold
                    )
                )

            position_multiplier = VolatilityUtils.calculate_position_size_multiplier(
                enter_price, atr
            )
            volatility_trailing_stop = (
                VolatilityUtils.calculate_volatility_adjusted_trailing_stop(
                    enter_price, enter_price, atr, cls.trailing_stop_percent
                )
            )

            golden_prefix = "🟡 GOLDEN: " if is_golden else ""
            ranked_reason = (
                f"{golden_prefix}{reason} (ranked #{rank} upward momentum, "
                f"trailing_stop={volatility_trailing_stop:.2f}%, "
                f"stop_loss={dynamic_stop_loss:.2f}%, "
                f"pos_size={position_multiplier:.0%})"
            )

            # Send enter long event
            await cls._send_trade_event(
                "enter_long",
                ticker,
                enter_price,
                action,
                ranked_reason,
                technical_analysis,
            )

            technical_indicators_for_enter = {
                k: v for k, v in technical_analysis.items() if k != "datetime_price"
            }

            await cls._enter_trade(
                ticker=ticker,
                action=action,
                enter_price=enter_price,
                enter_reason=ranked_reason,
                technical_indicators=technical_indicators_for_enter,
                dynamic_stop_loss=dynamic_stop_loss,
            )

        # Process downward momentum (short) trades
        for rank, (ticker, momentum_score, reason) in enumerate(top_downward, start=1):
            if not cls.running:
                break

            daily_limit_reached = await cls._has_reached_daily_trade_limit()
            is_golden = False
            market_data_response = market_data_dict.get(ticker, {})

            if daily_limit_reached:
                is_golden = cls._is_golden_ticker(momentum_score, market_data_response)
                if not is_golden:
                    break
                logger.info(
                    f"Daily limit reached, but {ticker} is GOLDEN - allowing entry"
                )

            active_trades = await cls._get_active_trades()
            active_count = len(active_trades)

            if active_count >= cls.max_active_trades:
                if abs(momentum_score) >= cls.exceptional_momentum_threshold:
                    preempted = await cls._preempt_low_profit_trade(
                        ticker, abs(momentum_score)
                    )
                    if not preempted:
                        continue
                else:
                    continue

            # Check if ticker is shortable before attempting short trade
            is_shortable, shortable_reason = (
                await MarketDataService.check_ticker_shortable(
                    ticker, indicator=cls.indicator_name()
                )
            )
            if not is_shortable:
                logger.debug(f"Skipping short entry for {ticker}: {shortable_reason}")
                continue

            # Re-check stock quality filters before entry (even for golden tickers)
            # This ensures RSI/stochastic filters are enforced at entry time
            if market_data_response:
                passes_filter, filter_reason = await cls._passes_stock_quality_filters(
                    ticker, market_data_response, momentum_score
                )
                if not passes_filter:
                    logger.info(
                        f"Skipping {ticker} short entry: {filter_reason} "
                        f"{'(was golden but failed filters at entry)' if is_golden else ''}"
                    )
                    continue

            action = "sell_to_open"
            quote_response = await MCPClient.get_quote(ticker)
            if not quote_response:
                continue

            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})
            enter_price = ticker_quote.get("bp", 0.0)

            if enter_price <= 0:
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            atr = technical_analysis.get("atr", 0)

            dynamic_stop_loss = await cls._calculate_dynamic_stop_loss(
                ticker, enter_price, technical_analysis
            )
            if atr > 0:
                dynamic_stop_loss = (
                    VolatilityUtils.calculate_volatility_adjusted_stop_loss(
                        enter_price, atr, cls.stop_loss_threshold
                    )
                )

            position_multiplier = VolatilityUtils.calculate_position_size_multiplier(
                enter_price, atr
            )
            volatility_trailing_stop = (
                VolatilityUtils.calculate_volatility_adjusted_trailing_stop(
                    enter_price, enter_price, atr, cls.trailing_stop_percent
                )
            )

            golden_prefix = "🟡 GOLDEN: " if is_golden else ""
            ranked_reason = (
                f"{golden_prefix}{reason} (ranked #{rank} downward momentum, "
                f"trailing_stop={volatility_trailing_stop:.2f}%, "
                f"stop_loss={dynamic_stop_loss:.2f}%, "
                f"pos_size={position_multiplier:.0%})"
            )

            # Send enter short event
            await cls._send_trade_event(
                "enter_short",
                ticker,
                enter_price,
                action,
                ranked_reason,
                technical_analysis,
            )

            technical_indicators_for_enter = {
                k: v for k, v in technical_analysis.items() if k != "datetime_price"
            }

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
        logger.info("UW-Enhanced Momentum exit service started")
        while cls.running:
            try:
                await cls._run_exit_cycle()
            except Exception as e:
                logger.exception(
                    f"Error in UW-Enhanced Momentum exit service: {str(e)}"
                )
                await asyncio.sleep(5)

    @classmethod
    @measure_latency
    async def _run_exit_cycle(cls):
        """Execute a single momentum exit monitoring cycle with cooling period"""
        if not await cls._check_market_open():
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        active_trades = await cls._get_active_trades()
        if not active_trades:
            await asyncio.sleep(cls.exit_cycle_seconds)
            return

        logger.info(
            f"Monitoring {len(active_trades)}/{cls.max_active_trades} active trades"
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
            dynamic_stop_loss = trade.get("dynamic_stop_loss")
            stop_loss_threshold = (
                float(dynamic_stop_loss)
                if dynamic_stop_loss is not None
                else cls.stop_loss_threshold
            )

            if not ticker or enter_price is None or enter_price <= 0:
                continue

            market_data_response = await MCPClient.get_market_data(ticker)
            if not market_data_response:
                continue

            technical_analysis = market_data_response.get("technical_analysis", {})
            current_price = technical_analysis.get("close_price", 0.0)
            atr = technical_analysis.get("atr", 0)

            if current_price <= 0:
                continue

            profit_percent = cls._calculate_profit_percent(
                enter_price, current_price, original_action
            )

            should_exit = False
            exit_reason = None

            # Hard stop loss always applies
            if profit_percent < stop_loss_threshold:
                should_exit = True
                exit_reason = (
                    f"Stop loss triggered: {profit_percent:.2f}% "
                    f"(threshold: {stop_loss_threshold:.2f}%)"
                )

            # Check if trailing stop should apply (cooling period)
            # Trailing stop should only protect profits, not trigger on losses
            if not should_exit and peak_profit_percent > 0 and profit_percent > 0:
                should_apply_trailing, cooling_reason = (
                    VolatilityUtils.should_apply_trailing_stop(
                        enter_price, created_at, profit_percent
                    )
                )
                if should_apply_trailing:
                    volatility_trailing_stop = (
                        VolatilityUtils.calculate_volatility_adjusted_trailing_stop(
                            enter_price, current_price, atr, cls.trailing_stop_percent
                        )
                    )
                    drop_from_peak = peak_profit_percent - profit_percent
                    if drop_from_peak >= volatility_trailing_stop:
                        should_exit = True
                        exit_reason = (
                            f"Volatility-adjusted trailing stop: profit dropped {drop_from_peak:.2f}% "
                            f"from peak {peak_profit_percent:.2f}% "
                            f"(threshold: {volatility_trailing_stop:.2f}%, current: {profit_percent:.2f}%)"
                        )
                else:
                    logger.debug(f"{ticker}: {cooling_reason}")
            elif not should_exit and peak_profit_percent > 0 and profit_percent <= 0:
                # Trade is already negative - trailing stop doesn't apply
                # The hard stop loss will handle it if it gets worse
                logger.debug(
                    f"Trailing stop not applicable for {ticker}: "
                    f"current profit {profit_percent:.2f}% is negative "
                    f"(peak was {peak_profit_percent:.2f}%)"
                )

            # Profit target
            if not should_exit:
                if profit_percent >= cls.profit_target_strong_momentum:
                    should_exit = True
                    exit_reason = f"Profit target reached: {profit_percent:.2f}%"

            if not should_exit:
                if profit_percent > peak_profit_percent:
                    peak_profit_percent = profit_percent
                    trailing_stop = (
                        VolatilityUtils.calculate_volatility_adjusted_trailing_stop(
                            enter_price, current_price, atr, cls.trailing_stop_percent
                        )
                    )

                skipped_reason = (
                    f"Profit: {profit_percent:.2f}%, "
                    f"trailing_stop: {trailing_stop:.2f}%, "
                    f"peak: {peak_profit_percent:.2f}%"
                )

                await DynamoDBClient.update_momentum_trade_trailing_stop(
                    ticker=ticker,
                    indicator=cls.indicator_name(),
                    trailing_stop=trailing_stop,
                    peak_profit_percent=peak_profit_percent,
                    skipped_exit_reason=skipped_reason,
                )

            if should_exit:
                logger.info(f"Exit signal for {ticker}: {exit_reason}")

                # Determine exit event type
                if original_action == "buy_to_open":
                    exit_event_type = "exit_long"
                    exit_action = "sell_to_close"
                else:
                    exit_event_type = "exit_short"
                    exit_action = "buy_to_close"

                technical_indicators_for_enter = trade.get(
                    "technical_indicators_for_enter"
                )
                technical_indicators_for_exit = {
                    k: v for k, v in technical_analysis.items() if k != "datetime_price"
                }

                # Send exit event
                await cls._send_trade_event(
                    exit_event_type,
                    ticker,
                    current_price,
                    exit_action,
                    exit_reason,
                    technical_indicators_for_exit,
                )

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
