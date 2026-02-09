#!/usr/bin/env python3
"""
Profit and Loss Analysis for Backtest Results

This script analyzes the CSV output from the backtesting script to calculate
profit and loss for each indicator, assuming simple entry/exit strategies.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import argparse


class BacktestAnalyzer:
    """Analyze backtest results to calculate P&L for indicators"""
    
    def __init__(self, csv_file: str):
        """Initialize analyzer with backtest CSV file"""
        self.df = pd.read_csv(csv_file)
        self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
        self.df = self.df.sort_values('timestamp')
        
    def calculate_simple_pnl(self, hold_minutes: int = 30) -> pd.DataFrame:
        """
        Calculate simple P&L assuming fixed holding period
        
        Args:
            hold_minutes: Minutes to hold each position before exit
            
        Returns:
            DataFrame with P&L calculations added
        """
        results = []
        
        for _, row in self.df.iterrows():
            entry_time = row['timestamp']
            entry_price = row['price']
            action = row['action']
            ticker = row['ticker']
            indicator = row['indicator']
            
            # Find exit price after holding period
            exit_time = entry_time + timedelta(minutes=hold_minutes)
            
            # Get future price at exit time
            future_data = self.df[
                (self.df['ticker'] == ticker) & 
                (self.df['timestamp'] >= exit_time)
            ]
            
            if future_data.empty:
                # If no future data, use last available price
                exit_price = entry_price
                exit_reason = "No future data"
            else:
                exit_price = future_data.iloc[0]['price']
                exit_reason = f"Exit after {hold_minutes} minutes"
            
            # Calculate P&L
            if action == 'buy_to_open':
                # Long position: profit if price goes up
                pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                pnl_amount = (exit_price - entry_price) * 100  # Assume 100 shares
            else:  # sell_to_open
                # Short position: profit if price goes down
                pnl_percent = ((entry_price - exit_price) / entry_price) * 100
                pnl_amount = (entry_price - exit_price) * 100  # Assume 100 shares
            
            result_row = row.copy()
            result_row['exit_time'] = exit_time
            result_row['exit_price'] = exit_price
            result_row['exit_reason'] = exit_reason
            result_row['hold_minutes'] = hold_minutes
            result_row['pnl_percent'] = pnl_percent
            result_row['pnl_amount'] = pnl_amount
            
            results.append(result_row)
        
        return pd.DataFrame(results)
    
    def calculate_indicator_summary(self, results_df: pd.DataFrame) -> Dict:
        """Calculate summary statistics for each indicator"""
        summary = {}
        
        for indicator in results_df['indicator'].unique():
            indicator_data = results_df[results_df['indicator'] == indicator]
            
            total_trades = len(indicator_data)
            profitable_trades = len(indicator_data[indicator_data['pnl_percent'] > 0])
            losing_trades = len(indicator_data[indicator_data['pnl_percent'] < 0])
            
            win_rate = (profitable_trades / total_trades) * 100 if total_trades > 0 else 0
            
            avg_pnl = indicator_data['pnl_percent'].mean()
            avg_win = indicator_data[indicator_data['pnl_percent'] > 0]['pnl_percent'].mean() if profitable_trades > 0 else 0
            avg_loss = indicator_data[indicator_data['pnl_percent'] < 0]['pnl_percent'].mean() if losing_trades > 0 else 0
            
            total_pnl = indicator_data['pnl_percent'].sum()
            max_win = indicator_data['pnl_percent'].max()
            max_loss = indicator_data['pnl_percent'].min()
            
            # Separate long and short performance
            long_trades = indicator_data[indicator_data['action'] == 'buy_to_open']
            short_trades = indicator_data[indicator_data['action'] == 'sell_to_open']
            
            long_avg_pnl = long_trades['pnl_percent'].mean() if len(long_trades) > 0 else 0
            short_avg_pnl = short_trades['pnl_percent'].mean() if len(short_trades) > 0 else 0
            
            summary[indicator] = {
                'total_trades': total_trades,
                'profitable_trades': profitable_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'avg_pnl_percent': avg_pnl,
                'avg_win_percent': avg_win,
                'avg_loss_percent': avg_loss,
                'total_pnl_percent': total_pnl,
                'max_win_percent': max_win,
                'max_loss_percent': max_loss,
                'long_avg_pnl_percent': long_avg_pnl,
                'short_avg_pnl_percent': short_avg_pnl,
                'long_trades': len(long_trades),
                'short_trades': len(short_trades)
            }
        
        return summary
    
    def calculate_time_based_pnl(self, hold_periods: List[int] = [5, 15, 30, 60, 120]) -> Dict:
        """Calculate P&L for different holding periods"""
        time_analysis = {}
        
        for hold_minutes in hold_periods:
            results_df = self.calculate_simple_pnl(hold_minutes)
            summary = self.calculate_indicator_summary(results_df)
            
            time_analysis[f'{hold_minutes}_min'] = summary
        
        return time_analysis
    
    def print_summary(self, summary: Dict, title: str = "Indicator Performance Summary"):
        """Print formatted summary"""
        print(f"\n{title}")
        print("=" * 80)
        
        for indicator, stats in summary.items():
            print(f"\n{indicator}:")
            print(f"  Total Trades: {stats['total_trades']}")
            print(f"  Win Rate: {stats['win_rate']:.2f}%")
            print(f"  Avg P&L: {stats['avg_pnl_percent']:.3f}%")
            print(f"  Total P&L: {stats['total_pnl_percent']:.2f}%")
            print(f"  Avg Win: {stats['avg_win_percent']:.3f}%")
            print(f"  Avg Loss: {stats['avg_loss_percent']:.3f}%")
            print(f"  Max Win: {stats['max_win_percent']:.3f}%")
            print(f"  Max Loss: {stats['max_loss_percent']:.3f}%")
            print(f"  Long Trades: {stats['long_trades']} (Avg: {stats['long_avg_pnl_percent']:.3f}%)")
            print(f"  Short Trades: {stats['short_trades']} (Avg: {stats['short_avg_pnl_percent']:.3f}%)")
    
    def print_time_analysis(self, time_analysis: Dict):
        """Print time-based analysis comparison"""
        print(f"\nTime-Based Holding Period Analysis")
        print("=" * 80)
        
        # Create comparison table
        periods = list(time_analysis.keys())
        indicators = list(time_analysis[periods[0]].keys())
        
        print(f"{'Indicator':<12} ", end="")
        for period in periods:
            print(f"{period.replace('_min', 'min'):<12} ", end="")
        print()
        
        print("-" * (12 + len(periods) * 13))
        
        for indicator in indicators:
            print(f"{indicator:<12} ", end="")
            for period in periods:
                stats = time_analysis[period][indicator]
                avg_pnl = stats['avg_pnl_percent']
                win_rate = stats['win_rate']
                print(f"{avg_pnl:+.2f}% ({win_rate:.0f}%) ", end="")
            print()
    
    def save_detailed_results(self, results_df: pd.DataFrame, filename: str):
        """Save detailed results with P&L calculations"""
        results_df.to_csv(filename, index=False)
        print(f"\nDetailed results saved to {filename}")


def main():
    """Main function to analyze backtest results"""
    parser = argparse.ArgumentParser(description='Analyze P&L from backtest results')
    parser.add_argument('csv_file', help='Backtest results CSV file')
    parser.add_argument('--hold-minutes', type=int, default=30, 
                       help='Holding period in minutes (default: 30)')
    parser.add_argument('--time-analysis', action='store_true',
                       help='Run analysis for multiple holding periods')
    parser.add_argument('--output', type=str, 
                       help='Output file for detailed results')
    
    args = parser.parse_args()
    
    try:
        # Initialize analyzer
        analyzer = BacktestAnalyzer(args.csv_file)
        
        print(f"Analyzing backtest results from {args.csv_file}")
        print(f"Total signals: {len(analyzer.df)}")
        
        # Basic analysis
        results_df = analyzer.calculate_simple_pnl(args.hold_minutes)
        summary = analyzer.calculate_indicator_summary(results_df)
        
        analyzer.print_summary(summary, f"Indicator Performance ({args.hold_minutes} minutes hold)")
        
        # Time-based analysis if requested
        if args.time_analysis:
            time_analysis = analyzer.calculate_time_based_pnl()
            analyzer.print_time_analysis(time_analysis)
        
        # Save detailed results if requested
        if args.output:
            analyzer.save_detailed_results(results_df, args.output)
        
        # Overall summary
        print(f"\nOverall Summary ({args.hold_minutes} minutes hold):")
        print("=" * 50)
        total_trades = len(results_df)
        total_profitable = len(results_df[results_df['pnl_percent'] > 0])
        overall_win_rate = (total_profitable / total_trades) * 100
        overall_avg_pnl = results_df['pnl_percent'].mean()
        
        print(f"Total Trades: {total_trades}")
        print(f"Overall Win Rate: {overall_win_rate:.2f}%")
        print(f"Overall Average P&L: {overall_avg_pnl:.3f}%")
        
        # Best and worst performers
        best_indicator = max(summary.items(), key=lambda x: x[1]['avg_pnl_percent'])
        worst_indicator = min(summary.items(), key=lambda x: x[1]['avg_pnl_percent'])
        
        print(f"\nBest Indicator: {best_indicator[0]} (Avg: {best_indicator[1]['avg_pnl_percent']:.3f}%)")
        print(f"Worst Indicator: {worst_indicator[0]} (Avg: {worst_indicator[1]['avg_pnl_percent']:.3f}%)")
        
    except Exception as e:
        print(f"Error analyzing results: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
