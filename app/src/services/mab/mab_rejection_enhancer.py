"""
MAB Rejection Enhancer for InactiveTickersForDayTrading

This module enhances the existing InactiveTickersForDayTrading table by adding
comprehensive MAB rejection reasons for tickers that have empty reason fields.
It provides both real-time enhancement and batch backfill capabilities.
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from loguru import logger

from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.mab.mab_service import MABService


class MABRejectionEnhancer:
    """
    Enhances InactiveTickersForDayTrading records with MAB rejection reasons.
    
    This class provides functionality to:
    1. Identify records with empty rejection reasons
    2. Generate appropriate MAB rejection reasons based on historical data
    3. Update records with enhanced rejection information
    4. Provide real-time enhancement for new records
    """
    
    def __init__(self):
        """Initialize the MAB rejection enhancer."""
        self.dynamodb_client = DynamoDBClient()
        self.mab_service = MABService()
    
    async def enhance_empty_rejection_records(
        self,
        indicator: str,
        hours_lookback: int = 24,
        batch_size: int = 50
    ) -> Dict[str, int]:
        """
        Enhance records with empty rejection reasons by adding MAB-based reasons.
        
        Args:
            indicator: Trading indicator name (e.g., "Penny Stocks")
            hours_lookback: How many hours back to look for records
            batch_size: Number of records to process in each batch
            
        Returns:
            Dictionary with enhancement statistics:
            {
                'total_found': int,
                'enhanced': int,
                'skipped': int,
                'errors': int
            }
        """
        logger.info(f"Starting MAB rejection enhancement for {indicator} (last {hours_lookback} hours)")
        
        stats = {
            'total_found': 0,
            'enhanced': 0,
            'skipped': 0,
            'errors': 0
        }
        
        try:
            # Get records with empty rejection reasons
            empty_records = await self._get_empty_rejection_records(
                indicator, hours_lookback
            )
            
            stats['total_found'] = len(empty_records)
            logger.info(f"Found {len(empty_records)} records with empty rejection reasons")
            
            if not empty_records:
                return stats
            
            # Process in batches
            for i in range(0, len(empty_records), batch_size):
                batch = empty_records[i:i + batch_size]
                batch_stats = await self._enhance_record_batch(batch, indicator)
                
                stats['enhanced'] += batch_stats['enhanced']
                stats['skipped'] += batch_stats['skipped']
                stats['errors'] += batch_stats['errors']
                
                logger.info(
                    f"Processed batch {i//batch_size + 1}: "
                    f"{batch_stats['enhanced']} enhanced, "
                    f"{batch_stats['skipped']} skipped, "
                    f"{batch_stats['errors']} errors"
                )
                
                # Small delay between batches to avoid overwhelming DynamoDB
                await asyncio.sleep(0.1)
            
            logger.info(
                f"MAB rejection enhancement complete for {indicator}: "
                f"{stats['enhanced']}/{stats['total_found']} records enhanced"
            )
            
        except Exception as e:
            logger.error(f"Error during MAB rejection enhancement: {str(e)}")
            stats['errors'] += 1
        
        return stats
    
    async def _get_empty_rejection_records(
        self,
        indicator: str,
        hours_lookback: int
    ) -> List[Dict[str, Any]]:
        """
        Get records from InactiveTickersForDayTrading with empty rejection reasons.
        
        Args:
            indicator: Trading indicator name
            hours_lookback: Hours to look back from now
            
        Returns:
            List of records with empty reason_not_to_enter_long AND reason_not_to_enter_short
        """
        try:
            # Calculate cutoff time
            cutoff_time = datetime.now(ZoneInfo('America/New_York'))
            cutoff_time = cutoff_time.replace(
                hour=cutoff_time.hour - hours_lookback,
                minute=0, second=0, microsecond=0
            )
            cutoff_timestamp = cutoff_time.isoformat()
            
            # Scan the table for records with empty rejection reasons
            # Note: This is a simplified approach. In production, you might want to use
            # a GSI (Global Secondary Index) on indicator + timestamp for better performance
            
            all_records = await self.dynamodb_client.scan(
                table_name='InactiveTickersForDayTrading',
                filter_expression=(
                    '#ind = :indicator AND #ts >= :cutoff AND '
                    '(attribute_not_exists(reason_not_to_enter_long) OR reason_not_to_enter_long = :empty) AND '
                    '(attribute_not_exists(reason_not_to_enter_short) OR reason_not_to_enter_short = :empty)'
                ),
                expression_attribute_names={
                    '#ind': 'indicator',
                    '#ts': 'timestamp'
                },
                expression_attribute_values={
                    ':indicator': indicator,
                    ':cutoff': cutoff_timestamp,
                    ':empty': ''
                }
            )
            
            logger.debug(f"Found {len(all_records)} records with empty rejection reasons")
            return all_records
            
        except Exception as e:
            logger.error(f"Error getting empty rejection records: {str(e)}")
            return []
    
    async def _enhance_record_batch(
        self,
        records: List[Dict[str, Any]],
        indicator: str
    ) -> Dict[str, int]:
        """
        Enhance a batch of records with MAB rejection reasons.
        
        Args:
            records: List of record dictionaries to enhance
            indicator: Trading indicator name
            
        Returns:
            Dictionary with batch statistics
        """
        batch_stats = {'enhanced': 0, 'skipped': 0, 'errors': 0}
        
        for record in records:
            try:
                ticker = record.get('ticker')
                if not ticker:
                    batch_stats['skipped'] += 1
                    continue
                
                # Generate MAB rejection reason
                enhanced_reasons = await self._generate_mab_rejection_reason(
                    ticker, indicator
                )
                
                if not enhanced_reasons['reason_long'] and not enhanced_reasons['reason_short']:
                    # No MAB data available, create a generic reason
                    enhanced_reasons = self._create_generic_rejection_reason(record)
                
                # Update the record
                success = await self._update_record_with_reasons(
                    record, enhanced_reasons
                )
                
                if success:
                    batch_stats['enhanced'] += 1
                    logger.debug(f"Enhanced {ticker} with MAB rejection reasons")
                else:
                    batch_stats['errors'] += 1
                    
            except Exception as e:
                logger.error(f"Error enhancing record {record.get('ticker', 'unknown')}: {str(e)}")
                batch_stats['errors'] += 1
        
        return batch_stats
    
    async def _generate_mab_rejection_reason(
        self,
        ticker: str,
        indicator: str
    ) -> Dict[str, str]:
        """
        Generate MAB rejection reason for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            
        Returns:
            Dictionary with 'reason_long' and 'reason_short' keys
        """
        try:
            # Get MAB stats for this ticker
            stats = await self.mab_service.get_stats(indicator, ticker)
            
            # Generate rejection reason based on MAB stats
            if stats is None:
                # New ticker - would have been explored by Thompson Sampling
                reason = "MAB: New ticker - not selected by Thompson Sampling (successes: 0, failures: 0, total: 0)"
            else:
                # Use the existing MAB rejection reason generator
                reason = MABService.get_rejection_reason(stats, ticker)
            
            # For penny stocks, we need to determine if this would be long or short
            # Since we don't have the momentum score, we'll apply to both directions
            return {
                'reason_long': reason,
                'reason_short': reason
            }
            
        except Exception as e:
            logger.error(f"Error generating MAB rejection reason for {ticker}: {str(e)}")
            return {'reason_long': '', 'reason_short': ''}
    
    def _create_generic_rejection_reason(
        self,
        record: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Create a generic rejection reason when MAB data is not available.
        
        Args:
            record: The original record dictionary
            
        Returns:
            Dictionary with generic rejection reasons
        """
        ticker = record.get('ticker', 'unknown')
        
        # Check if technical indicators suggest why it might have been rejected
        tech_indicators = record.get('technical_indicators', {})
        
        if isinstance(tech_indicators, str):
            import json
            try:
                tech_indicators = json.loads(tech_indicators)
            except:
                tech_indicators = {}
        
        # Extract momentum score if available
        momentum_score = tech_indicators.get('momentum_score', 0.0)
        
        if momentum_score == 0.0:
            # No momentum data
            reason = f"No entry signal generated - insufficient momentum data or market conditions not met"
        elif abs(momentum_score) < 1.5:
            # Low momentum
            reason = f"Momentum too low for entry: {momentum_score:.2f}% (minimum: 1.5%)"
        else:
            # Likely MAB rejection or capacity limits
            reason = f"Not selected for entry - may be due to MAB ranking, capacity limits, or market timing"
        
        return {
            'reason_long': reason if momentum_score >= 0 else '',
            'reason_short': reason if momentum_score < 0 else ''
        }
    
    async def _update_record_with_reasons(
        self,
        record: Dict[str, Any],
        enhanced_reasons: Dict[str, str]
    ) -> bool:
        """
        Update a record with enhanced rejection reasons.
        
        Args:
            record: Original record dictionary
            enhanced_reasons: Dictionary with 'reason_long' and 'reason_short'
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            ticker = record.get('ticker')
            timestamp = record.get('timestamp')
            
            if not ticker or not timestamp:
                logger.warning(f"Missing ticker or timestamp in record: {record}")
                return False
            
            # Update the record with enhanced reasons
            update_expression = "SET reason_not_to_enter_long = :reason_long, reason_not_to_enter_short = :reason_short"
            expression_attribute_values = {
                ':reason_long': enhanced_reasons['reason_long'],
                ':reason_short': enhanced_reasons['reason_short']
            }
            
            success = await self.dynamodb_client.update_item(
                table_name='InactiveTickersForDayTrading',
                key={'ticker': ticker, 'timestamp': timestamp},
                update_expression=update_expression,
                expression_attribute_values=expression_attribute_values
            )
            
            return success
            
        except Exception as e:
            logger.error(f"Error updating record: {str(e)}")
            return False
    
    @classmethod
    async def enhance_real_time_record(
        cls,
        ticker: str,
        indicator: str,
        technical_indicators: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Generate enhanced rejection reasons for real-time use.
        
        This method can be called when logging a new inactive ticker to
        immediately provide MAB-based rejection reasons.
        
        Args:
            ticker: Stock ticker symbol
            indicator: Trading indicator name
            technical_indicators: Technical indicators dictionary
            
        Returns:
            Dictionary with 'reason_long' and 'reason_short' keys
        """
        enhancer = cls()
        
        # First try to get MAB-based reasons
        mab_reasons = await enhancer._generate_mab_rejection_reason(ticker, indicator)
        
        # If MAB reasons are empty, create generic reasons
        if not mab_reasons['reason_long'] and not mab_reasons['reason_short']:
            fake_record = {
                'ticker': ticker,
                'technical_indicators': technical_indicators or {}
            }
            mab_reasons = enhancer._create_generic_rejection_reason(fake_record)
        
        return mab_reasons
    
    async def generate_enhanced_csv_export(
        self,
        indicator: str,
        hours_lookback: int = 24,
        output_file: str = "enhanced_inactive_tickers.csv"
    ) -> str:
        """
        Generate a CSV export with enhanced rejection reasons.
        
        Args:
            indicator: Trading indicator name
            hours_lookback: Hours to look back from now
            output_file: Output CSV file path
            
        Returns:
            Path to the generated CSV file
        """
        import csv
        import json
        
        logger.info(f"Generating enhanced CSV export for {indicator}")
        
        try:
            # Get all records for the indicator
            cutoff_time = datetime.now(ZoneInfo('America/New_York'))
            cutoff_time = cutoff_time.replace(
                hour=cutoff_time.hour - hours_lookback,
                minute=0, second=0, microsecond=0
            )
            cutoff_timestamp = cutoff_time.isoformat()
            
            all_records = await self.dynamodb_client.scan(
                table_name='InactiveTickersForDayTrading',
                filter_expression='#ind = :indicator AND #ts >= :cutoff',
                expression_attribute_names={
                    '#ind': 'indicator',
                    '#ts': 'timestamp'
                },
                expression_attribute_values={
                    ':indicator': indicator,
                    ':cutoff': cutoff_timestamp
                }
            )
            
            # Enhance records that need it
            enhanced_records = []
            for record in all_records:
                ticker = record.get('ticker', '')
                reason_long = record.get('reason_not_to_enter_long', '')
                reason_short = record.get('reason_not_to_enter_short', '')
                
                # If both reasons are empty, enhance them
                if not reason_long and not reason_short:
                    enhanced_reasons = await self._generate_mab_rejection_reason(ticker, indicator)
                    if not enhanced_reasons['reason_long'] and not enhanced_reasons['reason_short']:
                        enhanced_reasons = self._create_generic_rejection_reason(record)
                    
                    reason_long = enhanced_reasons['reason_long']
                    reason_short = enhanced_reasons['reason_short']
                
                # Prepare record for CSV
                tech_indicators = record.get('technical_indicators', '{}')
                if isinstance(tech_indicators, dict):
                    tech_indicators = json.dumps(tech_indicators)
                
                enhanced_records.append({
                    'ticker': ticker,
                    'indicator': record.get('indicator', ''),
                    'reason_not_to_enter_long': reason_long,
                    'reason_not_to_enter_short': reason_short,
                    'technical_indicators': tech_indicators,
                    'timestamp': record.get('timestamp', '')
                })
            
            # Write to CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'ticker', 'indicator', 'reason_not_to_enter_long', 
                    'reason_not_to_enter_short', 'technical_indicators', 'timestamp'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(enhanced_records)
            
            logger.info(f"Enhanced CSV export complete: {len(enhanced_records)} records written to {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Error generating enhanced CSV export: {str(e)}")
            raise


# CLI interface for running the enhancer
async def main():
    """Main function for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhance InactiveTickersForDayTrading with MAB rejection reasons')
    parser.add_argument('--indicator', default='Penny Stocks', help='Trading indicator name')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back')
    parser.add_argument('--export-csv', help='Export enhanced data to CSV file')
    parser.add_argument('--enhance-existing', action='store_true', help='Enhance existing records with empty reasons')
    
    args = parser.parse_args()
    
    enhancer = MABRejectionEnhancer()
    
    if args.export_csv:
        output_file = await enhancer.generate_enhanced_csv_export(
            indicator=args.indicator,
            hours_lookback=args.hours,
            output_file=args.export_csv
        )
        print(f"Enhanced CSV exported to: {output_file}")
    
    if args.enhance_existing:
        stats = await enhancer.enhance_empty_rejection_records(
            indicator=args.indicator,
            hours_lookback=args.hours
        )
        print(f"Enhancement complete: {stats}")


if __name__ == "__main__":
    asyncio.run(main())