# Requirements Document

## Introduction

This feature addresses critical issues in the Penny Stocks trading algorithm that is causing consistent losses. The current implementation exits trades too aggressively, doesn't account for bid-ask spread, and doesn't give trades room to develop. The goal is to implement a more robust exit strategy that allows trades to breathe while still protecting against significant losses.

## Glossary

- **Penny Stock**: Stock trading below $5 USD
- **Bid-Ask Spread**: Difference between highest bid price and lowest ask price, expressed as a percentage
- **Trailing Stop**: A stop-loss order that moves with the price to lock in profits
- **ATR (Average True Range)**: A volatility indicator measuring the average range of price movement
- **Breakeven Buffer**: A percentage buffer above entry price that accounts for bid-ask spread before considering a trade profitable
- **Peak Profit**: The highest profit percentage achieved during a trade's lifetime
- **Profit Lock Threshold**: The minimum profit level at which trailing stop protection activates

## Requirements

### Requirement 1

**User Story:** As a trader, I want the algorithm to account for bid-ask spread when determining profitability, so that I don't exit trades prematurely due to spread-induced paper losses.

#### Acceptance Criteria

1. WHEN entering a long trade, THE Penny Stocks Indicator SHALL calculate a breakeven price that includes the typical bid-ask spread (entry price + spread buffer)
2. WHEN evaluating trade profitability, THE Penny Stocks Indicator SHALL compare current price against the breakeven price rather than raw entry price
3. WHEN the bid-ask spread exceeds 3%, THE Penny Stocks Indicator SHALL reject the ticker for entry

### Requirement 2

**User Story:** As a trader, I want trades to have room to develop before being stopped out, so that normal price fluctuations don't trigger premature exits.

#### Acceptance Criteria

1. WHEN a trade is in the initial holding period (first 60 seconds), THE Penny Stocks Indicator SHALL only exit on significant losses exceeding -3%
2. WHEN a trade has not yet reached breakeven, THE Penny Stocks Indicator SHALL use a wider stop loss of -2% instead of immediate exit
3. WHEN evaluating exit conditions, THE Penny Stocks Indicator SHALL require the loss to persist for at least 2 consecutive price checks before exiting

### Requirement 3

**User Story:** As a trader, I want a tiered trailing stop system that protects profits while allowing winners to run, so that I can maximize gains on successful trades.

#### Acceptance Criteria

1. WHEN a trade reaches 1% profit, THE Penny Stocks Indicator SHALL activate a trailing stop at 0.5% below peak
2. WHEN a trade reaches 2% profit, THE Penny Stocks Indicator SHALL tighten the trailing stop to 0.3% below peak
3. WHEN a trade reaches 3% profit, THE Penny Stocks Indicator SHALL lock in at least 1.5% profit by setting stop at peak minus 1.5%
4. WHEN the trailing stop is triggered, THE Penny Stocks Indicator SHALL exit the trade and log the profit locked

### Requirement 4

**User Story:** As a trader, I want the algorithm to use volatility-based stop losses, so that stop distances are appropriate for each stock's price behavior.

#### Acceptance Criteria

1. WHEN entering a trade, THE Penny Stocks Indicator SHALL calculate ATR from recent bars
2. WHEN setting initial stop loss, THE Penny Stocks Indicator SHALL use 1.5x ATR as the stop distance, with a minimum of -1.5% and maximum of -4%
3. WHEN ATR cannot be calculated, THE Penny Stocks Indicator SHALL use a default stop loss of -2%

### Requirement 5

**User Story:** As a trader, I want the minimum holding period increased, so that trades have time to develop momentum.

#### Acceptance Criteria

1. WHEN a trade is entered, THE Penny Stocks Indicator SHALL enforce a minimum holding period of 60 seconds before any profit-taking exit
2. WHEN within the minimum holding period, THE Penny Stocks Indicator SHALL only exit on stop loss conditions (not profit targets)
3. WHEN the minimum holding period expires, THE Penny Stocks Indicator SHALL evaluate all exit conditions including profit targets

### Requirement 6

**User Story:** As a trader, I want better entry timing based on momentum confirmation, so that I enter trades with stronger directional conviction.

#### Acceptance Criteria

1. WHEN evaluating entry, THE Penny Stocks Indicator SHALL require momentum to be confirmed by at least 3 of the last 5 bars moving in the trend direction
2. WHEN the most recent bar moves against the trend, THE Penny Stocks Indicator SHALL skip entry and wait for confirmation
3. WHEN entering a trade, THE Penny Stocks Indicator SHALL log the momentum confirmation details

### Requirement 7

**User Story:** As a trader, I want the algorithm to track and report performance metrics, so that I can evaluate the effectiveness of the changes.

#### Acceptance Criteria

1. WHEN a trade exits, THE Penny Stocks Indicator SHALL log the hold duration, entry reason, exit reason, and profit/loss
2. WHEN the trading day ends, THE Penny Stocks Indicator SHALL calculate and log win rate, average win, average loss, and profit factor
3. WHEN a trade is stopped out, THE Penny Stocks Indicator SHALL record whether it was a spread-induced loss or genuine price movement
