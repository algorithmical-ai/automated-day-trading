# Design Document

## Overview

The Momentum Trading Simplified Validation system validates trade entry opportunities based on tradability filters rather than directional momentum. Unlike the Penny Stocks indicator which uses asymmetric validation (different rules for long vs short), the Momentum Indicator uses **symmetric validation** where all rejections apply equally to both long and short positions.

The key innovation is the focus on **tradability filters**: liquidity (volume), volatility (ATR), price levels, and security type. The system writes **all ticker evaluations** to the database with comprehensive technical indicators, enabling rich analysis even for rejected tickers.

## Architecture

### High-Level Architecture

```
┌─────────────────┐
│  Entry Cycle    │
│   Controller    │
└────────┬────────┘
         │
         ├──> Fetch Market Data & Calculate Technical Indicators
         │    ├─> RSI, MACD, Bollinger Bands
         │    ├─> ADX, EMA, Stochastic
         │    ├─> Volume metrics (SMA, OBV, MFI, A/D)
         │    ├─> Momentum indicators (CCI, Williams %R, ROC)
         │    ├─> Price averages (VWAP, VWMA, WMA)
         │    └─> ATR for volatility
         │
         ├──> Apply Validation Rules (Sequential, Symmetric)
         │    ├─> Security Type Check (warrant/derivative filter)
         │    ├─> Price Floor Check (>= $0.10)
         │    ├─> Absolute Volume Check (>= 500)
         │    ├─> Volume Ratio Check (>= 1.5x SMA)
         │    └─> Volatility Check (ATR% <= 5.0%)
         │
         ├──> Collect All Evaluation Records
         │    (both passing and failing, with full TA data)
         │
         └──> Batch Write to DynamoDB
```

### Symmetric Validation Flow

1. **Fetch Data**: Retrieve price/volume data and calculate comprehensive technical indicators
2. **Check Security Type**: Reject if ticker ends with W/R/RT/WS (warrants/derivatives)
3. **Check Price Floor**: Reject if price < $0.10
4. **Check Absolute Volume**: Reject if volume < 500
5. **Check Volume Ratio**: Reject if volume/SMA < 1.5x
6. **Check Volatility**: Reject if ATR% > 5.0%
7. **Record Result**: Create record with rejection reason (or empty strings for valid)
8. **Batch Write**: Write all records (passing and failing) to database

## Components and Interfaces

### TechnicalIndicatorCalculator

**Responsibility**: Calculate comprehensive technical analysis indicators

**Interface**:
```python
class TechnicalIndicatorCalculator:
    @staticmethod
    def calculate_indicators(bars: List[Dict], volume_data: List[int]) -> TechnicalIndicators:
        """
        Calculate all technical indicators from price and volume data.
        
        Returns:
            TechnicalIndicators containing:
            - rsi: float
            - macd: List[float] (3 values: macd, signal, histogram)
            - bollinger: List[float] (3 values: upper, middle, lower)
            - adx: float
            - ema_fast: float
            - ema_slow: float
            - volume_sma: float
            - obv: float (On-Balance Volume)
            - mfi: float (Money Flow Index)
            - ad: float (Accumulation/Distribution)
            - stoch: List[float] (2 values: %K, %D)
            - cci: float (Commodity Channel Index)
            - atr: float (Average True Range)
            - willr: float (Williams %R)
            - roc: float (Rate of Change)
            - vwap: float (Volume Weighted Average Price)
            - vwma: float (Volume Weighted Moving Average)
            - wma: float (Weighted Moving Average)
            - volume: int
            - close_price: float
            - datetime_price: List[Tuple[str, float]]
        """
```

### MomentumValidator

**Responsibility**: Apply symmetric validation rules

**Interface**:
```python
class MomentumValidator:
    def validate(
        self,
        ticker: str,
        technical_indicators: TechnicalIndicators
    ) -> ValidationResult:
        """
        Validate ticker for entry using symmetric rules.
        
        Returns:
            ValidationResult containing:
            - reason_not_to_enter_long: str (empty if valid)
            - reason_not_to_enter_short: str (empty if valid)
            
        Note: For Momentum Indicator, both reasons are always identical
        (symmetric rejection)
        """
```

**Validation Logic**:
1. Check security type (ticker suffix)
2. Check price floor (>= $0.10)
3. Check absolute volume (>= 500)
4. Check volume ratio (>= 1.5x SMA)
5. Check volatility (ATR% <= 5.0%)

