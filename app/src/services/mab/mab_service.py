"""
Multi-Armed Bandit Service for ticker selection using Thompson Sampling.

Implements MAB algorithm to intelligently select which tickers to trade based on
historical success rates. Uses Thompson Sampling to balance exploration and exploitation.
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from loguru import logger

from app.src.common.logging_utils import log_mab_selection, log_error_with_context
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.models.trade_models import MABStats


class MABService:
    """
    Multi-Armed Bandit service for intelligent ticker selection.

    Uses Thompson Sampling to rank tickers based on historical success rates.
    Maintains separate statistics for each indicator#ticker combination.
    Supports ticker exclusion for losing trades.
    """

    # Table name for MAB statistics
    MAB_STATS_TABLE = "MABForDayTradingService"

    # Singleton instance
    _instance: Optional["MABService"] = None

    def __init__(self):
        """Initialize MAB service with DynamoDB client."""
        self.dynamodb_client = DynamoDBClient()
        logger.info("MAB service initialized")

    @classmethod
    def configure(cls):
        """Configure and initialize the singleton MAB service instance."""
        if cls._instance is None:
            cls._instance = cls()
            logger.info("MAB service configured")

    @classmethod
    def _get_instance(cls) -> "MABService":
        """Get the singleton instance, creating it if necessary."""
        if cls._instance is None:
            cls.configure()
        return cls._instance

    async def get_stats(self, indicator: str, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get MAB statistics for a specific indicator#ticker combination.

        Args:
            indicator: Trading indicator name
            ticker: Stock ticker symbol

        Returns:
            Dictionary with statistics or None if not found
        """
        stats = await self.dynamodb_client.get_item(
            table_name=self.MAB_STATS_TABLE,
            key={"ticker": ticker, "indicator": indicator},
        )

        if stats:
            logger.debug(
                f"Retrieved MAB stats for {indicator}#{ticker}: "
                f"successes={stats.get('successes', 0)}, "
                f"failures={stats.get('failures', 0)}, "
                f"total={stats.get('total_trades', 0)}"
            )

        return stats

    async def update_stats(self, indicator: str, ticker: str, success: bool) -> bool:
        """
        Update MAB statistics after a trade completion.

        Args:
            indicator: Trading indicator name
            ticker: Stock ticker symbol
            success: True if trade was profitable, False otherwise

        Returns:
            True if update successful, False otherwise
        """
        # Get current stats or initialize new ones
        current_stats = await self.get_stats(indicator, ticker)

        if current_stats:
            # Update existing stats
            successes = current_stats.get("successes", 0)
            failures = current_stats.get("failures", 0)
            total_trades = current_stats.get("total_trades", 0)

            if success:
                successes += 1
            else:
                failures += 1
            total_trades += 1

            # Update in DynamoDB
            result = await self.dynamodb_client.update_item(
                table_name=self.MAB_STATS_TABLE,
                key={"ticker": ticker, "indicator": indicator},
                update_expression="SET successes = :s, failures = :f, total_trades = :t, last_updated = :lu",
                expression_attribute_values={
                    ":s": successes,
                    ":f": failures,
                    ":t": total_trades,
                    ":lu": datetime.now(timezone.utc).isoformat(),
                },
            )
        else:
            # Create new stats
            stats = MABStats(
                indicator_ticker=f"{indicator}#{ticker}",
                successes=1 if success else 0,
                failures=0 if success else 1,
                total_trades=1,
                last_updated=datetime.now(timezone.utc).isoformat(),
                excluded_until=None,
                ticker=ticker,
                indicator=indicator,
            )

            result = await self.dynamodb_client.put_item(
                table_name=self.MAB_STATS_TABLE, item=stats.to_dict()
            )

        if result:
            logger.info(
                f"Updated MAB stats for {indicator}#{ticker}: "
                f"success={success}, new_total={total_trades if current_stats else 1}"
            )
        else:
            logger.error(f"Failed to update MAB stats for {indicator}#{ticker}")

        return result

    async def exclude_ticker(
        self, indicator: str, ticker: str, duration_hours: int = 24
    ) -> bool:
        """
        Exclude a ticker from MAB selection for a specified duration.

        Used by Penny Stocks Indicator to exclude losing tickers for the rest of the day.

        Args:
            indicator: Trading indicator name
            ticker: Stock ticker symbol
            duration_hours: Hours to exclude ticker (default 24 for rest of day)

        Returns:
            True if exclusion successful, False otherwise
        """
        # Calculate exclusion end time
        from datetime import timedelta

        excluded_until = (
            datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        ).isoformat()

        # Get current stats or create new entry
        current_stats = await self.get_stats(indicator, ticker)

        if current_stats:
            # Update existing stats with exclusion
            result = await self.dynamodb_client.update_item(
                table_name=self.MAB_STATS_TABLE,
                key={"ticker": ticker, "indicator": indicator},
                update_expression="SET excluded_until = :eu, last_updated = :lu",
                expression_attribute_values={
                    ":eu": excluded_until,
                    ":lu": datetime.now(timezone.utc).isoformat(),
                },
            )
        else:
            # Create new stats with exclusion
            stats = MABStats(
                indicator_ticker=f"{indicator}#{ticker}",
                successes=0,
                failures=0,
                total_trades=0,
                last_updated=datetime.now(timezone.utc).isoformat(),
                excluded_until=excluded_until,
                ticker=ticker,
                indicator=indicator,
            )

            result = await self.dynamodb_client.put_item(
                table_name=self.MAB_STATS_TABLE, item=stats.to_dict()
            )

        if result:
            logger.info(
                f"Excluded {indicator}#{ticker} from MAB selection until {excluded_until}"
            )
        else:
            logger.error(f"Failed to exclude {indicator}#{ticker} from MAB selection")

        return result

    def _is_excluded(self, stats: Optional[Dict[str, Any]]) -> bool:
        """
        Check if a ticker is currently excluded from selection.

        Args:
            stats: MAB statistics dictionary

        Returns:
            True if ticker is excluded, False otherwise
        """
        if not stats or not stats.get("excluded_until"):
            return False

        excluded_until_str = stats["excluded_until"]
        excluded_until = datetime.fromisoformat(
            excluded_until_str.replace("Z", "+00:00")
        )
        now = datetime.now(timezone.utc)

        return now < excluded_until

    @classmethod
    def get_rejection_reason(cls, stats: Optional[Dict[str, Any]], ticker: str) -> str:
        """
        Generate a human-readable rejection reason for a ticker.

        Args:
            stats: MAB statistics for the ticker (or None for new tickers)
            ticker: Stock ticker symbol

        Returns:
            Rejection reason string with format:
            "MAB rejected: {reason} (successes: X, failures: Y, total: Z)"
        """
        if stats is None:
            # New ticker - should not be rejected, but if called, explain it's new
            return f"MAB: New ticker - explored by Thompson Sampling (successes: 0, failures: 0, total: 0)"

        successes = stats.get("successes", 0)
        failures = stats.get("failures", 0)
        total_trades = stats.get("total_trades", 0)
        excluded_until = stats.get("excluded_until")

        # Check if ticker is excluded
        if excluded_until:
            try:
                excluded_until_dt = datetime.fromisoformat(
                    excluded_until.replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                if now < excluded_until_dt:
                    return f"MAB rejected: Excluded until {excluded_until} (successes: {successes}, failures: {failures}, total: {total_trades})"
            except (ValueError, TypeError):
                pass

        # Calculate success rate
        if total_trades > 0:
            success_rate = (successes / total_trades) * 100
            return f"MAB rejected: Low historical success rate ({success_rate:.1f}%) (successes: {successes}, failures: {failures}, total: {total_trades})"
        else:
            # No trades yet but not excluded - shouldn't happen, but handle gracefully
            return f"MAB rejected: Insufficient trading history (successes: {successes}, failures: {failures}, total: {total_trades})"

    def thompson_sampling(self, stats_list: List[Dict[str, Any]]) -> List[int]:
        """
        Perform Thompson Sampling to rank tickers.

        Uses Beta distribution: Beta(alpha + successes, beta + failures)
        where alpha=1, beta=1 (uniform prior).

        Args:
            stats_list: List of statistics dictionaries with 'successes' and 'failures'

        Returns:
            List of indices sorted by Thompson Sampling scores (descending)
        """
        if not stats_list:
            return []

        scores = []

        for stats in stats_list:
            successes = stats.get("successes", 0)
            failures = stats.get("failures", 0)

            # Thompson Sampling: sample from Beta(1 + successes, 1 + failures)
            # Beta(1, 1) is uniform distribution for new tickers (exploration)
            alpha = 1 + successes
            beta = 1 + failures

            # Sample from Beta distribution
            score = np.random.beta(alpha, beta)
            scores.append(score)

        # Return indices sorted by score (descending)
        ranked_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )

        return ranked_indices

    async def select_tickers(
        self, indicator: str, candidates: List[str], direction: str, top_k: int
    ) -> List[str]:
        """
        Select top-k tickers using Thompson Sampling.

        Returns separate ranked lists for long and short directions.
        Excludes tickers that are currently excluded.

        Args:
            indicator: Trading indicator name
            candidates: List of candidate ticker symbols
            direction: "long" or "short"
            top_k: Number of tickers to select

        Returns:
            List of selected ticker symbols, ranked by Thompson Sampling
        """
        if not candidates:
            logger.debug(f"No candidates provided for MAB selection")
            return []

        # Get stats for all candidates
        stats_list = []
        valid_tickers = []

        for ticker in candidates:
            stats = await self.get_stats(indicator, ticker)

            # Skip excluded tickers
            if self._is_excluded(stats):
                logger.debug(f"Skipping excluded ticker {ticker} for {indicator}")
                continue

            # Use empty stats for new tickers (will be explored)
            if stats is None:
                stats = {"successes": 0, "failures": 0, "total_trades": 0}

            stats_list.append(stats)
            valid_tickers.append(ticker)

        if not valid_tickers:
            logger.warning(
                f"All {len(candidates)} candidates are excluded for {indicator} {direction}"
            )
            return []

        # Perform Thompson Sampling
        ranked_indices = self.thompson_sampling(stats_list)

        # Select top-k
        selected_tickers = [valid_tickers[i] for i in ranked_indices[:top_k]]

        # Prepare top selections with stats for logging
        top_selections = []
        if selected_tickers:
            for ticker in selected_tickers[:5]:  # Log top 5
                stats = await self.get_stats(indicator, ticker)
                if stats:
                    top_selections.append(
                        f"{ticker}(s:{stats.get('successes', 0)}/f:{stats.get('failures', 0)})"
                    )
                else:
                    top_selections.append(f"{ticker}(new)")

        # Use structured logging for MAB selection
        log_mab_selection(
            indicator_name=indicator,
            direction=direction,
            candidates_count=len(valid_tickers),
            selected_count=len(selected_tickers),
            top_selections=top_selections,
        )

        return selected_tickers

    @classmethod
    async def select_tickers_with_mab(
        cls,
        indicator: str,
        ticker_candidates: List[Tuple[str, float, str]],
        market_data_dict: Dict[str, Any],
        top_k: int,
    ) -> List[Tuple[str, float, str]]:
        """
        Helper method to select tickers using MAB from a list of (ticker, score, reason) tuples.

        Args:
            indicator: Trading indicator name
            ticker_candidates: List of (ticker, momentum_score, reason) tuples
            market_data_dict: Dictionary of market data (not used, kept for compatibility)
            top_k: Number of tickers to select

        Returns:
            List of selected (ticker, score, reason) tuples, ranked by Thompson Sampling
        """
        if not ticker_candidates:
            return []

        # Extract ticker symbols and determine direction from first score
        tickers = [t[0] for t in ticker_candidates]

        # Determine direction based on first ticker's score
        # Positive scores = long, negative scores = short
        first_score = ticker_candidates[0][1] if ticker_candidates else 0
        direction = "long" if first_score > 0 else "short"

        # Get MAB instance and select tickers
        instance = cls._get_instance()
        selected_ticker_symbols = await instance.select_tickers(
            indicator=indicator, candidates=tickers, direction=direction, top_k=top_k
        )

        # Return the original tuples for selected tickers, preserving order from MAB
        ticker_to_tuple = {t[0]: t for t in ticker_candidates}
        selected_tuples = [
            ticker_to_tuple[ticker]
            for ticker in selected_ticker_symbols
            if ticker in ticker_to_tuple
        ]

        return selected_tuples

    @classmethod
    async def get_rejected_tickers_with_reasons(
        cls,
        indicator: str,
        ticker_candidates: List[Tuple[str, float, str]],
        selected_tickers: List[str],
    ) -> Dict[str, Dict[str, str]]:
        """
        Get rejection reasons for tickers that passed validation but were rejected by MAB.

        Args:
            indicator: Trading indicator name
            ticker_candidates: List of (ticker, momentum_score, reason) tuples that passed validation
            selected_tickers: List of ticker symbols selected by MAB

        Returns:
            Dictionary mapping ticker -> {
                'reason_long': rejection reason for long (empty if selected or not applicable),
                'reason_short': rejection reason for short (empty if selected or not applicable),
                'momentum_score': momentum score
            }
        """
        instance = cls._get_instance()
        rejected_info = {}

        # Create set of selected tickers for fast lookup
        selected_set = set(selected_tickers)

        # Process each candidate
        for ticker, momentum_score, _ in ticker_candidates:
            # Skip if selected
            if ticker in selected_set:
                continue

            # Get MAB stats for this ticker
            stats = await instance.get_stats(indicator, ticker)

            # Determine if this is a long or short candidate
            is_long = momentum_score > 0
            is_short = momentum_score < 0

            # Generate rejection reasons
            if stats is None:
                # New ticker - explored by Thompson Sampling
                # Log as MAB rejection with "explored" reason
                rejection_reason = f"MAB: New ticker - explored by Thompson Sampling (successes: 0, failures: 0, total: 0)"
            else:
                # Existing ticker with stats
                rejection_reason = cls.get_rejection_reason(stats, ticker)

            rejected_info[ticker] = {
                "reason_long": rejection_reason if is_long else "",
                "reason_short": rejection_reason if is_short else "",
                "momentum_score": momentum_score,
            }

        return rejected_info

    @classmethod
    async def record_trade_outcome(
        cls,
        indicator: str,
        ticker: str,
        enter_price: float,
        exit_price: float,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Record the outcome of a trade and update MAB statistics.

        Args:
            indicator: Trading indicator name
            ticker: Stock ticker symbol
            enter_price: Entry price
            exit_price: Exit price
            action: Trade action ("buy_to_open" or "sell_to_open")
            context: Additional context (profit_percent, etc.)

        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()

        # Determine if trade was successful (profitable)
        if action == "buy_to_open":
            # Long trade: profitable if exit > enter
            success = exit_price > enter_price
        elif action == "sell_to_open":
            # Short trade: profitable if exit < enter
            success = exit_price < enter_price
        else:
            logger.warning(f"Unknown action {action} for {ticker}, treating as failure")
            success = False

        # Update MAB statistics
        result = await instance.update_stats(indicator, ticker, success)

        if result:
            profit_percent = context.get("profit_percent", 0.0) if context else 0.0
            logger.info(
                f"Recorded MAB outcome for {indicator}#{ticker}: "
                f"success={success}, profit={profit_percent:.2f}%"
            )

        return result

    @classmethod
    async def reset_daily_stats(cls, indicator: str) -> bool:
        """
        Reset daily MAB statistics for an indicator.

        This clears exclusions and resets temporary state for a new trading day.

        Args:
            indicator: Trading indicator name

        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()

        # Scan for all tickers with this indicator that have exclusions
        all_stats = await instance.dynamodb_client.scan(
            table_name=cls.MAB_STATS_TABLE,
            filter_expression="#ind = :indicator AND attribute_exists(excluded_until)",
            expression_attribute_names={"#ind": "indicator"},
            expression_attribute_values={":indicator": indicator},
        )

        # Clear exclusions for all tickers
        cleared_count = 0
        for stats in all_stats:
            if stats.get("excluded_until"):
                ticker = stats.get("ticker")
                await instance.dynamodb_client.update_item(
                    table_name=cls.MAB_STATS_TABLE,
                    key={"ticker": ticker, "indicator": indicator},
                    update_expression="REMOVE excluded_until SET last_updated = :lu",
                    expression_attribute_values={
                        ":lu": datetime.now(timezone.utc).isoformat()
                    },
                )
                cleared_count += 1

        logger.info(
            f"Reset daily MAB stats for {indicator}: cleared {cleared_count} exclusions"
        )

        return True
