# Requirements Document

## Introduction

This feature improves the penny stocks trading algorithm to detect and avoid entering trades at or near local price peaks. The current algorithm suffered significant losses ($287.35 on January 20, 2026) due to entering trades with high confidence scores (86-92%) that immediately reversed. The improvements focus on peak detection, enhanced confidence scoring, momentum deceleration detection, tighter stop losses for quick reversals, and dynamic position sizing.

## Glossary

- **Peak_Detector**: Component that identifies when price is at or near a local maximum relative to recent price history
- **Confidence_Calculator**: Component that calculates a predictive confidence score incorporating peak proximity, volume confirmation, and momentum acceleration
- **Momentum_Analyzer**: Component that detects momentum deceleration and acceleration patterns
- **Stop_Loss_Manager**: Component that manages dynamic stop losses based on trade conditions
- **Position_Sizer**: Component that determines position size based on confidence score and volatility
- **TrendAnalyzer**: Existing component that calculates trend metrics from price bars
- **Continuation_Score**: Metric (0.0-1.0) indicating how strongly the recent price action continues the overall trend
- **Peak_Proximity_Score**: Metric (0.0-1.0) indicating how close current price is to the recent peak (1.0 = at peak)
- **Volume_Confirmation_Score**: Metric (0.0-1.0) indicating whether volume supports the price movement
- **Momentum_Acceleration**: Rate of change of momentum (positive = accelerating, negative = decelerating)

## Requirements

### Requirement 1: Peak Detection

**User Story:** As a trader, I want the algorithm to detect when price is at or near a local peak, so that I can avoid entering long positions that are likely to reverse.

#### Acceptance Criteria

1. WHEN analyzing a ticker for entry, THE Peak_Detector SHALL calculate a peak_proximity_score between 0.0 and 1.0
2. WHEN the current price equals the highest price in the lookback window, THE Peak_Detector SHALL return a peak_proximity_score of 1.0
3. WHEN the current price is more than 3% below the peak price, THE Peak_Detector SHALL return a peak_proximity_score below 0.5
4. WHEN the peak_proximity_score exceeds 0.85, THE System SHALL reject the entry with reason "Price too close to local peak"
5. THE Peak_Detector SHALL use a configurable lookback window (default: 10 bars) for peak identification

### Requirement 2: Enhanced Confidence Scoring

**User Story:** As a trader, I want the confidence score to better predict trade outcomes, so that high confidence trades are more likely to be winners.

#### Acceptance Criteria

1. THE Confidence_Calculator SHALL incorporate peak_proximity_score with a negative weight (closer to peak = lower confidence)
2. THE Confidence_Calculator SHALL incorporate volume_confirmation_score with a positive weight (higher volume = higher confidence)
3. THE Confidence_Calculator SHALL incorporate momentum_acceleration with a positive weight (accelerating momentum = higher confidence)
4. WHEN calculating confidence, THE Confidence_Calculator SHALL weight factors as: momentum (25%), peak_proximity (25%), volume_confirmation (25%), momentum_acceleration (25%)
5. THE Confidence_Calculator SHALL output a score between 0.0 and 1.0
6. WHEN serializing confidence calculations, THE Confidence_Calculator SHALL encode them as JSON for logging

### Requirement 3: Volume Confirmation

**User Story:** As a trader, I want to verify that volume supports the price movement, so that I can avoid entering trades on weak volume.

#### Acceptance Criteria

1. THE Volume_Analyzer SHALL calculate volume_confirmation_score between 0.0 and 1.0
2. WHEN current volume exceeds the 20-bar average volume by 50% or more, THE Volume_Analyzer SHALL return a score of 1.0
3. WHEN current volume is below the 20-bar average volume, THE Volume_Analyzer SHALL return a score proportional to the ratio (current/average)
4. WHEN volume data is unavailable, THE Volume_Analyzer SHALL return a neutral score of 0.5

### Requirement 4: Momentum Deceleration Detection

**User Story:** As a trader, I want to detect when momentum is slowing down before entry, so that I can avoid entering trades at the end of a move.

#### Acceptance Criteria

1. THE Momentum_Analyzer SHALL calculate momentum_acceleration as the rate of change of momentum over the last 3 bars
2. WHEN momentum is increasing (accelerating), THE Momentum_Analyzer SHALL return a positive acceleration value
3. WHEN momentum is decreasing (decelerating), THE Momentum_Analyzer SHALL return a negative acceleration value
4. WHEN momentum_acceleration is below -2.0 (strong deceleration), THE System SHALL reject the entry with reason "Momentum decelerating"
5. THE Momentum_Analyzer SHALL normalize acceleration values to a -1.0 to 1.0 range for confidence scoring

### Requirement 5: Tighter Stop Losses for Quick Reversals

**User Story:** As a trader, I want tighter stop losses during the initial holding period, so that I can limit losses from quick reversals.

#### Acceptance Criteria

1. WHEN a trade is held for less than 3 minutes, THE Stop_Loss_Manager SHALL use a tighter initial stop loss of -5.0%
2. WHEN a trade is held for 3-5 minutes, THE Stop_Loss_Manager SHALL transition to the standard ATR-based stop loss
3. WHEN a trade loses more than 3% within the first 2 minutes, THE Stop_Loss_Manager SHALL trigger an early exit
4. IF the price drops more than 5% at any time during the first 3 minutes, THEN THE Stop_Loss_Manager SHALL trigger an emergency exit
5. THE Stop_Loss_Manager SHALL log all stop loss adjustments with timestamps and reasons

### Requirement 6: Dynamic Position Sizing

**User Story:** As a trader, I want position sizes to be reduced for lower confidence trades, so that I can limit exposure on riskier entries.

#### Acceptance Criteria

1. WHEN confidence_score is above 0.8, THE Position_Sizer SHALL use 100% of the standard position size
2. WHEN confidence_score is between 0.6 and 0.8, THE Position_Sizer SHALL use 75% of the standard position size
3. WHEN confidence_score is between 0.4 and 0.6, THE Position_Sizer SHALL use 50% of the standard position size
4. WHEN confidence_score is below 0.4, THE System SHALL reject the entry due to low confidence
5. THE Position_Sizer SHALL ensure minimum position size of $50 to avoid excessive commission impact

### Requirement 7: Entry Validation Pipeline

**User Story:** As a trader, I want all new validation checks integrated into the entry pipeline, so that trades are consistently validated before entry.

#### Acceptance Criteria

1. WHEN validating a ticker for entry, THE System SHALL execute checks in order: peak_detection, volume_confirmation, momentum_deceleration, confidence_calculation
2. WHEN any validation check fails, THE System SHALL log the rejection reason and skip to the next ticker
3. WHEN all validation checks pass, THE System SHALL proceed with position sizing and entry
4. THE System SHALL log all validation metrics for each ticker evaluated (pass or fail)
5. WHEN parsing validation logs, THE System SHALL deserialize JSON metrics correctly

### Requirement 8: Configuration Management

**User Story:** As a developer, I want all new thresholds to be configurable, so that I can tune the algorithm without code changes.

#### Acceptance Criteria

1. THE System SHALL expose peak_proximity_threshold as a configurable parameter (default: 0.85)
2. THE System SHALL expose momentum_deceleration_threshold as a configurable parameter (default: -2.0)
3. THE System SHALL expose initial_stop_loss_percent as a configurable parameter (default: -5.0)
4. THE System SHALL expose early_exit_loss_percent as a configurable parameter (default: -3.0)
5. THE System SHALL expose early_exit_time_seconds as a configurable parameter (default: 120)
6. THE System SHALL expose volume_lookback_bars as a configurable parameter (default: 20)
