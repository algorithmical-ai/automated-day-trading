# Requirements Document

## Introduction

This specification defines the trade entry validation logic for the Penny Stock Indicator system. The system analyzes penny stocks (stocks valued under $5 USD) and determines whether to enter long or short positions based on trend analysis, price levels, and data quality checks. The validation logic ensures that trades are only entered when conditions are favorable, reducing risk and improving profitability.

## Glossary

- **Penny Stock**: A stock with a price below $5.00 USD
- **Long Entry**: Buying a stock with the expectation that its price will increase
- **Short Entry**: Selling a stock short with the expectation that its price will decrease
- **Trend Continuation**: A measure (0.0-1.0) of how consistently recent price bars continue in the same direction
- **Momentum Score**: A percentage representing the strength and direction of price movement over recent bars
- **Peak Price**: The highest price observed in the recent bars window
- **Bottom Price**: The lowest price observed in the recent bars window
- **Bid-Ask Spread**: The difference between the highest price a buyer is willing to pay (bid) and the lowest price a seller is willing to accept (ask)
- **Recent Bars**: The last 5 price bars used for trend analysis
- **InactiveTickersForDayTrading**: DynamoDB table storing tickers that failed entry validation with rejection reasons

## Requirements

### Requirement 1

**User Story:** As a trading system, I want to validate trend direction before entering trades, so that I only enter long positions during upward trends and short positions during downward trends.

#### Acceptance Criteria

1. WHEN recent bars show a downward trend (negative momentum score) THEN the system SHALL reject long entry and record the reason as "Recent bars show downward trend"
2. WHEN recent bars show an upward trend (positive momentum score) THEN the system SHALL reject short entry and record the reason as "Recent bars show upward trend"
3. WHEN the system calculates momentum score THEN the system SHALL use the last 5 price bars to determine trend direction
4. WHEN recording rejection reasons THEN the system SHALL include the momentum score percentage in the reason text
5. WHEN a ticker is rejected for trend direction THEN the system SHALL store both long and short rejection reasons in InactiveTickersForDayTrading table

### Requirement 2

**User Story:** As a trading system, I want to validate trend continuation strength, so that I avoid entering trades when trends are losing momentum or reversing.

#### Acceptance Criteria

1. WHEN trend continuation score is below 0.7 for an upward trend THEN the system SHALL reject long entry with reason "trend is not continuing strongly"
2. WHEN trend continuation score is below 0.7 for a downward trend THEN the system SHALL reject short entry with reason "trend is not continuing strongly"
3. WHEN calculating continuation score THEN the system SHALL measure the proportion of recent price changes moving in the trend direction
4. WHEN continuation is weak THEN the system SHALL include the continuation score value in the rejection reason
5. WHEN a ticker shows weak continuation THEN the system SHALL still allow entry in the opposite direction if other criteria are met

### Requirement 3

**User Story:** As a trading system, I want to detect when prices are at extreme levels, so that I avoid entering long positions near peaks and short positions near bottoms.

#### Acceptance Criteria

1. WHEN current price is within 1.0% of the peak price during an upward trend THEN the system SHALL reject long entry with reason "at/near peak"
2. WHEN current price is within 1.0% of the bottom price during a downward trend THEN the system SHALL reject short entry with reason "at/near bottom"
3. WHEN checking price extremes THEN the system SHALL calculate the percentage difference between current price and peak/bottom
4. WHEN recording extreme price rejections THEN the system SHALL include both current price and extreme price values in the reason
5. WHEN price is at an extreme for one direction THEN the system SHALL still allow entry in the opposite direction if other criteria are met

### Requirement 4

**User Story:** As a trading system, I want to enforce minimum and maximum momentum thresholds, so that I only enter trades with sufficient but not excessive price movement.

#### Acceptance Criteria

1. WHEN absolute momentum score is below 3.0% THEN the system SHALL reject entry in the trend direction with reason "weak trend"
2. WHEN absolute momentum score exceeds 10.0% THEN the system SHALL reject entry in the trend direction with reason "excessive trend"
3. WHEN momentum is too weak for long entry THEN the system SHALL include the minimum threshold value (3.0%) in the rejection reason
4. WHEN momentum is too strong for entry THEN the system SHALL include the maximum threshold value (10.0%) in the rejection reason
5. WHEN momentum is outside acceptable range THEN the system SHALL record direction-specific rejection reasons for both long and short

### Requirement 5

**User Story:** As a trading system, I want to validate data quality before analysis, so that I only make trading decisions based on sufficient and reliable market data.

#### Acceptance Criteria

1. WHEN market data response is empty or null THEN the system SHALL reject both long and short entry with reason "No market data response"
2. WHEN the number of available bars is less than 5 THEN the system SHALL reject both long and short entry with reason "Insufficient bars data"
3. WHEN recording insufficient bars rejection THEN the system SHALL include both required count (5) and actual count in the reason
4. WHEN data quality check fails THEN the system SHALL apply the same rejection reason to both long and short directions
5. WHEN a ticker fails data quality checks THEN the system SHALL store the rejection in InactiveTickersForDayTrading table

### Requirement 6

**User Story:** As a trading system, I want to validate liquidity through bid-ask spread analysis, so that I avoid trading illiquid stocks with poor execution quality.

#### Acceptance Criteria

1. WHEN bid-ask spread percentage exceeds 2.0% THEN the system SHALL reject both long and short entry
2. WHEN calculating spread percentage THEN the system SHALL divide the spread by the mid-price and multiply by 100
3. WHEN recording spread rejection THEN the system SHALL include the actual spread percentage and threshold (2.0%) in the reason
4. WHEN bid or ask price is zero or negative THEN the system SHALL reject entry with reason "Invalid bid/ask"
5. WHEN spread is too wide THEN the system SHALL apply the same rejection reason to both long and short directions

### Requirement 7

**User Story:** As a trading system, I want to store rejection reasons in a structured format, so that I can analyze patterns and improve the trading strategy over time.

#### Acceptance Criteria

1. WHEN a ticker fails entry validation THEN the system SHALL write a record to InactiveTickersForDayTrading table
2. WHEN writing rejection records THEN the system SHALL include ticker symbol, indicator name, timestamp, and technical indicators
3. WHEN a rejection is direction-specific THEN the system SHALL populate reason_not_to_enter_long or reason_not_to_enter_short accordingly
4. WHEN a rejection applies to both directions THEN the system SHALL populate both reason_not_to_enter_long and reason_not_to_enter_short with the same reason
5. WHEN storing technical indicators THEN the system SHALL include relevant metrics such as momentum score, continuation score, peak price, and bottom price

### Requirement 8

**User Story:** As a trading system, I want to batch write rejection records efficiently, so that I minimize database operations and improve performance.

#### Acceptance Criteria

1. WHEN processing multiple tickers in an entry cycle THEN the system SHALL collect all rejection records before writing to the database
2. WHEN the entry cycle completes THEN the system SHALL write all collected rejection records in a single batch operation
3. WHEN batch writing fails THEN the system SHALL log the error without blocking the entry cycle
4. WHEN collecting rejection records THEN the system SHALL maintain a list of dictionaries with all required fields
5. WHEN a ticker passes validation THEN the system SHALL not include it in the rejection records batch
