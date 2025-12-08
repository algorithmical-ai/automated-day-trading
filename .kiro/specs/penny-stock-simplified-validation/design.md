# Design Document

## Overview

The Penny Stock Simplified Validation system is a streamlined version of the trade entry validation logic that determines whether to enter long or short positions for penny stocks (stocks under $5 USD). This design simplifies the validation approach by focusing on momentum score as the primary driver for trend-based decisions, removing complex continuation thresholds and peak/bottom checks.

The key innovation is the use of **empty strings to indicate valid entries**: when `reason_not_to_enter_long` or `reason_not_to_enter_short` is an empty string (""), that direction is tradeable. This provides a clear, simple signal for valid entry opportunities.

The system writes **all ticker evaluations** to the database, including both passing and failing tickers, enabling comprehensive analysis of market conditions and validation patterns.

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
         │    ├─> Momentum Score (primary driver)
         │    ├─> Continuation Score (for analysis)
         │    ├─> Peak/Bottom Prices (for analysis)
         │    └─> Reason String (human-readable)
         │
         ├──> Apply Validation Rules (Sequential)
         │    ├─> Liquidity Check (bid-ask spread)
         │    └─> Trend Direction Check (momentum-based)
         │
         ├──> Collect All Evaluation Records
         │    (both passing and failing)
         │
         └──> Batch Write to DynamoDB
```

### Simplified Validation Flow

1. **Fetch Data**: Retrieve 5 price bars and current quote for each ticker
2. **Calculate Metrics**: Compute momentum score, continuation, peak/bottom, and reason string
3. **Check Liquidity**: If spread > 2.0%, reject both directions
4. **Check Trend**: If momentum < 0, reject long; if momentum > 0, reject short
5. **Record Result**: Create record with rejection reasons (or empty strings for valid directions)
6. **Batch Write**: Write all records (passing and failing) to database

## Components and Interfaces

### TrendMetricsCalculator

**Responsibility**: Calculate all trend-related metrics from price bars

**Interface**:
```python
class TrendMetricsCalculator:
    @staticmethod
    def calculate_metrics(bars: List[Dict]) -> TrendMetrics:
        """
        Calculate trend metrics from price bars.
        
        Args:
            bars: List of price bar dictionaries with 'c' (close) prices
            
        Returns:
            TrendMetrics containing:
            - momentum_score: float (amplified trend strength)
            - continuation_score: float (0.0-1.0)
            - peak_price: float
            - bottom_price: float
            - reason: str (human-readable description)
        """
```

**Algorithm**:
- Use last 5 bars (or fewer if insufficient)
- Calculate price change percentage: (last - first) / first * 100
- Count up moves and down moves
- Calculate continuation: moves_in_trend_direction / total_moves
- Apply amplification based on move consistency
- Generate human-readable reason string

### SimplifiedValidator

**Responsibility**: Apply validation rules and determine entry validity

**Interface**:
```python
class SimplifiedValidator:
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote: Quote
    ) -> ValidationResult:
        """
        Validate ticker for entry.
        
        Returns:
            ValidationResult containing:
            - reason_not_to_enter_long: str (empty if valid)
            - reason_not_to_enter_short: str (empty if valid)
        """
```

**Validation Logic**:
1. Check bid-ask spread:
   - If spread > 2.0%: reject both directions
2. Check momentum for long:
   - If momentum < 0: reject long with "Recent bars show downward trend"
   - Otherwise: leave reason_not_to_enter_long as ""
3. Check momentum for short:
   - If momentum > 0: reject short with "Recent bars show upward trend"
   - Otherwise: leave reason_not_to_enter_short as ""

### EvaluationRecordBuilder

**Responsibility**: Build evaluation records for database storage

**Interface**:
```python
class EvaluationRecordBuilder:
    def build_record(
        self,
        ticker: str,
        indicator: str,
        validation_result: ValidationResult,
        trend_metrics: TrendMetrics
    ) -> Dict:
        """
        Build evaluation record for database.
        
        Returns:
            Dictionary with:
            - ticker: str
            - indicator: str
            - reason_not_to_enter_long: str
            - reason_not_to_enter_short: str
            - technical_indicators: Dict (JSON)
            - timestamp: str (ISO 8601)
        """
