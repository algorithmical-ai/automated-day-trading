"""
Threshold Adjustment Service
Uses LLM to analyze inactive tickers and dynamically adjust trading thresholds
"""

import asyncio
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import date
from app.src.common.loguru_logger import logger
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.bedrock.bedrock_client import BedrockClient
from app.src.services.trading.momentum_indicator import MomentumIndicator
from app.src.services.trading.deep_analyzer_indicator import DeepAnalyzerIndicator


class ThresholdAdjustmentService:
    """Service to analyze inactive tickers and adjust thresholds using LLM"""

    running: bool = False
    _task: Optional[asyncio.Task] = None
    analysis_interval_seconds: int = 300  # Run every 5 minutes

    @classmethod
    async def start(cls):
        """Start the threshold adjustment service"""
        if cls.running:
            logger.warning("Threshold adjustment service already running")
            return

        cls.running = True
        cls._task = asyncio.create_task(cls._run_service())
        logger.info("Threshold adjustment service started")

        # Return the task so it can be awaited if needed
        return cls._task

    @classmethod
    def stop(cls):
        """Stop the threshold adjustment service"""
        cls.running = False
        if cls._task:
            cls._task.cancel()
        logger.info("Threshold adjustment service stopped")

    @classmethod
    async def _run_service(cls):
        """Main service loop"""
        while cls.running:
            try:
                await cls._analyze_and_adjust_thresholds()
                await asyncio.sleep(cls.analysis_interval_seconds)
            except asyncio.CancelledError:
                logger.info("Threshold adjustment service cancelled")
                break
            except Exception as e:
                logger.exception(f"Error in threshold adjustment service: {str(e)}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying

    @classmethod
    async def _analyze_and_adjust_thresholds(cls):
        """Analyze inactive tickers and adjust thresholds for each indicator"""
        indicators = [
            ("Momentum Trading", MomentumIndicator),
            ("Deep Analyzer", DeepAnalyzerIndicator),
        ]

        for indicator_name, indicator_cls in indicators:
            if not cls.running:
                break

            try:
                await cls._analyze_indicator(indicator_name, indicator_cls)
            except Exception as e:
                logger.exception(f"Error analyzing {indicator_name}: {str(e)}")

    @classmethod
    async def _analyze_indicator(cls, indicator_name: str, indicator_cls: Any):
        """Analyze a specific indicator and adjust thresholds"""
        logger.info(f"Analyzing {indicator_name} for threshold adjustments...")

        # Get inactive tickers from last 5 minutes
        inactive_tickers = await DynamoDBClient.get_inactive_tickers_for_indicator(
            indicator=indicator_name, minutes_window=5
        )

        if not inactive_tickers:
            logger.debug(
                f"No inactive tickers found for {indicator_name} in last 5 minutes"
            )
            return

        logger.info(
            f"Found {len(inactive_tickers)} inactive tickers for {indicator_name}"
        )

        # Prepare data for LLM analysis
        analysis_data = cls._prepare_analysis_data(inactive_tickers, indicator_name)

        # Get current thresholds
        current_thresholds = cls._get_current_thresholds(indicator_cls)

        # Call LLM to analyze and suggest adjustments
        llm_response = await cls._call_llm_for_analysis(
            indicator_name, analysis_data, current_thresholds
        )

        if not llm_response:
            logger.warning(f"LLM returned no response for {indicator_name}")
            return

        # Parse LLM response and extract threshold changes
        threshold_changes, max_long, max_short = cls._parse_llm_response(
            llm_response, indicator_name
        )

        if threshold_changes or max_long != 5 or max_short != 5:
            # Apply threshold changes
            if threshold_changes:
                await cls._apply_threshold_changes(indicator_cls, threshold_changes)

            # Apply max trades adjustments (store as max_daily_trades for now)
            # Note: We could split this into separate long/short limits if needed
            total_max_trades = max_long + max_short
            if total_max_trades != indicator_cls.max_daily_trades:
                old_max = indicator_cls.max_daily_trades
                indicator_cls.max_daily_trades = total_max_trades
                logger.info(
                    f"Updated {indicator_cls.__name__}.max_daily_trades: "
                    f"{old_max} -> {total_max_trades} (long: {max_long}, short: {max_short})"
                )

            # Store event in DayTraderEvents table
            current_date = date.today().isoformat()
            await DynamoDBClient.store_day_trader_event(
                date=current_date,
                indicator=indicator_name,
                threshold_change=threshold_changes,
                max_long_trades=max_long,
                max_short_trades=max_short,
                llm_response=llm_response,
            )

            logger.info(
                f"Applied threshold adjustments for {indicator_name}: "
                f"thresholds={json.dumps(threshold_changes, indent=2)}, "
                f"max_long={max_long}, max_short={max_short}"
            )

    @classmethod
    def _prepare_analysis_data(
        cls, inactive_tickers: List[Dict[str, Any]], indicator_name: str
    ) -> Dict[str, Any]:
        """Prepare data for LLM analysis"""
        # Group by reason
        reasons_summary: Dict[str, int] = {}
        technical_indicators_samples = []

        for ticker_data in inactive_tickers[:50]:  # Limit to 50 for prompt size
            ticker = ticker_data.get("ticker", "UNKNOWN")
            reason_long = ticker_data.get("reason_not_to_enter_long")
            reason_short = ticker_data.get("reason_not_to_enter_short")
            tech_indicators = ticker_data.get("technical_indicators", {})

            if reason_long:
                reasons_summary[reason_long] = reasons_summary.get(reason_long, 0) + 1
            if reason_short:
                reasons_summary[reason_short] = reasons_summary.get(reason_short, 0) + 1

            if tech_indicators:
                technical_indicators_samples.append(
                    {
                        "ticker": ticker,
                        "indicators": tech_indicators,
                        "reason_long": reason_long,
                        "reason_short": reason_short,
                    }
                )

        return {
            "total_inactive": len(inactive_tickers),
            "reasons_summary": reasons_summary,
            "technical_indicators_samples": technical_indicators_samples[
                :10
            ],  # Limit samples
        }

    @classmethod
    def _get_current_thresholds(cls, indicator_cls: Any) -> Dict[str, Any]:
        """Get current threshold values from indicator class"""
        thresholds = {}

        # Momentum Indicator thresholds
        if hasattr(indicator_cls, "min_momentum_threshold"):
            thresholds["min_momentum_threshold"] = indicator_cls.min_momentum_threshold
            thresholds["max_momentum_threshold"] = getattr(
                indicator_cls, "max_momentum_threshold", None
            )
            thresholds["min_adx_threshold"] = indicator_cls.min_adx_threshold
            thresholds["rsi_oversold_for_long"] = indicator_cls.rsi_oversold_for_long
            thresholds["rsi_overbought_for_short"] = (
                indicator_cls.rsi_overbought_for_short
            )
            thresholds["min_daily_volume"] = indicator_cls.min_daily_volume
            thresholds["stop_loss_threshold"] = indicator_cls.stop_loss_threshold
            thresholds["trailing_stop_percent"] = indicator_cls.trailing_stop_percent

        # Deep Analyzer thresholds
        if hasattr(indicator_cls, "min_entry_score"):
            thresholds["min_entry_score"] = indicator_cls.min_entry_score

        # Common thresholds
        thresholds["max_active_trades"] = indicator_cls.max_active_trades
        thresholds["max_daily_trades"] = indicator_cls.max_daily_trades

        return thresholds

    @classmethod
    async def _call_llm_for_analysis(
        cls,
        indicator_name: str,
        analysis_data: Dict[str, Any],
        current_thresholds: Dict[str, Any],
    ) -> Optional[str]:
        """Call LLM to analyze and suggest threshold adjustments"""
        prompt = cls._construct_llm_prompt(
            indicator_name, analysis_data, current_thresholds
        )

        return await BedrockClient.invoke_model(prompt, max_tokens=4000)

    @classmethod
    def _construct_llm_prompt(
        cls,
        indicator_name: str,
        analysis_data: Dict[str, Any],
        current_thresholds: Dict[str, Any],
    ) -> str:
        """Construct prompt for LLM analysis"""
        reasons_summary = analysis_data.get("reasons_summary", {})
        tech_samples = analysis_data.get("technical_indicators_samples", [])

        prompt = f"""You are an expert quantitative trading analyst. Analyze the following data for the "{indicator_name}" trading indicator and suggest threshold adjustments to improve trade entry rates while maintaining profitability.

## Current Situation
- Total inactive tickers in last 5 minutes: {analysis_data.get('total_inactive', 0)}
- Current thresholds: {json.dumps(current_thresholds, indent=2)}

## Reasons for Not Entering Trades
{json.dumps(reasons_summary, indent=2)}

## Sample Technical Indicators
{json.dumps(tech_samples[:5], indent=2)}

## Your Task
1. Analyze why tickers are not entering trades
2. Suggest specific threshold adjustments (increase/decrease values)
3. Determine optimal max_long_trades and max_short_trades based on market conditions
4. Ensure adjustments maintain profitability (avoid over-trading)

## Response Format (JSON only, no markdown):
{{
  "threshold_changes": {{
    "min_momentum_threshold": <new_value_or_null>,
    "max_momentum_threshold": <new_value_or_null>,
    "min_adx_threshold": <new_value_or_null>,
    "rsi_oversold_for_long": <new_value_or_null>,
    "rsi_overbought_for_short": <new_value_or_null>,
    "min_daily_volume": <new_value_or_null>,
    "stop_loss_threshold": <new_value_or_null>,
    "trailing_stop_percent": <new_value_or_null>,
    "min_entry_score": <new_value_or_null>
  }},
  "max_long_trades": <integer>,
  "max_short_trades": <integer>,
  "reasoning": "<brief explanation of changes>"
}}

Only include threshold_changes for values you want to modify. Use null for unchanged values.
"""

        return prompt

    @classmethod
    def _parse_llm_response(
        cls, llm_response: str, indicator_name: str
    ) -> Tuple[Dict[str, Any], int, int]:
        """Parse LLM response and extract threshold changes"""
        try:
            # Try to extract JSON from response (might have markdown or extra text)
            response_text = llm_response.strip()

            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            response_json = json.loads(response_text)

            threshold_changes = response_json.get("threshold_changes", {})
            # Remove null values
            threshold_changes = {
                k: v for k, v in threshold_changes.items() if v is not None
            }

            max_long = response_json.get("max_long_trades", 5)
            max_short = response_json.get("max_short_trades", 5)

            return threshold_changes, max_long, max_short
        except Exception as e:
            logger.error(
                f"Error parsing LLM response for {indicator_name}: {str(e)}\n"
                f"Response: {llm_response[:500]}"
            )
            return {}, 5, 5

    @classmethod
    async def _apply_threshold_changes(
        cls, indicator_cls: Any, threshold_changes: Dict[str, Any]
    ):
        """Apply threshold changes to indicator class"""
        for key, value in threshold_changes.items():
            if hasattr(indicator_cls, key):
                old_value = getattr(indicator_cls, key)
                setattr(indicator_cls, key, value)
                logger.info(
                    f"Updated {indicator_cls.__name__}.{key}: "
                    f"{old_value} -> {value}"
                )
            else:
                logger.warning(f"Threshold {key} not found in {indicator_cls.__name__}")
