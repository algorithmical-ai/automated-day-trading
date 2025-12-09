# Requirements Document

## Introduction

The Momentum Trading Indicator is unable to compute momentum for tickers due to a data structure mismatch. The `TechnicalAnalysisLib.calculate_all_indicators()` method returns `datetime_price` as a dictionary (mapping timestamp strings to prices), but the `MomentumIndicator._calculate_momentum()` method expects it to be a list of entries. This causes the momentum calculation to fail, resulting in 0.00% momentum for all tickers and preventing any trades from being entered.

## Glossary

- **Momentum Indicator**: A trading indicator that analyzes price momentum to identify entry and exit signals
- **datetime_price**: A data structure containing historical price data with timestamps
- **TechnicalAnalysisLib**: A library that calculates technical indicators including datetime_price
- **MomentumIndicator**: The trading indicator class that uses momentum calculations for trade decisions
- **InactiveTickersForDayTrading**: A DynamoDB table that logs reasons why tickers were not entered into trades

## Requirements

### Requirement 1

**User Story:** As a trading system, I want the momentum indicator to correctly parse datetime_price data, so that momentum calculations produce accurate results and enable trade entries.

#### Acceptance Criteria

1. WHEN TechnicalAnalysisLib returns datetime_price as a dictionary THEN the MomentumIndicator SHALL correctly extract price values for momentum calculation
2. WHEN datetime_price contains timestamp-to-price mappings THEN the system SHALL convert them to a format compatible with momentum calculation
3. WHEN momentum is calculated from datetime_price THEN the system SHALL produce non-zero momentum values for tickers with actual price movement
4. WHEN datetime_price is empty or invalid THEN the system SHALL return 0.0 momentum with an appropriate reason message
5. WHEN datetime_price contains fewer than 3 data points THEN the system SHALL return 0.0 momentum with "Insufficient price data" reason

### Requirement 2

**User Story:** As a developer, I want the _calculate_momentum method to handle both dict and list formats for datetime_price, so that the system is resilient to data structure changes.

#### Acceptance Criteria

1. WHEN datetime_price is a dictionary with timestamp keys THEN the system SHALL extract prices in chronological order
2. WHEN datetime_price is a list of entries THEN the system SHALL extract prices using the existing logic
3. WHEN datetime_price format is unrecognized THEN the system SHALL log a warning and return 0.0 momentum
4. WHEN extracting prices from dictionary format THEN the system SHALL sort by timestamp to maintain chronological order
5. WHEN prices are extracted successfully THEN the system SHALL calculate momentum using the early-vs-recent average comparison

### Requirement 3

**User Story:** As a trading system, I want accurate momentum calculations to enable proper trade filtering, so that only tickers with sufficient momentum are considered for entry.

#### Acceptance Criteria

1. WHEN momentum is calculated THEN the system SHALL compare early period average to recent period average
2. WHEN momentum exceeds the minimum threshold THEN the ticker SHALL pass the momentum filter
3. WHEN momentum is below the minimum threshold THEN the ticker SHALL be rejected with a clear reason logged to InactiveTickersForDayTrading
4. WHEN momentum calculation fails THEN the system SHALL log the failure reason and reject the ticker
5. WHEN a ticker is rejected due to insufficient momentum THEN the rejection reason SHALL include the calculated momentum value and threshold

### Requirement 4

**User Story:** As a system operator, I want clear logging of momentum calculation failures, so that I can diagnose and fix data structure issues quickly.

#### Acceptance Criteria

1. WHEN datetime_price format is unexpected THEN the system SHALL log the actual format received
2. WHEN momentum calculation fails THEN the system SHALL log the ticker symbol and error details
3. WHEN a ticker is rejected THEN the system SHALL write the rejection reason to InactiveTickersForDayTrading table
4. WHEN datetime_price is successfully parsed THEN the system SHALL log the number of price points extracted at debug level
5. WHEN the system encounters a new datetime_price format THEN the system SHALL log a warning with format details