```

### InactiveTickerRepository

**Responsibility**: Persist evaluation records to DynamoDB

**Interface**:
```python
class InactiveTickerRepository:
    async def batch_write_evaluations(
        self,
        records: List[Dict]
    ) -> bool:
        """
        Write all evaluation records in batch.
        
        Args:
            records: List of evaluation dictionaries
                
        Returns:
            bool: True if successful, False otherwise
        """
```

## Data Models

### TrendMetrics

```python
@dataclass
class TrendMetrics:
    momentum_score: float  # Amplified trend strength (can be large positive/negative)
    continuation_score: float  # 0.0-1.0, proportion of moves in trend direction
    peak_price: float  # Highest price in recent bars
    bottom_price: float  # Lowest price in recent bars
    reason: str  # "Recent trend (N bars): X.XX% change, N up/M down moves, peak=$X, bottom=$Y, continuation=Z"
```

### Quote

```python
@dataclass
class Quote:
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

### ValidationResult

```python
@dataclass
class ValidationResult:
    reason_not_to_enter_long: str  # Empty string if valid for long entry
    reason_not_to_enter_short: str  # Empty string if valid for short entry
    
    @property
    def is_valid_for_long(self) -> bool:
        return self.reason_not_to_enter_long == ""
    
    @property
    def is_valid_for_short(self) -> bool:
        return self.reason_not_to_enter_short == ""
```

### EvaluationRecord

