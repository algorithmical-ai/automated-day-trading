"""
DynamoDB Client for managing active trades
"""
import boto3
import json
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
from loguru_logger import logger
from constants import (
    DYNAMODB_TABLE_NAME,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_DEFAULT_REGION
)

# New table for momentum-based trading
MOMENTUM_TRADING_TABLE_NAME = "ActiveTickersForAutomatedDayTrader"
# Ticker blacklist table
TICKER_BLACKLIST_TABLE_NAME = "TickerBlackList"
# MAB table for tracking ticker profitability
MAB_TABLE_NAME = "MABForDayTradingService"


class DynamoDBClient:
    """Client for DynamoDB operations"""
    
    def __init__(self):
        # Configure boto3 with credentials from environment/constants
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            self.dynamodb = boto3.resource(
                'dynamodb',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_DEFAULT_REGION
            )
        else:
            # Fall back to default credential chain (env vars, IAM role, etc.)
            self.dynamodb = boto3.resource('dynamodb', region_name=AWS_DEFAULT_REGION)
        
        self.table = self.dynamodb.Table(DYNAMODB_TABLE_NAME)
        self.momentum_table = self.dynamodb.Table(MOMENTUM_TRADING_TABLE_NAME)
        self.blacklist_table = self.dynamodb.Table(TICKER_BLACKLIST_TABLE_NAME)
        self.mab_table = self.dynamodb.Table(MAB_TABLE_NAME)
    
    def _convert_to_decimal(self, obj):
        """Convert float to Decimal for DynamoDB"""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_to_decimal(item) for item in obj]
        return obj
    
    def _convert_from_decimal(self, obj):
        """Convert Decimal to float from DynamoDB"""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_from_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_from_decimal(item) for item in obj]
        return obj
    
    async def add_trade(
        self, 
        ticker: str, 
        action: str, 
        indicator: str, 
        enter_price: float,
        enter_reason: str,
        enter_response: Dict[str, Any]
    ) -> bool:
        """Add a trade to DynamoDB"""
        try:
            item = {
                "ticker": ticker,
                "action": action,
                "indicator": indicator,
                "enter_price": self._convert_to_decimal(enter_price),
                "enter_reason": enter_reason,
                "enter_response": self._convert_to_decimal(enter_response),
                "created_at": datetime.utcnow().isoformat()
            }
            self.table.put_item(Item=item)
            logger.info(f"Added trade to DynamoDB: {ticker} - {action}")
            return True
        except Exception as e:
            logger.error(f"Error adding trade to DynamoDB: {str(e)}")
            return False
    
    async def get_all_active_trades(self) -> List[Dict[str, Any]]:
        """Get all active trades from DynamoDB"""
        try:
            response = self.table.scan()
            trades = []
            for item in response.get('Items', []):
                # Convert Decimal back to float
                converted_item = self._convert_from_decimal(item)
                trades.append(converted_item)
            return trades
        except Exception as e:
            logger.error(f"Error getting active trades from DynamoDB: {str(e)}")
            return []
    
    async def delete_trade(self, ticker: str) -> bool:
        """Delete a trade from DynamoDB"""
        try:
            self.table.delete_item(Key={"ticker": ticker})
            logger.info(f"Deleted trade from DynamoDB: {ticker}")
            return True
        except Exception as e:
            logger.error(f"Error deleting trade from DynamoDB: {str(e)}")
            return False
    
    # Methods for ActiveTickersForAutomatedDayTrader table
    
    async def add_momentum_trade(
        self,
        ticker: str,
        action: str,
        indicator: str,
        enter_price: float,
        enter_reason: str
    ) -> bool:
        """Add a momentum-based trade to ActiveTickersForAutomatedDayTrader table"""
        try:
            item = {
                "ticker": ticker,
                "action": action,
                "indicator": indicator,
                "enter_price": self._convert_to_decimal(enter_price),
                "enter_reason": enter_reason,
                "created_at": datetime.utcnow().isoformat()
            }
            self.momentum_table.put_item(Item=item)
            logger.info(f"Added momentum trade to DynamoDB: {ticker} - {action}")
            return True
        except Exception as e:
            logger.error(f"Error adding momentum trade to DynamoDB: {str(e)}")
            return False
    
    async def get_all_momentum_trades(self) -> List[Dict[str, Any]]:
        """Get all active momentum trades from ActiveTickersForAutomatedDayTrader table"""
        try:
            response = self.momentum_table.scan()
            trades = []
            for item in response.get('Items', []):
                # Convert Decimal back to float
                converted_item = self._convert_from_decimal(item)
                trades.append(converted_item)
            return trades
        except Exception as e:
            logger.error(f"Error getting momentum trades from DynamoDB: {str(e)}")
            return []
    
    async def delete_momentum_trade(self, ticker: str) -> bool:
        """Delete a momentum trade from ActiveTickersForAutomatedDayTrader table"""
        try:
            self.momentum_table.delete_item(Key={"ticker": ticker})
            logger.info(f"Deleted momentum trade from DynamoDB: {ticker}")
            return True
        except Exception as e:
            logger.error(f"Error deleting momentum trade from DynamoDB: {str(e)}")
            return False
    
    # Methods for TickerBlackList table
    
    async def get_blacklisted_tickers(self) -> List[str]:
        """Get all blacklisted tickers from TickerBlackList table"""
        try:
            response = self.blacklist_table.scan()
            blacklisted_tickers = []
            for item in response.get('Items', []):
                ticker = item.get('ticker')
                if ticker:
                    blacklisted_tickers.append(ticker)
            logger.debug(f"Found {len(blacklisted_tickers)} blacklisted tickers")
            return blacklisted_tickers
        except Exception as e:
            logger.error(f"Error getting blacklisted tickers from DynamoDB: {str(e)}")
            return []
    
    async def is_ticker_blacklisted(self, ticker: str) -> bool:
        """Check if a ticker is in the blacklist"""
        try:
            response = self.blacklist_table.get_item(Key={"ticker": ticker})
            return 'Item' in response
        except Exception as e:
            logger.error(f"Error checking if ticker {ticker} is blacklisted: {str(e)}")
            return False
    
    # Methods for MABForDayTradingService table
    
    async def get_mab_stats(self, ticker: str, indicator: str) -> Optional[Dict[str, Any]]:
        """Get MAB statistics for a ticker and indicator"""
        try:
            response = self.mab_table.get_item(
                Key={
                    "ticker": ticker,
                    "indicator": indicator
                }
            )
            if 'Item' in response:
                item = self._convert_from_decimal(response['Item'])
                return item
            return None
        except Exception as e:
            logger.error(f"Error getting MAB stats for {ticker}/{indicator}: {str(e)}")
            return None
    
    async def update_mab_reward(
        self,
        ticker: str,
        indicator: str,
        reward: float,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update MAB statistics with a reward (profit/loss)
        reward: positive for profit, negative for loss
        """
        try:
            # Get current stats or initialize
            current_stats = await self.get_mab_stats(ticker, indicator)
            
            if current_stats is None:
                # Initialize new entry
                item = {
                    "ticker": ticker,
                    "indicator": indicator,
                    "total_rewards": self._convert_to_decimal(0.0),
                    "total_pulls": 0,
                    "successful_trades": 0,
                    "failed_trades": 0,
                    "last_updated": datetime.utcnow().isoformat(),
                    "daily_reset_date": datetime.utcnow().date().isoformat()
                }
                if context:
                    item["last_context"] = context
                current_stats = item
            
            # Update statistics
            total_rewards = float(current_stats.get("total_rewards", 0.0)) + reward
            total_pulls = current_stats.get("total_pulls", 0) + 1
            
            if reward > 0:
                successful_trades = current_stats.get("successful_trades", 0) + 1
                failed_trades = current_stats.get("failed_trades", 0)
            else:
                successful_trades = current_stats.get("successful_trades", 0)
                failed_trades = current_stats.get("failed_trades", 0) + 1
            
            # Update item
            update_expression = "SET total_rewards = :tr, total_pulls = :tp, successful_trades = :st, failed_trades = :ft, last_updated = :lu"
            expression_values = {
                ":tr": self._convert_to_decimal(total_rewards),
                ":tp": total_pulls,
                ":st": successful_trades,
                ":ft": failed_trades,
                ":lu": datetime.utcnow().isoformat()
            }
            
            if context:
                update_expression += ", last_context = :lc"
                expression_values[":lc"] = context
            
            self.mab_table.update_item(
                Key={
                    "ticker": ticker,
                    "indicator": indicator
                },
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values
            )
            
            logger.debug(f"Updated MAB stats for {ticker}/{indicator}: reward={reward:.4f}, total_rewards={total_rewards:.4f}, pulls={total_pulls}")
            return True
        except Exception as e:
            logger.error(f"Error updating MAB reward for {ticker}/{indicator}: {str(e)}")
            return False
    
    async def reset_daily_mab_stats(self, indicator: str) -> bool:
        """
        Reset daily MAB statistics for all tickers with a given indicator
        This should be called at market open each day
        """
        try:
            today = datetime.utcnow().date().isoformat()
            
            # Scan all items with the indicator
            # Note: This is a scan operation, which can be expensive for large tables
            # In production, consider using GSI or different table design
            response = self.mab_table.scan(
                FilterExpression="indicator = :ind",
                ExpressionAttributeValues={":ind": indicator}
            )
            
            reset_count = 0
            for item in response.get('Items', []):
                ticker = item.get('ticker')
                daily_reset_date = item.get('daily_reset_date')
                
                # Only reset if not already reset today
                if daily_reset_date != today:
                    self.mab_table.update_item(
                        Key={
                            "ticker": ticker,
                            "indicator": indicator
                        },
                        UpdateExpression="SET daily_reset_date = :drd, daily_rewards = :dr, daily_pulls = :dp, last_updated = :lu",
                        ExpressionAttributeValues={
                            ":drd": today,
                            ":dr": self._convert_to_decimal(0.0),
                            ":dp": 0,
                            ":lu": datetime.utcnow().isoformat()
                        }
                    )
                    reset_count += 1
            
            logger.info(f"Reset daily MAB stats for {reset_count} tickers with indicator {indicator}")
            return True
        except Exception as e:
            logger.error(f"Error resetting daily MAB stats: {str(e)}")
            return False
    
    async def get_all_mab_stats_for_indicator(self, indicator: str) -> List[Dict[str, Any]]:
        """Get all MAB statistics for a given indicator"""
        try:
            response = self.mab_table.scan(
                FilterExpression="indicator = :ind",
                ExpressionAttributeValues={":ind": indicator}
            )
            stats = []
            for item in response.get('Items', []):
                converted_item = self._convert_from_decimal(item)
                stats.append(converted_item)
            return stats
        except Exception as e:
            logger.error(f"Error getting MAB stats for indicator {indicator}: {str(e)}")
            return []

