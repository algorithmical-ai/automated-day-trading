# Design Document

## Overview

The Penny Stock Entry Validation system is a critical component of the trading infrastructure that determines whether to enter long or short positions for penny stocks (stocks under $5 USD). The system analyzes market data, calculates trend metrics, and applies a series of validation rules to ensure trades are only entered under favorable conditions.

The design follows a pipeline architecture where each ticker flows through multiple validation stages. Rejections are captured with detailed reasons and stored for analysis. The system is optimized for high-frequency operation (1-second cycles) and processes multiple tickers in parallel batches.

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
         │    └─> Current Price
         │
         ├──> Apply Validation Rules (Sequential)
         │    ├─> Data Quality Checks
         │    ├─> Liquidity Checks
         │    ├─> Trend Direction Checks
         │    ├─> Continuation Checks
         │    ├─> Price Extreme Checks
         │    └─> Momentum Threshold Checks
         │
         ├──> Collect Rejection Records
         │
         └──> Batch Write to DynamoDB
```

### Component Interaction Flow

1. **Entry Cycle Controller**: Orchestrates the validation process for all candidate tickers
2. **Market Data Fetcher**: Retrieves price bars and quotes from Alpaca API in parallel
3. **Trend Analyzer**: Calculates momentum, continuation, and price extremes
4. **Validation Pipeline**: Applies rules sequentially, short-circuiting on first failure
5. **Rejection Collector**: Accumulates rejection records during the cycle
6. **Database Writer**: Batch writes all rejections to InactiveTickersForDayTrading table

## Components and Interfaces

### TrendAnalyzer

**Responsibility**: Calculate trend metrics from price bars

**Interface**:
```python
class TrendAnalyzer:
    @staticmethod
    def calculate_trend_metrics(bars: List[Dict]) -> TrendMetrics:
        """
        Calculate all trend-related metrics from price bars.
        
        Args:
            bars: List of price bar dictionaries with 'c' (close) prices
            
        Returns:
            TrendMetrics containing:
            - momentum_score: float (percentage, positive=up, negative=down)
            - continuation_score: float (0.0-1.0)
            - peak_price: float
            - bottom_price: float
            - reason: str (description of calculation)
        """
```

**Algorithm**:
- Extract last 5 bars (or fewer if insufficient data)
- Calculate overall price change: (last_price - first_price) / first_price * 100
- Calculate consistency: (up_moves - down_moves) / total_moves * 100
- Momentum = 70% overall change + 30% consistency
- Apply penalty if trend strength < 70% (multiply momentum by 0.3)
- Calculate continuation from last 2-3 bars in trend direction

### ValidationRule (Abstract Base)

**Responsibility**: Define interface for validation rules

**Interface**:
```python
class ValidationRule(ABC):
    @abstractmethod
    def validate(
        self,
        ticker: str,
        trend_metrics: TrendMetrics,
        quote_data: QuoteData,
        bars: List[Dict]
    ) -> ValidationResult:
        """
        Validate a ticker against this rule.
        
        Returns:
            ValidationResult containing:
            - passed: bool
            - reason_long: Optional[str] (rejection reason for long entry)
            - reason_short: Optional[str] (rejection reason for short entry)
        """
```

### Concrete Validation Rules

1. **DataQualityRule**: Checks for sufficient bars and valid market data
2. **LiquidityRule**: Validates bid-ask spread and quote validity
3. **TrendDirectionRule**: Ensures trend aligns with entry direction
4. **ContinuationRule**: Validates trend is continuing (not reversing)
5. **PriceExtremeRule**: Checks if price is at peak/bottom
6. **MomentumThresholdRule**: Enforces min/max momentum bounds

### RejectionCollector

**Responsibility**: Accumulate rejection records during entry cycle

**Interface**:
```python
class RejectionCollector:
    def add_rejection(
        self,
        ticker: str,
        indicator: str,
        reason_long: Optional[str],
        reason_short: Optional[str],
        technical_indicators: Optional[Dict]
    ) -> None:
        """Add a rejection record to the batch."""
        
    def get_records(self) -> List[Dict]:
        """Get all collected rejection records."""
        
    def clear(self) -> None:
        """Clear all collected records."""
