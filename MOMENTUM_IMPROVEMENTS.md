# Momentum Trading Indicator - PFSA Loss Fix

## Summary

Fixed the PFSA trade loss (-5.7%, -$113.84) by adding three key validations to prevent entering trades after momentum has peaked or when reversals are occurring.

## PFSA Trade Analysis

**Trade Details:**
- Entry: $0.13 at 13:28:13
- Exit: $0.1226 at 13:37:12 (~9 minutes)
- Loss: -$113.84 (-5.7%)
- Exit Reason: Stop loss triggered at -5.54%

**Root Causes:**
1. **Entered after momentum peaked**: The stock peaked at $0.16 earlier in the day (before 10:00), but entry happened at $0.13 (19% below peak)
2. **Entry price above recent_avg**: Entry at $0.13 was 8.3% above the recent_avg of $0.12, indicating momentum had already peaked
3. **Ultra-low price stock**: At $0.13, this is an ultra-low penny stock with wide spreads and high volatility
4. **Late entry**: Entry at 1:28 PM happened after the major momentum had already reversed

## Implemented Fixes

### 1. Recent Average Peak Validation ✅

**Problem**: Entry price was 8.3% above recent_avg (which represents the momentum peak).

**Solution**: Added validation to reject entries if the entry price is too far above the recent_avg from the momentum calculation.

**Implementation**:
- Added `_extract_recent_avg_from_reason()` method to parse recent_avg from the momentum reason string
- Added validation in `_process_ticker_entry()` that checks if `(entry_price - recent_avg) / recent_avg > threshold`
- Stricter threshold (3.0%) for ultra-low price stocks (< $0.20), standard threshold (5.0%) for others
- For PFSA: Would have rejected entry (8.3% > 3.0% threshold for $0.13 stock)

**Location**: `app/src/services/trading/momentum_indicator.py` lines 1417-1432 and 1635-1646

### 2. Immediate Momentum Check ✅

**Problem**: Momentum calculation and entry execution happen at different times, allowing reversals to occur in between.

**Solution**: Added a final check using the most recent 2-3 bars to verify momentum is still valid right before entry.

**Implementation**:
- Added `_check_immediate_momentum_for_entry()` method that analyzes the last 2-3 bars
- For longs: Checks if recent bars show upward movement (not strong downward reversal)
- For shorts: Checks if recent bars show downward movement (not strong upward reversal)
- Fetches bars data using `AlpacaClient.get_market_data()` right before entry
- If recent bars show reversal pattern, entry is rejected

**Location**: `app/src/services/trading/momentum_indicator.py` lines 1434-1490 and 1648-1659

### 3. Stricter Validation for Ultra-Low Price Stocks ✅

**Problem**: Ultra-low price stocks (< $0.20) have wider spreads, higher volatility, and are more prone to manipulation.

**Solution**: Added stricter validation specifically for ultra-low price stocks.

**Implementation**:
- Tighter spread threshold: 2.0% max spread for stocks < $0.20 (vs 3.0% default)
- Stricter recent_avg validation: 3.0% max above recent_avg (vs 5.0% for regular stocks)
- PFSA at $0.13 would have been subject to these stricter rules

**Location**: `app/src/services/trading/momentum_indicator.py` lines 1661-1671

## How These Fixes Would Have Prevented the PFSA Loss

### Recent Average Peak Validation
- **PFSA**: Entry at $0.13 was 8.3% above recent_avg of $0.12
- **Threshold**: 3.0% max for stocks < $0.20
- **Result**: Trade would have been **rejected** (8.3% > 3.0%)

### Immediate Momentum Check
- Would have analyzed the most recent 2-3 bars right before entry
- If bars showed downward reversal (which they likely did given the price decline), entry would be rejected

### Ultra-Low Price Stock Validation
- Stricter spread check (2.0% vs 3.0%)
- Combined with recent_avg validation, provides additional protection

## Configuration Parameters

Key parameters that can be tuned:

1. **Recent Average Threshold**: 
   - Ultra-low stocks (< $0.20): 3.0% max above recent_avg
   - Regular stocks: 5.0% max above recent_avg
   - Location: `max_price_above_recent_avg` in `_process_ticker_entry()`

2. **Ultra-Low Price Spread Threshold**: 2.0% max spread
   - Location: `ultra_low_price_max_spread = 2.0` in `_process_ticker_entry()`

3. **Immediate Momentum Check**: Uses last 2-3 bars
   - Location: `_check_immediate_momentum_for_entry()` method
   - Logic is conservative - requires clear reversal to reject

## Testing Recommendations

1. **Monitor rejection logs** to see how often these new validations trigger
2. **Track false rejections** - cases where entry was rejected but price continued favorably
3. **Compare win rates** before and after these changes
4. **Backtest on historical data** including the PFSA trade to verify it would have been rejected
5. **Monitor ultra-low price stock performance** to ensure the stricter rules don't block too many valid trades

## Files Modified

- `app/src/services/trading/momentum_indicator.py`:
  - Added `_extract_recent_avg_from_reason()` method (lines 1417-1432)
  - Added `_check_immediate_momentum_for_entry()` method (lines 1434-1490)
  - Added recent_avg peak validation in `_process_ticker_entry()` (lines 1635-1646)
  - Added immediate momentum check in `_process_ticker_entry()` (lines 1648-1659)
  - Added ultra-low price stock validation in `_process_ticker_entry()` (lines 1661-1671)

## Comparison with Penny Stocks Fix

These improvements are similar to the fixes applied to the Penny Stocks indicator:
- **Peak Price Validation**: Similar concept, but uses `recent_avg` instead of explicit peak price
- **Immediate Momentum Check**: Same logic, adapted for momentum indicator's bar format
- **Ultra-Low Price Protection**: Additional layer specific to very low-priced stocks

The momentum indicator fix is particularly important because:
- Momentum calculation uses historical averages (early_avg vs recent_avg)
- There's more latency between calculation and entry
- Ultra-low price stocks in momentum trading need extra protection

