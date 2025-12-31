# Confidence Score Implementation

## Overview

Added `confidence_score` field (0.0 to 1.0 scale) to webhook JSON payloads for both "Penny Stocks" and "Momentum Trading" indicators. This score can be used by the webhook receiver to determine trade quantity.

## Implementation Details

### Webhook Function Update

**File**: `app/src/services/webhook/send_signal.py`

- Added `confidence_score: Optional[float] = None` parameter to `send_signal_to_webhook()` function
- Added `confidence_score` to internal `_send_signal_to_webhook_impl()` function
- Added confidence_score to payload with clamping to 0.0-1.0 range
- Confidence score is included in the JSON payload sent to webhooks

### Penny Stocks Indicator

**File**: `app/src/services/trading/penny_stocks_indicator.py`

**Method**: `_calculate_confidence_score()`

**Factors Considered** (weighted combination):
1. **Momentum Score** (35% weight)
   - Normalized from min_momentum_threshold (5.0%) to max reasonable (20.0%)
   - Higher momentum = higher confidence

2. **Peak Distance** (25% weight)
   - Optimal: 2-5% below peak = 1.0 confidence
   - Too close (< 1%) = 0.7 confidence
   - Too far (> 10%) = 0.8 confidence

3. **Spread** (20% weight)
   - Lower spread = higher confidence
   - Normalized based on max_bid_ask_spread_percent (0.75%)

4. **Volume** (15% weight)
   - Higher volume = higher confidence
   - Normalized based on min_volume (10,000)

5. **Rank** (5% weight)
   - Rank 1 = 1.0
   - Rank 2 = 0.9
   - Rank 3+ = 0.8

**Formula**:
```python
confidence = (
    momentum_normalized * 0.35 +
    peak_factor * 0.25 +
    spread_factor * 0.20 +
    volume_factor * 0.15 +
    rank_factor * 0.05
)
# Clamped to 0.0-1.0
```

### Momentum Trading Indicator

**File**: `app/src/services/trading/momentum_indicator.py`

**Method**: `_calculate_confidence_score()`

**Factors Considered** (weighted combination):
1. **Momentum Score** (30% weight)
   - Normalized from min_momentum_threshold (1.5%) to max_momentum_threshold (15.0%)
   - Higher momentum = higher confidence

2. **Recent Average Distance** (25% weight)
   - Optimal: 1-3% below recent_avg = 1.0 confidence
   - Too close (< 0.5%) = 0.7 confidence
   - Too far (> 5%) = 0.8 confidence

3. **Spread** (20% weight)
   - Lower spread = higher confidence
   - Normalized based on max_bid_ask_spread_percent (3.0%)

4. **Volume** (15% weight)
   - Higher volume = higher confidence
   - Normalized based on min_daily_volume (1,000)

5. **Rank** (5% weight)
   - Rank 1 = 1.0
   - Rank 2 = 0.9

6. **RSI** (5% weight)
   - Optimal: 50-65 for longs = 1.0 confidence
   - Good: 45-50 or 65-70 = 0.9 confidence
   - Acceptable: 40-45 or 70-75 = 0.8 confidence
   - Less ideal: outside these ranges = 0.7 confidence

7. **Golden Status** (multiplier)
   - Golden/exceptional tickers get 10% bonus (capped at 1.0)

**Formula**:
```python
confidence = (
    momentum_normalized * 0.30 +
    recent_avg_factor * 0.25 +
    spread_factor * 0.20 +
    volume_factor * 0.15 +
    rank_factor * 0.05 +
    rsi_factor * 0.05
) * golden_factor
# Clamped to 0.0-1.0
```

## Webhook Payload Structure

The webhook JSON payload now includes:

```json
{
  "ticker_symbol": "AAPL",
  "action": "BUY_TO_OPEN",
  "indicator": "Penny Stocks",
  "enter_reason": "...",
  "enter_price": 3.80,
  "technical_indicators": {...},
  "confidence_score": 0.85,
  ...
}
```

## Usage Example

Webhook receivers can use `confidence_score` to determine trade quantity:

```python
# Example: Scale position size based on confidence
base_quantity = 1000
quantity = int(base_quantity * confidence_score)

# Or use tiers
if confidence_score >= 0.9:
    quantity = large_position
elif confidence_score >= 0.7:
    quantity = medium_position
else:
    quantity = small_position
```

## Score Interpretation

- **0.9-1.0**: Very high confidence - strong momentum, optimal entry conditions
- **0.7-0.9**: High confidence - good momentum, favorable conditions
- **0.5-0.7**: Moderate confidence - acceptable conditions
- **0.3-0.5**: Low confidence - weaker conditions
- **0.0-0.3**: Very low confidence - poor conditions (should be rare as trades are filtered)

## Testing Recommendations

1. Monitor confidence scores in production logs
2. Correlate confidence scores with trade outcomes
3. Adjust weights if needed based on performance data
4. Track average confidence scores by indicator type
5. Validate that scores are reasonable (most trades should be 0.5-0.9 range)

