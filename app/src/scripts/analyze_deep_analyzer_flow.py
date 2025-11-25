"""
Analyze DeepAnalyzerIndicator flow after tickers are fetched
Focuses on why no trades are entered despite having tickers
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, Any, List
import pytz

from app.src.common.loguru_logger import logger
from app.src.services.trading.deep_analyzer_indicator import DeepAnalyzerIndicator
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.mcp.mcp_client import MCPClient


async def analyze_flow():
    """Analyze the DeepAnalyzerIndicator flow to find where trades are being blocked"""
    
    print("=" * 80)
    print("DeepAnalyzerIndicator Flow Analysis")
    print("=" * 80)
    print()
    
    # Configure services
    DeepAnalyzerIndicator.configure()
    DynamoDBClient.configure()
    MCPClient.configure()
    
    # 1. Get screened tickers
    print("1. Screened Tickers")
    print("-" * 80)
    all_tickers = await DeepAnalyzerIndicator._get_screened_tickers()
    print(f"   Total screened tickers: {len(all_tickers)}")
    if not all_tickers:
        print("   ⚠️  No tickers - stopping analysis")
        return
    
    # 2. Filter out active and cooldown tickers
    print("\n2. Filtering Active/Cooldown Tickers")
    print("-" * 80)
    active_trades = await DeepAnalyzerIndicator._get_active_trades()
    active_ticker_set = await DeepAnalyzerIndicator._get_active_ticker_set()
    active_count = len(active_trades)
    print(f"   Active trades: {active_count}/{DeepAnalyzerIndicator.max_active_trades}")
    
    candidates_to_fetch = [
        ticker
        for ticker in all_tickers
        if ticker not in active_ticker_set
        and not DeepAnalyzerIndicator._is_ticker_in_cooldown(ticker)
    ]
    
    cooldown_count = sum(1 for ticker in all_tickers if DeepAnalyzerIndicator._is_ticker_in_cooldown(ticker))
    print(f"   Tickers in cooldown: {cooldown_count}")
    print(f"   Candidates after filtering: {len(candidates_to_fetch)}")
    
    if not candidates_to_fetch:
        print("   ⚠️  No candidates after filtering - all tickers are active or in cooldown")
        return
    
    # 3. Fetch market data for a sample
    print("\n3. Market Data Fetch Test (First 5 Candidates)")
    print("-" * 80)
    sample_tickers = candidates_to_fetch[:5]
    market_data_dict = await DeepAnalyzerIndicator._fetch_market_data_batch(
        sample_tickers, max_concurrent=5
    )
    
    market_data_count = sum(1 for v in market_data_dict.values() if v is not None)
    print(f"   Successfully fetched market data: {market_data_count}/{len(sample_tickers)}")
    
    # 4. Evaluate sample tickers for entry
    print("\n4. Entry Evaluation Test (Sample Tickers)")
    print("-" * 80)
    
    from app.src.services.market_data.market_data_service import MarketDataService
    
    evaluation_results = []
    
    for ticker in sample_tickers:
        market_data = market_data_dict.get(ticker)
        if not market_data:
            print(f"   {ticker}: ⚠️  No market data")
            continue
        
        # Evaluate for entry
        action, signal_data, reason, detailed_results = await DeepAnalyzerIndicator._evaluate_ticker_for_entry(
            ticker, market_data
        )
        
        if action and signal_data:
            entry_score = signal_data.get("entry_score", 0.0)
            is_golden = signal_data.get("is_golden", False)
            passed_threshold = entry_score >= DeepAnalyzerIndicator.min_entry_score
            
            evaluation_results.append({
                "ticker": ticker,
                "action": action,
                "entry_score": entry_score,
                "passed_threshold": passed_threshold,
                "is_golden": is_golden,
                "reason": reason,
            })
            
            status = "✅ PASSED" if passed_threshold else f"❌ Score {entry_score:.2f} < {DeepAnalyzerIndicator.min_entry_score}"
            golden_marker = " 🟡 GOLDEN" if is_golden else ""
            print(f"   {ticker}: {status}{golden_marker} - {action} (score: {entry_score:.2f})")
        else:
            # Get detailed reasons
            long_reason = "N/A"
            short_reason = "N/A"
            
            if detailed_results:
                long_result = detailed_results.get("long_result", {})
                short_result = detailed_results.get("short_result", {})
                
                long_enter = long_result.get("enter", False)
                short_enter = short_result.get("enter", False)
                
                if not long_enter:
                    long_reason = long_result.get("message", "No entry signal")
                if not short_enter:
                    short_reason = short_result.get("message", "No entry signal")
            
            evaluation_results.append({
                "ticker": ticker,
                "action": None,
                "entry_score": 0.0,
                "passed_threshold": False,
                "is_golden": False,
                "reason": reason,
                "long_reason": long_reason,
                "short_reason": short_reason,
            })
            
            print(f"   {ticker}: ❌ No entry signal")
            print(f"      Long: {long_reason}")
            print(f"      Short: {short_reason}")
    
    # 5. Analyze results
    print("\n5. Analysis Summary")
    print("-" * 80)
    
    passed_count = sum(1 for r in evaluation_results if r.get("passed_threshold", False))
    no_signal_count = sum(1 for r in evaluation_results if not r.get("action"))
    low_score_count = sum(1 for r in evaluation_results if r.get("action") and not r.get("passed_threshold"))
    
    print(f"   Sample Results (from {len(sample_tickers)} tickers):")
    print(f"      ✅ Passed threshold: {passed_count}")
    print(f"      ❌ No entry signal: {no_signal_count}")
    print(f"      ⚠️  Low entry score: {low_score_count}")
    
    # 6. Check daily limit
    print("\n6. Daily Trade Limit Check")
    print("-" * 80)
    today = date.today().isoformat()
    completed_trades = await DynamoDBClient.get_completed_trade_count(
        date=today, indicator=DeepAnalyzerIndicator.indicator_name()
    )
    daily_limit_reached = completed_trades >= DeepAnalyzerIndicator.max_daily_trades
    print(f"   Completed trades today: {completed_trades}/{DeepAnalyzerIndicator.max_daily_trades}")
    if daily_limit_reached:
        print("   ⚠️  Daily limit reached (only golden tickers can bypass)")
    
    # 7. Check MAB selection
    print("\n7. MAB Selection Test")
    print("-" * 80)
    
    # Get all candidates that passed
    all_candidates = []
    for ticker in candidates_to_fetch[:20]:  # Test with first 20
        market_data = await MCPClient.get_market_data(ticker)
        if not market_data:
            continue
        
        action, signal_data, reason, _ = await DeepAnalyzerIndicator._evaluate_ticker_for_entry(
            ticker, market_data
        )
        
        if action and signal_data:
            entry_score = signal_data.get("entry_score", 0.0)
            if entry_score >= DeepAnalyzerIndicator.min_entry_score:
                all_candidates.append((ticker, entry_score, reason))
    
    print(f"   Candidates passing threshold: {len(all_candidates)}")
    
    if all_candidates:
        # Separate long and short
        long_candidates = [(t, s, r) for t, s, r in all_candidates if "Long" in r or "buy" in r.lower()]
        short_candidates = [(t, s, r) for t, s, r in all_candidates if "Short" in r or "sell" in r.lower()]
        
        print(f"   Long candidates: {len(long_candidates)}")
        print(f"   Short candidates: {len(short_candidates)}")
        
        # Test MAB selection
        from app.src.services.mab.mab_service import MABService
        
        if long_candidates:
            long_mab_candidates = [(t, s, r) for t, s, r in long_candidates]
            # Get market data dict for MAB
            long_tickers = [t for t, _, _ in long_mab_candidates]
            long_market_data = await DeepAnalyzerIndicator._fetch_market_data_batch(long_tickers, max_concurrent=10)
            
            top_long = await MABService.select_tickers_with_mab(
                DeepAnalyzerIndicator.indicator_name(),
                ticker_candidates=long_mab_candidates,
                market_data_dict=long_market_data,
                top_k=DeepAnalyzerIndicator.top_k,
            )
            print(f"   MAB selected {len(top_long)} long tickers (top_k={DeepAnalyzerIndicator.top_k})")
            if top_long:
                for rank, (ticker, score, _) in enumerate(top_long, 1):
                    print(f"      {rank}. {ticker} (score: {score:.2f})")
        
        if short_candidates:
            short_mab_candidates = [(t, s, r) for t, s, r in short_candidates]
            short_tickers = [t for t, _, _ in short_mab_candidates]
            short_market_data = await DeepAnalyzerIndicator._fetch_market_data_batch(short_tickers, max_concurrent=10)
            
            top_short = await MABService.select_tickers_with_mab(
                DeepAnalyzerIndicator.indicator_name(),
                ticker_candidates=short_mab_candidates,
                market_data_dict=short_market_data,
                top_k=DeepAnalyzerIndicator.top_k,
            )
            print(f"   MAB selected {len(top_short)} short tickers (top_k={DeepAnalyzerIndicator.top_k})")
            if top_short:
                for rank, (ticker, score, _) in enumerate(top_short, 1):
                    print(f"      {rank}. {ticker} (score: {score:.2f})")
    else:
        print("   ⚠️  No candidates passed threshold - MAB has nothing to select from")
    
    # 8. Final Summary
    print("\n" + "=" * 80)
    print("Root Cause Analysis")
    print("=" * 80)
    
    issues = []
    
    if not candidates_to_fetch:
        issues.append("All tickers are active or in cooldown")
    elif market_data_count == 0:
        issues.append("Failed to fetch market data for all tickers")
    elif no_signal_count == len(evaluation_results):
        issues.append("MarketDataService not returning entry signals (all enter=False)")
    elif low_score_count > 0 and passed_count == 0:
        issues.append(f"All entry scores below minimum threshold ({DeepAnalyzerIndicator.min_entry_score})")
    elif passed_count > 0 and len(all_candidates) == 0:
        issues.append("Candidates passing threshold but not being selected")
    elif len(all_candidates) > 0 and (len(long_candidates) == 0 and len(short_candidates) == 0):
        issues.append("MAB not selecting any tickers despite candidates")
    elif daily_limit_reached and passed_count > 0:
        issues.append("Daily limit reached - need golden tickers to bypass")
    
    if issues:
        print("Identified issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("No obvious blocking issues found in sample.")
        print("Recommendation: Check full logs for 'Evaluated X tickers' and 'MAB selected' messages")
        print("to see the actual numbers during trading hours.")
    
    print()


if __name__ == "__main__":
    asyncio.run(analyze_flow())