```

### InactiveTickerRepository

**Responsibility**: Persist rejection records to DynamoDB

**Interface**:
```python
class InactiveTickerRepository:
    async def batch_write_rejections(
        self,
        records: List[Dict]
    ) -> bool:
        """
        Write rejection records in batch to InactiveTickersForDayTrading table.
        
        Args:
            records: List of rejection dictionaries with fields:
                - ticker: str
                - indicator: str
                - reason_not_to_enter_long: Optional[str]
                - reason_not_to_enter_short: Optional[str]
                - technical_indicators: Optional[Dict]
                - timestamp: str (ISO format)
                
        Returns:
            bool: True if successful, False otherwise
        """
```

## Data Models

### TrendMetrics

```python
@dataclass
class TrendMetrics:
    momentum_score: float  # Percentage, positive=upward, negative=downward
    continuation_score: float  # 0.0-1.0, proportion of recent moves in trend direction
    peak_price: float  # Highest price in recent bars
    bottom_price: float  # Lowest price in recent bars
    reason: str  # Human-readable description of trend calculation
```

### QuoteData

```python
@dataclass
class QuoteData:
    ticker: str
    bid: float
    ask: float
    mid_price: float  # (bid + ask) / 2
    spread_percent: float  # (ask - bid) / mid_price * 100
```

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: bool
    reason_long: Optional[str] = None  # Rejection reason for long entry
    reason_short: Optional[str] = None  # Rejection reason for short entry
```

### RejectionRecord

