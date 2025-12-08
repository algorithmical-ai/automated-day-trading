"""
Repository for persisting inactive ticker rejection records to DynamoDB.

This module provides batch writing capabilities for rejection records to the
InactiveTickersForDayTrading table.
"""

from typing import List, Dict, Any
import aioboto3
from botocore.exceptions import ClientError, BotoCoreError
from app.src.common.loguru_logger import logger
from app.src.db.dynamodb_client import _convert_floats_to_decimals


class InactiveTickerRepository:
    """
    Repository for writing rejection records to DynamoDB.
    
    Provides batch write operations with error handling and retry logic.
    """
    
    TABLE_NAME = "InactiveTickersForDayTrading"
    MAX_BATCH_SIZE = 25  # DynamoDB batch_write_item limit
    
    def __init__(self, dynamodb_client=None):
        """
        Initialize repository.
        
        Args:
            dynamodb_client: Optional DynamoDBClient instance for dependency injection
        """
        self.dynamodb_client = dynamodb_client
        
        # If no client provided, we'll use aioboto3 directly
        if dynamodb_client is None:
            import os
            self.session = aioboto3.Session(
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
            )
        else:
            self.session = dynamodb_client.session
    
    async def batch_write_rejections(
        self,
        records: List[Dict[str, Any]]
    ) -> bool:
        """
        Write rejection records in batch to InactiveTickersForDayTrading table.
        
        Handles batching (DynamoDB limit is 25 items per batch) and retries
        for unprocessed items.
        
        Args:
            records: List of rejection dictionaries with fields:
                - ticker: str
                - indicator: str
                - reason_not_to_enter_long: Optional[str]
                - reason_not_to_enter_short: Optional[str]
                - technical_indicators: Optional[Dict]
                - timestamp: str (ISO format)
                
        Returns:
            bool: True if all records written successfully, False if any failures
        """
        if not records:
            logger.debug("No rejection records to write")
            return True
        
        try:
            # Convert floats to Decimals for DynamoDB compatibility
            converted_records = [_convert_floats_to_decimals(record) for record in records]
            
            # Split into batches of 25 (DynamoDB limit)
            batches = [
                converted_records[i:i + self.MAX_BATCH_SIZE]
                for i in range(0, len(converted_records), self.MAX_BATCH_SIZE)
            ]
            
            total_written = 0
            total_failed = 0
            
            async with self.session.resource('dynamodb') as dynamodb:
                table = await dynamodb.Table(self.TABLE_NAME)
                
                for batch_num, batch in enumerate(batches, 1):
                    try:
                        # Use batch_writer for automatic retry of unprocessed items
                        async with table.batch_writer() as batch_writer:
                            for record in batch:
                                await batch_writer.put_item(Item=record)
                        
                        total_written += len(batch)
                        logger.debug(
                            f"Batch {batch_num}/{len(batches)} written successfully "
                            f"({len(batch)} records)"
                        )
                        
                    except (ClientError, BotoCoreError) as e:
                        total_failed += len(batch)
                        logger.error(
                            f"Failed to write batch {batch_num}/{len(batches)}: {str(e)}",
                            extra={
                                "operation": "batch_write_rejections",
                                "table": self.TABLE_NAME,
                                "batch_size": len(batch),
                                "error": str(e)
                            }
                        )
                        # Continue with next batch instead of failing completely
                        continue
            
            logger.info(
                f"Batch write complete: {total_written} written, {total_failed} failed",
                extra={
                    "operation": "batch_write_rejections",
                    "table": self.TABLE_NAME,
                    "total_records": len(records),
                    "written": total_written,
                    "failed": total_failed
                }
            )
            
            # Return True only if all records were written
            return total_failed == 0
            
        except Exception as e:
            logger.error(
                f"Unexpected error in batch_write_rejections: {str(e)}",
                extra={
                    "operation": "batch_write_rejections",
                    "table": self.TABLE_NAME,
                    "total_records": len(records),
                    "error": str(e)
                }
            )
            return False
    
    async def write_single_rejection(
        self,
        record: Dict[str, Any]
    ) -> bool:
        """
        Write a single rejection record to the table.
        
        Args:
            record: Rejection record dictionary
            
        Returns:
            bool: True if successful, False otherwise
        """
        return await self.batch_write_rejections([record])