All checks apply symmetrically to both long and short.

### MomentumEvaluationRecordBuilder

**Responsibility**: Build evaluation records with comprehensive technical indicators

**Interface**:
```python
class MomentumEvaluationRecordBuilder:
    def build_record(
        self,
        ticker: str,
        indicator: str,
        validation_result: ValidationResult,
        technical_indicators: TechnicalIndicators
    ) -> Dict:
        """
        Build evaluation record for database.
        
        Returns:
            Dictionary with:
            - ticker: str
            - indicator: str ("Momentum Trading")
            - reason_not_to_enter_long: str
            - reason_not_to_enter_short: str
            - technical_indicators: Dict (comprehensive TA data)
            - timestamp: str (ISO 8601)
        """
```

## Data Models

### TechnicalIndicators

```python
@dataclass
class TechnicalIndicators:
    # Momentum indicators
    rsi: float
    macd: List[float]  # [macd, signal, histogram]
    stoch: List[float]  # [%K, %D]
    cci: float
    willr: float
    roc: float
    
    # Trend indicators
    adx: float
    ema_fast: float
    ema_slow: float
    
    # Volatility indicators
    bollinger: List[float]  # [upper, middle, lower]
    atr: float
    
    # Volume indicators
    volume: int
    volume_sma: float
    obv: float
    mfi: float
    ad: float
    
    # Price averages
    vwap: float
    vwma: float
    wma: float
    close_price: float
    
    # Time series data
    datetime_price: List[Tuple[str, float]]
```

### ValidationResult

