# Implementation Plan: Penny Stock Peak Detection

## Overview

This implementation adds peak detection and enhanced validation to the penny stocks trading algorithm. The work is organized into logical phases: data models, core analyzers, confidence calculation, exit engine enhancements, position sizing, and pipeline integration.

## Tasks

- [x] 1. Create data models and configuration
  - [x] 1.1 Create `PeakDetectionConfig` dataclass in `app/src/services/trading/peak_detection_config.py`
    - Define all configurable parameters with defaults
    - Implement `to_dict()` and `from_dict()` methods for JSON serialization
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  
  - [x] 1.2 Create result dataclasses in `app/src/services/trading/peak_detection_models.py`
    - `PeakDetectionResult`, `VolumeConfirmationResult`, `MomentumAccelerationResult`
    - `ConfidenceComponents`, `EnhancedConfidenceResult`, `PositionSizeResult`
    - `ValidationResult` with `to_json()` and `from_json()` methods
    - _Requirements: 2.6, 7.5_
  
  - [ ]* 1.3 Write property test for ValidationResult JSON round-trip
    - **Property 19: ValidationResult JSON Round-Trip**
    - **Validates: Requirements 2.6, 7.5**

- [x] 2. Implement PeakDetector
  - [x] 2.1 Create `PeakDetector` class in `app/src/services/trading/peak_detector.py`
    - Implement `detect_peak()` method with lookback window
    - Calculate peak_proximity_score using distance from peak
    - Handle edge cases (empty bars, insufficient data)
    - _Requirements: 1.1, 1.2, 1.3, 1.5_
  
  - [ ]* 2.2 Write property test for peak proximity score range
    - **Property 1: Peak Proximity Score Range Invariant**
    - **Validates: Requirements 1.1**
  
  - [ ]* 2.3 Write property test for peak proximity below threshold
    - **Property 2: Peak Proximity Below Threshold When Far From Peak**
    - **Validates: Requirements 1.3**

- [x] 3. Implement VolumeAnalyzer
  - [x] 3.1 Create `VolumeAnalyzer` class in `app/src/services/trading/volume_analyzer.py`
    - Implement `analyze_volume()` method with lookback window
    - Calculate volume_confirmation_score based on volume ratio
    - Handle edge cases (no volume data, zero average)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  
  - [ ]* 3.2 Write property test for volume confirmation score range
    - **Property 6: Volume Confirmation Score Range Invariant**
    - **Validates: Requirements 3.1**
  
  - [ ]* 3.3 Write property test for high volume score maximum
    - **Property 7: High Volume Score Maximum**
    - **Validates: Requirements 3.2**
  
  - [ ]* 3.4 Write property test for volume score proportionality
    - **Property 8: Volume Score Proportionality**
    - **Validates: Requirements 3.3**

- [x] 4. Implement MomentumAccelerationAnalyzer
  - [x] 4.1 Create `MomentumAccelerationAnalyzer` class in `app/src/services/trading/momentum_acceleration_analyzer.py`
    - Implement `analyze_acceleration()` method
    - Calculate momentum for consecutive bars and compute acceleration
    - Normalize acceleration to [-1.0, 1.0] range
    - _Requirements: 4.1, 4.2, 4.3, 4.5_
  
  - [ ]* 4.2 Write property test for momentum acceleration sign correctness
    - **Property 9: Momentum Acceleration Sign Correctness**
    - **Validates: Requirements 4.2, 4.3**
  
  - [ ]* 4.3 Write property test for normalized acceleration range
    - **Property 10: Normalized Acceleration Range Invariant**
    - **Validates: Requirements 4.5**

