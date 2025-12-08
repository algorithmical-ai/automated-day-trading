# Requirements Document

## Introduction

This specification defines a simplified trade entry validation logic for the Penny Stock Indicator system. The system analyzes penny stocks (stocks valued under $5 USD) and determines whether to enter long or short positions based on momentum-driven trend analysis and liquidity checks. The validation logic uses a streamlined approach where momentum score is the primary driver for trend-based decisions, and empty rejection reasons indicate valid entry opportunities.

## Glossary

- **Penny Stock**: A stock with a price below $5.00 USD
- **Long Entry**: Buying a stock with the expectation that its price will increase
- **Short Entry**: Selling a stock short with the expectation that its price will decrease
- **Momentum Score**: A calculated value representing the strength and direction of price movement over recent bars, considering both price change percentage and move consistency
- **Continuation Score**: A measure (0.0-1.0) of how consistently recent price bars continue in the same direction
- **Peak Price**: The highest price observed in the recent bars window
- **Bottom Price**: The lowest price observed in the recent bars window
- **Bid-Ask Spread**: The difference between the highest price a buyer is willing to pay (bid) and the lowest price a seller is willing to accept (ask)
- **Recent Bars**: The last 5 price bars used for trend analysis
- **InactiveTickersForDayTrading**: DynamoDB table storing tickers that failed entry validation with rejection reasons
- **Valid Entry**: A direction (long or short) where the rejection reason field is an empty string ("")

## Requirements

### Requirement 1

**User Story:** As a trading system, I want to validate trend direction using momentum score before entering trades, so that I only enter long positions during upward trends and short positions during downward trends.

#### Acceptance Criteria

1. WHEN momentum score is negative (< 0) THEN the system SHALL reject long entry and record the reason as "Recent bars show downward trend (X.XX%), not suitable for long entry"
2. WHEN momentum score is positive (> 0) THEN the system SHALL reject short entry and record the reason as "Recent bars show upward trend (X.XX%), not suitable for short entry"
3. WHEN the system calculates momentum score THEN the system SHALL use the last 5 price bars to determine trend direction
4. WHEN recording rejection reasons THEN the system SHALL include the momentum score value in the reason text
5. WHEN momentum score is negative THEN the system SHALL leave reason_not_to_enter_short as empty string to indicate short entry is valid

### Requirement 2

**User Story:** As a trading system, I want to validate liquidity through bid-ask spread analysis, so that I avoid trading illiquid stocks with poor execution quality.

#### Acceptance Criteria

1. WHEN bid-ask spread percentage exceeds 2.0% THEN the system SHALL reject both long and short entry
2. WHEN calculating spread percentage THEN the system SHALL divide the spread by the mid-price and multiply by 100
3. WHEN recording spread rejection THEN the system SHALL include the actual spread percentage and threshold (2.0%) in the reason as "Bid-ask spread too wide: X.XX% > 2.0%"
4. WHEN spread is too wide THEN the system SHALL apply the same rejection reason to both reason_not_to_enter_long and reason_not_to_enter_short
5. WHEN bid or ask price is zero or negative THEN the system SHALL reject entry with reason "Invalid bid/ask prices"

### Requirement 3

**User Story:** As a trading system, I want to store rejection reasons and technical indicators in a structured format, so that I can analyze patterns and improve the trading strategy over time.

#### Acceptance Criteria

1. WHEN a ticker is evaluated THEN the system SHALL write a record to InactiveTickersForDayTrading table
2. WHEN writing records THEN the system SHALL include ticker symbol, indicator name ("Penny Stocks"), timestamp, and technical_indicators JSON
3. WHEN a direction is valid for entry THEN the system SHALL set the corresponding reason field (reason_not_to_enter_long or reason_not_to_enter_short) to empty string ("")
4. WHEN a direction is invalid for entry THEN the system SHALL populate the corresponding reason field with a descriptive rejection message
5. WHEN storing technical indicators THEN the system SHALL include momentum_score, continuation_score, peak_price, bottom_price, and reason fields in JSON format

### Requirement 4

**User Story:** As a trading system, I want to calculate momentum score from price bars, so that I can make informed trend-based entry decisions.

#### Acceptance Criteria

1. WHEN calculating momentum score THEN the system SHALL use the last 5 price bars
2. WHEN calculating momentum score THEN the system SHALL consider both overall price change percentage and the ratio of up moves to down moves
3. WHEN calculating momentum score THEN the system SHALL produce a value that amplifies small price changes based on move consistency
4. WHEN all price bars are identical THEN the system SHALL set momentum score to 0.0
5. WHEN insufficient bars are available (< 5) THEN the system SHALL calculate momentum score using available bars

### Requirement 5

**User Story:** As a trading system, I want to calculate continuation score from price bars, so that I can include this metric in technical indicators for analysis.

#### Acceptance Criteria

1. WHEN calculating continuation score THEN the system SHALL measure the proportion of recent price changes moving in the overall trend direction
2. WHEN calculating continuation score THEN the system SHALL produce a value between 0.0 and 1.0
3. WHEN all moves are in the same direction THEN the system SHALL set continuation score to 1.0
4. WHEN moves are evenly split between directions THEN the system SHALL set continuation score to approximately 0.5
5. WHEN storing continuation score THEN the system SHALL include it in the technical_indicators JSON field

### Requirement 6

**User Story:** As a trading system, I want to identify peak and bottom prices from recent bars, so that I can include these metrics in technical indicators for analysis.

#### Acceptance Criteria

1. WHEN analyzing recent bars THEN the system SHALL identify the highest price as peak_price
2. WHEN analyzing recent bars THEN the system SHALL identify the lowest price as bottom_price
3. WHEN storing peak and bottom prices THEN the system SHALL include them in the technical_indicators JSON field
4. WHEN only one bar is available THEN the system SHALL set both peak_price and bottom_price to that bar's price
5. WHEN bars contain invalid prices (null, negative) THEN the system SHALL filter them out before calculating peak and bottom

### Requirement 7

**User Story:** As a trading system, I want to generate a human-readable reason string describing the trend calculation, so that I can understand the basis for entry decisions.

#### Acceptance Criteria

1. WHEN calculating trend metrics THEN the system SHALL generate a reason string in the format "Recent trend (5 bars): X.XX% change, N up/M down moves, peak=$X, bottom=$Y, continuation=Z"
2. WHEN storing the reason string THEN the system SHALL include it in the technical_indicators JSON field
3. WHEN the number of bars is less than 5 THEN the system SHALL include the actual bar count in the reason string
4. WHEN recording up and down moves THEN the system SHALL count the number of bars where price increased vs decreased
5. WHEN formatting prices in the reason THEN the system SHALL use two decimal places

### Requirement 8

**User Story:** As a trading system, I want to batch write all ticker evaluations efficiently, so that I minimize database operations and improve performance.

#### Acceptance Criteria

1. WHEN processing multiple tickers in an entry cycle THEN the system SHALL collect all evaluation records before writing to the database
2. WHEN the entry cycle completes THEN the system SHALL write all collected records in a single batch operation
3. WHEN batch writing fails THEN the system SHALL log the error without blocking the entry cycle
4. WHEN collecting records THEN the system SHALL include both passing tickers (empty rejection reasons) and failing tickers (populated rejection reasons)
5. WHEN a ticker passes validation for both directions THEN the system SHALL write a record with both reason fields as empty strings