```python
@dataclass
class ValidationResult:
    reason_not_to_enter_long: str  # Empty string if valid
    reason_not_to_enter_short: str  # Empty string if valid
    
    @property
    def is_valid(self) -> bool:
        """Check if entry is valid (both reasons empty)."""
        return (self.reason_not_to_enter_long == "" and 
                self.reason_not_to_enter_short == "")
    
    @property
    def is_symmetric_rejection(self) -> bool:
        """Check if rejection is symmetric (both reasons identical)."""
        return (self.reason_not_to_enter_long == 
                self.reason_not_to_enter_short)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Warrant/derivative suffix rejection

*For any* ticker ending with W, R, RT, or WS, both reason_not_to_enter_long and reason_not_to_enter_short should contain "Excluded" and "warrant/option".

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

### Property 2: Symmetric rejection for security type

*For any* ticker rejected as a warrant/derivative, both reason_not_to_enter_long and reason_not_to_enter_short should be identical.

**Validates: Requirements 1.5**

### Property 3: Price floor rejection

*For any* ticker with close price less than $0.10, both reason_not_to_enter_long and reason_not_to_enter_short should contain "Price too low" and the actual price value.

**Validates: Requirements 2.1, 2.2, 2.5**

### Property 4: Symmetric rejection for price

*For any* ticker rejected due to low price, both reason_not_to_enter_long and reason_not_to_enter_short should be identical.

**Validates: Requirements 2.3**

### Property 5: Price floor pass-through

*For any* ticker with close price greater than or equal to $0.10, the price validation should not reject the ticker.

**Validates: Requirements 2.4**

### Property 6: Absolute volume rejection

*For any* ticker with volume less than 500, both reason_not_to_enter_long and reason_not_to_enter_short should contain "Volume too low" and the actual volume value.

**Validates: Requirements 3.1, 3.2, 3.5**

### Property 7: Symmetric rejection for volume

*For any* ticker rejected due to low volume, both reason_not_to_enter_long and reason_not_to_enter_short should be identical.

**Validates: Requirements 3.3**

### Property 8: Absolute volume pass-through

*For any* ticker with volume greater than or equal to 500, the absolute volume validation should not reject the ticker.

**Validates: Requirements 3.4**

### Property 9: Volume ratio calculation

*For any* volume and volume_sma values, the calculated ratio should equal volume / volume_sma.

**Validates: Requirements 4.2**

### Property 10: Volume ratio rejection

*For any* ticker with volume ratio less than 1.5, both reason_not_to_enter_long and reason_not_to_enter_short should contain "Volume ratio too low" with the ratio, volume, and SMA values.

**Validates: Requirements 4.1, 4.3**

### Property 11: Symmetric rejection for volume ratio

*For any* ticker rejected due to low volume ratio, both reason_not_to_enter_long and reason_not_to_enter_short should be identical.

**Validates: Requirements 4.4**

### Property 12: ATR percentage calculation

*For any* ATR and close price values, the ATR percentage should equal (ATR / close_price) * 100.

**Validates: Requirements 5.2**

### Property 13: Volatility rejection

*For any* ticker with ATR percentage exceeding 5.0%, both reason_not_to_enter_long and reason_not_to_enter_short should contain "Too volatile" with the ATR percentage and limit.

**Validates: Requirements 5.1, 5.3**

### Property 14: Symmetric rejection for volatility

*For any* ticker rejected due to high volatility, both reason_not_to_enter_long and reason_not_to_enter_short should be identical.

**Validates: Requirements 5.4**

### Property 15: All evaluations are persisted

*For any* ticker evaluation (passing or failing), a record should be written to the InactiveTickersForDayTrading table.

**Validates: Requirements 6.1**

### Property 16: Evaluation records contain required fields

*For any* evaluation record, it should contain ticker, indicator ("Momentum Trading"), timestamp, and technical_indicators fields.

**Validates: Requirements 6.2**

### Property 17: Passing ticker has empty reasons

*For any* ticker that passes all validation, both reason_not_to_enter_long and reason_not_to_enter_short should be empty strings.

**Validates: Requirements 6.3**

### Property 18: Failing ticker has symmetric reasons

*For any* ticker that fails validation, both reason_not_to_enter_long and reason_not_to_enter_short should contain identical text.

**Validates: Requirements 6.4**

### Property 19: Technical indicators completeness

*For any* evaluation record, the technical_indicators JSON should contain all required fields: RSI, MACD, Bollinger Bands, ADX, EMA, volume metrics, momentum indicators, price averages, ATR, volume, close_price, and datetime_price.

**Validates: Requirements 6.5, 7.1-7.10**

### Property 20: Records collected before write

*For any* entry cycle processing multiple tickers, no database writes should occur until all tickers have been evaluated.

**Validates: Requirements 8.1**

### Property 21: Single batch write per cycle

*For any* entry cycle, exactly one batch write operation should be performed to write all evaluation records.

**Validates: Requirements 8.2**

### Property 22: Database failures don't block cycle

*For any* entry cycle where batch write fails, the system should log the error and continue without throwing an exception.

**Validates: Requirements 8.3**

### Property 23: Batch includes passing and failing tickers

*For any* entry cycle with mixed results, the batch should include both tickers with empty rejection reasons (passing) and tickers with populated rejection reasons (failing).

**Validates: Requirements 8.4**

### Property 24: All symmetric rejections are identical

*For any* ticker in the Momentum Indicator system, if either reason field is non-empty, both reason fields should contain identical text.

**Validates: Requirements 1.5, 2.3, 3.3, 4.4, 5.4, 6.4**

## Error Handling

### Market Data Errors

- **No Response**: Log error, skip ticker for this cycle
- **Malformed Response**: Log error, skip ticker
- **Insufficient Data**: Calculate indicators with available data, mark as incomplete
- **Invalid Prices**: Filter out null/negative prices before calculation

### Calculation Errors

- **Division by Zero**: Use safe division that returns 0.0 or appropriate default
- **Invalid Volume SMA**: Reject with "Invalid volume SMA" for both directions
- **Invalid Price for ATR**: Reject with "Invalid price for ATR calculation" for both directions
- **Missing Technical Indicator**: Set to 0.0 or NaN, log warning

### Database Errors

- **Write Failure**: Log error with full context, continue to next cycle
- **Connection Loss**: Log error, continue (don't block trading)
- **Throttling**: Log warning, continue
- **Malformed Records**: Log error, exclude from batch

### Edge Cases

- **Zero Volume SMA**: Reject with "Invalid volume SMA"
- **Zero or Negative Price**: Reject with "Invalid price for ATR calculation"
- **Warrant Suffix Variations**: Handle W, R, RT, WS, and case variations
- **All Indicators Zero**: Valid scenario, don't reject

## Testing Strategy

### Unit Testing

Unit tests will verify specific examples and edge cases:

- Warrant/derivative suffix detection (W, R, RT, WS)
- Price floor boundary ($0.09, $0.10, $0.11)
- Volume floor boundary (499, 500, 501)
- Volume ratio boundary (1.4x, 1.5x, 1.6x)
- ATR percentage boundary (4.9%, 5.0%, 5.1%)
- Zero/negative volume SMA
- Zero/negative price for ATR calculation
- Symmetric rejection verification

### Property-Based Testing

Property-based tests will verify universal properties across all inputs using the Hypothesis library for Python. Each test will run a minimum of 100 iterations with randomly generated inputs.

**Test Configuration**:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property
- Shrinking: Enabled to find minimal failing examples
- Seed: Random (logged on failure for reproducibility)

**Generator Strategies**:

1. **Ticker Generator**: Generate tickers with and without warrant suffixes
2. **Price Generator**: Generate prices around $0.10 threshold
3. **Volume Generator**: Generate volumes around 500 threshold
4. **Volume Ratio Generator**: Generate ratios around 1.5x threshold
5. **ATR Percentage Generator**: Generate ATR% around 5.0% threshold
6. **Technical Indicators Generator**: Generate complete TA data structures

**Property Test Tagging**:
Each property-based test will include a comment tag:
```python
# Feature: momentum-simplified-validation, Property N: [property description]
```

### Integration Testing

Integration tests will verify end-to-end flows:

- Full entry cycle with mocked market data
- Batch writing to DynamoDB (mocked or local)
- Mixed results (some passing, some failing tickers)
- Error recovery (API failures, database failures)
- Symmetric rejection verification across all rules

## Performance Considerations

### Latency Requirements

- **Entry Cycle**: Complete within 2 seconds for up to 100 tickers
- **Technical Indicator Calculation**: < 10ms per ticker (comprehensive TA)
- **Validation**: < 1ms per ticker (5 simple checks)
- **Batch Write**: < 100ms for up to 100 records

### Optimization Strategies

1. **Parallel TA Calculation**: Calculate indicators for multiple tickers concurrently
2. **Sequential Validation**: Early termination on first failure
3. **Batch Database Writes**: Single write operation per cycle
4. **Cached Calculations**: Reuse intermediate values where possible

### Scalability

- **Stateless**: Can run multiple instances
- **Async Operation**: Non-blocking I/O
- **DynamoDB**: Auto-scales with load
- **Minimal Computation**: Simple threshold checks

## Deployment Considerations

### Configuration

Configurable via environment variables:

- `MIN_PRICE_THRESHOLD` (default: 0.10)
- `MIN_VOLUME_THRESHOLD` (default: 500)
- `MIN_VOLUME_RATIO` (default: 1.5)
- `MAX_ATR_PERCENT` (default: 5.0)
- `INDICATOR_NAME` (default: "Momentum Trading")
- `WARRANT_SUFFIXES` (default: "W,R,RT,WS")

### Monitoring

Key metrics:

- Rejection rate by rule type
- Percentage of tickers passing validation
- Average technical indicator calculation time
- Database write success rate
- Cycle completion time

### Logging

Log levels:

- **DEBUG**: Individual ticker evaluation results
- **INFO**: Cycle summaries (N tickers, M passing, rejection breakdown)
- **WARNING**: Data quality issues, calculation errors
- **ERROR**: Database failures

## Comparison with Penny Stocks Indicator

### Key Differences

1. **Symmetric vs Asymmetric**: Momentum uses symmetric rejection (both directions), Penny Stocks uses asymmetric (direction-specific)
2. **Tradability vs Trend**: Momentum focuses on tradability filters, Penny Stocks focuses on trend direction
3. **Technical Indicators**: Momentum includes comprehensive TA data, Penny Stocks includes basic trend metrics
4. **Rejection Reasons**: Momentum has 5 symmetric rules, Penny Stocks has 2 asymmetric rules

### Similarities

1. **Empty String Semantics**: Both use empty string to indicate valid entry
2. **Batch Writing**: Both write all evaluations in single batch
3. **Comprehensive Recording**: Both record passing and failing tickers
4. **Error Handling**: Both handle errors gracefully without blocking

## Future Enhancements

1. **Adaptive Thresholds**: Adjust thresholds based on market conditions
2. **Machine Learning**: Predict optimal threshold values
3. **Multi-Timeframe Analysis**: Consider multiple bar intervals
4. **Correlation Analysis**: Avoid entering correlated positions
5. **Real-Time Alerts**: Notify when high-quality opportunities are found
