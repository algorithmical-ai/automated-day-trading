# Requirements Document: MAB Rejection Logging

## Introduction

When the Multi-Armed Bandit (MAB) service rejects a ticker during the entry cycle, the system should log the rejection reason to the `InactiveTickersForDayTrading` table. Currently, MAB rejects tickers based on their historical success rates (stored in `MABForDayTradingService` table), but these rejections are not being logged to the inactive tickers table. This feature ensures complete visibility into why tickers are not being traded, including MAB-based rejections.

## Glossary

- **MAB (Multi-Armed Bandit)**: Service that intelligently selects which tickers to trade based on historical success rates using Thompson Sampling
- **MAB Rejection**: When MAB filters out a ticker from the selection pool due to low historical success rate or exclusion status
- **InactiveTickersForDayTrading**: DynamoDB table that logs all tickers evaluated but not traded, including rejection reasons
- **reason_not_to_enter_long**: Field in InactiveTickersForDayTrading table explaining why a ticker was not entered as a long position
- **reason_not_to_enter_short**: Field in InactiveTickersForDayTrading table explaining why a ticker was not entered as a short position
- **Thompson Sampling**: Probabilistic algorithm used by MAB to rank tickers based on Beta distribution of historical success rates

## Requirements

### Requirement 1: Log MAB Rejections for Long Positions

**User Story:** As a trader, I want to see why MAB rejected a ticker for long entry, so that I can understand the MAB selection process and validate the algorithm's decisions.

#### Acceptance Criteria

1. WHEN a ticker passes all validation filters but is rejected by MAB for long entry THEN the system SHALL log the rejection to `InactiveTickersForDayTrading` table with `reason_not_to_enter_long` populated
2. WHEN MAB rejects a ticker for long entry THEN the `reason_not_to_enter_long` field SHALL include the historical success rate (successes/total trades) and Thompson Sampling score
3. WHEN a ticker is excluded from MAB selection (excluded_until timestamp is in future) THEN the system SHALL log the rejection with reason indicating exclusion status and exclusion end time
4. WHEN a new ticker has no historical data THEN the system SHALL log it as passed (not rejected) since new tickers are explored by Thompson Sampling

### Requirement 2: Log MAB Rejections for Short Positions

**User Story:** As a trader, I want to see why MAB rejected a ticker for short entry, so that I can understand the MAB selection process for short trades.

#### Acceptance Criteria

1. WHEN a ticker passes all validation filters but is rejected by MAB for short entry THEN the system SHALL log the rejection to `InactiveTickersForDayTrading` table with `reason_not_to_enter_short` populated
2. WHEN MAB rejects a ticker for short entry THEN the `reason_not_to_enter_short` field SHALL include the historical success rate (successes/total trades) and Thompson Sampling score
3. WHEN a ticker is excluded from MAB selection for short entry THEN the system SHALL log the rejection with reason indicating exclusion status
4. WHEN a new ticker has no historical data for short entry THEN the system SHALL log it as passed (not rejected) since new tickers are explored

### Requirement 3: Distinguish Between Validation Rejections and MAB Rejections

**User Story:** As a system analyst, I want to distinguish between tickers rejected by validation filters versus those rejected by MAB, so that I can analyze the effectiveness of each filtering stage.

#### Acceptance Criteria

1. WHEN a ticker is rejected by validation filters THEN the system SHALL log it with validation-specific rejection reasons (e.g., "Insufficient bars", "Low momentum")
2. WHEN a ticker passes validation but is rejected by MAB THEN the system SHALL log it with MAB-specific rejection reason (e.g., "MAB rejected: Low historical success rate")
3. WHEN logging MAB rejections THEN the reason field SHALL clearly indicate it is a MAB rejection (prefix with "MAB rejected:" or similar)
4. WHEN a ticker is not logged at all THEN it means the ticker was selected by MAB and entered as a trade

### Requirement 4: Include Technical Indicators in MAB Rejection Logs

**User Story:** As a data analyst, I want to see the technical indicators at the time of MAB rejection, so that I can correlate MAB decisions with market conditions.

#### Acceptance Criteria

1. WHEN logging a MAB rejection THEN the system SHALL include `technical_indicators` field with relevant metrics (momentum score, volume, price, etc.)
2. WHEN technical indicators are not available THEN the system SHALL log an empty or minimal technical_indicators object
3. WHEN logging MAB rejections THEN the technical_indicators field SHALL be consistent with the format used for validation rejections

### Requirement 5: Handle Direction-Specific MAB Rejections

**User Story:** As a trader, I want to see separate rejection reasons for long and short directions, so that I can understand if MAB rejects a ticker for one direction but not the other.

#### Acceptance Criteria

1. WHEN a ticker is rejected by MAB for long entry but passes for short entry THEN the system SHALL populate `reason_not_to_enter_long` with MAB rejection reason and leave `reason_not_to_enter_short` empty
2. WHEN a ticker is rejected by MAB for short entry but passes for long entry THEN the system SHALL populate `reason_not_to_enter_short` with MAB rejection reason and leave `reason_not_to_enter_long` empty
3. WHEN a ticker is rejected by MAB for both long and short entries THEN the system SHALL populate both `reason_not_to_enter_long` and `reason_not_to_enter_short` with appropriate MAB rejection reasons
4. WHEN a ticker passes MAB for both directions THEN the system SHALL NOT log it to InactiveTickersForDayTrading table (it was selected for trading)