```python
@dataclass
class EvaluationRecord:
    ticker: str
    indicator: str  # "Penny Stocks"
    reason_not_to_enter_long: str
    reason_not_to_enter_short: str
    technical_indicators: Dict[str, Any]  # JSON with momentum_score, continuation_score, etc.
    timestamp: str  # ISO 8601 format
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Negative momentum rejects long entry

*For any* ticker with negative momentum score, long entry should be rejected with a reason containing "downward trend" and the momentum score value.

**Validates: Requirements 1.1, 1.4**

### Property 2: Positive momentum rejects short entry

*For any* ticker with positive momentum score, short entry should be rejected with a reason containing "upward trend" and the momentum score value.

**Validates: Requirements 1.2, 1.4**

### Property 3: Negative momentum allows short entry

*For any* ticker with negative momentum score, the reason_not_to_enter_short field should be an empty string (indicating short entry is valid).

**Validates: Requirements 1.5**

### Property 4: Positive momentum allows long entry

*For any* ticker with positive momentum score, the reason_not_to_enter_long field should be an empty string (indicating long entry is valid).

**Validates: Requirements 1.5**

### Property 5: Wide spread rejects both directions

*For any* ticker with bid-ask spread exceeding 2.0%, both reason_not_to_enter_long and reason_not_to_enter_short should be populated with rejection reasons.

**Validates: Requirements 2.1**

### Property 6: Spread calculation correctness

*For any* bid and ask prices, the spread percentage should equal ((ask - bid) / ((bid + ask) / 2)) * 100.

**Validates: Requirements 2.2**

### Property 7: Wide spread rejection format

*For any* ticker rejected due to wide spread, the rejection reason should match the format "Bid-ask spread too wide: X.XX% > 2.0%" and include both the actual spread and threshold.

**Validates: Requirements 2.3**

### Property 8: Wide spread applies to both directions identically

*For any* ticker with spread > 2.0%, both reason_not_to_enter_long and reason_not_to_enter_short should contain identical text.

**Validates: Requirements 2.4**

### Property 9: All evaluations are persisted

*For any* ticker evaluation (passing or failing), a record should be written to the InactiveTickersForDayTrading table.

**Validates: Requirements 3.1**

### Property 10: Evaluation records contain required fields

*For any* evaluation record, it should contain ticker, indicator ("Penny Stocks"), timestamp, and technical_indicators fields.

**Validates: Requirements 3.2**

### Property 11: Valid direction has empty reason

*For any* direction that is valid for entry, the corresponding reason field should be an empty string.

**Validates: Requirements 3.3**

### Property 12: Invalid direction has non-empty reason

*For any* direction that is invalid for entry, the corresponding reason field should contain a non-empty descriptive message.

**Validates: Requirements 3.4**

### Property 13: Technical indicators contain all metrics

*For any* evaluation record, the technical_indicators JSON should contain momentum_score, continuation_score, peak_price, bottom_price, and reason fields.

**Validates: Requirements 3.5**

### Property 14: Momentum amplifies consistent moves

*For any* set of price bars with consistent directional moves, the momentum score magnitude should be greater than the raw price change percentage.

**Validates: Requirements 4.3**

### Property 15: Continuation score bounds

*For any* set of price bars, the continuation score should be between 0.0 and 1.0 inclusive.

**Validates: Requirements 5.2**

### Property 16: Continuation score calculation

*For any* set of price bars, the continuation score should equal the proportion of price changes moving in the overall trend direction.

**Validates: Requirements 5.1**

### Property 17: Peak price is maximum

*For any* set of price bars, the peak_price should equal the maximum close price in the bars.

**Validates: Requirements 6.1**

### Property 18: Bottom price is minimum

*For any* set of price bars, the bottom_price should equal the minimum close price in the bars.

**Validates: Requirements 6.2**

### Property 19: Peak and bottom in technical indicators

*For any* evaluation record, the technical_indicators JSON should contain both peak_price and bottom_price fields.

**Validates: Requirements 6.3**

### Property 20: Reason string format

*For any* trend calculation, the reason string should match the format "Recent trend (N bars): X.XX% change, N up/M down moves, peak=$X, bottom=$Y, continuation=Z".

**Validates: Requirements 7.1**

### Property 21: Reason string in technical indicators

*For any* evaluation record, the technical_indicators JSON should contain a reason field with the trend description.

**Validates: Requirements 7.2**

### Property 22: Reason string reflects actual bar count

*For any* trend calculation with fewer than 5 bars, the reason string should include the actual number of bars used.

**Validates: Requirements 7.3**

### Property 23: Up/down move counts are accurate

*For any* set of price bars, the up and down move counts in the reason string should accurately reflect the number of bars where price increased vs decreased.

**Validates: Requirements 7.4**

### Property 24: Price formatting in reason

*For any* reason string, peak and bottom prices should be formatted with exactly two decimal places.

**Validates: Requirements 7.5**

### Property 25: Records collected before write

*For any* entry cycle processing multiple tickers, no database writes should occur until all tickers have been evaluated.

**Validates: Requirements 8.1**

### Property 26: Single batch write per cycle

*For any* entry cycle, exactly one batch write operation should be performed to write all evaluation records.

**Validates: Requirements 8.2**

### Property 27: Database failures don't block cycle

*For any* entry cycle where batch write fails, the system should log the error and continue without throwing an exception.

**Validates: Requirements 8.3**

### Property 28: Batch includes passing and failing tickers

*For any* entry cycle with mixed results, the batch should include both tickers with empty rejection reasons (passing) and tickers with populated rejection reasons (failing).

**Validates: Requirements 8.4**

### Property 29: Fully passing ticker has empty reasons

*For any* ticker that passes validation for both directions, the evaluation record should have both reason_not_to_enter_long and reason_not_to_enter_short as empty strings.

**Validates: Requirements 8.5**

## Error Handling

### Market Data Errors

- **No Response**: Log error, skip ticker for this cycle
- **Malformed Response**: Log error, skip ticker
- **Insufficient Bars**: Calculate metrics with available bars (minimum 1)
- **Invalid Prices**: Filter out null/negative prices before calculation

### Calculation Errors

- **Division by Zero**: Use safe division that returns 0.0
- **Empty Bars After Filtering**: Set all metrics to 0.0, peak/bottom to 0.0
- **Single Bar**: Use that bar's price for all calculations
- **All Prices Identical**: Momentum = 0.0, continuation = 0.0

### Database Errors

- **Write Failure**: Log error with full context, continue to next cycle
- **Connection Loss**: Log error, continue (don't block trading)
- **Throttling**: Log warning, continue
- **Malformed Records**: Log error, exclude from batch

### Edge Cases

- **Zero Bid or Ask**: Reject both directions with "Invalid bid/ask prices"
- **Negative Bid or Ask**: Reject both directions with "Invalid bid/ask prices"
- **Bid > Ask**: Calculate spread normally (will be negative, likely fail other checks)
- **Zero Momentum**: Allow both directions (empty rejection reasons)

## Testing Strategy

### Unit Testing

Unit tests will verify specific examples and edge cases:

- Zero and negative bid/ask prices
- Identical prices across all bars (zero momentum)
- Single bar scenarios
- Empty bars after filtering invalid prices
- Spread calculation edge cases
- Reason string formatting

### Property-Based Testing

Property-based tests will verify universal properties across all inputs using the Hypothesis library for Python. Each test will run a minimum of 100 iterations with randomly generated inputs.

**Test Configuration**:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property
- Shrinking: Enabled to find minimal failing examples
- Seed: Random (logged on failure for reproducibility)

**Generator Strategies**:

1. **Price Bar Generator**: Generate lists of price bars with:
   - Length (1-10 bars, focusing on 5)
   - Price range ($0.01-$5.00 for penny stocks)
   - Trend patterns (upward, downward, sideways, mixed)
   - Consistency levels (all same direction, mixed, random)

2. **Quote Generator**: Generate bid/ask quotes with:
   - Valid spreads (0.1%-5.0%)
   - Edge cases (zero, negative, identical bid/ask)
   - Spreads around threshold (1.8%, 2.0%, 2.2%)

3. **Momentum Score Generator**: Generate momentum scores:
   - Negative values (downward trends)
   - Positive values (upward trends)
   - Zero (no trend)
   - Large values (strong trends with amplification)

**Property Test Tagging**:
Each property-based test will include a comment tag:
```python
# Feature: penny-stock-simplified-validation, Property N: [property description]
```

### Integration Testing

Integration tests will verify end-to-end flows:

- Full entry cycle with mocked Alpaca API
- Batch writing to DynamoDB (mocked or local)
- Mixed results (some passing, some failing tickers)
- Error recovery (API failures, database failures)
- Performance (100+ tickers per cycle)

## Performance Considerations

### Latency Requirements

- **Entry Cycle**: Complete within 1 second for up to 100 tickers
- **Trend Calculation**: < 1ms per ticker
- **Validation**: < 1ms per ticker (simplified logic)
- **Batch Write**: < 100ms for up to 100 records

### Optimization Strategies

1. **Simplified Validation**: Only 2 checks (liquidity + momentum) vs 6+ in complex version
2. **Parallel Data Fetching**: Fetch bars and quotes concurrently
3. **Single Batch Write**: All records written at once
4. **No Early Termination**: Always calculate all metrics for analysis (but fast enough)

### Scalability

- **Stateless**: Can run multiple instances
- **Async Operation**: Non-blocking I/O
- **DynamoDB**: Auto-scales with load
- **Minimal Computation**: Simple calculations, no complex thresholds

## Deployment Considerations

### Configuration

Configurable via environment variables:

- `MAX_BID_ASK_SPREAD` (default: 2.0)
- `RECENT_BARS_COUNT` (default: 5)
- `INDICATOR_NAME` (default: "Penny Stocks")

### Monitoring

Key metrics:

- Rejection rate by reason type
- Percentage of tickers valid for long/short/both
- Average momentum score distribution
- Database write success rate
- Cycle completion time

### Logging

Log levels:

- **DEBUG**: Individual ticker evaluation results
- **INFO**: Cycle summaries (N tickers, M valid long, K valid short)
- **WARNING**: API errors, data quality issues
- **ERROR**: Database failures

## Comparison with Complex Version

### Removed Complexity

1. **No Continuation Threshold**: Removed 0.7 continuation check
2. **No Peak/Bottom Checks**: Removed 1.0% extreme price checks
3. **No Momentum Thresholds**: Removed 3.0% min and 10.0% max checks
4. **Simplified Rules**: Only 2 validation rules vs 6

### Retained Features

1. **Momentum Score**: Still primary driver (with amplification)
2. **Bid-Ask Spread**: Still validates liquidity
3. **Technical Indicators**: Still captures all metrics for analysis
4. **Batch Writing**: Still efficient database operations

### Benefits

1. **Simpler Logic**: Easier to understand and maintain
2. **Faster Execution**: Fewer checks to perform
3. **More Opportunities**: Fewer rejections means more potential trades
4. **Better Analysis**: All tickers recorded (not just rejections)

