"""
Deep Analyzer Trading Indicator
Uses MarketDataService for deep technical analysis to identify entry and exit signals
"""

import asyncio
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, date, timezone
import pytz

from app.src.common.loguru_logger import logger
from app.src.common.utils import measure_latency
from app.src.services.mcp.mcp_client import MCPClient
from app.src.services.market_data.market_data_service import MarketDataService
from app.src.services.mab.mab_service import MABService
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.trading.base_trading_indicator import BaseTradingIndicator
from app.src.services.trading.realtime_quote_utils import RealtimeQuoteUtils


class DeepAnalyzerIndicator(BaseTradingIndicator):
    """Deep Analyzer trading indicator using MarketDataService"""

    # Deep Analyzer specific configuration
    top_k: int = 2
    min_entry_score: float = (
        0.60  # Minimum entry score from MarketDataService (lowered from 0.70)
    )
    exceptional_entry_score: float = (
        0.75  # Exceptional entry score for golden tickers (lowered from 0.90)
    )
    
    # Penny stock trailing stop configuration
    max_stock_price_for_penny_treatment: float = (
        5.0  # Stocks under $5 get special handling (tight trailing stops)
    )
    penny_stock_trailing_stop_percent: float = (
        1.0  # Exit penny stocks when profit drops 1.0% from peak (take profit quickly)
    )
    penny_stock_trailing_stop_activation_profit: float = (
        0.5  # Activate trailing stop after +0.5% profit for penny stocks
    )

    @classmethod
    def indicator_name(cls) -> str:
        return "Deep Analyzer"

    @classmethod
    async def _get_dynamic_entry_threshold(cls) -> float:
        """Adjust entry threshold based on market conditions"""
        # Get market-wide data (simplified - could use VIX or other indicators)
        base_threshold = 0.70
        
        # During first/last hour, require stronger signals (more noise)
        est_tz = pytz.timezone("America/New_York")
        current_hour = datetime.now(est_tz).hour
        if current_hour == 9 or current_hour >= 15:
            base_threshold += 0.05
        
        # Could add VIX-based adjustment here if VIX data is available
        # market_tide = await cls._get_market_volatility_index()
        # if market_tide.get("vix_level", 20) > 25:
        #     base_threshold += 0.05
        # elif market_tide.get("vix_level", 20) < 15:
        #     base_threshold -= 0.03
        
        return min(0.85, max(0.60, base_threshold))

    @classmethod
    async def _check_portfolio_correlation(
        cls,
        new_ticker: str,
        action: str,
        active_trades: List[Dict]
    ) -> Tuple[bool, str]:
        """Prevent over-concentration in correlated assets"""
        if not active_trades:
            return True, "First position"
        
        # Simplified correlation check - count same-direction trades
        # In a full implementation, you'd check sectors, industries, etc.
        same_direction_count = sum(
            1 for trade in active_trades
            if trade.get("action") == action
        )
        
        max_same_direction = 3  # Max 3 positions in same direction
        if same_direction_count >= max_same_direction:
            return False, f"Already have {same_direction_count} {action} positions (max: {max_same_direction})"
        
        return True, f"Correlation check passed ({same_direction_count} same-direction positions)"

    @classmethod
    def _is_golden_ticker(
        cls, entry_score: float, signal_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check if ticker is a "golden" opportunity with exceptional entry score or golden flag
        Golden tickers can bypass daily trade limits
        """
        # Check golden flag from MarketDataService
        if signal_data and signal_data.get("is_golden", False):
            return True

        # Exceptional entry score
        if entry_score >= cls.exceptional_entry_score:
            return True

        return False

    @classmethod
    async def _evaluate_ticker_for_entry(
        cls, ticker: str, market_data: Dict[str, Any]
    ) -> Tuple[
        Optional[str], Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]
    ]:
        """
        Evaluate ticker for entry using MarketDataService
        Returns: (action, signal_data, reason, detailed_results) or (None, None, reason, detailed_results) if no entry
        detailed_results contains long_result and short_result for logging purposes
        """
        try:
            # Evaluate for long entry (buy_to_open)
            long_result = await MarketDataService.enter_trade(
                ticker=ticker,
                action="buy_to_open",
                market_data=market_data,
                indicator=cls.indicator_name(),
            )

            # Evaluate for short entry (sell_to_open)
            # First check if ticker is shortable before attempting short trade
            is_shortable, shortable_reason = (
                await MarketDataService.check_ticker_shortable(
                    ticker, indicator=cls.indicator_name()
                )
            )
            if not is_shortable:
                logger.debug(f"Skipping short entry for {ticker}: {shortable_reason}")
                short_result: Dict[str, Any] = {
                    "ticker": ticker,
                    "action": "sell_to_open",
                    "signal": None,
                    "enter": False,
                    "analysis": {},
                    "message": f"Cannot proceed with short: {shortable_reason}",
                }
            else:
                short_result = await MarketDataService.enter_trade(
                    ticker=ticker,
                    action="sell_to_open",
                    market_data=market_data,
                    indicator=cls.indicator_name(),
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

            detailed_results = {
                "long_result": long_result,
                "short_result": short_result,
            }

            # Choose the better signal
            if long_enter and short_enter:
                if long_score >= short_score:
                    return (
                        "buy_to_open",
                        long_result.get("signal"),
                        f"Long entry (score: {long_score:.2f})",
                        detailed_results,
                    )
                else:
                    return (
                        "sell_to_open",
                        short_result.get("signal"),
                        f"Short entry (score: {short_score:.2f})",
                        detailed_results,
                    )
            elif long_enter:
                return (
                    "buy_to_open",
                    long_result.get("signal"),
                    f"Long entry (score: {long_score:.2f})",
                    detailed_results,
                )
            elif short_enter:
                return (
                    "sell_to_open",
                    short_result.get("signal"),
                    f"Short entry (score: {short_score:.2f})",
                    detailed_results,
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

                return None, None, reason, detailed_results

        except Exception as e:
            logger.error(f"Error evaluating {ticker} for entry: {str(e)}")
            return None, None, f"Error: {str(e)}", None

    @classmethod
    async def _evaluate_ticker_for_exit(
        cls,
        ticker: str,
        enter_price: float,
        action: str,
        entry_score: Optional[float] = None,  # Store from entry
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Enhanced exit with Deep Analyzer specific logic including signal reversal detection
        Returns: (should_exit, exit_reason, exit_data)
        """
        try:
            # Get current entry score to detect degradation
            market_data = await MCPClient.get_market_data(ticker)
            if market_data:
                current_action, current_signal, _, _ = await cls._evaluate_ticker_for_entry(ticker, market_data)
                
                # Signal reversal detection
                if current_signal:
                    current_score = current_signal.get("entry_score", 0)
                    
                    # If entry score has dropped significantly, consider exiting
                    if entry_score and current_score < entry_score * 0.5:  # Score dropped by 50%+
                        return True, f"Entry score degraded: {entry_score:.2f} -> {current_score:.2f}", {"degradation": True}
                    
                    # If opposite signal now qualifies
                    opposite_action = "sell_to_open" if action == "buy_to_open" else "buy_to_open"
                    if current_action == opposite_action and current_score >= cls.min_entry_score:
                        return True, f"Reversal signal detected: {opposite_action} score {current_score:.2f}", {"reversal": True}
            
            # Fall back to MarketDataService exit logic
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

        # Check daily limit (will be bypassed for golden tickers later)
        daily_limit_reached = await cls._has_reached_daily_trade_limit()
        if daily_limit_reached:
            logger.info(
                f"Daily trade limit reached: {cls.daily_trades_count}/{cls.max_daily_trades}. "
                "Will still check for golden/exceptional opportunities."
            )

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

        # Fetch market data in parallel batches (increased concurrency for speed)
        market_data_dict = await cls._fetch_market_data_batch(
            candidates_to_fetch, max_concurrent=25
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

            # Evaluate for entry
            action, signal_data, reason, detailed_results = (
                await cls._evaluate_ticker_for_entry(ticker, market_data_response)
            )

            if action and signal_data:
                entry_score = signal_data.get("entry_score", 0.0)
                # Use dynamic threshold based on market conditions
                dynamic_threshold = await cls._get_dynamic_entry_threshold()
                if entry_score >= dynamic_threshold:
                    # Check portfolio correlation before adding to candidates
                    active_trades = await cls._get_active_trades()
                    correlation_ok, correlation_reason = await cls._check_portfolio_correlation(
                        ticker, action, active_trades
                    )
                    if not correlation_ok:
                        stats["no_entry_signal"] += 1  # Reuse this stat
                        logger.debug(f"Skipping {ticker}: {correlation_reason}")
                        inactive_ticker_logs.append(
                            {
                                "ticker": ticker,
                                "indicator": cls.indicator_name(),
                                "reason_not_to_enter_long": correlation_reason if action == "buy_to_open" else None,
                                "reason_not_to_enter_short": correlation_reason if action == "sell_to_open" else None,
                                "technical_indicators": technical_analysis,
                            }
                        )
                        continue
                    
                    stats["passed"] += 1
                    ticker_candidates.append(
                        (ticker, entry_score, action, signal_data, reason)
                    )
                    logger.info(
                        f"{ticker} passed Deep Analyzer filters: {action} "
                        f"(score: {entry_score:.2f}, threshold: {dynamic_threshold:.2f}, {reason})"
                    )
                else:
                    stats["low_entry_score"] += 1
                    logger.debug(
                        f"Skipping {ticker}: entry score {entry_score:.2f} < "
                        f"dynamic threshold {dynamic_threshold:.2f}"
                    )
                    # Log reason based on action
                    if action == "buy_to_open":
                        reason_long = f"Entry score {entry_score:.2f} < dynamic threshold {dynamic_threshold:.2f}"
                        reason_short = None
                    else:  # sell_to_open
                        reason_long = None
                        reason_short = f"Entry score {entry_score:.2f} < dynamic threshold {dynamic_threshold:.2f}"

                    inactive_ticker_logs.append(
                        {
                            "ticker": ticker,
                            "indicator": cls.indicator_name(),
                            "reason_not_to_enter_long": reason_long,
                            "reason_not_to_enter_short": reason_short,
                            "technical_indicators": technical_analysis,
                        }
                    )
            else:
                stats["no_entry_signal"] += 1
                logger.debug(f"Skipping {ticker}: {reason}")

                # Use detailed_results from evaluation to avoid double API calls
                reason_long = None
                reason_short = None

                if detailed_results:
                    long_result = detailed_results.get("long_result", {})
                    short_result = detailed_results.get("short_result", {})

                    long_enter = long_result.get("enter", False)
                    short_enter = short_result.get("enter", False)

                    if not long_enter:
                        reason_long = long_result.get("message", "No entry signal")
                    if not short_enter:
                        reason_short = short_result.get("message", "No entry signal")

                inactive_ticker_logs.append(
                    {
                        "ticker": ticker,
                        "indicator": cls.indicator_name(),
                        "reason_not_to_enter_long": reason_long,
                        "reason_not_to_enter_short": reason_short,
                        "technical_indicators": technical_analysis,
                    }
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
            f"Evaluated {len(ticker_candidates)} tickers with valid entry signals "
            f"(filtered: {stats['no_market_data']} no data, "
            f"{stats['no_entry_signal']} no entry signal, "
            f"{stats['low_entry_score']} low entry score < {cls.min_entry_score})"
        )

        # Log market condition summary
        if stats["no_entry_signal"] > 0:
            no_signal_pct = (
                (stats["no_entry_signal"] / len(candidates_to_fetch)) * 100
                if candidates_to_fetch
                else 0
            )
            if no_signal_pct > 70:
                logger.info(
                    f"Market condition: {no_signal_pct:.1f}% of tickers show no clear trend "
                    f"({stats['no_entry_signal']}/{len(candidates_to_fetch)}). "
                    f"Market appears choppy/trendless - system correctly staying on sidelines."
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

        # Log summary of candidates before entry attempts
        if len(ticker_candidates) > 0:
            logger.info(
                f"Deep Analyzer entry cycle summary: "
                f"{len(long_candidates)} long candidates, {len(short_candidates)} short candidates, "
                f"MAB selected {len(top_long)} long + {len(top_short)} short = {len(top_long) + len(top_short)} total"
            )
        else:
            logger.warning(
                f"Deep Analyzer entry cycle: No tickers passed entry evaluation. "
                f"Stats: {stats['no_market_data']} no data, "
                f"{stats['no_entry_signal']} no entry signal, "
                f"{stats['low_entry_score']} low entry score"
            )

        # Create lookup for signal data
        long_signal_lookup = {
            t: (signal, reason) for t, _, _, signal, reason in long_candidates
        }
        short_signal_lookup = {
            t: (signal, reason) for t, _, _, signal, reason in short_candidates
        }

        # Enter trades for long candidates
        long_entries_attempted = 0
        long_entries_successful = 0
        long_entries_blocked = {"daily_limit": 0, "max_capacity": 0, "quote_failed": 0}

        for rank, (ticker, entry_score, _) in enumerate(top_long, start=1):
            if not cls.running:
                break

            long_entries_attempted += 1

            # Check if daily limit reached (allow golden tickers to bypass)
            daily_limit_reached = await cls._has_reached_daily_trade_limit()
            is_golden = False

            if daily_limit_reached:
                signal_data, _ = long_signal_lookup.get(ticker, (None, ""))
                is_golden = cls._is_golden_ticker(entry_score, signal_data)
                if not is_golden:
                    logger.info(
                        f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                        f"Skipping {ticker} (not golden/exceptional, score: {entry_score:.2f})."
                    )
                    long_entries_blocked["daily_limit"] += 1
                    break
                else:
                    logger.info(
                        f"Daily trade limit reached, but {ticker} is GOLDEN "
                        f"(entry_score: {entry_score:.2f}) - allowing entry"
                    )

            active_trades = await cls._get_active_trades()
            active_count = len(active_trades)

            if active_count >= cls.max_active_trades:
                logger.info(
                    f"At max capacity ({active_count}/{cls.max_active_trades}), "
                    f"skipping {ticker} (entry score: {entry_score:.2f})"
                )
                long_entries_blocked["max_capacity"] += 1
                continue

            action = "buy_to_open"
            signal_data, reason = long_signal_lookup.get(ticker, (None, ""))

            # Get current price hint for penny stock detection
            market_data_response = market_data_dict.get(ticker)
            current_price_hint = None
            if market_data_response:
                technical_analysis = market_data_response.get("technical_analysis", {})
                current_price_hint = technical_analysis.get("close_price", 0.0)

            # Get entry price using real-time quotes for penny stocks
            enter_price, quote_source = await RealtimeQuoteUtils.get_entry_price_quote(
                ticker, action, current_price_hint, cls.max_stock_price_for_penny_treatment
            )

            if enter_price is None or enter_price <= 0:
                logger.warning(
                    f"Failed to get entry price for {ticker} from {quote_source}, skipping"
                )
                long_entries_blocked["quote_failed"] += 1
                continue

            # Log quote source for debugging
            if quote_source == "realtime_alpaca":
                logger.info(
                    f"🚀 Using real-time Alpaca quote for {ticker} entry (penny stock fast entry)"
                )

            # Use the is_golden from daily limit check, or check signal_data if not already set
            if not is_golden:
                is_golden = (
                    signal_data.get("is_golden", False) if signal_data else False
                )

            golden_prefix = "🟡 GOLDEN: " if is_golden else ""
            ranked_reason = f"{golden_prefix}{reason} (ranked #{rank} long, entry_score: {entry_score:.2f})"
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

            success = await cls._enter_trade(
                ticker=ticker,
                action=action,
                enter_price=enter_price,
                enter_reason=ranked_reason,
                technical_indicators=technical_indicators_for_enter,
                entry_score=entry_score,
            )
            if success:
                long_entries_successful += 1

        # Log long entry summary
        if long_entries_attempted > 0:
            logger.info(
                f"Deep Analyzer long entries: {long_entries_attempted} attempted, "
                f"{long_entries_successful} successful, "
                f"blocked: {long_entries_blocked}"
            )

        # Enter trades for short candidates
        short_entries_attempted = 0
        short_entries_successful = 0
        short_entries_blocked = {"daily_limit": 0, "max_capacity": 0, "quote_failed": 0}

        for rank, (ticker, entry_score, _) in enumerate(top_short, start=1):
            if not cls.running:
                break

            short_entries_attempted += 1

            # Check if daily limit reached (allow golden tickers to bypass)
            daily_limit_reached = await cls._has_reached_daily_trade_limit()
            is_golden = False

            if daily_limit_reached:
                signal_data, _ = short_signal_lookup.get(ticker, (None, ""))
                is_golden = cls._is_golden_ticker(entry_score, signal_data)
                if not is_golden:
                    logger.info(
                        f"Daily trade limit reached ({cls.daily_trades_count}/{cls.max_daily_trades}). "
                        f"Skipping {ticker} (not golden/exceptional, score: {entry_score:.2f})."
                    )
                    short_entries_blocked["daily_limit"] += 1
                    break
                else:
                    logger.info(
                        f"Daily trade limit reached, but {ticker} is GOLDEN "
                        f"(entry_score: {entry_score:.2f}) - allowing entry"
                    )

            active_trades = await cls._get_active_trades()
            active_count = len(active_trades)

            if active_count >= cls.max_active_trades:
                logger.info(
                    f"At max capacity ({active_count}/{cls.max_active_trades}), "
                    f"skipping {ticker} (entry score: {entry_score:.2f})"
                )
                short_entries_blocked["max_capacity"] += 1
                continue

            action = "sell_to_open"
            signal_data, reason = short_signal_lookup.get(ticker, (None, ""))

            # Get current price hint for penny stock detection
            market_data_response = market_data_dict.get(ticker)
            current_price_hint = None
            if market_data_response:
                technical_analysis = market_data_response.get("technical_analysis", {})
                current_price_hint = technical_analysis.get("close_price", 0.0)

            # Get entry price using real-time quotes for penny stocks
            enter_price, quote_source = await RealtimeQuoteUtils.get_entry_price_quote(
                ticker, action, current_price_hint, cls.max_stock_price_for_penny_treatment
            )

            if enter_price is None or enter_price <= 0:
                logger.warning(
                    f"Failed to get entry price for {ticker} from {quote_source}, skipping"
                )
                short_entries_blocked["quote_failed"] += 1
                continue

            # Log quote source for debugging
            if quote_source == "realtime_alpaca":
                logger.info(
                    f"🚀 Using real-time Alpaca quote for {ticker} short entry (penny stock fast entry)"
                )

            # Use the is_golden from daily limit check, or check signal_data if not already set
            if not is_golden:
                is_golden = (
                    signal_data.get("is_golden", False) if signal_data else False
                )

            golden_prefix = "🟡 GOLDEN: " if is_golden else ""
            ranked_reason = f"{golden_prefix}{reason} (ranked #{rank} short, entry_score: {entry_score:.2f})"
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

            success = await cls._enter_trade(
                ticker=ticker,
                action=action,
                enter_price=enter_price,
                enter_reason=ranked_reason,
                technical_indicators=technical_indicators_for_enter,
                entry_score=entry_score,
            )
            if success:
                short_entries_successful += 1

        # Log short entry summary
        if short_entries_attempted > 0:
            logger.info(
                f"Deep Analyzer short entries: {short_entries_attempted} attempted, "
                f"{short_entries_successful} successful, "
                f"blocked: {short_entries_blocked}"
            )

        # Final summary
        total_attempted = long_entries_attempted + short_entries_attempted
        total_successful = long_entries_successful + short_entries_successful
        if total_attempted > 0:
            logger.info(
                f"Deep Analyzer entry cycle complete: {total_attempted} entries attempted, "
                f"{total_successful} successful. "
                f"Long: {long_entries_successful}/{long_entries_attempted}, "
                f"Short: {short_entries_successful}/{short_entries_attempted}"
            )
        elif len(top_long) == 0 and len(top_short) == 0:
            logger.warning(
                f"Deep Analyzer entry cycle: MAB selected 0 tickers. "
                f"Had {len(long_candidates)} long and {len(short_candidates)} short candidates."
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

            # Get entry score from trade record if available
            entry_score = None
            if "entry_score" in trade:
                entry_score = trade.get("entry_score")
            elif "technical_indicators_for_enter" in trade:
                # Try to extract from technical indicators
                tech_indicators = trade.get("technical_indicators_for_enter", {})
                if isinstance(tech_indicators, dict):
                    entry_score = tech_indicators.get("entry_score")
            
            # Check penny stock trailing stop before MarketDataService evaluation
            is_penny_stock = enter_price < cls.max_stock_price_for_penny_treatment
            should_exit = False
            exit_reason = None
            exit_data = None
            
            if is_penny_stock:
                # Get current price for penny stock trailing stop check using real-time quotes
                current_price, quote_source = await RealtimeQuoteUtils.get_exit_price_quote(
                    ticker, original_action, enter_price, cls.max_stock_price_for_penny_treatment
                )
                
                if current_price and current_price > 0:
                    # Calculate current profit
                    profit_percent = cls._calculate_profit_percent(
                        enter_price, current_price, original_action
                    )
                    
                    # Get peak profit from trade record or use current as initial peak
                    peak_profit_percent = float(trade.get("peak_profit_percent", profit_percent))
                    if profit_percent > peak_profit_percent:
                        peak_profit_percent = profit_percent
                    
                    # Check if trailing stop should activate (after +0.5% profit)
                    if peak_profit_percent >= cls.penny_stock_trailing_stop_activation_profit:
                        # Get latest quote right before trailing stop trigger check using real-time quotes
                        final_price, final_quote_source = await RealtimeQuoteUtils.get_exit_price_quote(
                            ticker, original_action, enter_price, cls.max_stock_price_for_penny_treatment
                        )
                        
                        if final_price and final_price > 0:
                            current_price = final_price  # Update to latest quote
                            # Recalculate profit with latest price for trailing stop check
                            profit_percent = cls._calculate_profit_percent(
                                enter_price, current_price, original_action
                            )
                        
                        # Check if profit dropped by 1% from peak
                        drop_from_peak = peak_profit_percent - profit_percent
                        if drop_from_peak >= cls.penny_stock_trailing_stop_percent:
                            should_exit = True
                            exit_reason = (
                                f"Penny stock trailing stop triggered: profit dropped {drop_from_peak:.2f}% "
                                f"from peak of {peak_profit_percent:.2f}% (current: {profit_percent:.2f}%, "
                                f"trailing stop: {cls.penny_stock_trailing_stop_percent:.2f}%)"
                            )
                            exit_data = {"current_price": current_price}
                            logger.info(
                                f"Penny stock {ticker} (${enter_price:.2f}): {exit_reason} "
                                f"(using {final_quote_source or quote_source} quote)"
                            )
            
            # If penny stock trailing stop didn't trigger, evaluate with MarketDataService
            if not should_exit:
                should_exit, exit_reason, exit_data = await cls._evaluate_ticker_for_exit(
                    ticker=ticker,
                    enter_price=enter_price,
                    action=original_action,
                    entry_score=entry_score,
                )

            if should_exit:
                # Get current price from exit_data
                exit_price = exit_data.get("current_price", 0.0) if exit_data else 0.0

                if exit_price <= 0:
                    # Fallback: get current price using real-time quotes for penny stocks
                    exit_price, exit_quote_source = await RealtimeQuoteUtils.get_exit_price_quote(
                        ticker, original_action, enter_price, cls.max_stock_price_for_penny_treatment
                    )

                if exit_price is None or exit_price <= 0:
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

                # Get latest quote right before exit using real-time quotes for penny stocks
                latest_exit_price, latest_exit_quote_source = await RealtimeQuoteUtils.get_exit_price_quote(
                    ticker, original_action, enter_price, cls.max_stock_price_for_penny_treatment
                )

                if latest_exit_price and latest_exit_price > 0:
                    exit_price = latest_exit_price  # Update to latest quote
                    is_penny_stock = enter_price < cls.max_stock_price_for_penny_treatment
                    if latest_exit_quote_source == "realtime_alpaca" and is_penny_stock:
                        logger.info(
                            f"🚀 Using real-time Alpaca quote for {ticker} exit: ${exit_price:.4f} "
                            f"(penny stock fast exit)"
                        )
                    else:
                        logger.debug(
                            f"Using {latest_exit_quote_source} quote for {ticker} exit: ${exit_price:.4f}"
                        )
                else:
                    logger.warning(
                        f"Failed to get latest exit quote for {ticker} from {latest_exit_quote_source}, "
                        f"using previously fetched price ${exit_price:.4f}"
                    )

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
