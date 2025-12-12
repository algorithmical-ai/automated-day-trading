"""
Bandit Decision Service for intelligent trade entry decisions.

Implements a Multi-Armed Bandit algorithm using Thompson Sampling to control
trade entry decisions based on intraday performance history.
"""
from typing import Tuple, Optional, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from loguru import logger

from app.src.db.dynamodb_client import DynamoDBClient
from app.src.models.bandit_models import IntradayStats, BanditDecision


# Valid actions for the can_proceed tool
VALID_ENTRY_ACTIONS = {"buy_to_open", "sell_to_open"}
VALID_EXIT_ACTIONS = {"sell_to_close", "buy_to_close"}
VALID_ACTIONS = VALID_ENTRY_ACTIONS | VALID_EXIT_ACTIONS

# Invalid ticker patterns
INVALID_TICKERS = {"PENDING", "N/A", "NULL", "NONE", ""}


def _get_est_now() -> str:
    """Get current timestamp in EST timezone."""
    est_tz = ZoneInfo('America/New_York')
    return datetime.now(est_tz).isoformat()


def _get_est_date() -> str:
    """Get current date in EST timezone (YYYY-MM-DD)."""
    est_tz = ZoneInfo('America/New_York')
    return datetime.now(est_tz).strftime('%Y-%m-%d')


