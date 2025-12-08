"""
Repository for persisting ticker evaluation records to DynamoDB.

This module handles batch writing of evaluation records (both passing
and failing tickers) to the InactiveTickersForDayTrading table.
"""

import json
from typing import List, Dict, Any
from decimal import Decimal
import aioboto3
from botocore.exceptions import ClientError, BotoCoreError
from loguru import logger


def _convert_to_dynamodb_format(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert evaluation record to DynamoDB format.
    
    Converts floats to Decimals and handles nested dictionaries.
    
    Args:
        record: Evaluation record dictionary
        
    Returns:
        DynamoDB-compatible record
    """
    def convert_value(value):
        if isinstance(value, dict):
            return {k: convert_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [convert_value(item) for item in value]
        elif isinstance(value, float):
            return Decimal(str(value))
        else:
            return value
    
    return convert_value(record)


class InactiveTickerRepository:
    """Repository for persisting evaluation records to DynamoDB."""
    
    def __init__(self, table_name: str = "InactiveTickersForDayTrading"):
        """
        Initialize repository.
        
        Args:
            table_name: Name of the DynamoDB table (default: InactiveTickersForDayTrading)
        """
        self.table_name = table_name
        self.session = aioboto3.Session()
    
    async def batch_write_evaluations(
        self,
        records: List[Dict[str, Any]]
    ) -> bool:
        """
        Write all evaluation records in batch to DynamoDB.
        
        This method writes all records (both passing and failing tickers)
        in a single batch operation. If the batch write fails, it logs
        the error and returns False without throwing an exception.
        
        Args:
            records: List of evaluation dictionaries with fields:
                - ticker: str
                - indicator: str
                - reason_not_to_enter_long: str
                - reason_not_to_enter_short: str
                - technical_indicators: Dict
                - timestamp: str (ISO 8601)
                
        Returns:
            True if successful, False otherwise
        """
        if not records:
            logger.debug("No evaluation records to write")
            return True
        
        try:
            # Convert records to DynamoDB format
            dynamodb_records = [_convert_to_dynamodb_format(record) for record in records]
            
            # Prepare batch write requests
            # DynamoDB batch_write_item has a limit of 25 items per request
            batch_size = 25
            batches = [
                dynamodb_records[i:i + batch_size]
                for i in range(0, len(dynamodb_records), batch_size)
            ]
            
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(self.table_name)
                
                for batch in batches:
                    # Build batch write request
                    request_items = {
                        self.table_name: [
                            {'PutRequest': {'Item': record}}
                            for record in batch
                        ]
                    }
                    
                    # Execute batch write
                    async with self.session.client('dynamodb') as client:
                        response = await client.batch_write_item(RequestItems=request_items)
                    
                    # Handle unprocessed items (retry logic)
                    unprocessed = response.get('UnprocessedItems', {})
                    retry_count = 0
                    max_retries = 3
                    
                    while unprocessed and retry_count < max_retries:
                        logger.warning(
                            f"Retrying {len(unprocessed.get(self.table_name, []))} unprocessed items",
                            extra={
                                "operation": "batch_write_evaluations",
                                "table": self.table_name,
                                "retry_count": retry_count + 1
                            }
                        )
                        
                        # Exponential backoff
                        import asyncio
                        await asyncio.sleep(2 ** retry_count)
                        
                        async with self.session.client('dynamodb') as client:
                            response = await client.batch_write_item(RequestItems=unprocessed)
                        
                        unprocessed = response.get('UnprocessedItems', {})
                        retry_count += 1
                    
                    if unprocessed:
                        logger.error(
                            f"Failed to write {len(unprocessed.get(self.table_name, []))} items after {max_retries} retries",
                            extra={
                                "operation": "batch_write_evaluations",
                                "table": self.table_name,
                                "status": "partial_failure"
                            }
                        )
            
            logger.info(
                f"Successfully wrote {len(records)} evaluation records to DynamoDB",
                extra={
                    "operation": "batch_write_evaluations",
                    "table": self.table_name,
                    "status": "success",
                    "record_count": len(records)
                }
            )
            return True
            
        except ClientError as e:
            logger.error(
                f"DynamoDB ClientError in batch_write_evaluations: {e.response['Error']['Message']}",
                extra={
                    "operation": "batch_write_evaluations",
                    "table": self.table_name,
                    "status": "failed",
                    "error_code": e.response['Error']['Code'],
                    "error_message": e.response['Error']['Message']
                }
            )
            return False
            
        except BotoCoreError as e:
            logger.error(
                f"DynamoDB BotoCoreError in batch_write_evaluations: {str(e)}",
                extra={
                    "operation": "batch_write_evaluations",
                    "table": self.table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
            
        except Exception as e:
            logger.error(
                f"Unexpected error in batch_write_evaluations: {str(e)}",
                extra={
                    "operation": "batch_write_evaluations",
                    "table": self.table_name,
                    "status": "failed",
                    "error": str(e)
                }
            )
            return False
