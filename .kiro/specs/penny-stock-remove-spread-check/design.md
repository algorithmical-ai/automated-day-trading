# Design Document

## Overview

The Penny Stock Spread Check Removal system simplifies the validation logic for penny stock momentum trading by eliminating bid-ask spread validation. The current system uses a validation pipeline that includes liquidity checks through bid-ask spread analysis, which can be overly restrictive for fast-moving momentum trades. This design removes the LiquidityRule from the validation pipeline while maintaining all other validation rules (data quality, trend direction, continuation, price extremes, and momentum thresholds).

The key change is the removal of spread-based rejections, allowing the system to capture momentum opportunities regardless of liquidity conditions. This aligns with the momentum trading strategy where quick entries and exits are prioritized over liquidity concerns.

## Architecture

### High-Level Architecture

```
┌─────────────────┐
│  Entry Cycle    │
│   Controller    │
└────────┬────────┘
         │
         ├──> Fetch Market Data (Parallel Batches)
         │
         ├──> Calculate Trend Metrics
         │    ├─> Momentum Score
         │    ├─> Continuation Score
         │    ├─> Peak/Bottom Prices
         │    └─> Reason String
         │
         ├──> Apply Validation Rules (Sequential)
         │    ├─> DataQualityRule ✓
         │    ├─> TrendDirectionRule ✓
         │    ├─> ContinuationRule ✓
         │    ├─> PriceExtremeRule ✓
         │    ├─> MomentumThresholdRule ✓
         │    └─> LiquidityRule ✗ (REMOVED)
         │
         ├──> Collect All Evaluation Records
         │    (both passing and failing)
         │
         └──> Batch Write to DynamoDB
```

### Validation Flow Changes

**Before (with LiquidityRule)**:
1. Check data quality
2. Check liquidity (bid-ask spread) → **REJECT if spread > 2%**
3. Check trend direction
4. Check continuation
5. Check price extremes
6. Check momentum thresholds

**After (without LiquidityRule)**:
1. Check data quality
2. Check trend direction
3. Check continuation
4. Check price extremes
5. Check momentum thresholds

## Components and Interfaces

### Modified: PennyStocksIndicator._validate_ticker_with_pipeline

**Responsibility**: Validate ticker using the validation pipeline (without liquidity checks)

**Interface**:
```python
@classmethod
async def _validate_ticker_with_pipeline(
    cls,
    ticker: str,
    bars: List[Dict[str, Any]],
    quote_data: QuoteData,
    collector: RejectionCollector
) -> bool:
    """
    Validate ticker using the validation pipeline.
    
    Args:
        ticker: Stock ticker symbol
        bars: Historical price bars
        quote_data: Current quote data
        collector: RejectionCollector to accumulate rejections
        
    Returns:
        True if ticker passes all validation rules, False otherwise
    """
```

**Changes**:
- Remove LiquidityRule from the rules list
- Keep all other validation rules unchanged
- Maintain the same sequential validation flow with early termination

**Before**:
```python
rules = [
    DataQualityRule(required_bars=cls.recent_bars_for_trend),
    LiquidityRule(max_spread_percent=cls.max_bid_ask_spread_percent),  # REMOVED
    TrendDirectionRule(),
    ContinuationRule(min_continuation=0.7),
    PriceExtremeRule(extreme_threshold_percent=1.0),
    MomentumThresholdRule(
        min_momentum=cls.min_momentum_threshold,
        max_momentum=cls.max_momentum_threshold
    )
]
```

**After**:
```python
rules = [
    DataQualityRule(required_bars=cls.recent_bars_for_trend),
    # LiquidityRule removed - no longer checking bid-ask spread
    TrendDirectionRule(),
    ContinuationRule(min_continuation=0.7),
    PriceExtremeRule(extreme_threshold_percent=1.0),
    MomentumThresholdRule(
        min_momentum=cls.min_momentum_threshold,
        max_momentum=cls.max_momentum_threshold
    )
]
```

### Modified: PennyStocksIndicator._passes_filters

**Responsibility**: Check if ticker passes filters for entry (simplified without spread checks)

**Interface**:
```python
@classmethod
async def _passes_filters(
    cls,
    ticker: str,
    bars_data: Optional[Dict[str, Any]],
    momentum_score: float,
) -> Tuple[bool, str, Optional[str]]:
    """
    Check if ticker passes filters for entry.
    Returns (passes, reason, reason_for_direction)
    """
```

**Changes**:
- Remove bid-ask spread calculation
- Remove spread percentage comparison
- Remove spread-related rejection reasons
- Keep all other filter checks (price range, volume, price discrepancy)

