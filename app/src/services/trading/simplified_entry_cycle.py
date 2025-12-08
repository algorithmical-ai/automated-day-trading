"""
Simplified entry cycle for penny stock validation.

This module provides a streamlined entry cycle implementation that uses
the simplified validation system with momentum-driven decisions.
"""

import asyncio
from typing import List, Dict, Any, Tuple
from loguru import logger

from app.src.models.simplified_validation import Quote
from app.src.services.trading.trend_metrics_calculator import TrendMetricsCalculator
from app.src.services.trading.simplified_validator import SimplifiedValidator
from app.src.services.trading.evaluation_record_builder import EvaluationRecordBuilder
from app.src.services.trading.inactive_ticker_repository import InactiveTickerRepository
from app.src.services.trading.validation_monitor import ValidationMonitor
from app.src.config.simplified_validation_config import SimplifiedValidationConfig


class SimplifiedEntryCycle:
    """Simplified entry cycle for penny stock validation."""
    
    def __init__(self):
        """Initialize the simplified entry cycle."""
        self.config = SimplifiedValidationConfig
        self.validator = SimplifiedValidator(
            max_bid_ask_spread=self.config.get_max_bid_ask_spread()
        )
        self.record_builder = EvaluationRecordBuilder(
            indicator_name=self.config.get_indicator_name()
        )
        self.repository = InactiveTickerRepository()
        self.monitor = ValidationMonitor()
    
    async def evaluate_ticker(
        self,
        ticker: str,
        bars: List[Dict[str, Any]],
        bid: float,
        ask: float
    ) -> Tuple[bool, bool, Dict[str, Any]]:
        """
        Evaluate a single ticker for entry.
        
        Args:
            ticker: Stock ticker symbol
            bars: Historical price bars
            bid: Current bid price
            ask: Current ask price
            
        Returns:
            Tuple of (is_valid_for_long, is_valid_for_short, evaluation_record)
        """
        # Calculate trend metrics
        trend_metrics = TrendMetricsCalculator.calculate_metrics(bars)
        
        # Create quote object
        quote = Quote(ticker=ticker, bid=bid, ask=ask)
        
        # Validate
        validation_result = self.validator.validate(ticker, trend_metrics, quote)
        
        # Build evaluation record
        record = self.record_builder.build_record(
            ticker=ticker,
            validation_result=validation_result,
            trend_metrics=trend_metrics
        )
        
        # Record statistics
        self.monitor.record_evaluation(
            is_valid_long=validation_result.is_valid_for_long,
            is_valid_short=validation_result.is_valid_for_short,
            momentum_score=trend_metrics.momentum_score,
            rejection_reason_long=validation_result.reason_not_to_enter_long,
            rejection_reason_short=validation_result.reason_not_to_enter_short
        )
        
        # Log individual evaluation
        if validation_result.is_valid_for_long or validation_result.is_valid_for_short:
            directions = []
            if validation_result.is_valid_for_long:
                directions.append("LONG")
            if validation_result.is_valid_for_short:
                directions.append("SHORT")
            logger.info(
                f"✅ {ticker} valid for {'/'.join(directions)}: "
                f"momentum={trend_metrics.momentum_score:.2f}"
            )
        else:
            logger.debug(
                f"❌ {ticker} rejected: "
                f"long='{validation_result.reason_not_to_enter_long}', "
                f"short='{validation_result.reason_not_to_enter_short}'"
            )
        
        return (
            validation_result.is_valid_for_long,
            validation_result.is_valid_for_short,
            record
        )
    
    async def run_cycle(
        self,
        tickers_with_data: List[Tuple[str, List[Dict[str, Any]], float, float]]
    ) -> List[Tuple[str, bool, bool, float]]:
        """
        Run a complete evaluation cycle for multiple tickers.
        
        Args:
            tickers_with_data: List of tuples (ticker, bars, bid, ask)
            
        Returns:
            List of tuples (ticker, is_valid_long, is_valid_short, momentum_score)
        """
        # Reset monitor for new cycle
        self.monitor.reset()
        
        # Collect all evaluation records
        evaluation_records = []
        results = []
        
        logger.info(f"Starting simplified validation cycle for {len(tickers_with_data)} tickers")
        
        # Evaluate all tickers
        for ticker, bars, bid, ask in tickers_with_data:
            try:
                is_valid_long, is_valid_short, record = await self.evaluate_ticker(
                    ticker, bars, bid, ask
                )
                
                evaluation_records.append(record)
                
                # Extract momentum score from record
                momentum_score = record['technical_indicators']['momentum_score']
                
                results.append((ticker, is_valid_long, is_valid_short, momentum_score))
                
            except Exception as e:
                logger.error(
                    f"Error evaluating {ticker}: {str(e)}",
                    extra={
                        "operation": "evaluate_ticker",
                        "ticker": ticker,
                        "error": str(e)
                    }
                )
                continue
        
        # Batch write all evaluation records
        if evaluation_records:
            logger.debug(f"Writing {len(evaluation_records)} evaluation records to DynamoDB")
            
            try:
                success = await self.repository.batch_write_evaluations(evaluation_records)
                if success:
                    logger.info(f"Successfully wrote {len(evaluation_records)} evaluation records")
                else:
                    logger.warning("Some evaluation records failed to write")
            except Exception as e:
                logger.error(
                    f"Error writing evaluation records: {str(e)}",
                    extra={
                        "operation": "batch_write_evaluations",
                        "record_count": len(evaluation_records),
                        "error": str(e)
                    }
                )
        
        # Log cycle summary
        self.monitor.log_cycle_summary()
        
        return results
