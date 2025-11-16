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