- [x] 5. Checkpoint - Core analyzers complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement EnhancedConfidenceCalculator
  - [x] 6.1 Create `EnhancedConfidenceCalculator` class in `app/src/services/trading/enhanced_confidence_calculator.py`
    - Implement `calculate_confidence()` with weighted factors
    - Normalize inputs and compute weighted sum
    - Set rejection_reason if confidence below threshold
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  
  - [ ]* 6.2 Write property test for confidence factor monotonicity
    - **Property 4: Confidence Factor Monotonicity**
    - **Validates: Requirements 2.1, 2.2, 2.3**
  
  - [ ]* 6.3 Write property test for confidence score range
    - **Property 5: Confidence Score Range Invariant**
    - **Validates: Requirements 2.5**

- [x] 7. Implement EnhancedExitDecisionEngine
  - [x] 7.1 Extend `ExitDecisionEngine` in `app/src/services/trading/penny_stock_utils.py`
    - Add initial period tight stop loss (-5%)
    - Add early exit logic (-3% within 2 minutes)
    - Add emergency exit during initial period (-5% within 3 minutes)
    - Maintain backward compatibility with existing exit logic
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  
  - [ ]* 7.2 Write property test for initial period tight stop loss
    - **Property 12: Initial Period Tight Stop Loss**
    - **Validates: Requirements 5.1**
  
  - [ ]* 7.3 Write property test for ATR stop transition
    - **Property 13: ATR Stop Transition**
    - **Validates: Requirements 5.2**
  
  - [ ]* 7.4 Write property test for early exit on quick loss
    - **Property 14: Early Exit on Quick Loss**
    - **Validates: Requirements 5.3**
  
  - [ ]* 7.5 Write property test for emergency exit during initial period
    - **Property 15: Emergency Exit During Initial Period**
    - **Validates: Requirements 5.4**

- [x] 8. Implement DynamicPositionSizer
  - [x] 8.1 Create `DynamicPositionSizer` class in `app/src/services/trading/dynamic_position_sizer.py`
    - Implement `calculate_position_size()` with confidence tiers
    - Enforce minimum position size of $50
    - Return rejection for confidence below 0.4
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  
  - [ ]* 8.2 Write property test for position sizing tier correctness
    - **Property 16: Position Sizing Tier Correctness**
    - **Validates: Requirements 6.1, 6.2, 6.3**
  
  - [ ]* 8.3 Write property test for low confidence rejection
    - **Property 17: Low Confidence Rejection**
    - **Validates: Requirements 6.4**
  
  - [ ]* 8.4 Write property test for minimum position size invariant
    - **Property 18: Minimum Position Size Invariant**
    - **Validates: Requirements 6.5**

- [x] 9. Checkpoint - All components complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integrate validation pipeline
  - [x] 10.1 Create `EnhancedValidationPipeline` class in `app/src/services/trading/enhanced_validation_pipeline.py`
    - Orchestrate PeakDetector, VolumeAnalyzer, MomentumAccelerationAnalyzer, EnhancedConfidenceCalculator
    - Execute checks in order with early rejection
    - Return complete ValidationResult with all metrics
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  
  - [ ]* 10.2 Write property test for peak rejection threshold
    - **Property 3: Peak Rejection Threshold**
    - **Validates: Requirements 1.4**
  
  - [ ]* 10.3 Write property test for deceleration rejection threshold
    - **Property 11: Deceleration Rejection Threshold**
    - **Validates: Requirements 4.4**

- [x] 11. Integrate with PennyStocksIndicator
  - [x] 11.1 Update `_validate_ticker_with_pipeline()` in `penny_stocks_indicator.py`
    - Replace existing validation with EnhancedValidationPipeline
    - Add peak detection check before entry
    - Add momentum deceleration check
    - Log all validation metrics
    - _Requirements: 1.4, 4.4, 7.1, 7.2, 7.3, 7.4_
  
  - [x] 11.2 Update `_process_ticker_entry()` to use DynamicPositionSizer
    - Calculate position size based on confidence score
    - Pass position size to trade execution
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  
  - [x] 11.3 Update exit cycle to use EnhancedExitDecisionEngine
    - Replace ExitDecisionEngine with enhanced version
    - Ensure tighter stops during initial period
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 12. Final checkpoint - Full integration complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- Checkpoints ensure incremental validation
