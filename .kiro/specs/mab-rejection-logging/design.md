# Design Document: MAB Rejection Logging

## Overview

This feature adds comprehensive logging of MAB (Multi-Armed Bandit) rejection decisions to the `InactiveTickersForDayTrading` table. When the MAB service filters out a ticker during the entry cycle, the system will now record the rejection reason in the appropriate direction-specific field (`reason_not_to_enter_long` or `reason_not_to_enter_short`). This provides complete visibility into the MAB selection process and enables analysis of MAB effectiveness.

## Architecture

The MAB rejection logging is implemented through a three-stage pipeline:

1. **Validation Stage**: Tickers are validated against quality filters (volume, price, technical indicators, etc.)
2. **MAB Selection Stage**: Validated tickers are ranked using Thompson Sampling based on historical success rates
3. **Logging Stage**: Tickers rejected at either stage are logged to `InactiveTickersForDayTrading` table with appropriate rejection reasons

The logging happens after MAB selection completes, capturing all tickers that passed validation but were not selected by MAB.

## Components and Interfaces

### 1. MABService Enhancement

**Location**: `app/src/services/mab/mab_service.py`

**New Method**: `get_rejection_reason()`
```python
@classmethod
def get_rejection_reason(
    cls,
    stats: Optional[Dict[str, Any]],
    ticker: str,
    direction: str
) -> str:
    """
    Generate a human-readable rejection reason for a ticker.
    
    Args:
        stats: MAB statistics for the ticker (or None for new tickers)
        ticker: Stock ticker symbol
        direction: "long" or "short"
        
    Returns:
        Rejection reason string with format:
        "MAB rejected: {reason} (successes: X, failures: Y, total: Z, score: S)"
    """
```

**Enhanced Method**: `select_tickers_with_mab()`
- Now returns information about rejected tickers in addition to selected ones
- Provides rejection reasons for each rejected ticker

### 2. DynamoDBClient Enhancement

**Location**: `app/src/db/dynamodb_client.py`

**Existing Method**: `log_inactive_ticker()`
- Already supports logging with `reason_not_to_enter_long` and `reason_not_to_enter_short`
- No changes needed - will be used as-is

### 3. Trading Indicator Enhancement

**Location**: `app/src/services/trading/penny_stocks_indicator.py` and `app/src/services/trading/momentum_indicator.py`

**Enhanced Method**: `_run_entry_cycle()`
- After MAB selection, identify tickers that passed validation but were rejected by MAB
- For each rejected ticker, determine the direction (long/short) based on momentum score
- Log the rejection with appropriate direction-specific reason

**New Helper Method**: `_log_mab_rejections()`
```python
@classmethod
async def _log_mab_rejections(
    cls,
    all_candidates: List[Tuple[str, float, str]],
    selected_tickers: Set[str],
    market_data_dict: Dict[str, Any],
    mab_stats_dict: Dict[str, Optional[Dict[str, Any]]]
) -> None:
    """
    Log tickers that passed validation but were rejected by MAB.
    
    Args:
        all_candidates: All (ticker, momentum_score, reason) tuples that passed validation
        selected_tickers: Set of tickers selected by MAB
        market_data_dict: Market data for all candidates
        mab_stats_dict: MAB statistics for all candidates
    """
```

## Data Models

### MAB Rejection Reason Format

```
"MAB rejected: {reason} (successes: X, failures: Y, total: Z)"
```

Examples:
- `"MAB rejected: Low historical success rate (successes: 2, failures: 8, total: 10)"`
- `"MAB rejected: Excluded until 2025-12-08 15:30:00+00:00 (successes: 0, failures: 0, total: 0)"`
- `"MAB rejected: New ticker - explored by Thompson Sampling (successes: 0, failures: 0, total: 0)"`

### InactiveTickersForDayTrading Table Entry

```python
{
    'ticker': 'AAPL',
    'indicator': 'Penny Stocks',
    'timestamp': '2025-12-08T10:30:00-05:00',  # EST/EDT timezone
    'reason_not_to_enter_long': 'MAB rejected: Low historical success rate (successes: 2, failures: 8, total: 10)',
    'reason_not_to_enter_short': '',  # Empty if not rejected for this direction
    'technical_indicators': '{"momentum_score": 2.5, "volume": 50000, "close_price": 3.25}'
}
```

## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

### Property 1: MAB Rejection Logging for Long Positions

*For any* ticker that passes validation filters but is rejected by MAB for long entry, the system should log it to `InactiveTickersForDayTrading` with `reason_not_to_enter_long` populated and `reason_not_to_enter_short` empty.

**Validates: Requirements 1.1, 5.1**

