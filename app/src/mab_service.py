"""
Contextual Multi-Armed Bandit Service for ticker selection
Uses Thompson Sampling for contextual bandits to balance exploration and exploitation
"""

import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime
from common.loguru_logger import logger
from db.dynamodb_client import DynamoDBClient


class MABService:
    """
    Contextual Multi-Armed Bandit service for selecting profitable tickers
    
    Uses Thompson Sampling with linear contextual features:
    - Tracks profitability per ticker per day
    - Uses context features (momentum, time, volatility, etc.)
    - Balances exploration vs exploitation
    - Resets daily at market open
    """
    
    def __init__(self, db_client: DynamoDBClient, indicator: str = "Momentum Trading"):
        self.db_client = db_client
        self.indicator = indicator
        # Thompson Sampling parameters
        self.alpha = 1.0  # Prior parameter for success
        self.beta = 1.0   # Prior parameter for failure
        # Exploration-exploitation balance
        self.exploration_rate = 0.1  # 10% exploration, 90% exploitation
        # Minimum pulls before penalizing
        self.min_pulls_for_penalty = 3
    
    def _extract_context_features(
        self,
        momentum_score: float,
        market_data: Optional[Dict[str, Any]] = None,
        time_of_day: Optional[float] = None
    ) -> np.ndarray:
        """
        Extract context features for the bandit
        Returns normalized feature vector
        """
        features = []
        
        # Momentum score (normalized to [-1, 1])
        features.append(np.tanh(momentum_score / 10.0))  # Normalize momentum
        
        # Time of day (0 = market open, 1 = market close)
        if time_of_day is None:
            now = datetime.now()
            # Assume market hours 9:30 AM - 4:00 PM (6.5 hours)
            market_open_hour = 9.5
            market_close_hour = 16.0
            current_hour = now.hour + now.minute / 60.0
            if market_open_hour <= current_hour <= market_close_hour:
                time_of_day = (current_hour - market_open_hour) / (market_close_hour - market_open_hour)
            else:
                time_of_day = 0.5  # Default to middle of day
        features.append(time_of_day)
        
        # Volatility (if available from market_data)
        if market_data:
            technical_analysis = market_data.get("technical_analysis", {})
            # Use price range as proxy for volatility
            datetime_price = technical_analysis.get("datetime_price", [])
            if datetime_price and len(datetime_price) > 1:
                prices = [float(entry[1]) for entry in datetime_price if len(entry) >= 2]
                if prices:
                    price_range = (max(prices) - min(prices)) / (sum(prices) / len(prices)) if prices else 0.0
                    features.append(np.tanh(price_range))  # Normalize volatility
                else:
                    features.append(0.0)
            else:
                features.append(0.0)
        else:
            features.append(0.0)
        
        # Bias term
        features.append(1.0)
        
        return np.array(features)
    
    def _calculate_thompson_score(
        self,
        ticker: str,
        context_features: np.ndarray,
        mab_stats: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Calculate Thompson Sampling score for a ticker given context
        Higher score = more likely to be selected
        """
        if mab_stats is None:
            # New ticker: use prior (exploration)
            # Sample from Beta(alpha, beta) which is uniform when alpha=beta=1
            prior_mean = self.alpha / (self.alpha + self.beta)
            # Add context-based adjustment for new tickers
            context_bias = np.dot(context_features[:3], [0.1, 0.05, 0.05])  # Small context influence
            return prior_mean + context_bias
        
        # Calculate success rate
        successful_trades = mab_stats.get("successful_trades", 0)
        failed_trades = mab_stats.get("failed_trades", 0)
        total_pulls = mab_stats.get("total_pulls", 0)
        
        if total_pulls == 0:
            # No history, use prior
            prior_mean = self.alpha / (self.alpha + self.beta)
            context_bias = np.dot(context_features[:3], [0.1, 0.05, 0.05])
            return prior_mean + context_bias
        
        # Thompson Sampling: sample from Beta distribution
        # Posterior: Beta(alpha + successes, beta + failures)
        alpha_posterior = self.alpha + successful_trades
        beta_posterior = self.beta + failed_trades
        
        # Sample from Beta distribution
        # Using approximation: mean + small random noise
        mean_success_rate = alpha_posterior / (alpha_posterior + beta_posterior)
        
        # Add context-based adjustment
        # Higher momentum and volatility in favorable context should boost score
        context_adjustment = np.dot(context_features[:3], [0.15, 0.1, 0.1])
        
        # Penalize tickers with many failed trades relative to successful ones
        if total_pulls >= self.min_pulls_for_penalty:
            failure_penalty = (failed_trades / total_pulls) * 0.3  # Up to 30% penalty
            mean_success_rate -= failure_penalty
        
        # Boost tickers with high success rate
        if successful_trades > 0 and total_pulls > 0:
            success_boost = (successful_trades / total_pulls) * 0.2  # Up to 20% boost
            mean_success_rate += success_boost
        
        # Add some exploration noise (Thompson Sampling naturally does this via sampling)
        exploration_noise = np.random.normal(0, 0.05) if np.random.random() < self.exploration_rate else 0
        
        final_score = mean_success_rate + context_adjustment + exploration_noise
        
        # Ensure score is in [0, 1] range
        return np.clip(final_score, 0.0, 1.0)
    
    async def select_tickers_with_mab(
        self,
        ticker_candidates: List[Tuple[str, float, str]],  # (ticker, momentum_score, reason)
        market_data_dict: Optional[Dict[str, Dict[str, Any]]] = None,
        top_k: int = 10
    ) -> List[Tuple[str, float, str]]:
        """
        Select top-k tickers using contextual MAB
        
        Args:
            ticker_candidates: List of (ticker, momentum_score, reason) tuples
            market_data_dict: Optional dict mapping ticker -> market_data
            top_k: Number of tickers to select
        
        Returns:
            List of selected (ticker, momentum_score, reason) tuples, sorted by MAB score
        """
        if not ticker_candidates:
            return []
        
        scored_tickers = []
        
        for ticker, momentum_score, reason in ticker_candidates:
            # Get MAB stats for this ticker
            mab_stats = await self.db_client.get_mab_stats(ticker, self.indicator)
            
            # Extract context features
            market_data = market_data_dict.get(ticker) if market_data_dict else None
            context_features = self._extract_context_features(
                momentum_score=momentum_score,
                market_data=market_data
            )
            
            # Calculate MAB score
            mab_score = self._calculate_thompson_score(
                ticker=ticker,
                context_features=context_features,
                mab_stats=mab_stats
            )
            
            scored_tickers.append((ticker, momentum_score, reason, mab_score))
        
        # Sort by MAB score (descending)
        scored_tickers.sort(key=lambda x: x[3], reverse=True)
        
        # Select top-k
        selected = scored_tickers[:top_k]
        
        logger.info(
            f"MAB selected {len(selected)} tickers from {len(ticker_candidates)} candidates. "
            f"Top scores: {[f'{t[0]}:{t[3]:.3f}' for t in selected[:5]]}"
        )
        
        # Return in original format (ticker, momentum_score, reason)
        return [(ticker, momentum, reason) for ticker, momentum, reason, _ in selected]
    
    async def record_trade_outcome(
        self,
        ticker: str,
        enter_price: float,
        exit_price: float,
        action: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record the outcome of a trade (profit/loss) as a reward for MAB
        
        Args:
            ticker: Ticker symbol
            enter_price: Entry price
            exit_price: Exit price
            action: Original action (buy_to_open or sell_to_open)
            context: Optional context features
        
        Returns:
            True if successfully recorded
        """
        # Calculate profit percentage
        if action == "buy_to_open":
            # Long trade: profit if exit > enter
            profit_percent = ((exit_price - enter_price) / enter_price) * 100
        elif action == "sell_to_open":
            # Short trade: profit if exit < enter
            profit_percent = ((enter_price - exit_price) / enter_price) * 100
        else:
            logger.warning(f"Unknown action {action} for ticker {ticker}")
            return False
        
        # Convert profit percentage to reward
        # Normalize to [-1, 1] range for MAB
        # Positive profit = positive reward, negative profit = negative reward
        reward = np.tanh(profit_percent / 10.0)  # Scale: 10% profit = ~0.76 reward
        
        # Add context if not provided
        if context is None:
            context = {
                "profit_percent": profit_percent,
                "enter_price": enter_price,
                "exit_price": exit_price,
                "action": action,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Update MAB stats
        success = await self.db_client.update_mab_reward(
            ticker=ticker,
            indicator=self.indicator,
            reward=reward,
            context=context
        )
        
        if success:
            logger.info(
                f"Recorded MAB reward for {ticker}: {profit_percent:.2f}% profit "
                f"(reward: {reward:.4f})"
            )
        else:
            logger.warning(f"Failed to record MAB reward for {ticker}")
        
        return success
    
    async def should_trade_ticker(
        self,
        ticker: str,
        momentum_score: float,
        market_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, float, str]:
        """
        Determine if a ticker should be traded based on MAB
        
        Returns:
            (should_trade, mab_score, reason)
        """
        # Get MAB stats
        mab_stats = await self.db_client.get_mab_stats(ticker, self.indicator)
        
        # Extract context
        context_features = self._extract_context_features(
            momentum_score=momentum_score,
            market_data=market_data
        )
        
        # Calculate MAB score
        mab_score = self._calculate_thompson_score(
            ticker=ticker,
            context_features=context_features,
            mab_stats=mab_stats
        )
        
        # Decision threshold
        # Lower threshold = more permissive (trades more tickers)
        # Higher threshold = more selective (only trades high-scoring tickers)
        threshold = 0.3  # Trade if MAB score >= 0.3
        
        should_trade = mab_score >= threshold
        
        if mab_stats:
            total_pulls = mab_stats.get("total_pulls", 0)
            successful_trades = mab_stats.get("successful_trades", 0)
            failed_trades = mab_stats.get("failed_trades", 0)
            reason = (
                f"MAB score: {mab_score:.3f} (pulls: {total_pulls}, "
                f"success: {successful_trades}, failures: {failed_trades})"
            )
        else:
            reason = f"MAB score: {mab_score:.3f} (new ticker, exploring)"
        
        return should_trade, mab_score, reason
    
    async def reset_daily_stats(self) -> bool:
        """Reset daily MAB statistics (call at market open)"""
        return await self.db_client.reset_daily_mab_stats(self.indicator)

