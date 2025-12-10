#!/usr/bin/env python3
"""
Quick script to enhance MAB rejections and generate improved CSV.

This script will:
1. Enhance existing records with empty rejection reasons
2. Generate a new CSV with all rejection reasons populated
3. Show statistics about the improvements
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


async def main():
    """Run the MAB enhancement process."""
    print("🚀 Starting MAB Rejection Enhancement for Penny Stocks")
    print("=" * 60)
    
    enhancer = MABRejectionEnhancer()
    
    # Step 1: Enhance existing records
    print("\n📝 Step 1: Enhancing existing records with empty rejection reasons...")
    stats = await enhancer.enhance_empty_rejection_records(
        indicator="Penny Stocks",
        hours_lookback=72,  # Look back 3 days
        batch_size=25
    )
    
    print(f"\n📊 Enhancement Results:")
    print(f"   • Total records found with empty reasons: {stats['total_found']}")
    print(f"   • Successfully enhanced: {stats['enhanced']}")
    print(f"   • Skipped: {stats['skipped']}")
    print(f"   • Errors: {stats['errors']}")
    
    if stats['total_found'] > 0:
        success_rate = (stats['enhanced'] / stats['total_found']) * 100
        print(f"   • Success rate: {success_rate:.1f}%")
    
    # Step 2: Generate enhanced CSV
    print("\n📄 Step 2: Generating enhanced CSV export...")
    output_file = "enhanced_penny_stocks_with_mab_reasons.csv"
    
    try:
        result_file = await enhancer.generate_enhanced_csv_export(
            indicator="Penny Stocks",
            hours_lookback=72,
            output_file=output_file
        )
        
        print(f"✅ Enhanced CSV exported to: {result_file}")
        
        # Step 3: Analyze the results
        print("\n📈 Step 3: Analyzing enhanced data...")
        
        try:
            import pandas as pd
            df = pd.read_csv(result_file)
            
            print(f"\n📋 CSV Analysis:")
            print(f"   • Total records: {len(df):,}")
            
            # Count records with populated reasons
            long_reasons = df['reason_not_to_enter_long'].notna() & (df['reason_not_to_enter_long'] != '')
            short_reasons = df['reason_not_to_enter_short'].notna() & (df['reason_not_to_enter_short'] != '')
            any_reason = long_reasons | short_reasons
            
            print(f"   • Records with long entry reasons: {long_reasons.sum():,}")
            print(f"   • Records with short entry reasons: {short_reasons.sum():,}")
            print(f"   • Records with any reason: {any_reason.sum():,}")
            print(f"   • Coverage: {(any_reason.sum() / len(df) * 100):.1f}%")
            
            # Analyze MAB-specific rejections
            mab_long = df['reason_not_to_enter_long'].str.contains('MAB', na=False)
            mab_short = df['reason_not_to_enter_short'].str.contains('MAB', na=False)
            mab_any = mab_long | mab_short
            
            print(f"\n🤖 MAB Rejection Analysis:")
            print(f"   • Records with MAB long rejections: {mab_long.sum():,}")
            print(f"   • Records with MAB short rejections: {mab_short.sum():,}")
            print(f"   • Records with any MAB rejection: {mab_any.sum():,}")
            
            if mab_any.sum() > 0:
                mab_percentage = (mab_any.sum() / any_reason.sum() * 100) if any_reason.sum() > 0 else 0
                print(f"   • MAB rejections as % of all rejections: {mab_percentage:.1f}%")
            
            # Show sample MAB rejection reasons
            mab_samples = df[mab_any].head(5)
            if len(mab_samples) > 0:
                print(f"\n📝 Sample MAB Rejection Reasons:")
                for i, (_, row) in enumerate(mab_samples.iterrows(), 1):
                    ticker = row['ticker']
                    long_reason = row['reason_not_to_enter_long'] if pd.notna(row['reason_not_to_enter_long']) else ''
                    short_reason = row['reason_not_to_enter_short'] if pd.notna(row['reason_not_to_enter_short']) else ''
                    
                    print(f"   {i}. {ticker}:")
                    if long_reason and 'MAB' in long_reason:
                        print(f"      Long: {long_reason[:80]}{'...' if len(long_reason) > 80 else ''}")
                    if short_reason and 'MAB' in short_reason:
                        print(f"      Short: {short_reason[:80]}{'...' if len(short_reason) > 80 else ''}")
            
            # Show improvement statistics
            empty_before = len(df) - any_reason.sum()
            if stats['enhanced'] > 0:
                print(f"\n✨ Improvement Summary:")
                print(f"   • Records that were empty before enhancement: {empty_before + stats['enhanced']:,}")
                print(f"   • Records enhanced with MAB reasons: {stats['enhanced']:,}")
                print(f"   • Records still empty after enhancement: {empty_before:,}")
                
                if empty_before + stats['enhanced'] > 0:
                    improvement_rate = (stats['enhanced'] / (empty_before + stats['enhanced']) * 100)
                    print(f"   • Improvement rate: {improvement_rate:.1f}%")
        
        except ImportError:
            print("   (pandas not available for detailed analysis)")
        except Exception as e:
            print(f"   Error during analysis: {str(e)}")
        
        print(f"\n🎉 Enhancement complete! Check the file: {result_file}")
        print("\nThe enhanced CSV now includes:")
        print("   • MAB rejection reasons for tickers not selected by the algorithm")
        print("   • Historical success/failure statistics for each ticker")
        print("   • Exclusion reasons for tickers blocked from trading")
        print("   • Enhanced technical analysis context")
        
    except Exception as e:
        print(f"❌ Error during CSV export: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())