#!/usr/bin/env python3
"""
Script to enhance InactiveTickersForDayTrading records with MAB rejection reasons.

This script identifies records with empty rejection reasons and populates them
with appropriate MAB-based explanations.

Usage:
    python scripts/enhance_mab_rejections.py --indicator "Penny Stocks" --hours 24
    python scripts/enhance_mab_rejections.py --export-csv enhanced_penny_stocks.csv
    python scripts/enhance_mab_rejections.py --enhance-existing --indicator "Penny Stocks"
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.src.services.mab.mab_rejection_enhancer import MABRejectionEnhancer
from app.src.common.loguru_logger import logger


async def enhance_penny_stocks_rejections():
    """Enhance penny stocks rejection records with MAB reasons."""
    logger.info("🚀 Starting MAB rejection enhancement for Penny Stocks")
    
    enhancer = MABRejectionEnhancer()
    
    # Enhance existing records with empty rejection reasons
    stats = await enhancer.enhance_empty_rejection_records(
        indicator="Penny Stocks",
        hours_lookback=48,  # Look back 48 hours to catch more records
        batch_size=25
    )
    
    logger.info(f"📊 Enhancement Statistics:")
    logger.info(f"   Total records found: {stats['total_found']}")
    logger.info(f"   Successfully enhanced: {stats['enhanced']}")
    logger.info(f"   Skipped: {stats['skipped']}")
    logger.info(f"   Errors: {stats['errors']}")
    
    if stats['enhanced'] > 0:
        success_rate = (stats['enhanced'] / stats['total_found']) * 100 if stats['total_found'] > 0 else 0
        logger.info(f"   Success rate: {success_rate:.1f}%")
    
    return stats


async def export_enhanced_csv():
    """Export enhanced data to CSV for analysis."""
    logger.info("📄 Generating enhanced CSV export")
    
    enhancer = MABRejectionEnhancer()
    
    output_file = "enhanced_penny_stocks_with_mab_reasons.csv"
    
    try:
        result_file = await enhancer.generate_enhanced_csv_export(
            indicator="Penny Stocks",
            hours_lookback=48,
            output_file=output_file
        )
        
        logger.info(f"✅ Enhanced CSV exported to: {result_file}")
        
        # Print sample of the enhanced data
        import pandas as pd
        df = pd.read_csv(result_file)
        
        logger.info(f"📈 CSV Summary:")
        logger.info(f"   Total records: {len(df)}")
        
        # Count records with populated reasons
        long_reasons = df['reason_not_to_enter_long'].notna() & (df['reason_not_to_enter_long'] != '')
        short_reasons = df['reason_not_to_enter_short'].notna() & (df['reason_not_to_enter_short'] != '')
        
        logger.info(f"   Records with long reasons: {long_reasons.sum()}")
        logger.info(f"   Records with short reasons: {short_reasons.sum()}")
        logger.info(f"   Records with any reason: {(long_reasons | short_reasons).sum()}")
        
        # Show sample of MAB rejection reasons
        mab_rejections = df[
            df['reason_not_to_enter_long'].str.contains('MAB', na=False) |
            df['reason_not_to_enter_short'].str.contains('MAB', na=False)
        ]
        
        if len(mab_rejections) > 0:
            logger.info(f"   Records with MAB rejections: {len(mab_rejections)}")
            logger.info("   Sample MAB rejection reasons:")
            for _, row in mab_rejections.head(3).iterrows():
                ticker = row['ticker']
                long_reason = row['reason_not_to_enter_long']
                short_reason = row['reason_not_to_enter_short']
                
                if long_reason and 'MAB' in long_reason:
                    logger.info(f"     {ticker} (long): {long_reason[:100]}...")
                if short_reason and 'MAB' in short_reason:
                    logger.info(f"     {ticker} (short): {short_reason[:100]}...")
        
        return result_file
        
    except Exception as e:
        logger.error(f"❌ Error exporting CSV: {str(e)}")
        raise


async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Enhance InactiveTickersForDayTrading with MAB rejection reasons',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enhance existing records and export CSV
  python scripts/enhance_mab_rejections.py --enhance --export
  
  # Only export enhanced CSV (no database updates)
  python scripts/enhance_mab_rejections.py --export
  
  # Only enhance existing records (no CSV export)
  python scripts/enhance_mab_rejections.py --enhance
        """
    )
    
    parser.add_argument(
        '--enhance', 
        action='store_true', 
        help='Enhance existing records with empty rejection reasons'
    )
    parser.add_argument(
        '--export', 
        action='store_true', 
        help='Export enhanced data to CSV file'
    )
    parser.add_argument(
        '--indicator', 
        default='Penny Stocks', 
        help='Trading indicator name (default: Penny Stocks)'
    )
    
    args = parser.parse_args()
    
    if not args.enhance and not args.export:
        logger.info("No action specified. Use --enhance and/or --export")
        parser.print_help()
        return
    
    try:
        if args.enhance:
            await enhance_penny_stocks_rejections()
        
        if args.export:
            await export_enhanced_csv()
        
        logger.info("🎉 All operations completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Script failed: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())