### Property 2: MAB Rejection Reason Format

*For any* MAB rejection, the `reason_not_to_enter_long` or `reason_not_to_enter_short` field should contain the prefix "MAB rejected:" followed by historical success rate information (successes, failures, total trades).

**Validates: Requirements 1.2, 2.2, 3.2, 3.3**

### Property 3: MAB Rejection Logging for Short Positions

*For any* ticker that passes validation filters but is rejected by MAB for short entry, the system should log it to `InactiveTickersForDayTrading` with `reason_not_to_enter_short` populated and `reason_not_to_enter_long` empty.

**Validates: Requirements 2.1, 5.2**

### Property 4: New Tickers Not Logged as Rejected

*For any* new ticker with no historical MAB data, the system should NOT log it to `InactiveTickersForDayTrading` table (new tickers are explored by Thompson Sampling, not rejected).

**Validates: Requirements 1.4, 2.4**

### Property 5: Excluded Tickers Logged with Exclusion Reason

*For any* ticker that is excluded from MAB selection (has `excluded_until` timestamp in future), the system should log it with rejection reason indicating exclusion status and end time.

**Validates: Requirements 1.3, 2.3**

### Property 6: Technical Indicators Included in MAB Rejections

*For any* MAB rejection, the `technical_indicators` field should be populated with relevant metrics (momentum score, volume, price) in JSON format.

**Validates: Requirements 4.1, 4.3**

### Property 7: Direction-Specific Rejection Handling

*For any* ticker rejected by MAB for both long and short entries, the system should populate both `reason_not_to_enter_long` and `reason_not_to_enter_short` with appropriate MAB rejection reasons.

**Validates: Requirements 5.3**

### Property 8: Selected Tickers Not Logged

*For any* ticker selected by MAB for trading, the system should NOT log it to `InactiveTickersForDayTrading` table.

**Validates: Requirements 5.4**

## Error Handling

1. **Missing MAB Statistics**: If a ticker has no MAB statistics (new ticker), it should not be logged as rejected since new tickers are explored by Thompson Sampling.

2. **Missing Technical Indicators**: If technical indicators are not available for a rejected ticker, log an empty or minimal `technical_indicators` object.

3. **DynamoDB Write Failures**: If logging a rejection fails, log a warning but continue processing other rejections (don't block the entry cycle).

4. **Concurrent MAB Updates**: If MAB statistics are updated between validation and logging, use the statistics available at logging time.

## Testing Strategy

### Unit Tests

- Test `get_rejection_reason()` with various MAB statistics (high success rate, low success rate, excluded, new ticker)
- Test direction-specific rejection logging (long only, short only, both)
- Test technical indicators are properly serialized to JSON
- Test that selected tickers are not logged
- Test that new tickers (no stats) are not logged as rejected

### Property-Based Tests

**Property 1: MAB Rejection Logging for Long Positions**
- Generate random tickers with positive momentum scores
- Mock MAB to reject them
- Verify log entry exists with `reason_not_to_enter_long` populated
- Verify `reason_not_to_enter_short` is empty

**Property 2: MAB Rejection Reason Format**
- Generate random MAB statistics (successes, failures)
- Generate rejection reasons
- Verify reason contains "MAB rejected:" prefix
- Verify reason contains success rate information

**Property 3: MAB Rejection Logging for Short Positions**
- Generate random tickers with negative momentum scores
- Mock MAB to reject them
- Verify log entry exists with `reason_not_to_enter_short` populated
- Verify `reason_not_to_enter_long` is empty

**Property 4: New Tickers Not Logged as Rejected**
- Generate new tickers with no MAB statistics
- Verify they are NOT logged to InactiveTickersForDayTrading
- Verify they are selected by MAB (explored)

**Property 5: Excluded Tickers Logged with Exclusion Reason**
- Generate tickers with `excluded_until` timestamp in future
- Verify they are logged with rejection reason
- Verify reason mentions exclusion status

**Property 6: Technical Indicators Included in MAB Rejections**
- Generate random technical indicators
- Log MAB rejections with these indicators
- Verify `technical_indicators` field contains the data in JSON format

**Property 7: Direction-Specific Rejection Handling**
- Generate tickers rejected for both long and short
- Verify both `reason_not_to_enter_long` and `reason_not_to_enter_short` are populated

**Property 8: Selected Tickers Not Logged**
- Generate tickers selected by MAB
- Verify they are NOT logged to InactiveTickersForDayTrading

### Integration Tests

- Test end-to-end entry cycle with MAB rejection logging
- Verify rejected tickers appear in InactiveTickersForDayTrading table
- Verify selected tickers do not appear in the table
- Verify timestamps are in EST/EDT timezone
