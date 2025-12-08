"""
DynamoDB client for automated day trading application.
Provides async operations for data persistence with error handling and logging.
"""
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from decimal import Decimal
import aioboto3
from botocore.exceptions import ClientError, BotoCoreError
from loguru import logger


def _convert_floats_to_decimals(obj: Any) -> Any:
    """
    Recursively convert all float values to Decimal for DynamoDB compatibility.
    DynamoDB doesn't support native Python float types.
    
    Args:
        obj: Object to convert (can be dict, list, float, or any other type)
        
    Returns:
        Object with all floats converted to Decimals
    """
    if isinstance(obj, dict):
        return {k: _convert_floats_to_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_floats_to_decimals(item) for item in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    else:
        return obj


class DynamoDBClient:
    """
    Async DynamoDB client with comprehensive error handling.
    
    Provides operations: put_item, get_item, delete_item, query, scan, update_item
    All operations include detailed logging and graceful degradation on failures.
    """
    
    def __init__(self):
        """Initialize DynamoDB client with AWS credentials from environment."""
        self.aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        self.aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        self.aws_region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
        
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            logger.warning("AWS credentials not found in environment variables")
        
        # Initialize aioboto3 session
        self.session = aioboto3.Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region
        )
        
        logger.info(f"DynamoDB client initialized for region: {self.aws_region}")
    
    async def put_item(self, table_name: str, item: Dict[str, Any]) -> bool:
        """
        Insert item into DynamoDB table.
        
        Args:
            table_name: Name of the DynamoDB table
            item: Dictionary containing item data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(table_name)
                await table.put_item(Item=item)
            
            logger.debug(
                f"DynamoDB put_item successful",
                extra={
                    "operation": "put_item",
                    "table": table_name,
                    "status": "success"
                }
            )
            return True
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in put_item: {e.response['Error']['Message']}",
                extra={
                    "operation": "put_item",
                    "table": table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return False
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in put_item: {str(e)}",
                extra={
                    "operation": "put_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
            
        except Exception as e:
            logger.error(
                f"Unexpected error in put_item: {str(e)}",
                extra={
                    "operation": "put_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
    
    async def get_item(self, table_name: str, key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Retrieve item from DynamoDB table by key.
        
        Args:
            table_name: Name of the DynamoDB table
            key: Dictionary containing partition key (and sort key if applicable)
            
        Returns:
            Item dictionary if found, None otherwise
        """
        try:
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(table_name)
                response = await table.get_item(Key=key)
            
            item = response.get('Item')
            
            logger.debug(
                f"DynamoDB get_item successful",
                extra={
                    "operation": "get_item",
                    "table": table_name,
                    "status": "success",
                    "found": item is not None
                }
            )
            
            return item
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in get_item: {e.response['Error']['Message']}",
                extra={
                    "operation": "get_item",
                    "table": table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return None
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in get_item: {str(e)}",
                extra={
                    "operation": "get_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return None
            
        except Exception as e:
            logger.error(
                f"Unexpected error in get_item: {str(e)}",
                extra={
                    "operation": "get_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return None
    
    async def delete_item(self, table_name: str, key: Dict[str, Any]) -> bool:
        """
        Delete item from DynamoDB table.
        
        Args:
            table_name: Name of the DynamoDB table
            key: Dictionary containing partition key (and sort key if applicable)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(table_name)
                await table.delete_item(Key=key)
            
            logger.debug(
                f"DynamoDB delete_item successful",
                extra={
                    "operation": "delete_item",
                    "table": table_name,
                    "status": "success"
                }
            )
            return True
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in delete_item: {e.response['Error']['Message']}",
                extra={
                    "operation": "delete_item",
                    "table": table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return False
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in delete_item: {str(e)}",
                extra={
                    "operation": "delete_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
            
        except Exception as e:
            logger.error(
                f"Unexpected error in delete_item: {str(e)}",
                extra={
                    "operation": "delete_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
    
    async def query(
        self,
        table_name: str,
        key_condition_expression: str,
        expression_attribute_values: Dict[str, Any],
        expression_attribute_names: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Query DynamoDB table with conditions.
        
        Args:
            table_name: Name of the DynamoDB table
            key_condition_expression: Key condition expression string
            expression_attribute_values: Dictionary of expression attribute values
            expression_attribute_names: Optional dictionary of expression attribute names
            
        Returns:
            List of items matching the query, empty list on error
        """
        try:
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(table_name)
                
                query_params = {
                    'KeyConditionExpression': key_condition_expression,
                    'ExpressionAttributeValues': expression_attribute_values
                }
                
                if expression_attribute_names:
                    query_params['ExpressionAttributeNames'] = expression_attribute_names
                
                response = await table.query(**query_params)
                items = response.get('Items', [])
            
            logger.debug(
                f"DynamoDB query successful",
                extra={
                    "operation": "query",
                    "table": table_name,
                    "status": "success",
                    "items_count": len(items)
                }
            )
            
            return items
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in query: {e.response['Error']['Message']}",
                extra={
                    "operation": "query",
                    "table": table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return []
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in query: {str(e)}",
                extra={
                    "operation": "query",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return []
            
        except Exception as e:
            logger.error(
                f"Unexpected error in query: {str(e)}",
                extra={
                    "operation": "query",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return []
    
    async def scan(
        self,
        table_name: str,
        filter_expression: Optional[str] = None,
        expression_attribute_values: Optional[Dict[str, Any]] = None,
        expression_attribute_names: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan DynamoDB table with optional filter.
        
        Args:
            table_name: Name of the DynamoDB table
            filter_expression: Optional filter expression string
            expression_attribute_values: Optional dictionary of expression attribute values
            expression_attribute_names: Optional dictionary of expression attribute names
            
        Returns:
            List of items from scan, empty list on error
        """
        try:
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(table_name)
                
                scan_params = {}
                
                if filter_expression:
                    scan_params['FilterExpression'] = filter_expression
                
                if expression_attribute_values:
                    scan_params['ExpressionAttributeValues'] = expression_attribute_values
                
                if expression_attribute_names:
                    scan_params['ExpressionAttributeNames'] = expression_attribute_names
                
                response = await table.scan(**scan_params)
                items = response.get('Items', [])
            
            logger.debug(
                f"DynamoDB scan successful",
                extra={
                    "operation": "scan",
                    "table": table_name,
                    "status": "success",
                    "items_count": len(items)
                }
            )
            
            return items
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in scan: {e.response['Error']['Message']}",
                extra={
                    "operation": "scan",
                    "table": table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return []
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in scan: {str(e)}",
                extra={
                    "operation": "scan",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return []
            
        except Exception as e:
            logger.error(
                f"Unexpected error in scan: {str(e)}",
                extra={
                    "operation": "scan",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return []
    
    async def update_item(
        self,
        table_name: str,
        key: Dict[str, Any],
        update_expression: str,
        expression_attribute_values: Dict[str, Any],
        expression_attribute_names: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Update item attributes in DynamoDB table.
        
        Args:
            table_name: Name of the DynamoDB table
            key: Dictionary containing partition key (and sort key if applicable)
            update_expression: Update expression string
            expression_attribute_values: Dictionary of expression attribute values
            expression_attribute_names: Optional dictionary of expression attribute names
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(table_name)
                
                update_params = {
                    'Key': key,
                    'UpdateExpression': update_expression,
                    'ExpressionAttributeValues': expression_attribute_values
                }
                
                if expression_attribute_names:
                    update_params['ExpressionAttributeNames'] = expression_attribute_names
                
                await table.update_item(**update_params)
            
            logger.debug(
                f"DynamoDB update_item successful",
                extra={
                    "operation": "update_item",
                    "table": table_name,
                    "status": "success"
                }
            )
            return True
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in update_item: {e.response['Error']['Message']}",
                extra={
                    "operation": "update_item",
                    "table": table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return False
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in update_item: {str(e)}",
                extra={
                    "operation": "update_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
            
        except Exception as e:
            logger.error(
                f"Unexpected error in update_item: {str(e)}",
                extra={
                    "operation": "update_item",
                    "table": table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
    
    # =========================================================================
    # Class-level helper methods for trading operations
    # =========================================================================
    
    _instance: Optional['DynamoDBClient'] = None
    
    @classmethod
    def configure(cls):
        """Configure and initialize the singleton DynamoDB client instance."""
        if cls._instance is None:
            cls._instance = cls()
            logger.info("DynamoDB client configured")
    
    @classmethod
    def _get_instance(cls) -> 'DynamoDBClient':
        """Get the singleton instance, creating it if necessary."""
        if cls._instance is None:
            cls.configure()
        return cls._instance
    
    @classmethod
    async def add_momentum_trade(
        cls,
        ticker: str,
        action: str,
        indicator: str,
        enter_price: float,
        enter_reason: str,
        technical_indicators_for_enter: Optional[Dict[str, Any]] = None,
        dynamic_stop_loss: Optional[float] = None,
        entry_score: Optional[float] = None,
    ) -> bool:
        """
        Add an active trade to the ActiveTickersForAutomatedDayTrader table.
        
        Args:
            ticker: Stock ticker symbol
            action: Trade action ("buy_to_open" or "sell_to_open")
            indicator: Trading indicator name
            enter_price: Entry price
            enter_reason: Reason for entering trade
            technical_indicators_for_enter: Technical indicators at entry
            dynamic_stop_loss: Dynamic stop loss value
            entry_score: Entry score (for Deep Analyzer)
            
        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()
        
        item = {
            'ticker': ticker,
            'action': action,
            'indicator': indicator,
            'enter_price': enter_price,
            'enter_reason': enter_reason,
            'technical_indicators_for_enter': technical_indicators_for_enter or {},
            'dynamic_stop_loss': dynamic_stop_loss or 0.0,
            'trailing_stop': 0.0,  # Will be updated when activated
            'peak_profit_percent': 0.0,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        if entry_score is not None:
            item['entry_score'] = entry_score
        
        return await instance.put_item(
            table_name='ActiveTickersForAutomatedDayTrader',
            item=item
        )
    
    @classmethod
    async def get_all_momentum_trades(cls, indicator: str) -> List[Dict[str, Any]]:
        """
        Get all active trades for a specific indicator.
        
        Args:
            indicator: Trading indicator name
            
        Returns:
            List of active trade dictionaries
        """
        instance = cls._get_instance()
        
        # Scan table with filter for indicator (using expression attribute name for reserved keyword)
        trades = await instance.scan(
            table_name='ActiveTickersForAutomatedDayTrader',
            filter_expression='#ind = :indicator',
            expression_attribute_names={'#ind': 'indicator'},
            expression_attribute_values={':indicator': indicator}
        )
        
        return trades
    
    @classmethod
    async def delete_momentum_trade(cls, ticker: str, indicator: str) -> bool:
        """
        Delete an active trade from the ActiveTickersForAutomatedDayTrader table.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            
        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()
        
        return await instance.delete_item(
            table_name='ActiveTickersForAutomatedDayTrader',
            key={'ticker': ticker}
        )
    
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
        Add a completed trade to the CompletedTradesForMarketData table.
        
        Args:
            date: Trade date (yyyy-mm-dd)
            indicator: Trading indicator name
            ticker: Stock ticker symbol
            action: Trade action
            enter_price: Entry price
            enter_reason: Entry reason
            enter_timestamp: Entry timestamp (ISO format UTC)
            exit_price: Exit price
            exit_timestamp: Exit timestamp (ISO format UTC)
            exit_reason: Exit reason
            profit_or_loss: Profit or loss amount
            technical_indicators_for_enter: Technical indicators at entry
            technical_indicators_for_exit: Technical indicators at exit
            
        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()
        
        item = {
            'date': date,
            'ticker_indicator': f"{ticker}#{indicator}",  # Sort key
            'ticker': ticker,
            'indicator': indicator,
            'action': action,
            'enter_price': enter_price,
            'enter_reason': enter_reason,
            'enter_timestamp': enter_timestamp,
            'exit_price': exit_price,
            'exit_timestamp': exit_timestamp,
            'exit_reason': exit_reason,
            'profit_or_loss': profit_or_loss,
            'technical_indicators_for_enter': technical_indicators_for_enter or {},
            'technical_indicators_for_exit': technical_indicators_for_exit or {}
        }
        
        return await instance.put_item(
            table_name='CompletedTradesForMarketData',
            item=item
        )
    
    @classmethod
    async def get_completed_trade_count(cls, date: str, indicator: str) -> int:
        """
        Get the count of completed trades for a specific date and indicator.
        
        Args:
            date: Trade date (yyyy-mm-dd)
            indicator: Trading indicator name
            
        Returns:
            Number of completed trades
        """
        instance = cls._get_instance()
        
        # Query by date partition key and filter by indicator
        trades = await instance.query(
            table_name='CompletedTradesForMarketData',
            key_condition_expression='#date = :date',
            expression_attribute_names={'#date': 'date'},
            expression_attribute_values={':date': date}
        )
        
        # Filter by indicator
        indicator_trades = [t for t in trades if t.get('indicator') == indicator]
        
        return len(indicator_trades)
    
    @classmethod
    async def log_inactive_ticker(
        cls,
        ticker: str,
        indicator: str,
        reason_not_to_enter_long: str,
        reason_not_to_enter_short: str,
        technical_indicators: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log an inactive ticker (evaluated but not traded) to InactiveTickersForDayTrading table.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            reason_not_to_enter_long: Reason for not entering long position
            reason_not_to_enter_short: Reason for not entering short position
            technical_indicators: Technical indicators at evaluation time
            
        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Convert technical_indicators to use Decimals instead of floats
        tech_indicators = _convert_floats_to_decimals(technical_indicators or {})
        
        item = {
            'ticker': ticker,
            'indicator': indicator,
            'timestamp': timestamp,
            'reason_not_to_enter_long': reason_not_to_enter_long,
            'reason_not_to_enter_short': reason_not_to_enter_short,
            'technical_indicators': tech_indicators
        }
        
        return await instance.put_item(
            table_name='InactiveTickersForDayTrading',
            item=item
        )
    
    @classmethod
    async def log_inactive_ticker_reason(
        cls,
        ticker: str,
        indicator: str,
        reason_not_to_enter_long: str,
        reason_not_to_enter_short: str,
        technical_indicators: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Alias for log_inactive_ticker for backward compatibility.
        Log an inactive ticker (evaluated but not traded) to InactiveTickersForDayTrading table.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            reason_not_to_enter_long: Reason for not entering long position
            reason_not_to_enter_short: Reason for not entering short position
            technical_indicators: Technical indicators at evaluation time
            
        Returns:
            True if successful, False otherwise
        """
        return await cls.log_inactive_ticker(
            ticker=ticker,
            indicator=indicator,
            reason_not_to_enter_long=reason_not_to_enter_long,
            reason_not_to_enter_short=reason_not_to_enter_short,
            technical_indicators=technical_indicators
        )
    
    @classmethod
    async def get_inactive_tickers_for_indicator(
        cls,
        indicator: str,
        minutes_window: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get inactive tickers for a specific indicator from the last N minutes.
        
        Args:
            indicator: Trading indicator name
            minutes_window: Time window in minutes (default: 5)
            
        Returns:
            List of inactive ticker dictionaries
        """
        instance = cls._get_instance()
        
        # Calculate the timestamp for N minutes ago
        from datetime import timedelta
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_window)
        cutoff_timestamp = cutoff_time.isoformat()
        
        # Query table by indicator (sort key) with timestamp filter
        # Since indicator is the sort key, we need to scan and filter
        inactive_tickers = await instance.scan(
            table_name='InactiveTickersForDayTrading',
            filter_expression='#ind = :indicator AND #ts >= :cutoff',
            expression_attribute_names={'#ind': 'indicator', '#ts': 'timestamp'},
            expression_attribute_values={
                ':indicator': indicator,
                ':cutoff': cutoff_timestamp
            }
        )
        
        return inactive_tickers
    
    @classmethod
    async def store_day_trader_event(
        cls,
        date: str,
        indicator: str,
        threshold_change: Dict[str, Any],
        max_long_trades: int,
        max_short_trades: int,
        llm_response: str
    ) -> bool:
        """
        Store a threshold adjustment event in the DayTraderEvents table.
        
        Args:
            date: Event date (yyyy-mm-dd)
            indicator: Trading indicator name
            threshold_change: Dictionary of threshold changes (old and new values)
            max_long_trades: Recommended max long trades
            max_short_trades: Recommended max short trades
            llm_response: Full LLM response text
            
        Returns:
            True if successful, False otherwise
        """
        instance = cls._get_instance()
        
        # Get current time in EST for last_updated
        from datetime import timezone as tz
        from zoneinfo import ZoneInfo
        est_time = datetime.now(ZoneInfo('America/New_York')).isoformat()
        
        item = {
            'date': date,
            'indicator': indicator,
            'last_updated': est_time,
            'threshold_change': threshold_change,
            'max_long_trades': max_long_trades,
            'max_short_trades': max_short_trades,
            'llm_response': llm_response
        }
        
        return await instance.put_item(
            table_name='DayTraderEvents',
            item=item
        )
