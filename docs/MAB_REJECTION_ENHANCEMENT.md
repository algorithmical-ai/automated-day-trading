# MAB Rejection Enhancement for InactiveTickersForDayTrading

This document explains how to enhance the `InactiveTickersForDayTrading` table with comprehensive MAB (Multi-Armed Bandit) rejection reasons.

## Problem Statement

The `InactiveTickersForDayTrading` table contains records of tickers that were evaluated but not traded. However, many records have empty `reason_not_to_enter_long` and `reason_not_to_enter_short` fields, creating confusion about whether tickers were:

1. **Rejected by MAB** (not selected for trading) - BAD outcome
2. **Selected by MAB** but failed entry validation - NEEDS INVESTIGATION  
3. **Successfully traded** (should appear in ActiveTickers) - GOOD outcome

This ambiguity makes it difficult to analyze MAB performance and debug trading issues.

## Solution Overview

The MAB Rejection Enhancement system provides:

1. **Historical Enhancement**: Backfill empty rejection reasons in existing records
2. **Real-time Enhancement**: Ensure new records always have populated rejection reasons
3. **Comprehensive Logging**: Log ALL ticker outcomes with clear categorization
4. **Enhanced Reporting**: Generate detailed CSV exports for analysis

### Comprehensive Ticker Outcome Logging

The enhanced system now logs **every ticker** with clear outcome categories:

- ❌ **MAB Rejected**: Passed validation but not selected by MAB
- ✅ **MAB Selected**: Chosen by MAB for trading attempt  
- ⚠️ **Selected but Failed Entry**: Chosen by MAB but failed entry validation
- 🚀 **Successfully Traded**: Entered active trade (appears in ActiveTickers)

## Key Components

### 1. MABRejectionEnhancer (`app/src/services/mab/mab_rejection_enhancer.py`)

Main class that provides:
- `enhance_empty_rejection_records()`: Backfill existing records
- `enhance_real_time_record()`: Generate reasons for new records
- `generate_enhanced_csv_export()`: Create enhanced CSV files

### 2. Enhanced Penny Stocks Indicator

The penny stocks indicator has been enhanced to automatically populate rejection reasons using the MAB rejection enhancer when MAB data is not available.

### 3. Utility Scripts

- `scripts/enhance_mab_rejections.py`: Full-featured CLI tool
- `scripts/run_mab_enhancement.py`: Quick enhancement script

## Types of Rejection Reasons

### MAB Rejection Reasons (❌ Not Selected)

When tickers pass validation but MAB doesn't select them:

```
MAB rejected: Low historical success rate (30.0%) (successes: 3, failures: 7, total: 10)
MAB rejected: Excluded until 2024-12-10T15:30:00-05:00 (successes: 0, failures: 3, total: 3)
MAB: New ticker - not selected by Thompson Sampling (successes: 0, failures: 0, total: 0)
```

### MAB Selection Reasons (✅ Selected)

When tickers are chosen by MAB for trading:

```
✅ Selected by MAB for long entry - ranked in top 2 (success rate: 75.0%, momentum: 3.2%)
✅ Selected by MAB for short entry - ranked in top 2 (new ticker, momentum: -2.8%)
```

### Entry Failure Reasons (⚠️ Selected but Failed)

When MAB-selected tickers fail entry validation:

```
⚠️ Selected by MAB for long entry (momentum: 4.1%) but failed validation: Bid-ask spread too wide: 5.2% > max 3.0%
⚠️ Selected by MAB for long entry (momentum: 2.9%) but failed validation: At max capacity (10/10), momentum 2.9% < exceptional threshold 8.0%
⚠️ Selected by MAB for long entry (momentum: 3.5%) but failed validation: Momentum not confirmed: only 2/5 bars in trend
```

### Generic Rejections

When MAB data is not available:

```
Momentum too low for entry: 0.8% (minimum: 1.5%)
No entry signal generated - insufficient momentum data or market conditions not met
Not selected for entry - may be due to MAB ranking, capacity limits, or market timing
```

## Usage Instructions

### Quick Enhancement (Recommended)

Run the quick enhancement script to backfill existing records and generate an enhanced CSV:

```bash
python scripts/run_mab_enhancement.py
```

This will:
1. Enhance existing records with empty rejection reasons
2. Generate `enhanced_penny_stocks_with_mab_reasons.csv`
3. Show detailed statistics about the improvements

### Advanced Usage

For more control, use the full-featured script:

```bash
# Enhance existing records only
python scripts/enhance_mab_rejections.py --enhance

# Export enhanced CSV only (no database updates)
python scripts/enhance_mab_rejections.py --export

# Both enhance and export
python scripts/enhance_mab_rejections.py --enhance --export

# Specify different indicator
python scripts/enhance_mab_rejections.py --enhance --indicator "Momentum Trading"
```

### Programmatic Usage

