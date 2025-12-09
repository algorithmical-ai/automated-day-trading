# Requirements Document

## Introduction

This specification addresses critical bugs in the Momentum Trading Indicator's exit logic that are causing premature exits and consistent losses. Analysis of recent trades shows 7 consecutive losing trades with very short holding times (1-4 minutes), all exiting in the wrong direction. The root cause is the "dip from peak" exit logic that triggers on normal market noise rather than actual trend reversals.

## Glossary

- **Momentum Indicator**: A trading indicator that enters long positions on upward momentum and short positions on downward momentum
- **Peak Price Since Entry**: The highest price observed since a long trade was entered
- **Bottom Price Since Entry**: The lowest price observed since a short trade was entered
- **Dip from Peak**: The percentage drop from the peak price to the current price
- **Rise from Bottom**: The percentage rise from the bottom price to the current price
- **Profit from Entry**: The percentage profit/loss calculated from the entry price to the current price
- **Trailing Stop**: A dynamic stop loss that moves with the price to lock in profits

## Requirements

### Requirement 1

**User Story:** As a trader, I want the exit logic to only trigger profit-taking exits when the trade is actually profitable, so that I don't exit losing trades prematurely.

#### Acceptance Criteria

1. WHEN the Momentum Indicator evaluates a long trade for "dip from peak" exit THEN the Momentum Indicator SHALL only trigger the exit if the current profit from entry is positive (profit_from_entry > 0)
2. WHEN the Momentum Indicator evaluates a short trade for "rise from bottom" exit THEN the Momentum Indicator SHALL only trigger the exit if the current profit from entry is positive (profit_from_entry > 0)
3. WHEN a trade has negative profit from entry THEN the Momentum Indicator SHALL NOT trigger a "dip from peak" or "rise from bottom" exit regardless of peak/bottom calculations

### Requirement 2

**User Story:** As a trader, I want the peak/bottom price tracking to only consider prices that occurred after trade entry, so that exit decisions are based on actual trade performance.

#### Acceptance Criteria

1. WHEN the Momentum Indicator calculates peak_price_since_entry for a long trade THEN the Momentum Indicator SHALL only consider bar prices with timestamps after the trade's created_at timestamp
2. WHEN the Momentum Indicator calculates bottom_price_since_entry for a short trade THEN the Momentum Indicator SHALL only consider bar prices with timestamps after the trade's created_at timestamp
3. WHEN no bars exist after the trade entry timestamp THEN the Momentum Indicator SHALL use the entry price as the initial peak/bottom value

### Requirement 3

**User Story:** As a trader, I want a minimum profit threshold before profit-taking exits can trigger, so that normal market noise doesn't cause premature exits.

#### Acceptance Criteria

1. WHEN the Momentum Indicator evaluates a trade for "dip from peak" or "rise from bottom" exit THEN the Momentum Indicator SHALL require a minimum profit of 0.5% from entry before allowing the exit
2. WHEN a trade has profit from entry below 0.5% THEN the Momentum Indicator SHALL NOT trigger profit-taking exits regardless of dip/rise calculations
3. WHEN the minimum profit threshold is met THEN the Momentum Indicator SHALL use a 1.0% dip/rise threshold instead of 0.5% to reduce noise-triggered exits

### Requirement 4

**User Story:** As a trader, I want the exit logic to have a minimum time buffer after entry before profit-taking exits can trigger, so that initial price volatility doesn't cause immediate exits.

#### Acceptance Criteria

1. WHEN a trade has been held for less than 60 seconds THEN the Momentum Indicator SHALL NOT trigger "dip from peak" or "rise from bottom" exits
2. WHEN a trade has been held for 60 seconds or more AND meets profit thresholds THEN the Momentum Indicator SHALL evaluate dip/rise exit conditions normally
3. WHEN the minimum holding time is not met THEN the Momentum Indicator SHALL still evaluate stop loss conditions to protect against significant losses

### Requirement 5

**User Story:** As a trader, I want clear logging when profit-taking exits are skipped due to insufficient profit, so that I can understand why trades are being held.

#### Acceptance Criteria

1. WHEN a "dip from peak" exit is skipped due to negative profit THEN the Momentum Indicator SHALL log the skip reason including current profit percentage
2. WHEN a "rise from bottom" exit is skipped due to negative profit THEN the Momentum Indicator SHALL log the skip reason including current profit percentage
3. WHEN a profit-taking exit is skipped due to minimum profit threshold THEN the Momentum Indicator SHALL log the current profit and required threshold
