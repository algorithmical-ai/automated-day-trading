"""
Momentum entry cycle for trade validation.

This module provides entry cycle orchestration for momentum trading
with symmetric validation and comprehensive technical indicators.
"""

import asyncio
from typing import List, Dict, Any, Tuple
from loguru import logger

from app.src.services.trading.technical_indicator_calculator import TechnicalIndicatorCalculator
from app.src.services.trading.momentum_validator import MomentumValidator
from app.src.services.trading.momentum_evaluation_record_builder import MomentumEvaluationRecordBuilder
from app.src.services.trading.inactive_ticker_repository import InactiveTickerRepository


class MomentumEntryCycle:
    """Entry cycle orchestration for momentum trading validation."""
    
    def __init__(
        self,
        min_price: float = 0.10,
        min_volume: int = 500,
        min_volume_ratio: float = 1.5,
        max_atr_percent: float = 5.0,
        indicator_name: str = "Momentum Trading"
    ):
        """
        Initialize momentum entry cycle.
        
        Args:
            min_price: Minimum price threshold
            min_volume: Minimum volume threshold
            min_volume_ratio: Minimum volume/SMA ratio
            max_atr_percent: Maximum ATR percentage
            indicator_name: Name of the indicator
        """
        self.validator = MomentumValidator(
            min_price=min_price,
            min_volume=min_volume,
            min_volume_ratio=min_volume_ratio,
            max_atr_percent=max_atr_percent
        )
        self.record_builder = MomentumEvaluationRecordBuilder(
            indicator_name=indicator_name
        )
        self.repository = InactiveTickerRepository()
        
        # Statistics tracking
        self.stats = {
            'total_evaluated': 0,
            'passed': 0,
            'rejected_security_type': 0,
            'rejected_price': 0,
            'rejected_volume': 0,
            'rejected_volume_ratio': 0,
            'rejected_volatility': 0
        }
    
    async def evaluate_ticker(
        self,
        ticker: str,
        bars: List[Dict[str, Any]]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Evaluate a single ticker for entry.
        
        Args:
            ticker: Stock ticker symbol
            bars: Historical price bars with OHLCV data
            
        Returns:
            Tuple of (is_valid, evaluation_record)
        """
        # Calculate comprehensive technical indicators
        technical_indicators = TechnicalIndicatorCalculator.calculate_indicators(bars)
        
        # Validate using symmetric rules
        validation_result = self.validator.validate(ticker, technical_indicators)
        
        # Build evaluation record
        record = self.record_builder.build_record(
            ticker=ticker,
            validation_result=validation_result,
            technical_indicators=technical_indicators
        )
        
        # Update statistics
        self.stats['total_evaluated'] += 1
        
        if validation_result.is_valid:
            self.stats['passed'] += 1
            logger.info(
                f"✅ {ticker} VALID for entry: "
                f"price=${technical_indicators.close_price:.2f}, "
                f"volume={technical_indicators.volume:,}, "
                f"ATR={technical_indicators.atr:.2f}"
            )
        else:
            # Track rejection reasons
            reason = validation_result.reason_not_to_enter_long
            if "warrant" in reason.lower() or "option" in reason.lower():
                self.stats['rejected_security_type'] += 1
            elif "price too low" in reason.lower():
                self.stats['rejected_price'] += 1
            elif "volume too low" in reason.lower():
                self.stats['rejected_volume'] += 1
            elif "volume ratio" in reason.lower():
                self.stats['rejected_volume_ratio'] += 1
            elif "volatile" in reason.lower():
                self.stats['rejected_volatility'] += 1
            
            logger.debug(
                f"❌ {ticker} REJECTED: {reason}"
            )
        
        return (validation_result.is_valid, record)
    
    async def run_cycle(
        self,
        tickers_with_data: List[Tuple[str, List[Dict[str, Any]]]]
    ) -> List[Tuple[str, bool]]:
        """
        Run a complete evaluation cycle for multiple tickers.
        
        Args:
            tickers_with_data: List of tuples (ticker, bars)
            
        Returns:
            List of tuples (ticker, is_valid)
        """
        # Reset statistics
        self.stats = {
            'total_evaluated': 0,
            'passed': 0,
            'rejected_security_type': 0,
            'rejected_price': 0,
            'rejected_volume': 0,
            'rejected_volume_ratio': 0,
            'rejected_volatility': 0
        }
        
        # Collect all evaluation records
        evaluation_records = []
        results = []
        
        logger.info(
            f"Starting momentum validation cycle for {len(tickers_with_data)} tickers"
        )
        
        # Evaluate all tickers
        for ticker, bars in tickers_with_data:
            try:
                is_valid, record = await self.evaluate_ticker(ticker, bars)
                evaluation_records.append(record)
                results.append((ticker, is_valid))
                
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
            logger.debug(
                f"Writing {len(evaluation_records)} evaluation records to DynamoDB"
            )
            
            try:
                success = await self.repository.batch_write_evaluations(evaluation_records)
                if success:
                    logger.info(
                        f"Successfully wrote {len(evaluation_records)} evaluation records"
                    )
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
        self._log_cycle_summary()
        
        return results
    
    def _log_cycle_summary(self):
        """Log comprehensive cycle statistics."""
        total = self.stats['total_evaluated']
        passed = self.stats['passed']
        
        if total == 0:
            logger.info("No tickers evaluated in this cycle")
            return
        
        pass_rate = (passed / total) * 100
        
        logger.info(
            f"📊 Momentum Validation Cycle Summary: "
            f"{total} tickers evaluated, "
            f"{passed} passed ({pass_rate:.1f}%), "
            f"{total - passed} rejected ({100 - pass_rate:.1f}%)",
            extra={
                "operation": "momentum_cycle_summary",
                "total_evaluated": total,
                "passed": passed,
                "pass_rate": pass_rate
            }
        )
        
        # Log rejection breakdown
        if total > passed:
            logger.info(
                f"📉 Rejection Breakdown: "
                f"security_type={self.stats['rejected_security_type']}, "
                f"price={self.stats['rejected_price']}, "
                f"volume={self.stats['rejected_volume']}, "
                f"volume_ratio={self.stats['rejected_volume_ratio']}, "
                f"volatility={self.stats['rejected_volatility']}",
                extra={
                    "operation": "rejection_breakdown",
                    **{k: v for k, v in self.stats.items() if k.startswith('rejected_')}
                }
            )