**Code to Remove**:
```python
# Get current price from quote
quote_response = await AlpacaClient.quote(ticker)
if not quote_response:
    return False, "Unable to get quote", None

quote_data = quote_response.get("quote", {})
quotes = quote_data.get("quotes", {})
ticker_quote = quotes.get(ticker, {})

bid = ticker_quote.get("bp", 0.0)
ask = ticker_quote.get("ap", 0.0)

if bid <= 0 or ask <= 0:
    return False, f"Invalid bid/ask: bid={bid}, ask={ask}", None

# Use mid price
current_price = (bid + ask) / 2.0

# Check bid-ask spread  ← REMOVE THIS SECTION
spread = ask - bid
spread_percent = (spread / current_price) * 100 if current_price > 0 else 100
if spread_percent > cls.max_bid_ask_spread_percent:
    return (
        False,
        f"Bid-ask spread too wide: {spread_percent:.2f}% > {cls.max_bid_ask_spread_percent}%",
        None,
    )
```

### Modified: PennyStocksIndicator._process_ticker_entry

**Responsibility**: Process entry for a single ticker (without spread validation before entry)

**Interface**: Unchanged

**Changes**:
- Remove spread check before entry
- Keep entry price calculation (still uses bid/ask for entry price)
- Keep all other entry validation logic

**Code to Remove**:
```python
# Check bid-ask spread before entry  ← REMOVE THIS SECTION
mid_price = (bid + ask) / 2.0
spread = ask - bid
spread_percent = (spread / mid_price) * 100 if mid_price > 0 else 100
if spread_percent > cls.max_bid_ask_spread_percent:
    logger.warning(
        f"Skipping {ticker}: bid-ask spread too wide: {spread_percent:.2f}% > {cls.max_bid_ask_spread_percent}%"
    )
    return False
```

### Unchanged Components

The following components remain unchanged:

- **TrendAnalyzer**: Continues to calculate momentum, continuation, peak/bottom
- **RejectionCollector**: Continues to collect rejection records
- **InactiveTickerRepository**: Continues to batch write records to DynamoDB
- **Other ValidationRules**: DataQualityRule, TrendDirectionRule, ContinuationRule, PriceExtremeRule, MomentumThresholdRule all remain active

## Data Models

All data models remain unchanged:

### TrendMetrics

```python
@dataclass
class TrendMetrics:
    momentum_score: float
    continuation_score: float
    peak_price: float
    bottom_price: float
    reason: str
```

### QuoteData

```python
@dataclass
class QuoteData:
    ticker: str
    bid: float
    ask: float
    
    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2
    
    @property
    def spread_percent(self) -> float:
        return ((self.ask - self.bid) / self.mid_price) * 100
```

**Note**: QuoteData still has spread_percent property, but it's no longer used in validation.

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: bool
    reason_long: Optional[str] = None
    reason_short: Optional[str] = None
```

### EvaluationRecord

```python
@dataclass
class EvaluationRecord:
    ticker: str
    indicator: str
    reason_not_to_enter_long: str
    reason_not_to_enter_short: str
    technical_indicators: Dict[str, Any]
    timestamp: str
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Wide spread does not reject entries

*For any* ticker with bid-ask spread exceeding 2.0% and valid momentum, the ticker should pass validation if all other rules pass.

**Validates: Requirements 1.3, 2.3, 2.4**

### Property 2: Rejection reasons never mention spread

*For any* ticker that is rejected, the rejection reason should not contain the words "spread", "bid-ask", or "liquidity".

**Validates: Requirements 1.5, 4.4, 5.4**

### Property 3: Positive momentum allows long entry regardless of spread

*For any* ticker with positive momentum score and any bid-ask spread value, if all non-spread rules pass, then reason_not_to_enter_long should be empty.

**Validates: Requirements 2.3**

### Property 4: Negative momentum allows short entry regardless of spread

*For any* ticker with negative momentum score and any bid-ask spread value, if all non-spread rules pass, then reason_not_to_enter_short should be empty.

**Validates: Requirements 2.4**

### Property 5: Entry price calculation unchanged

*For any* quote with bid and ask prices, the entry price for long positions should equal ask price, and entry price for short positions should equal bid price.

**Validates: Requirements 1.4**

### Property 6: DataQualityRule still active

*For any* ticker with fewer than 5 bars, the ticker should be rejected with a reason mentioning "Insufficient bars".

**Validates: Requirements 3.1**

### Property 7: TrendDirectionRule still active

*For any* ticker with negative momentum, the ticker should be rejected for long entry with a reason mentioning "downward trend".

**Validates: Requirements 3.2**

### Property 8: ContinuationRule still active

*For any* ticker with continuation score below 0.7, the ticker should be rejected for the trend direction with a reason mentioning "not continuing strongly".

**Validates: Requirements 3.3**

### Property 9: PriceExtremeRule still active