```python
from app.src.services.mab.mab_rejection_enhancer import MABRejectionEnhancer

# Create enhancer instance
enhancer = MABRejectionEnhancer()

# Enhance existing records
stats = await enhancer.enhance_empty_rejection_records(
    indicator="Penny Stocks",
    hours_lookback=24
)

# Generate real-time rejection reason
reasons = await MABRejectionEnhancer.enhance_real_time_record(
    ticker="AAPL",
    indicator="Penny Stocks",
    technical_indicators={"momentum_score": 2.5}
)

# Export enhanced CSV
csv_file = await enhancer.generate_enhanced_csv_export(
    indicator="Penny Stocks",
    hours_lookback=48,
    output_file="enhanced_data.csv"
)
```

## Enhanced CSV Format

The enhanced CSV includes all original fields plus populated rejection reasons:

```csv
ticker,indicator,reason_not_to_enter_long,reason_not_to_enter_short,technical_indicators,timestamp
AAPL,Penny Stocks,"MAB rejected: Low success rate (30.0%) (successes: 3, failures: 7, total: 10)","","{""close_price"": 150.0, ""volume"": 1000}",2024-12-10T10:30:00-05:00
GOOGL,Penny Stocks,"","MAB rejected: Excluded until 2024-12-10T15:30:00-05:00 (successes: 0, failures: 2, total: 2)","{""close_price"": 2800.0, ""volume"": 500}",2024-12-10T10:31:00-05:00
```

## Understanding MAB Rejection Reasons

### Success Rate Rejections

```
MAB rejected: Low historical success rate (30.0%) (successes: 3, failures: 7, total: 10)
```

- The ticker has a 30% historical success rate (3 wins out of 10 trades)
- MAB algorithm ranked it below other candidates with better success rates

### Exclusion Rejections

```
MAB rejected: Excluded until 2024-12-10T15:30:00-05:00 (successes: 0, failures: 3, total: 3)
```

- The ticker is temporarily excluded from trading due to recent losses
- Exclusion typically lasts until end of trading day for penny stocks

### New Ticker Rejections

```
MAB: New ticker - not selected by Thompson Sampling (successes: 0, failures: 0, total: 0)
```

- The ticker has no trading history
- Thompson Sampling algorithm chose to explore other tickers instead

## Benefits

### For Analysis

1. **Complete Picture**: Every record now has a rejection reason
2. **MAB Insights**: Understand how the MAB algorithm makes decisions
3. **Performance Tracking**: See which tickers are consistently rejected and why
4. **Strategy Optimization**: Identify patterns in rejections to improve algorithms

### For Debugging

1. **Troubleshooting**: Quickly identify why specific tickers weren't traded
2. **Algorithm Validation**: Verify MAB algorithm is working as expected
3. **Data Quality**: Ensure all evaluation results are properly logged

### For Reporting

1. **Comprehensive Reports**: Generate complete trading activity reports
2. **Stakeholder Communication**: Explain trading decisions with data
3. **Compliance**: Maintain detailed audit trails of all trading decisions

## Configuration

### Environment Variables

The enhancer uses the same AWS credentials as the main application:

```bash
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
```

### Customization

You can customize the enhancement behavior by modifying:

- `hours_lookback`: How far back to look for records (default: 24 hours)
- `batch_size`: Number of records to process at once (default: 25)
- Rejection reason templates in the `MABRejectionEnhancer` class

## Monitoring and Maintenance

### Regular Enhancement

Consider running the enhancement script daily to keep rejection reasons up to date:

```bash
# Add to cron job
0 2 * * * /path/to/python /path/to/scripts/run_mab_enhancement.py
```

### Performance Considerations

- The enhancement process uses DynamoDB scan operations, which can be expensive for large datasets
- Consider implementing a GSI (Global Secondary Index) on `indicator + timestamp` for better performance
- Batch processing helps manage DynamoDB throughput limits

### Monitoring

Monitor the enhancement process through:

1. **Logs**: Check application logs for enhancement statistics
2. **Metrics**: Track success rates and error counts
3. **Data Quality**: Regularly verify rejection reason coverage

## Troubleshooting

### Common Issues

1. **Empty Rejection Reasons**: If reasons are still empty after enhancement, check MAB service connectivity
2. **Performance Issues**: Reduce batch size or add delays between batches
3. **AWS Permissions**: Ensure DynamoDB read/write permissions are configured

### Error Handling

The enhancement process includes comprehensive error handling:

- Individual record failures don't stop the entire batch
- Detailed error logging helps identify specific issues
- Graceful degradation when MAB data is unavailable

## Future Enhancements

Potential improvements:

1. **Real-time Streaming**: Enhance records as they're created using DynamoDB Streams
2. **Machine Learning**: Use ML to predict rejection reasons when data is incomplete
3. **Advanced Analytics**: Add more sophisticated rejection reason categorization
4. **Performance Optimization**: Implement GSI for faster queries

## Testing

Run the test suite to verify functionality:

```bash
python -m pytest tests/test_mab_rejection_enhancer.py -v
```

The tests cover:
- MAB rejection reason generation
- Generic rejection reason creation
- Record enhancement logic
- Error handling scenarios
- Real-time enhancement functionality