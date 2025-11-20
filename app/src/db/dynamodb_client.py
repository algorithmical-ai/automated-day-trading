"""
DynamoDB Client for managing active trades
"""

import boto3
import json
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
import pytz
from app.src.common.loguru_logger import logger

try:
    import numpy as np

    FLOAT_TYPES = (float, np.floating)
except Exception:  # numpy might not be available
    FLOAT_TYPES = (float,)
from app.src.config.constants import (
    DYNAMODB_TABLE_NAME,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_DEFAULT_REGION,
)

# New table for momentum-based trading
MOMENTUM_TRADING_TABLE_NAME = "ActiveTickersForAutomatedDayTrader"
# Ticker blacklist table
TICKER_BLACKLIST_TABLE_NAME = "TickerBlackList"
# MAB table for tracking ticker profitability
MAB_TABLE_NAME = "MABForDayTradingService"
# Completed trades table
COMPLETED_TRADES_TABLE_NAME = "CompletedTradesForAutomatedDayTrading"


class DynamoDBClient:
    """Client for DynamoDB operations"""

    _dynamodb = None
    _table = None
    _momentum_table = None
    _blacklist_table = None
    _mab_table = None
    _completed_trades_table = None

    @classmethod
    def _ensure_tables(cls):
        if cls._table:
            return

        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            cls._dynamodb = boto3.resource(
                "dynamodb",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_DEFAULT_REGION,
            )
        else:
            cls._dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)

        cls._table = cls._dynamodb.Table(DYNAMODB_TABLE_NAME)
        cls._momentum_table = cls._dynamodb.Table(MOMENTUM_TRADING_TABLE_NAME)
        cls._blacklist_table = cls._dynamodb.Table(TICKER_BLACKLIST_TABLE_NAME)
        cls._mab_table = cls._dynamodb.Table(MAB_TABLE_NAME)
        cls._completed_trades_table = cls._dynamodb.Table(COMPLETED_TRADES_TABLE_NAME)

    @classmethod
    def configure(cls, **kwargs):
        """
        Optional configuration hook. Currently acts as a no-op but ensures
        resources are initialized eagerly when invoked.
        """
        cls._ensure_tables()

    @classmethod
    def _is_float_type(cls, obj):
        """Check if object is a float type that needs conversion to Decimal"""
        if isinstance(obj, bool):
            return False
        if isinstance(obj, FLOAT_TYPES):
            return True
        # Check for numpy float types
        try:
            import numpy as np

            if isinstance(obj, (np.floating, np.float16, np.float32, np.float64)):
                return True
            # Check if it's a numpy number that's a float
            if hasattr(np, "number") and isinstance(obj, np.number):
                if isinstance(obj, np.floating):
                    return True
        except (ImportError, AttributeError):
            pass
        return False

    @classmethod
    def _convert_to_decimal(cls, obj):
        """Convert float-like values to Decimal for DynamoDB"""
        if isinstance(obj, bool):
            return obj
        # Check for float types (including numpy floats)
        if cls._is_float_type(obj):
            # Convert float (or numpy floating) to Decimal using string to preserve precision
            return Decimal(str(float(obj)))
        # Handle numpy integer types
        try:
            import numpy as np

            if isinstance(obj, (np.integer, np.int8, np.int16, np.int32, np.int64)):
                return int(obj)
        except (ImportError, AttributeError):
            pass
        # Also check for int types that might need conversion (numpy ints)
        if isinstance(obj, (int,)) and not isinstance(obj, bool):
            # Keep as int (DynamoDB supports integers)
            return obj
        if isinstance(obj, dict):
            return {k: cls._convert_to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls._convert_to_decimal(item) for item in obj]
        return obj

    @classmethod
    def _ensure_all_floats_converted(cls, obj):
        """Recursively ensure all float values in a structure are converted to Decimal"""
        if isinstance(obj, dict):
            converted = {}
            for key, value in obj.items():
                if cls._is_float_type(value):
                    converted[key] = Decimal(str(float(value)))
                elif isinstance(value, (dict, list)):
                    converted[key] = cls._ensure_all_floats_converted(value)
                else:
                    converted[key] = value
            return converted
        elif isinstance(obj, list):
            return [cls._ensure_all_floats_converted(item) for item in obj]
        elif cls._is_float_type(obj):
            return Decimal(str(float(obj)))
        return obj

    @classmethod
    def _convert_from_decimal(cls, obj):
        """Convert Decimal to float from DynamoDB"""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: cls._convert_from_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls._convert_from_decimal(item) for item in obj]
        return obj

    @classmethod
    async def add_trade(
        cls,
        ticker: str,
        action: str,
        indicator: str,
        enter_price: float,
        enter_reason: str,
        enter_response: Dict[str, Any],
    ) -> bool:
        """Add a trade to DynamoDB"""
        try:
            cls._ensure_tables()
            item = {
                "ticker": ticker,
                "action": action,
                "indicator": indicator,
                "enter_price": cls._convert_to_decimal(enter_price),
                "enter_reason": enter_reason,
                "enter_response": cls._convert_to_decimal(enter_response),
                "created_at": datetime.utcnow().isoformat(),
            }
            cls._table.put_item(Item=item)
            logger.info(f"Added trade to DynamoDB: {ticker} - {action}")
            return True
        except Exception as e:
            logger.error(f"Error adding trade to DynamoDB: {str(e)}")
            return False

    @classmethod
    async def get_all_active_trades(cls) -> List[Dict[str, Any]]:
        """Get all active trades from DynamoDB"""
        try:
            cls._ensure_tables()
            response = cls._table.scan()
            trades = []
            for item in response.get("Items", []):
                # Convert Decimal back to float
                converted_item = cls._convert_from_decimal(item)
                trades.append(converted_item)
            return trades
        except Exception as e:
            logger.error(f"Error getting active trades from DynamoDB: {str(e)}")
            return []

    @classmethod
    async def delete_trade(cls, ticker: str) -> bool:
        """Delete a trade from DynamoDB"""
        try:
            cls._ensure_tables()
            cls._table.delete_item(Key={"ticker": ticker})
            logger.info(f"Deleted trade from DynamoDB: {ticker}")
            return True
        except Exception as e:
            logger.error(f"Error deleting trade from DynamoDB: {str(e)}")
            return False

    # Methods for ActiveTickersForAutomatedDayTrader table

    @classmethod
    async def add_momentum_trade(
        cls,
        ticker: str,
        action: str,
        indicator: str,
        enter_price: float,
        enter_reason: str,
    ) -> bool:
        """Add a momentum-based trade to ActiveTickersForAutomatedDayTrader table"""
        try:
            cls._ensure_tables()
            item = {
                "ticker": ticker,
                "action": action,
                "indicator": indicator,
                "enter_price": cls._convert_to_decimal(enter_price),
                "enter_reason": enter_reason,
                "trailing_stop": cls._convert_to_decimal(0.5),  # Initialize to 0.5%
                "peak_profit_percent": cls._convert_to_decimal(0.0),  # Initialize to 0%
                "created_at": datetime.utcnow().isoformat(),
            }
            cls._momentum_table.put_item(Item=item)
            logger.info(f"Added momentum trade to DynamoDB: {ticker} - {action}")
            return True
        except Exception as e:
            logger.error(f"Error adding momentum trade to DynamoDB: {str(e)}")
            return False

    @classmethod
    async def get_all_momentum_trades(cls) -> List[Dict[str, Any]]:
        """Get all active momentum trades from ActiveTickersForAutomatedDayTrader table"""
        try:
            cls._ensure_tables()
            response = cls._momentum_table.scan()
            trades = []
            for item in response.get("Items", []):
                # Convert Decimal back to float
                converted_item = cls._convert_from_decimal(item)
                trades.append(converted_item)
            return trades
        except Exception as e:
            logger.error(f"Error getting momentum trades from DynamoDB: {str(e)}")
            return []

    @classmethod
    async def delete_momentum_trade(cls, ticker: str) -> bool:
        """Delete a momentum trade from ActiveTickersForAutomatedDayTrader table"""
        try:
            cls._ensure_tables()
            cls._momentum_table.delete_item(Key={"ticker": ticker})
            logger.info(f"Deleted momentum trade from DynamoDB: {ticker}")
            return True
        except Exception as e:
            logger.error(f"Error deleting momentum trade from DynamoDB: {str(e)}")
            return False

    @classmethod
    async def update_momentum_trade_skip_reason(
        cls, ticker: str, skipped_exit_reason: str
    ) -> bool:
        """Update a momentum trade with skipped exit reason and updated_at timestamp in EST"""
        try:
            cls._ensure_tables()
            # Get EST timezone
            est_tz = pytz.timezone("US/Eastern")
            # Get current time in EST
            est_time = datetime.now(est_tz)
            updated_at = est_time.isoformat()

            update_expression = "SET skipped_exit_reason = :ser, updated_at = :ua"
            expression_values = {
                ":ser": skipped_exit_reason,
                ":ua": updated_at,
            }

            cls._momentum_table.update_item(
                Key={"ticker": ticker},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
            )
            logger.debug(
                f"Updated momentum trade skip reason for {ticker}: {skipped_exit_reason}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Error updating momentum trade skip reason for {ticker}: {str(e)}"
            )
            return False

    @classmethod
    async def update_momentum_trade_trailing_stop(
        cls,
        ticker: str,
        trailing_stop: float,
        peak_profit_percent: float,
        skipped_exit_reason: Optional[str] = None,
    ) -> bool:
        """Update a momentum trade with trailing stop, peak profit, and optionally skipped exit reason"""
        try:
            cls._ensure_tables()
            # Get EST timezone
            est_tz = pytz.timezone("US/Eastern")
            # Get current time in EST
            est_time = datetime.now(est_tz)
            updated_at = est_time.isoformat()

            update_expression = (
                "SET trailing_stop = :ts, peak_profit_percent = :ppp, updated_at = :ua"
            )
            expression_values = {
                ":ts": cls._convert_to_decimal(trailing_stop),
                ":ppp": cls._convert_to_decimal(peak_profit_percent),
                ":ua": updated_at,
            }

            if skipped_exit_reason:
                update_expression += ", skipped_exit_reason = :ser"
                expression_values[":ser"] = skipped_exit_reason

            cls._momentum_table.update_item(
                Key={"ticker": ticker},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
            )
            logger.debug(
                f"Updated trailing stop for {ticker}: {trailing_stop:.2f}%, peak: {peak_profit_percent:.2f}%"
            )
            return True
        except Exception as e:
            logger.error(
                f"Error updating trailing stop for {ticker}: {str(e)}"
            )
            return False

    # Methods for TickerBlackList table

    @classmethod
    async def get_blacklisted_tickers(cls) -> List[str]:
        """Get all blacklisted tickers from TickerBlackList table"""
        try:
            cls._ensure_tables()
            response = cls._blacklist_table.scan()
            blacklisted_tickers = []
            for item in response.get("Items", []):
                ticker = item.get("ticker")
                if ticker:
                    blacklisted_tickers.append(ticker)
            logger.debug(f"Found {len(blacklisted_tickers)} blacklisted tickers")
            return blacklisted_tickers
        except Exception as e:
            logger.error(f"Error getting blacklisted tickers from DynamoDB: {str(e)}")
            return []

    @classmethod
    async def is_ticker_blacklisted(cls, ticker: str) -> bool:
        """Check if a ticker is in the blacklist"""
        try:
            cls._ensure_tables()
            response = cls._blacklist_table.get_item(Key={"ticker": ticker})
            return "Item" in response
        except Exception as e:
            logger.error(f"Error checking if ticker {ticker} is blacklisted: {str(e)}")
            return False

    # Methods for MABForDayTradingService table

    @classmethod
    async def get_mab_stats(
        cls, ticker: str, indicator: str
    ) -> Optional[Dict[str, Any]]:
        """Get MAB statistics for a ticker and indicator"""
        try:
            cls._ensure_tables()
            response = cls._mab_table.get_item(
                Key={"ticker": ticker, "indicator": indicator}
            )
            if "Item" in response:
                item = cls._convert_from_decimal(response["Item"])
                return item
            return None
        except Exception as e:
            logger.error(f"Error getting MAB stats for {ticker}/{indicator}: {str(e)}")
            return None

    @classmethod
    async def update_mab_reward(
        cls,
        ticker: str,
        indicator: str,
        reward: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update MAB statistics with a reward (profit/loss)
        reward: positive for profit, negative for loss
        """
        try:
            # Get current stats or initialize
            current_stats = await cls.get_mab_stats(ticker, indicator)

            # Convert reward to float first (in case it's a numpy type), then to Decimal for calculation
            reward_float = float(reward)

            # Calculate new statistics
            # Get current total_rewards as float (it might be Decimal from DB)
            current_total_rewards = (
                current_stats.get("total_rewards", 0.0) if current_stats else 0.0
            )
            if isinstance(current_total_rewards, Decimal):
                current_total_rewards = float(current_total_rewards)
            total_rewards = current_total_rewards + reward_float
            total_pulls = (
                current_stats.get("total_pulls", 0) if current_stats else 0
            ) + 1

            if reward_float > 0:
                successful_trades = (
                    current_stats.get("successful_trades", 0) if current_stats else 0
                ) + 1
                failed_trades = (
                    current_stats.get("failed_trades", 0) if current_stats else 0
                )
            else:
                successful_trades = (
                    current_stats.get("successful_trades", 0) if current_stats else 0
                )
                failed_trades = (
                    current_stats.get("failed_trades", 0) if current_stats else 0
                ) + 1

            if current_stats is None:
                # Create new entry with calculated values
                item = {
                    "ticker": ticker,
                    "indicator": indicator,
                    "total_rewards": cls._convert_to_decimal(total_rewards),
                    "total_pulls": total_pulls,
                    "successful_trades": successful_trades,
                    "failed_trades": failed_trades,
                    "last_updated": datetime.utcnow().isoformat(),
                    "daily_reset_date": datetime.utcnow().date().isoformat(),
                }
                if context:
                    context_converted = cls._convert_to_decimal(context)
                    context_converted = cls._ensure_all_floats_converted(
                        context_converted
                    )
                    item["last_context"] = context_converted

                item = cls._ensure_all_floats_converted(item)

                # Put the new item
                cls._ensure_tables()
                cls._mab_table.put_item(Item=item)
            else:
                # Update existing item
                update_expression = "SET total_rewards = :tr, total_pulls = :tp, successful_trades = :st, failed_trades = :ft, last_updated = :lu"
                expression_values = {
                    ":tr": cls._convert_to_decimal(total_rewards),
                    ":tp": total_pulls,
                    ":st": successful_trades,
                    ":ft": failed_trades,
                    ":lu": datetime.utcnow().isoformat(),
                }

                if context:
                    context_converted = cls._convert_to_decimal(context)
                    context_converted = cls._ensure_all_floats_converted(
                        context_converted
                    )
                    update_expression += ", last_context = :lc"
                    expression_values[":lc"] = context_converted

                expression_values = cls._ensure_all_floats_converted(expression_values)

                cls._ensure_tables()
                cls._mab_table.update_item(
                    Key={"ticker": ticker, "indicator": indicator},
                    UpdateExpression=update_expression,
                    ExpressionAttributeValues=expression_values,
                )

            logger.debug(
                f"Updated MAB stats for {ticker}/{indicator}: reward={reward:.4f}, total_rewards={total_rewards:.4f}, pulls={total_pulls}"
            )
            return True
        except Exception as e:
            logger.exception(
                f"Error updating MAB reward for {ticker}/{indicator}: {str(e)}"
            )
            return False

    @classmethod
    async def reset_daily_mab_stats(cls, indicator: str) -> bool:
        """
        Reset daily MAB statistics for all tickers with a given indicator
        This should be called at market open each day
        """
        try:
            today = datetime.utcnow().date().isoformat()

            # Scan all items with the indicator
            # Note: This is a scan operation, which can be expensive for large tables
            # In production, consider using GSI or different table design
            # Use ExpressionAttributeNames because "indicator" is a reserved keyword
            cls._ensure_tables()
            response = cls._mab_table.scan(
                FilterExpression="#ind = :ind",
                ExpressionAttributeNames={"#ind": "indicator"},
                ExpressionAttributeValues={":ind": indicator},
            )

            reset_count = 0
            for item in response.get("Items", []):
                ticker = item.get("ticker")
                daily_reset_date = item.get("daily_reset_date")

                # Only reset if not already reset today
                if daily_reset_date != today:
                    cls._mab_table.update_item(
                        Key={"ticker": ticker, "indicator": indicator},
                        UpdateExpression="SET daily_reset_date = :drd, daily_rewards = :dr, daily_pulls = :dp, last_updated = :lu",
                        ExpressionAttributeValues={
                            ":drd": today,
                            ":dr": cls._convert_to_decimal(0.0),
                            ":dp": 0,
                            ":lu": datetime.utcnow().isoformat(),
                        },
                    )
                    reset_count += 1

            logger.info(
                f"Reset daily MAB stats for {reset_count} tickers with indicator {indicator}"
            )
            return True
        except Exception as e:
            logger.error(f"Error resetting daily MAB stats: {str(e)}")
            return False

    @classmethod
    async def get_all_mab_stats_for_indicator(
        cls, indicator: str
    ) -> List[Dict[str, Any]]:
        """Get all MAB statistics for a given indicator"""
        try:
            cls._ensure_tables()
            response = cls._mab_table.scan(
                FilterExpression="indicator = :ind",
                ExpressionAttributeValues={":ind": indicator},
            )
            stats = []
            for item in response.get("Items", []):
                converted_item = cls._convert_from_decimal(item)
                stats.append(converted_item)
            return stats
        except Exception as e:
            logger.error(f"Error getting MAB stats for indicator {indicator}: {str(e)}")
            return []

    # Methods for CompletedTradesForAutomatedDayTrading table

    @classmethod
    async def add_completed_trade(
        cls,
        date: str,
        indicator: str,
        ticker: str,
        action: str,
        enter_price: float,
        enter_reason: str,
        enter_timestamp: str,
        exit_price: float,
        exit_timestamp: str,
        exit_reason: str,
        profit_or_loss: float,
        technical_indicators_for_enter: Optional[Dict[str, Any]] = None,
        technical_indicators_for_exit: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Add a completed trade to CompletedTradesForAutomatedDayTrading table
        Updates overall statistics (profit/loss, counts, etc.)
        """
        try:
            # Prepare the completed trade entry
            completed_trade = {
                "ticker": ticker,
                "action": action.upper(),  # Ensure uppercase (BUY_TO_OPEN, SELL_TO_OPEN)
                "enter_price": cls._convert_to_decimal(enter_price),
                "enter_reason": enter_reason,
                "enter_timestamp": enter_timestamp,
                "exit_price": cls._convert_to_decimal(exit_price),
                "exit_timestamp": exit_timestamp,
                "exit_reason": exit_reason,
                "profit_or_loss": cls._convert_to_decimal(profit_or_loss),
                "technical_indicators_for_enter": cls._convert_to_decimal(
                    technical_indicators_for_enter or {}
                ),
                "technical_indicators_for_exit": cls._convert_to_decimal(
                    technical_indicators_for_exit or {}
                ),
            }

            # Ensure all floats are converted
            completed_trade = cls._ensure_all_floats_converted(completed_trade)

            # Try to get existing item
            try:
                cls._ensure_tables()
                response = cls._completed_trades_table.get_item(
                    Key={"date": date, "indicator": indicator}
                )
                existing_item = response.get("Item")
            except Exception as e:
                logger.warning(
                    f"Error getting existing completed trades item: {str(e)}"
                )
                existing_item = None

            if existing_item:
                # Update existing item
                # Convert existing item from Decimal to native types
                existing_item = cls._convert_from_decimal(existing_item)

                # Get current values
                completed_trades_list = existing_item.get("completed_trades", [])
                overall_profit_loss = existing_item.get("overall_profit_loss", 0.0)
                completed_trade_count = existing_item.get("completed_trade_count", 0)
                overall_profit_loss_long = existing_item.get(
                    "overall_profit_loss_long", 0.0
                )
                overall_profit_loss_short = existing_item.get(
                    "overall_profit_loss_short", 0.0
                )

                # Add new trade to list
                # Note: completed_trades_list items may need conversion, but we'll convert the whole list when writing
                completed_trades_list.append(completed_trade)

                # Convert the entire list to ensure all values are properly formatted
                completed_trades_list = cls._convert_to_decimal(completed_trades_list)

                # Update statistics
                new_overall_profit_loss = overall_profit_loss + float(profit_or_loss)
                new_completed_trade_count = completed_trade_count + 1

                # Update long/short profit based on action
                if action.upper() == "BUY_TO_OPEN":
                    new_overall_profit_loss_long = overall_profit_loss_long + float(
                        profit_or_loss
                    )
                    new_overall_profit_loss_short = overall_profit_loss_short
                elif action.upper() == "SELL_TO_OPEN":
                    new_overall_profit_loss_long = overall_profit_loss_long
                    new_overall_profit_loss_short = overall_profit_loss_short + float(
                        profit_or_loss
                    )
                else:
                    # Unknown action, don't update long/short
                    new_overall_profit_loss_long = overall_profit_loss_long
                    new_overall_profit_loss_short = overall_profit_loss_short

                expression_values = {
                    ":ct": completed_trades_list,
                    ":opl": cls._convert_to_decimal(new_overall_profit_loss),
                    ":ctc": new_completed_trade_count,
                    ":opll": cls._convert_to_decimal(new_overall_profit_loss_long),
                    ":opls": cls._convert_to_decimal(new_overall_profit_loss_short),
                }
                expression_values = cls._ensure_all_floats_converted(expression_values)

                # Update item
                cls._completed_trades_table.update_item(
                    Key={"date": date, "indicator": indicator},
                    UpdateExpression=(
                        "SET completed_trades = :ct, "
                        "overall_profit_loss = :opl, "
                        "completed_trade_count = :ctc, "
                        "overall_profit_loss_long = :opll, "
                        "overall_profit_loss_short = :opls"
                    ),
                    ExpressionAttributeValues=expression_values,
                )
            else:
                # Create new item
                # Determine initial long/short profit
                initial_profit_loss_long = (
                    float(profit_or_loss) if action.upper() == "BUY_TO_OPEN" else 0.0
                )
                initial_profit_loss_short = (
                    float(profit_or_loss) if action.upper() == "SELL_TO_OPEN" else 0.0
                )

                new_item = {
                    "date": date,
                    "indicator": indicator,
                    "completed_trades": [completed_trade],
                    "overall_profit_loss": cls._convert_to_decimal(profit_or_loss),
                    "completed_trade_count": 1,
                    "overall_profit_loss_long": cls._convert_to_decimal(
                        initial_profit_loss_long
                    ),
                    "overall_profit_loss_short": cls._convert_to_decimal(
                        initial_profit_loss_short
                    ),
                }

                # Ensure all floats are converted
                new_item = cls._ensure_all_floats_converted(new_item)

                cls._completed_trades_table.put_item(Item=new_item)

            logger.info(
                f"Added completed trade for {ticker} to CompletedTradesForAutomatedDayTrading "
                f"(date: {date}, indicator: {indicator}, profit/loss: {profit_or_loss:.2f})"
            )
            return True
        except Exception as e:
            logger.exception(
                f"Error adding completed trade for {ticker} to CompletedTradesForAutomatedDayTrading: {str(e)}"
            )
            return False