*For any* ticker with current price within 1% of peak (for upward trends) or bottom (for downward trends), the ticker should be rejected with a reason mentioning "at/near peak" or "at/near bottom".

**Validates: Requirements 3.4**

### Property 10: MomentumThresholdRule still active

*For any* ticker with absolute momentum below 3.0% or above 10.0%, the ticker should be rejected with a reason mentioning "weak" or "excessive" trend.

**Validates: Requirements 3.5**

### Property 11: Evaluation records maintain structure

*For any* evaluation record written to the database, it should contain ticker, indicator, timestamp, reason_not_to_enter_long, reason_not_to_enter_short, and technical_indicators fields.

**Validates: Requirements 5.1, 5.2, 5.3**

### Property 12: Technical indicators unchanged

*For any* evaluation record, the technical_indicators JSON should contain momentum_score, continuation_score, peak_price, and bottom_price fields.

**Validates: Requirements 5.5**

### Property 13: Configuration parameter ignored

*For any* value of max_bid_ask_spread_percent configuration, the validation behavior should be identical (spread is not checked).

**Validates: Requirements 7.1**

### Property 14: Logs don't reference spread config

*For any* log message generated during validation, it should not reference max_bid_ask_spread_percent or spread-related configuration.

**Validates: Requirements 7.4**

## Error Handling

### Market Data Errors

Error handling remains unchanged:

- **No Response**: Log error, skip ticker for this cycle
- **Malformed Response**: Log error, skip ticker
- **Insufficient Bars**: Reject with DataQualityRule
- **Invalid Prices**: Filter out null/negative prices before calculation

### Quote Data Errors

**Changed behavior**:

- **Zero Bid or Ask**: Previously rejected both directions with "Invalid bid/ask prices"
  - **New**: Still need bid/ask for entry price calculation, but don't validate spread
  - **Action**: Continue to reject if bid/ask are invalid (needed for entry price)
- **Negative Bid or Ask**: Same as above
- **Bid > Ask**: Previously would calculate negative spread
  - **New**: No longer calculate or validate spread
  - **Action**: Allow entry if other rules pass

### Validation Errors

- **Rule Failure**: Log rejection reason, add to collector, continue to next ticker
- **Multiple Rule Failures**: Only first failure is recorded (early termination)
- **Database Write Failure**: Log error, continue to next cycle

### Edge Cases

- **Zero Momentum**: Handled by TrendDirectionRule (no rejection for either direction)
- **Extreme Spread Values**: No longer cause rejections
- **Missing Quote Data**: Still needed for entry price, reject if unavailable

## Testing Strategy

### Unit Testing

Unit tests will verify specific examples and edge cases:

- Validation pipeline without LiquidityRule
- Tickers with wide spreads passing validation
- Entry price calculation still using bid/ask
- Rejection reasons not containing spread-related text
- Configuration parameter being ignored
- All other validation rules still active

### Property-Based Testing

Property-based tests will verify universal properties across all inputs using the Hypothesis library for Python. Each test will run a minimum of 100 iterations with randomly generated inputs.

**Test Configuration**:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property
- Shrinking: Enabled to find minimal failing examples
- Seed: Random (logged on failure for reproducibility)

**Generator Strategies**:

1. **Spread Generator**: Generate bid-ask spreads with:
   - Narrow spreads (0.1%-1.9%)
   - Wide spreads (2.1%-10.0%)
   - Extreme spreads (10%+)
   - Edge cases (zero spread, negative spread)

2. **Momentum Generator**: Generate momentum scores:
   - Positive values (upward trends)
   - Negative values (downward trends)
   - Zero (no trend)
   - Values below/above thresholds

3. **Combined Generator**: Generate tickers with:
   - Various spread values
   - Various momentum values
   - Various continuation scores
   - Various price positions (peak/bottom/middle)

**Property Test Tagging**:
Each property-based test will include a comment tag:
```python
# Feature: penny-stock-remove-spread-check, Property N: [property description]
```

**Key Properties to Test**:

1. **Property 1**: Wide spread + valid momentum → passes validation
2. **Property 2**: Rejection reasons never contain "spread"
3. **Property 3**: Positive momentum + any spread → long entry allowed
4. **Property 4**: Negative momentum + any spread → short entry allowed
5. **Property 5**: Entry price = ask (long) or bid (short)
6. **Property 13**: Changing max_bid_ask_spread_percent doesn't affect validation

### Integration Testing

Integration tests will verify end-to-end flows:

- Full entry cycle with tickers having wide spreads
- Validation pipeline execution without LiquidityRule
- Database records not containing spread-related rejections
- Entry price calculation in actual trade entries
- Configuration changes not affecting behavior

### Regression Testing

Regression tests will ensure:

- All other validation rules still work correctly
- Database schema remains compatible
- Rejection record format unchanged
- Technical indicators structure unchanged
- MAB selection still works with new validation

## Performance Considerations

### Performance Improvements

1. **Fewer Validation Checks**: Removing LiquidityRule reduces validation time
2. **No Spread Calculation**: Eliminates spread percentage calculation in _passes_filters
3. **Faster Validation**: One less rule to evaluate per ticker

### Expected Impact

- **Validation Time**: ~10-15% faster per ticker (one less rule)
- **Entry Opportunities**: ~20-30% more tickers pass validation (no spread rejections)
- **Cycle Time**: Slightly faster due to fewer calculations

### Scalability

No changes to scalability characteristics:

- Still stateless and can run multiple instances
- Still uses async operations
- Still uses batch writes to DynamoDB
- Still processes tickers in parallel batches

## Deployment Considerations

### Configuration Changes

**No configuration changes required**:

- `max_bid_ask_spread_percent` parameter is ignored but doesn't need to be removed
- All other configuration parameters remain unchanged
- No environment variable changes needed

### Backward Compatibility

**Fully backward compatible**:

- Database schema unchanged
- Record format unchanged
- API interfaces unchanged
- Configuration file format unchanged

### Migration Strategy

**Zero-downtime deployment**:

1. Deploy new code with LiquidityRule removed
2. System immediately stops checking spread
3. More tickers pass validation
4. No database migrations needed
5. No configuration updates needed

### Monitoring

**Key metrics to monitor**:

- Validation pass rate (should increase)
- Rejection reasons distribution (no spread-related rejections)
- Entry success rate
- Trade performance with wider spreads
- Cycle completion time (should decrease slightly)

### Logging

**Log changes**:

- Remove spread-related log messages from validation
- Remove spread percentage from entry logs
- Keep all other logging unchanged

**Example log changes**:

Before:
```
Skipping AAPL: bid-ask spread too wide: 2.5% > 2.0%
Entry price for AAPL: $150.25 (bid=$150.00, ask=$150.50, spread=0.33%)
```

After:
```
Entry price for AAPL: $150.25 (bid=$150.00, ask=$150.50)
```

## Comparison with Previous Version

### Removed Features

1. **LiquidityRule**: No longer validates bid-ask spread
2. **Spread Calculation in _passes_filters**: No longer calculates spread percentage
3. **Spread Check in _process_ticker_entry**: No longer validates spread before entry
4. **Spread-related Rejections**: No longer rejects tickers due to wide spreads
5. **Spread-related Logging**: No longer logs spread information in validation

### Retained Features

1. **All Other Validation Rules**: DataQualityRule, TrendDirectionRule, ContinuationRule, PriceExtremeRule, MomentumThresholdRule
2. **Entry Price Calculation**: Still uses bid/ask for entry price
3. **Database Structure**: Same record format and schema
4. **Batch Writing**: Same efficient database operations
5. **Rejection Collection**: Same rejection tracking mechanism

### Benefits

1. **Simpler Logic**: One less validation rule to maintain
2. **Faster Execution**: Fewer checks per ticker
3. **More Opportunities**: More tickers pass validation
4. **Better for Momentum**: Aligns with fast entry/exit strategy
5. **Cleaner Code**: Less spread-related code to maintain

### Risks

1. **Execution Quality**: May enter trades with poor liquidity
2. **Slippage**: Wider spreads may cause more slippage
3. **Exit Difficulty**: May be harder to exit positions with wide spreads

**Mitigation**:

- Fast exit strategy (0.5% trailing stop) minimizes exposure
- Momentum-based entries mean quick in-and-out
- Exit monitoring every 1 second allows fast response to issues
- MAB learning will identify tickers with poor execution quality

## Code Changes Summary

### Files to Modify

1. **app/src/services/trading/penny_stocks_indicator.py**
   - Remove LiquidityRule from _validate_ticker_with_pipeline
   - Remove spread calculation from _passes_filters
   - Remove spread check from _process_ticker_entry
   - Remove spread-related logging

2. **tests/property/test_validation_rules.py** (if exists)
   - Remove LiquidityRule tests
   - Add tests for spread not affecting validation

3. **tests/test_penny_stocks_indicator.py** (if exists)
   - Update tests to reflect no spread validation
   - Add tests for wide spreads passing validation

### Files Not Modified

1. **app/src/services/trading/validation/rules.py**
   - LiquidityRule class remains (not deleted, just not used)
   - All other rule classes unchanged

2. **app/src/services/trading/validation/models.py**
   - QuoteData class unchanged (spread_percent property remains)
   - All other model classes unchanged

3. **app/src/db/dynamodb_client.py**
   - No changes to database operations

4. **app/src/services/mab/mab_service.py**
   - No changes to MAB selection logic
