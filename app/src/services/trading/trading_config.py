"""
Trading Configuration Constants

Centralized configuration for ATR multipliers and other trading constants
to ensure consistency across all trading indicators.
"""

# =============================================================================
# ATR Multipliers (Standardized across all indicators)
# =============================================================================

# Stop Loss: 2.5x ATR (INCREASED from 2.0x - need more room for volatility)
ATR_STOP_LOSS_MULTIPLIER = 2.5

# Trailing Stop: 1.5x ATR (for dynamic trailing stops)
ATR_TRAILING_STOP_MULTIPLIER = 1.5

# Volatility Utils Legacy: 2.5x ATR for trailing stop (used in some legacy code)
# Note: This may differ from indicator-specific trailing stops
ATR_TRAILING_STOP_MULTIPLIER_LEGACY = 2.5

# Volatility Utils Stop Loss: 3.0x ATR (for VolatilityUtils utility)
# Note: Indicators use 2.0x, but VolatilityUtils.calculate_volatility_adjusted_stop_loss uses 3.0x
ATR_STOP_LOSS_MULTIPLIER_VOLATILITY_UTILS = 3.0

# =============================================================================
# Stop Loss Bounds
# =============================================================================

# Penny stock stop loss bounds
PENNY_STOCK_STOP_LOSS_MIN = -2.0  # Tightened from -8.0 to limit max loss
PENNY_STOCK_STOP_LOSS_MAX = -2.0  # Tightened from -4.0 to enforce 2% stop

# Standard stock stop loss bounds
STANDARD_STOCK_STOP_LOSS_MIN = -6.0
STANDARD_STOCK_STOP_LOSS_MAX = -4.0

# =============================================================================
# Trailing Stop Bounds
# =============================================================================

# Base trailing stop percentage
BASE_TRAILING_STOP_PERCENT = 2.0

# Short trailing stop multiplier (wider stops for shorts)
TRAILING_STOP_SHORT_MULTIPLIER = 1.5

# Maximum trailing stop for shorts
MAX_TRAILING_STOP_SHORT = 4.0