```python
@dataclass
class RejectionRecord:
    ticker: str
    indicator: str
    reason_not_to_enter_long: Optional[str]
    reason_not_to_enter_short: Optional[str]
    technical_indicators: Optional[Dict[str, Any]]
    timestamp: str  # ISO 8601 format
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Trend direction rejection consistency

*For any* ticker with a calculated momentum score, if the momentum is negative (downward trend), then long entry should be rejected with a reason containing "downward trend", and if the momentum is positive (upward trend), then short entry should be rejected with a reason containing "upward trend".

**Validates: Requirements 1.1, 1.2**

### Property 2: Momentum score includes percentage in reason

*For any* ticker rejected due to trend direction, the rejection reason should contain the momentum score as a percentage value.

**Validates: Requirements 1.4**

### Property 3: Trend direction rejection populates both reason fields

*For any* ticker rejected due to trend direction, both reason_not_to_enter_long and reason_not_to_enter_short fields should be populated in the rejection record.

**Validates: Requirements 1.5**

### Property 4: Weak continuation rejects appropriate direction

*For any* ticker with an upward trend and continuation score below 0.7, long entry should be rejected with a reason containing "not continuing strongly", and for any ticker with a downward trend and continuation score below 0.7, short entry should be rejected with a reason containing "not continuing strongly".

**Validates: Requirements 2.1, 2.2**

### Property 5: Continuation score calculation correctness

*For any* sequence of price bars, the continuation score should equal the proportion of recent price changes that move in the overall trend direction.

**Validates: Requirements 2.3**

### Property 6: Weak continuation includes score in reason

*For any* ticker rejected due to weak continuation, the rejection reason should contain the continuation score value.

**Validates: Requirements 2.4**

### Property 7: Price near peak rejects long entry

*For any* ticker with an upward trend where the current price is within 1.0% of the peak price, long entry should be rejected with a reason containing "at/near peak".

**Validates: Requirements 3.1**

### Property 8: Price near bottom rejects short entry

*For any* ticker with a downward trend where the current price is within 1.0% of the bottom price, short entry should be rejected with a reason containing "at/near bottom".

**Validates: Requirements 3.2**

### Property 9: Price extreme percentage calculation

*For any* current price and extreme price (peak or bottom), the calculated percentage difference should equal ((current_price - extreme_price) / extreme_price) * 100.

**Validates: Requirements 3.3**

### Property 10: Extreme price rejection includes both prices

*For any* ticker rejected due to price being at an extreme, the rejection reason should contain both the current price and the extreme price values.

**Validates: Requirements 3.4**

### Property 11: Weak momentum rejects trend direction

*For any* ticker with absolute momentum score below 3.0%, entry in the trend direction should be rejected with a reason containing "weak trend" and the minimum threshold value (3.0%).

**Validates: Requirements 4.1, 4.3**

### Property 12: Excessive momentum rejects trend direction

*For any* ticker with absolute momentum score exceeding 10.0%, entry in the trend direction should be rejected with a reason containing "excessive trend" and the maximum threshold value (10.0%).

**Validates: Requirements 4.2, 4.4**

### Property 13: Out-of-range momentum populates both reason fields

*For any* ticker with momentum outside the acceptable range (< 3.0% or > 10.0%), both reason_not_to_enter_long and reason_not_to_enter_short should be populated with direction-specific reasons.

**Validates: Requirements 4.5**

### Property 14: Data quality failures apply to both directions

*For any* ticker that fails data quality checks (no market data, insufficient bars, invalid bid/ask), both reason_not_to_enter_long and reason_not_to_enter_short should contain identical rejection reasons.

**Validates: Requirements 5.4, 6.5**

### Property 15: Data quality rejections are persisted

*For any* ticker that fails data quality checks, a rejection record should be written to the InactiveTickersForDayTrading table.

**Validates: Requirements 5.5**

### Property 16: Bid-ask spread calculation correctness

*For any* bid and ask prices, the spread percentage should equal ((ask - bid) / ((bid + ask) / 2)) * 100.

**Validates: Requirements 6.2**

### Property 17: Wide spread rejection includes values

*For any* ticker rejected due to wide bid-ask spread, the rejection reason should contain both the actual spread percentage and the threshold value (2.0%).

**Validates: Requirements 6.3**

### Property 18: All rejections are persisted

*For any* ticker that fails entry validation for any reason, a record should be written to the InactiveTickersForDayTrading table.

**Validates: Requirements 7.1**

### Property 19: Rejection records contain required fields

*For any* rejection record written to the database, it should contain ticker symbol, indicator name, timestamp, and technical indicators fields.

**Validates: Requirements 7.2**

### Property 20: Direction-specific rejections populate correct field

*For any* rejection that is direction-specific (e.g., upward trend blocks short, downward trend blocks long), only the appropriate reason field (reason_not_to_enter_long or reason_not_to_enter_short) should be populated for that specific direction.

**Validates: Requirements 7.3**

### Property 21: Bidirectional rejections populate both fields identically

*For any* rejection that applies to both directions (e.g., data quality, liquidity), both reason_not_to_enter_long and reason_not_to_enter_short should contain identical text.

**Validates: Requirements 7.4**

### Property 22: Technical indicators include trend metrics

*For any* rejection record with technical indicators, the indicators should include momentum score, continuation score, peak price, and bottom price when available.

**Validates: Requirements 7.5**

### Property 23: Rejections are collected before database write

*For any* entry cycle processing multiple tickers, no database writes should occur until all tickers have been processed.

**Validates: Requirements 8.1**

### Property 24: Single batch write per cycle

*For any* entry cycle that completes, exactly one batch write operation should be performed to write all rejection records.

**Validates: Requirements 8.2**

### Property 25: Database failures don't block entry cycle

*For any* entry cycle where the batch write fails, the system should log the error and continue to the next cycle without throwing an exception.

**Validates: Requirements 8.3**

### Property 26: Rejection collector maintains proper structure

*For any* rejection added to the collector, the internal data structure should be a dictionary containing all required fields (ticker, indicator, reason_not_to_enter_long, reason_not_to_enter_short, technical_indicators, timestamp).

**Validates: Requirements 8.4**

### Property 27: Passing tickers excluded from rejection batch

*For any* entry cycle with mixed results (some passing, some failing), only the tickers that failed validation should appear in the rejection records batch.

**Validates: Requirements 8.5**

## Error Handling

### Market Data Errors

- **No Response**: When Alpaca API returns no data, reject with "No market data response" for both directions
- **Malformed Response**: Log error and treat as no response
- **Timeout**: Retry once with exponential backoff, then treat as no response
- **Rate Limiting**: Respect rate limits, queue requests if necessary

### Calculation Errors

- **Division by Zero**: When calculating percentages with zero denominators, use safe division that returns 0.0
- **Invalid Price Data**: When bars contain null or negative prices, skip those bars and log warning
- **Insufficient Data**: When fewer than 3 bars available, reject with "Insufficient bars data"

### Database Errors

- **Write Failure**: Log error with full context, continue to next cycle
- **Connection Loss**: Attempt reconnection, queue writes if possible
- **Throttling**: Implement exponential backoff for retries
- **Validation Errors**: Log malformed records, exclude from batch

### Edge Cases

- **Empty Bars List**: Treat as insufficient data
- **All Prices Identical**: Momentum score = 0.0, continuation = 0.0
- **Single Bar**: Reject with insufficient data
- **Negative Prices**: Filter out, log warning
- **Zero Bid or Ask**: Reject with "Invalid bid/ask"

## Testing Strategy

### Unit Testing

Unit tests will verify specific examples and edge cases:

- Empty market data responses
- Insufficient bars (0, 1, 2, 3, 4 bars)
- Invalid bid/ask prices (zero, negative)
- Identical prices across all bars
- Single bar scenarios
- Null/None values in data structures
- Database connection failures
- Malformed API responses

### Property-Based Testing

Property-based tests will verify universal properties across all inputs using the Hypothesis library for Python. Each test will run a minimum of 100 iterations with randomly generated inputs.

**Test Configuration**:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property
- Shrinking: Enabled to find minimal failing examples
- Seed: Random (for reproducibility, seed will be logged on failure)

**Generator Strategies**:

1. **Price Bar Generator**: Generate lists of price bars with configurable:
   - Length (1-200 bars)
   - Price range ($0.01-$5.00 for penny stocks)
   - Trend direction (upward, downward, sideways)
   - Volatility level (low, medium, high)

2. **Quote Data Generator**: Generate bid/ask quotes with:
   - Valid spreads (0.1%-5.0%)
   - Invalid scenarios (zero, negative, reversed)
   - Edge cases (identical bid/ask)

3. **Momentum Score Generator**: Generate momentum scores in ranges:
   - Weak: -3.0% to 3.0%
   - Normal: 3.0% to 10.0%
   - Excessive: > 10.0% or < -10.0%

4. **Continuation Score Generator**: Generate continuation scores:
   - Weak: 0.0 to 0.7
   - Strong: 0.7 to 1.0

**Property Test Tagging**:
Each property-based test will include a comment tag in this format:
```python
# Feature: penny-stock-entry-validation, Property N: [property description]
```

This tag explicitly links the test to the correctness property it validates, ensuring traceability between design and implementation.

### Integration Testing

Integration tests will verify end-to-end flows:

- Full entry cycle with real market data structure (mocked API)
- Batch writing to DynamoDB (using local DynamoDB or mocks)
- Concurrent processing of multiple tickers
- Error recovery and retry logic
- Performance under load (100+ tickers per cycle)

### Test Data

Test data will include:

- Historical price bars from real penny stocks
- Edge cases discovered in production
- Synthetic data covering all validation rule combinations
- Boundary values for all thresholds (3.0%, 10.0%, 0.7, 1.0%, 2.0%)

## Performance Considerations

### Latency Requirements

- **Entry Cycle**: Complete within 1 second for up to 100 tickers
- **Trend Calculation**: < 1ms per ticker
- **Validation Pipeline**: < 5ms per ticker
- **Batch Write**: < 100ms for up to 100 records

### Optimization Strategies

1. **Parallel Market Data Fetching**: Process tickers in batches of 25 concurrent requests
2. **Early Termination**: Stop validation pipeline on first failure
3. **Batch Database Writes**: Single write operation per cycle
4. **In-Memory Caching**: Cache trend calculations within cycle
5. **Lazy Evaluation**: Only fetch quotes when needed for validation

### Scalability

- **Horizontal**: System is stateless, can run multiple instances
- **Vertical**: Optimized for single-threaded async operation
- **Database**: DynamoDB auto-scales with load
- **API Rate Limits**: Respect Alpaca rate limits (200 req/min)

## Deployment Considerations

### Configuration

All thresholds should be configurable via environment variables:

- `MIN_MOMENTUM_THRESHOLD` (default: 3.0)
- `MAX_MOMENTUM_THRESHOLD` (default: 10.0)
- `MIN_CONTINUATION_SCORE` (default: 0.7)
- `PRICE_EXTREME_THRESHOLD` (default: 1.0)
- `MAX_BID_ASK_SPREAD` (default: 2.0)
- `RECENT_BARS_COUNT` (default: 5)

### Monitoring

Key metrics to monitor:

- Rejection rate by rule type
- Average validation latency
- Database write success rate
- API error rate
- Tickers processed per cycle

### Logging

Log levels:

- **DEBUG**: Individual ticker validation results
- **INFO**: Cycle summaries, batch write results
- **WARNING**: API errors, retry attempts
- **ERROR**: Database failures, unexpected exceptions

## Future Enhancements

1. **Machine Learning**: Train model to predict optimal thresholds based on historical performance
2. **Adaptive Thresholds**: Adjust thresholds based on market volatility
3. **Multi-Timeframe Analysis**: Consider multiple bar intervals (1min, 5min, 15min)
4. **Volume Analysis**: Incorporate volume trends into validation
5. **Correlation Analysis**: Avoid entering correlated positions
6. **Real-Time Alerts**: Notify when high-quality opportunities are rejected
