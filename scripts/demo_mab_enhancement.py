#!/usr/bin/env python3
"""
Demo script showing MAB rejection enhancement capabilities.

This script demonstrates how the MAB rejection enhancer works by:
1. Showing sample rejection reasons for different scenarios
2. Demonstrating real-time enhancement
3. Showing before/after comparisons
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.src.services.mab.mab_rejection_enhancer import MABRejectionEnhancer


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'-'*40}")
    print(f"  {title}")
    print(f"{'-'*40}")


async def demo_mab_rejection_reasons():
    """Demonstrate different types of MAB rejection reasons."""
    print_header("MAB Rejection Enhancement Demo")
    
    enhancer = MABRejectionEnhancer()
    
    # Demo 1: Ticker with poor historical performance
    print_section("Demo 1: Ticker with Poor Historical Performance")
    
    # Simulate MAB stats for a poorly performing ticker
    poor_stats = {
        'successes': 1,
        'failures': 9,
        'total_trades': 10,
        'excluded_until': None
    }
    
    poor_reason = enhancer.mab_service.get_rejection_reason(poor_stats, 'POOR')
    print(f"Ticker: POOR")
    print(f"Historical Performance: 1 success, 9 failures (10% success rate)")
    print(f"MAB Rejection Reason:")
    print(f"  {poor_reason}")
    
    # Demo 2: Excluded ticker
    print_section("Demo 2: Temporarily Excluded Ticker")
    
    from datetime import datetime, timezone, timedelta
    excluded_until = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    
    excluded_stats = {
        'successes': 0,
        'failures': 3,
        'total_trades': 3,
        'excluded_until': excluded_until
    }
    
    excluded_reason = enhancer.mab_service.get_rejection_reason(excluded_stats, 'EXCL')
    print(f"Ticker: EXCL")
    print(f"Status: Temporarily excluded due to recent losses")
    print(f"Excluded until: {excluded_until}")
    print(f"MAB Rejection Reason:")
    print(f"  {excluded_reason}")
    
    # Demo 3: New ticker (no history)
    print_section("Demo 3: New Ticker (No Trading History)")
    
    new_reason = enhancer.mab_service.get_rejection_reason(None, 'NEWT')
    print(f"Ticker: NEWT")
    print(f"Status: New ticker with no trading history")
    print(f"MAB Rejection Reason:")
    print(f"  {new_reason}")
    
    # Demo 4: Generic rejection reasons
    print_section("Demo 4: Generic Rejection Reasons (No MAB Data)")
    
    # Low momentum
    low_momentum_record = {
        'ticker': 'LOWM',
        'technical_indicators': {'momentum_score': 0.8}
    }
    low_momentum_reason = enhancer._create_generic_rejection_reason(low_momentum_record)
    print(f"Ticker: LOWM")
    print(f"Momentum: 0.8% (below 1.5% threshold)")
    print(f"Generic Rejection Reason:")
    print(f"  Long: {low_momentum_reason['reason_long']}")
    
    # High momentum (likely MAB rejection)
    high_momentum_record = {
        'ticker': 'HIGHM',
        'technical_indicators': {'momentum_score': 5.2}
    }
    high_momentum_reason = enhancer._create_generic_rejection_reason(high_momentum_record)
    print(f"\nTicker: HIGHM")
    print(f"Momentum: 5.2% (above threshold, likely MAB rejection)")
    print(f"Generic Rejection Reason:")
    print(f"  Long: {high_momentum_reason['reason_long']}")
    
    # No momentum data
    no_data_record = {
        'ticker': 'NODATA',
        'technical_indicators': {}
    }
    no_data_reason = enhancer._create_generic_rejection_reason(no_data_record)
    print(f"\nTicker: NODATA")
    print(f"Momentum: No data available")
    print(f"Generic Rejection Reason:")
    print(f"  Long: {no_data_reason['reason_long']}")


async def demo_real_time_enhancement():
    """Demonstrate real-time enhancement functionality."""
    print_section("Demo 5: Real-Time Enhancement")
    
    print("Simulating real-time rejection reason generation...")
    
    # Simulate different scenarios
    scenarios = [
        {
            'ticker': 'AAPL',
            'technical_indicators': {'momentum_score': 2.5, 'volume': 1000000},
            'description': 'Large cap with moderate momentum'
        },
        {
            'ticker': 'PENNY',
            'technical_indicators': {'momentum_score': 0.9, 'volume': 50000},
            'description': 'Penny stock with low momentum'
        },
        {
            'ticker': 'VOLATILE',
            'technical_indicators': {'momentum_score': 8.5, 'volume': 2000000},
            'description': 'High momentum stock (likely MAB rejection)'
        }
    ]
    
    for scenario in scenarios:
        print(f"\nScenario: {scenario['description']}")
        print(f"Ticker: {scenario['ticker']}")
        print(f"Technical Indicators: {scenario['technical_indicators']}")
        
        # Generate real-time rejection reasons
        reasons = await MABRejectionEnhancer.enhance_real_time_record(
            ticker=scenario['ticker'],
            indicator='Penny Stocks',
            technical_indicators=scenario['technical_indicators']
        )
        
        print(f"Generated Rejection Reasons:")
        if reasons['reason_long']:
            print(f"  Long: {reasons['reason_long']}")
        if reasons['reason_short']:
            print(f"  Short: {reasons['reason_short']}")
        if not reasons['reason_long'] and not reasons['reason_short']:
            print(f"  No rejection reasons generated (would be selected)")


def demo_csv_format():
    """Show the enhanced CSV format."""
    print_section("Demo 6: Enhanced CSV Format")
    
    print("Before Enhancement (empty rejection reasons):")
    print("ticker,indicator,reason_not_to_enter_long,reason_not_to_enter_short,technical_indicators,timestamp")
    print('AAPL,Penny Stocks,"","","{""close_price"": 150.0, ""volume"": 1000}",2024-12-10T10:30:00-05:00')
    print('GOOGL,Penny Stocks,"","","{""close_price"": 2800.0, ""volume"": 500}",2024-12-10T10:31:00-05:00')
    
    print("\nAfter Enhancement (populated rejection reasons):")
    print("ticker,indicator,reason_not_to_enter_long,reason_not_to_enter_short,technical_indicators,timestamp")
    print('AAPL,Penny Stocks,"MAB rejected: Low success rate (30.0%) (successes: 3, failures: 7, total: 10)","","{""close_price"": 150.0, ""volume"": 1000}",2024-12-10T10:30:00-05:00')
    print('GOOGL,Penny Stocks,"","MAB rejected: Excluded until 2024-12-10T15:30:00-05:00 (successes: 0, failures: 2, total: 2)","{""close_price"": 2800.0, ""volume"": 500}",2024-12-10T10:31:00-05:00')


def show_usage_examples():
    """Show usage examples."""
    print_section("Usage Examples")
    
    print("1. Quick Enhancement (Recommended):")
    print("   python scripts/run_mab_enhancement.py")
    
    print("\n2. Enhance Existing Records:")
    print("   python scripts/enhance_mab_rejections.py --enhance")
    
    print("\n3. Export Enhanced CSV:")
    print("   python scripts/enhance_mab_rejections.py --export")
    
    print("\n4. Both Enhance and Export:")
    print("   python scripts/enhance_mab_rejections.py --enhance --export")
    
    print("\n5. Programmatic Usage:")
    print("""
   from app.src.services.mab.mab_rejection_enhancer import MABRejectionEnhancer
   
   enhancer = MABRejectionEnhancer()
   
   # Enhance existing records
   stats = await enhancer.enhance_empty_rejection_records(
       indicator="Penny Stocks",
       hours_lookback=24
   )
   
   # Generate CSV export
   csv_file = await enhancer.generate_enhanced_csv_export(
       indicator="Penny Stocks",
       output_file="enhanced_data.csv"
   )
    """)


async def main():
    """Run the demo."""
    try:
        await demo_mab_rejection_reasons()
        await demo_real_time_enhancement()
        demo_csv_format()
        show_usage_examples()
        
        print_header("Demo Complete!")
        print("\nKey Benefits of MAB Rejection Enhancement:")
        print("  ✅ Complete rejection reason coverage")
        print("  ✅ MAB algorithm transparency")
        print("  ✅ Better debugging and analysis")
        print("  ✅ Improved audit trails")
        print("  ✅ Enhanced reporting capabilities")
        
        print(f"\nNext Steps:")
        print(f"  1. Run: python scripts/run_mab_enhancement.py")
        print(f"  2. Check the generated CSV file")
        print(f"  3. Analyze the enhanced rejection reasons")
        print(f"  4. Set up regular enhancement schedule")
        
    except Exception as e:
        print(f"❌ Demo failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())