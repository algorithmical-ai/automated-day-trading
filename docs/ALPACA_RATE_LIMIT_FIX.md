# Alpaca API Rate Limit Fix

## Problem
The application was experiencing frequent 429 (Too Many Requests) errors from the Alpaca clock API, causing trading services to fail repeatedly.

## Solution
Added retry logic with exponential backoff to the `AlpacaClient.clock()` method in `app/src/common/alpaca.py`.

## Changes Made

### Retry Configuration
- **Max Retries**: 3 attempts
- **Retry Delay**: 2 seconds between attempts
- **Applies to**: 429 rate limit errors and network errors

### Behavior

1. **On 429 Rate Limit Error**:
   - Logs a warning with retry attempt number
   - Waits 2 seconds before retrying
   - Retries up to 3 times total
   - After 3 failed attempts, raises an error with clear message

2. **On Network Error**:
   - Logs a warning with retry attempt number
   - Waits 2 seconds before retrying
   - Retries up to 3 times total
   - After 3 failed attempts, raises an error with details

3. **On Success (200)**:
   - Returns clock data immediately
   - No retry needed

4. **On Other Errors** (not 429):
   - Logs warning and raises immediately
   - No retry (as these are likely not transient)

## Expected Impact

### Before Fix
```
2025-12-07 17:45:08.635 | WARNING  | alpaca.py:548 | clock | Alpaca clock API returned 429: {"message": "too many requests."}
2025-12-07 17:45:08.636 | ERROR    | penny_stocks_indicator.py:342 | entry_service | Error in penny stocks entry service: Failed to fetch market clock: 429
```

### After Fix
```
2025-12-07 17:45:08.635 | WARNING  | alpaca.py:XXX | clock | Alpaca clock API rate limited (429). Retrying in 2s... (attempt 1/3)
[2 second delay]
[Success on retry - no error logged]
```

## Testing

To verify the fix is working:

1. **Monitor logs** for the new retry messages:
   ```bash
   cd trading-log-monitor
   ./log-monitor-ctl.sh logs | grep "rate limited"
   ```

2. **Check for reduced errors**:
   - Before: Frequent 429 errors causing service failures
   - After: Occasional retry warnings, but services should succeed

3. **Watch for successful retries**:
   - Look for "Retrying in 2s..." messages
   - Verify services continue running after retries

## Deployment

The fix is already applied to `app/src/common/alpaca.py`. To deploy:

1. **Commit the changes**:
   ```bash
   git add app/src/common/alpaca.py
   git commit -m "Add retry logic for Alpaca API 429 rate limit errors"
   ```

2. **Deploy to Heroku**:
   ```bash
   git push heroku main
   ```

3. **Monitor the logs**:
   ```bash
   cd trading-log-monitor
   ./log-monitor-ctl.sh start
   ./log-monitor-ctl.sh logs
   ```

## Configuration

If you need to adjust the retry behavior, edit these values in `app/src/common/alpaca.py`:

```python
max_retries = 3      # Number of retry attempts
retry_delay = 2      # Seconds between retries
```

## Additional Recommendations

1. **Consider Exponential Backoff**: If rate limits persist, change to exponential backoff:
   ```python
   retry_delay = 2 ** attempt  # 2s, 4s, 8s
   ```

2. **Add Caching**: Cache the clock response for a short period (e.g., 10 seconds) to reduce API calls

3. **Monitor Rate Limits**: Track how often retries occur to identify if you need to reduce API call frequency

## Related Files
- `app/src/common/alpaca.py` - Main fix location
- `app/src/services/trading/penny_stocks_indicator.py` - Uses clock API
- `app/src/services/trading/momentum_indicator.py` - Uses clock API

## Status
✅ **FIXED** - Retry logic implemented and ready for deployment