class BanditDecisionService:
    """
    Service for making bandit-based trade decisions.
    
    Uses Thompson Sampling to balance exploration (trying new tickers)
    with exploitation (favoring historically successful tickers).
    """
    
    BANDIT_TABLE = "BanditAlgorithmTable"
    
    # Decision threshold - sample must exceed this to proceed
    DECISION_THRESHOLD = 0.5
    
    # Singleton instance
    _instance: Optional['BanditDecisionService'] = None
    
    def __init__(self):
        """Initialize the service with DynamoDB client."""
        self.dynamodb_client = DynamoDBClient()
        logger.info("BanditDecisionService initialized")
    
    @classmethod
    def configure(cls):
        """Configure and initialize the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            logger.info("BanditDecisionService configured")
    
    @classmethod
    def _get_instance(cls) -> 'BanditDecisionService':
        """Get the singleton instance, creating it if necessary."""
        if cls._instance is None:
            cls.configure()
        return cls._instance
    
    @staticmethod
    def thompson_sample(alpha: int, beta: int) -> float:
        """
        Sample from Beta distribution for Thompson Sampling.
        
        This is a pure function that can be tested independently.
        
        Args:
            alpha: Alpha parameter (1 + successes)
            beta: Beta parameter (1 + failures)
            
        Returns:
            Sample from Beta(alpha, beta) distribution
        """
        return float(np.random.beta(alpha, beta))
    
    @classmethod
    def calculate_decision(
        cls,
        successes: int,
        failures: int,
        confidence_score: float,
        action: str
    ) -> Tuple[bool, str]:
        """
        Pure function for decision calculation.
        
        Args:
            successes: Number of successful trades today
            failures: Number of failed trades today
            confidence_score: Signal confidence (0 to 1)
            action: Trade action
            
        Returns:
            Tuple of (decision: bool, reason: str)
        """
        action_lower = action.lower()
        
        # Exit actions always proceed
        if action_lower in VALID_EXIT_ACTIONS:
            return True, "Exit actions always allowed to proceed"
        
        # Thompson Sampling: Beta(1 + successes, 1 + failures)
        alpha = 1 + successes
        beta_param = 1 + failures
        
        # Sample from Beta distribution
        sample = cls.thompson_sample(alpha, beta_param)
        
        # Adjust threshold based on confidence score
        # Higher confidence = lower threshold (more likely to proceed)
        adjusted_threshold = cls.DECISION_THRESHOLD * (1 - confidence_score * 0.3)
        
        decision = sample > adjusted_threshold
        
        # Build reason string
        success_rate = successes / (successes + failures) if (successes + failures) > 0 else 0.5
        
        if decision:
            reason = (
                f"Thompson Sampling approved: sample={sample:.3f} > threshold={adjusted_threshold:.3f} "
                f"(successes={successes}, failures={failures}, rate={success_rate:.1%}, confidence={confidence_score:.2f})"
            )
        else:
            reason = (
                f"Thompson Sampling rejected: sample={sample:.3f} <= threshold={adjusted_threshold:.3f} "
                f"(successes={successes}, failures={failures}, rate={success_rate:.1%}, confidence={confidence_score:.2f})"
            )
        
        return decision, reason
    
    @classmethod
    def validate_inputs(
        cls,
        ticker: str,
        indicator: str,
        current_price: float,
        action: str,
        confidence_score: float
    ) -> None:
        """
        Validate all input parameters.
        
        Raises:
            ValueError: If any parameter is invalid
        """
        # Validate ticker
        ticker_upper = ticker.upper().strip() if ticker else ""
        if not ticker_upper or ticker_upper in INVALID_TICKERS or len(ticker_upper) < 1:
            raise ValueError(
                f"Invalid ticker '{ticker}'. Please provide a valid stock ticker symbol (e.g., AAPL, MSFT, TSLA)"
            )
        
        # Validate indicator
        if not indicator or not indicator.strip():
            raise ValueError("Invalid indicator. Indicator cannot be empty.")
        
        # Validate action
        action_lower = action.lower().strip() if action else ""
        if action_lower not in VALID_ACTIONS:
            raise ValueError(
                f"Invalid action '{action}'. Must be one of: {', '.join(sorted(VALID_ACTIONS))}"
            )
        
        # Validate confidence_score
        if not isinstance(confidence_score, (int, float)) or confidence_score < 0 or confidence_score > 1:
            raise ValueError(
                f"Invalid confidence_score '{confidence_score}'. Must be a number between 0 and 1."
            )
        
        # Validate current_price
        if not isinstance(current_price, (int, float)) or current_price <= 0:
            raise ValueError(
                f"Invalid current_price '{current_price}'. Must be a positive number."
            )
    
    async def get_intraday_stats(
        self,
        ticker: str,
        indicator: str
    ) -> IntradayStats:
        """
        Get current day's success/failure counts for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            
        Returns:
            IntradayStats for the current day, or neutral stats if not found
        """
        today = _get_est_date()
        
        try:
            item = await self.dynamodb_client.get_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator}
            )
            
            if item and item.get('date') == today:
                return IntradayStats.from_dict(item)
            
            # No data for today - return neutral stats
            logger.debug(f"No intraday stats for {ticker}/{indicator} on {today}, using neutral prior")
            return IntradayStats.create_neutral(ticker.upper(), indicator)
            
        except Exception as e:
            logger.error(f"Failed to get intraday stats for {ticker}/{indicator}: {e}")
            # Fail-open: return neutral stats
            return IntradayStats.create_neutral(ticker.upper(), indicator)
    
    async def get_entry_price(
        self,
        ticker: str,
        indicator: str,
        entry_action: str
    ) -> Optional[float]:
        """
        Get the most recent entry price for a ticker/indicator on the current day.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            entry_action: The entry action to look for (buy_to_open or sell_to_open)
            
        Returns:
            Entry price if found, None otherwise
        """
        today = _get_est_date()
        
        try:
            item = await self.dynamodb_client.get_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator}
            )
            
            if item and item.get('date') == today:
                # Check if the stored entry_action matches what we're looking for
                stored_entry_action = item.get('entry_action', '').lower()
                if stored_entry_action == entry_action.lower():
                    entry_price = item.get('entry_price')
                    if entry_price is not None:
                        return float(entry_price)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get entry price for {ticker}/{indicator}: {e}")
            return None
    
    async def record_entry_price(
        self,
        ticker: str,
        indicator: str,
        entry_price: float,
        entry_action: str
    ) -> bool:
        """
        Record the entry price for a trade.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            entry_price: The entry price
            entry_action: The entry action (buy_to_open or sell_to_open)
            
        Returns:
            True if successful, False otherwise
        """
        now = _get_est_now()
        today = _get_est_date()
        
        try:
            result = await self.dynamodb_client.update_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator},
                update_expression="SET entry_price = :ep, entry_action = :ea, last_updated = :lu, #d = :date",
                expression_attribute_values={
                    ":ep": entry_price,
                    ":ea": entry_action,
                    ":lu": now,
                    ":date": today
                },
                expression_attribute_names={"#d": "date"}
            )
            
            if result:
                logger.debug(f"Recorded entry price {entry_price} for {ticker}/{indicator} ({entry_action})")
            
            return result
            
        except Exception as e:
            logger.error(f"Error recording entry price for {ticker}/{indicator}: {e}")
            return False
    
    async def process_exit_and_update_stats(
        self,
        ticker: str,
        indicator: str,
        exit_price: float,
        exit_action: str
    ) -> Tuple[bool, str]:
        """
        Process an exit action and update the bandit stats based on profitability.
        
        For sell_to_close: compare with buy_to_open entry price
        For buy_to_close: compare with sell_to_open entry price
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            exit_price: The exit/current price
            exit_action: The exit action (sell_to_close or buy_to_close)
            
        Returns:
            Tuple of (is_profitable: bool, reason: str)
        """
        ticker_upper = ticker.upper()
        
        # Determine the corresponding entry action
        if exit_action.lower() == "sell_to_close":
            entry_action = "buy_to_open"
        else:  # buy_to_close
            entry_action = "sell_to_open"
        
        # Get the entry price
        entry_price = await self.get_entry_price(ticker_upper, indicator, entry_action)
        
        if entry_price is None:
            logger.warning(
                f"No entry price found for {ticker_upper}/{indicator} ({entry_action}), "
                f"cannot determine profitability"
            )
            return True, f"No entry price found for {entry_action}, allowing exit"
        
        # Calculate profitability
        if exit_action.lower() == "sell_to_close":
            # Long trade: profitable if exit > entry
            is_profitable = exit_price > entry_price
            profit_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # buy_to_close
            # Short trade: profitable if exit < entry
            is_profitable = exit_price < entry_price
            profit_pct = ((entry_price - exit_price) / entry_price) * 100
        
        # Update the bandit stats
        await self.update_outcome(ticker_upper, indicator, is_profitable)
        
        # If not profitable, mark the ticker as blocked for further entry trades today
        if not is_profitable:
            await self.block_ticker_for_today(ticker_upper, indicator, entry_action)
        
        reason = (
            f"Exit processed: entry={entry_price:.2f}, exit={exit_price:.2f}, "
            f"profit={profit_pct:.2f}%, profitable={is_profitable}"
        )
        
        logger.info(
            f"Processed exit for {ticker_upper}/{indicator}: {reason}"
        )
        
        return is_profitable, reason
    
    async def block_ticker_for_today(
        self,
        ticker: str,
        indicator: str,
        blocked_action: str
    ) -> bool:
        """
        Block a ticker from further entry trades of a specific type for today.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            blocked_action: The action to block (buy_to_open or sell_to_open)
            
        Returns:
            True if successful, False otherwise
        """
        now = _get_est_now()
        today = _get_est_date()
        
        try:
            # Get current blocked actions
            item = await self.dynamodb_client.get_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator}
            )
            
            blocked_actions = []
            if item and item.get('date') == today:
                blocked_actions = item.get('blocked_actions', [])
                if isinstance(blocked_actions, str):
                    blocked_actions = [blocked_actions]
            
            # Add the new blocked action if not already blocked
            if blocked_action.lower() not in [a.lower() for a in blocked_actions]:
                blocked_actions.append(blocked_action.lower())
            
            # Update in DynamoDB
            result = await self.dynamodb_client.update_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator},
                update_expression="SET blocked_actions = :ba, last_updated = :lu, #d = :date",
                expression_attribute_values={
                    ":ba": blocked_actions,
                    ":lu": now,
                    ":date": today
                },
                expression_attribute_names={"#d": "date"}
            )
            
            if result:
                logger.info(
                    f"Blocked {blocked_action} for {ticker}/{indicator} for the rest of today"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error blocking ticker {ticker}/{indicator}: {e}")
            return False
    
    async def is_action_blocked(
        self,
        ticker: str,
        indicator: str,
        action: str
    ) -> Tuple[bool, str]:
        """
        Check if an action is blocked for a ticker today.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            action: The action to check
            
        Returns:
            Tuple of (is_blocked: bool, reason: str)
        """
        today = _get_est_date()
        
        try:
            item = await self.dynamodb_client.get_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator}
            )
            
            if item and item.get('date') == today:
                blocked_actions = item.get('blocked_actions', [])
                if isinstance(blocked_actions, str):
                    blocked_actions = [blocked_actions]
                
                if action.lower() in [a.lower() for a in blocked_actions]:
                    return True, f"Action {action} is blocked for {ticker} today due to previous unprofitable trade"
            
            return False, ""
            
        except Exception as e:
            logger.error(f"Error checking if action is blocked for {ticker}/{indicator}: {e}")
            # Fail-open: don't block
            return False, ""
    
    async def record_decision(
        self,
        ticker: str,
        indicator: str,
        action: str,
        current_price: float,
        confidence_score: float,
        decision: bool,
        reason: str,
        intraday_stats: IntradayStats
    ) -> bool:
        """
        Record the decision in DynamoDB using update_item to preserve blocked_actions.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            action: Trade action
            current_price: Current price
            confidence_score: Signal confidence
            decision: The decision made
            reason: Reason for decision
            intraday_stats: Current intraday stats
            
        Returns:
            True if successful, False otherwise
        """
        now = _get_est_now()
        today = _get_est_date()
        
        try:
            # Use update_item instead of put_item to preserve blocked_actions
            result = await self.dynamodb_client.update_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator},
                update_expression=(
                    "SET #d = :date, successes = :s, failures = :f, "
                    "total_decisions = :td, last_decision = :ld, "
                    "last_decision_timestamp = :ldt, last_confidence_score = :lcs, "
                    "last_price = :lp, last_action = :la, last_reason = :lr, "
                    "last_updated = :lu"
                ),
                expression_attribute_values={
                    ":date": today,
                    ":s": intraday_stats.successes,
                    ":f": intraday_stats.failures,
                    ":td": intraday_stats.total_decisions + 1,
                    ":ld": decision,
                    ":ldt": now,
                    ":lcs": confidence_score,
                    ":lp": current_price,
                    ":la": action,
                    ":lr": reason,
                    ":lu": now
                },
                expression_attribute_names={"#d": "date"}
            )
            
            if result:
                logger.debug(f"Recorded decision for {ticker}/{indicator}: {decision}")
            else:
                logger.warning(f"Failed to record decision for {ticker}/{indicator}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error recording decision for {ticker}/{indicator}: {e}")
            # Fail-open: don't block the decision
            return False
    
    async def update_outcome(
        self,
        ticker: str,
        indicator: str,
        success: bool
    ) -> bool:
        """
        Update the bandit state after trade completion.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            success: True if trade was profitable
            
        Returns:
            True if successful, False otherwise
        """
        today = _get_est_date()
        now = _get_est_now()
        
        try:
            # Get current stats
            stats = await self.get_intraday_stats(ticker, indicator)
            
            # Update counts
            if success:
                new_successes = stats.successes + 1
                new_failures = stats.failures
            else:
                new_successes = stats.successes
                new_failures = stats.failures + 1
            
            # Update in DynamoDB
            result = await self.dynamodb_client.update_item(
                table_name=self.BANDIT_TABLE,
                key={"ticker": ticker.upper(), "indicator": indicator},
                update_expression="SET successes = :s, failures = :f, last_updated = :lu, #d = :date",
                expression_attribute_values={
                    ":s": new_successes,
                    ":f": new_failures,
                    ":lu": now,
                    ":date": today
                },
                expression_attribute_names={"#d": "date"}
            )
            
            if result:
                logger.info(
                    f"Updated outcome for {ticker}/{indicator}: success={success}, "
                    f"new_stats=(s:{new_successes}, f:{new_failures})"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error updating outcome for {ticker}/{indicator}: {e}")
            return False
    
    @classmethod
    async def can_proceed(
        cls,
        ticker: str,
        indicator: str,
        current_price: float,
        action: str,
        confidence_score: float
    ) -> BanditDecision:
        """
        Main entry point: determine if a trade should proceed.
        
        For entry actions (buy_to_open, sell_to_open):
        - Check if the action is blocked due to previous unprofitable trade
        - Use Thompson Sampling to decide based on intraday performance
        - Record the entry price for later comparison
        
        For exit actions (sell_to_close, buy_to_close):
        - Always allow the exit
        - Compare with entry price to determine profitability
        - Update bandit stats and block future entries if unprofitable
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            current_price: Current price
            action: Trade action
            confidence_score: Signal confidence (0 to 1)
            
        Returns:
            BanditDecision with the result
            
        Raises:
            ValueError: If inputs are invalid
        """
        # Validate inputs
        cls.validate_inputs(ticker, indicator, current_price, action, confidence_score)
        
        instance = cls._get_instance()
        ticker_upper = ticker.upper().strip()
        action_lower = action.lower().strip()
        
        # Get intraday stats
        stats = await instance.get_intraday_stats(ticker_upper, indicator)
        
        # Handle exit actions - process profitability and update stats
        if action_lower in VALID_EXIT_ACTIONS:
            is_profitable, exit_reason = await instance.process_exit_and_update_stats(
                ticker=ticker_upper,
                indicator=indicator,
                exit_price=current_price,
                exit_action=action_lower
            )
            
            # Refresh stats after update
            stats = await instance.get_intraday_stats(ticker_upper, indicator)
            
            # Exit actions always proceed
            decision = True
            reason = f"Exit allowed. {exit_reason}"
        else:
            # Entry actions - check if blocked first
            is_blocked, block_reason = await instance.is_action_blocked(
                ticker_upper, indicator, action_lower
            )
            
            if is_blocked:
                decision = False
                reason = block_reason
            elif stats.total_decisions == 0:
                # First entry of the day for this ticker+indicator - always allow
                decision = True
                reason = f"First {action_lower} of the day for {ticker_upper}/{indicator} - automatically approved"
                
                # Record the entry price for later comparison
                await instance.record_entry_price(
                    ticker=ticker_upper,
                    indicator=indicator,
                    entry_price=current_price,
                    entry_action=action_lower
                )
            else:
                # Use Thompson Sampling for subsequent entry decisions
                decision, reason = cls.calculate_decision(
                    successes=stats.successes,
                    failures=stats.failures,
                    confidence_score=confidence_score,
                    action=action_lower
                )
                
                # If approved, record the entry price for later comparison
                if decision:
                    await instance.record_entry_price(
                        ticker=ticker_upper,
                        indicator=indicator,
                        entry_price=current_price,
                        entry_action=action_lower
                    )
        
        # Create result
        result = BanditDecision(
            decision=decision,
            ticker=ticker_upper,
            indicator=indicator,
            action=action_lower,
            reason=reason,
            intraday_stats=stats,
            confidence_score=confidence_score,
            current_price=current_price,
            timestamp=_get_est_now()
        )
        
        # Record decision (fire and forget - don't block on failure)
        await instance.record_decision(
            ticker=ticker_upper,
            indicator=indicator,
            action=action_lower,
            current_price=current_price,
            confidence_score=confidence_score,
            decision=decision,
            reason=reason,
            intraday_stats=stats
        )
        
        logger.info(
            f"can_proceed({ticker_upper}, {indicator}, {action_lower}): "
            f"decision={decision}, confidence={confidence_score:.2f}"
        )
        
        return result
