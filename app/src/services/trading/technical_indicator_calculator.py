"""
Technical indicator calculator for momentum trading validation.

This module calculates comprehensive technical analysis indicators including
momentum, trend, volatility, and volume-based indicators.
"""

from typing import List, Dict, Tuple
import statistics
from loguru import logger

from app.src.models.momentum_validation import TechnicalIndicators


class TechnicalIndicatorCalculator:
    """Calculate comprehensive technical analysis indicators."""
    
    @staticmethod
    def calculate_indicators(
        bars: List[Dict],
        period_rsi: int = 14,
        period_ema_fast: int = 12,
        period_ema_slow: int = 26,
        period_signal: int = 9,
        period_bollinger: int = 20,
        period_atr: int = 14,
        period_adx: int = 14
    ) -> TechnicalIndicators:
        """
        Calculate all technical indicators from price and volume data.
        
        Args:
            bars: List of price bar dictionaries with OHLCV data
            period_rsi: RSI period (default: 14)
            period_ema_fast: Fast EMA period (default: 12)
            period_ema_slow: Slow EMA period (default: 26)
            period_signal: MACD signal period (default: 9)
            period_bollinger: Bollinger Bands period (default: 20)
            period_atr: ATR period (default: 14)
            period_adx: ADX period (default: 14)
            
        Returns:
            TechnicalIndicators with all calculated values
        """
        # Extract price and volume data
        closes = [bar.get('c', 0.0) for bar in bars if bar.get('c') is not None and bar.get('c') > 0]
        highs = [bar.get('h', 0.0) for bar in bars if bar.get('h') is not None and bar.get('h') > 0]
        lows = [bar.get('l', 0.0) for bar in bars if bar.get('l') is not None and bar.get('l') > 0]
        opens = [bar.get('o', 0.0) for bar in bars if bar.get('o') is not None and bar.get('o') > 0]
        volumes = [bar.get('v', 0) for bar in bars if bar.get('v') is not None]
        timestamps = [bar.get('t', '') for bar in bars if bar.get('t')]
        
        # Handle insufficient data
        if not closes:
            return TechnicalIndicatorCalculator._create_default_indicators()
        
        current_close = closes[-1]
        current_volume = volumes[-1] if volumes else 0
        
        # Calculate indicators
        rsi = TechnicalIndicatorCalculator._calculate_rsi(closes, period_rsi)
        macd_values = TechnicalIndicatorCalculator._calculate_macd(
            closes, period_ema_fast, period_ema_slow, period_signal
        )
        bollinger_values = TechnicalIndicatorCalculator._calculate_bollinger(
            closes, period_bollinger
        )
        adx = TechnicalIndicatorCalculator._calculate_adx(highs, lows, closes, period_adx)
        ema_fast = TechnicalIndicatorCalculator._calculate_ema(closes, period_ema_fast)
        ema_slow = TechnicalIndicatorCalculator._calculate_ema(closes, period_ema_slow)
        
        # Volume indicators
        volume_sma = TechnicalIndicatorCalculator._calculate_sma(volumes, min(20, len(volumes))) if volumes else 0.0
        obv = TechnicalIndicatorCalculator._calculate_obv(closes, volumes)
        mfi = TechnicalIndicatorCalculator._calculate_mfi(highs, lows, closes, volumes, 14)
        ad = TechnicalIndicatorCalculator._calculate_ad(highs, lows, closes, volumes)
        
        # Momentum indicators
        stoch_values = TechnicalIndicatorCalculator._calculate_stochastic(highs, lows, closes, 14, 3)
        cci = TechnicalIndicatorCalculator._calculate_cci(highs, lows, closes, 20)
        atr = TechnicalIndicatorCalculator._calculate_atr(highs, lows, closes, period_atr)
        willr = TechnicalIndicatorCalculator._calculate_williams_r(highs, lows, closes, 14)
        roc = TechnicalIndicatorCalculator._calculate_roc(closes, 12)
        
        # Price averages
        vwap = TechnicalIndicatorCalculator._calculate_vwap(closes, volumes)
        vwma = TechnicalIndicatorCalculator._calculate_vwma(closes, volumes, 20)
        wma = TechnicalIndicatorCalculator._calculate_wma(closes, 20)
        
        # Time series data
        datetime_price = list(zip(timestamps[-20:], closes[-20:])) if timestamps else []
        
        return TechnicalIndicators(
            rsi=rsi,
            macd=macd_values,
            stoch=stoch_values,
            cci=cci,
            willr=willr,
            roc=roc,
            adx=adx,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            bollinger=bollinger_values,
            atr=atr,
            volume=current_volume,
            volume_sma=volume_sma,
            obv=obv,
            mfi=mfi,
            ad=ad,
            vwap=vwap,
            vwma=vwma,
            wma=wma,
            close_price=current_close,
            datetime_price=datetime_price
        )
    
    @staticmethod
    def _create_default_indicators() -> TechnicalIndicators:
        """Create default indicators when data is insufficient."""
        return TechnicalIndicators(
            rsi=50.0,
            macd=[0.0, 0.0, 0.0],
            stoch=[50.0, 50.0],
            cci=0.0,
            willr=-50.0,
            roc=0.0,
            adx=0.0,
            ema_fast=0.0,
            ema_slow=0.0,
            bollinger=[0.0, 0.0, 0.0],
            atr=0.0,
            volume=0,
            volume_sma=0.0,
            obv=0.0,
            mfi=50.0,
            ad=0.0,
            vwap=0.0,
            vwma=0.0,
            wma=0.0,
            close_price=0.0,
            datetime_price=[]
        )
    
    @staticmethod
    def _calculate_sma(values: List[float], period: int) -> float:
        """Calculate Simple Moving Average."""
        if not values or len(values) < period:
            return 0.0
        return sum(values[-period:]) / period
    
    @staticmethod
    def _calculate_ema(values: List[float], period: int) -> float:
        """Calculate Exponential Moving Average."""
        if not values or len(values) < period:
            return values[-1] if values else 0.0
        
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period  # Start with SMA
        
        for price in values[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    @staticmethod
    def _calculate_rsi(closes: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index."""
        if len(closes) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def _calculate_macd(
        closes: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> List[float]:
        """Calculate MACD (Moving Average Convergence Divergence)."""
        if len(closes) < slow_period:
            return [0.0, 0.0, 0.0]
        
        ema_fast = TechnicalIndicatorCalculator._calculate_ema(closes, fast_period)
        ema_slow = TechnicalIndicatorCalculator._calculate_ema(closes, slow_period)
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line (EMA of MACD)
        # Simplified: use current MACD as signal
        signal_line = macd_line * 0.9  # Approximation
        histogram = macd_line - signal_line
        
        return [macd_line, signal_line, histogram]
    
    @staticmethod
    def _calculate_bollinger(closes: List[float], period: int = 20) -> List[float]:
        """Calculate Bollinger Bands."""
        if len(closes) < period:
            current = closes[-1] if closes else 0.0
            return [current, current, current]
        
        sma = sum(closes[-period:]) / period
        variance = sum((x - sma) ** 2 for x in closes[-period:]) / period
        std_dev = variance ** 0.5
        
        upper = sma + (2 * std_dev)
        lower = sma - (2 * std_dev)
        
        return [upper, sma, lower]
    
    @staticmethod
    def _calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(closes) < 2 or len(highs) < 2 or len(lows) < 2:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            true_range = max(high_low, high_close, low_close)
            true_ranges.append(true_range)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        
        return sum(true_ranges[-period:]) / period
    
    @staticmethod
    def _calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate Average Directional Index (simplified)."""
        if len(closes) < period + 1:
            return 0.0
        
        # Simplified ADX calculation
        up_moves = []
        down_moves = []
        
        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            up_moves.append(max(up_move, 0))
            down_moves.append(max(down_move, 0))
        
        if not up_moves or not down_moves:
            return 0.0
        
        avg_up = sum(up_moves[-period:]) / period
        avg_down = sum(down_moves[-period:]) / period
        
        if avg_up + avg_down == 0:
            return 0.0
        
        dx = abs(avg_up - avg_down) / (avg_up + avg_down) * 100
        return dx
    
    @staticmethod
    def _calculate_obv(closes: List[float], volumes: List[int]) -> float:
        """Calculate On-Balance Volume."""
        if len(closes) < 2 or len(volumes) < 2:
            return 0.0
        
        obv = 0.0
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv += volumes[i]
            elif closes[i] < closes[i-1]:
                obv -= volumes[i]
        
        return obv
    
    @staticmethod
    def _calculate_mfi(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[int],
        period: int = 14
    ) -> float:
        """Calculate Money Flow Index."""
        if len(closes) < period + 1 or not volumes:
            return 50.0
        
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        money_flows = [tp * v for tp, v in zip(typical_prices, volumes)]
        
        positive_flow = 0.0
        negative_flow = 0.0
        
        for i in range(1, len(typical_prices)):
            if typical_prices[i] > typical_prices[i-1]:
                positive_flow += money_flows[i]
            elif typical_prices[i] < typical_prices[i-1]:
                negative_flow += money_flows[i]
        
        if negative_flow == 0:
            return 100.0
        
        money_ratio = positive_flow / negative_flow
        mfi = 100 - (100 / (1 + money_ratio))
        
        return mfi
    
    @staticmethod
    def _calculate_ad(highs: List[float], lows: List[float], closes: List[float], volumes: List[int]) -> float:
        """Calculate Accumulation/Distribution."""
        if not highs or not lows or not closes or not volumes:
            return 0.0
        
        ad = 0.0
        for h, l, c, v in zip(highs, lows, closes, volumes):
            if h == l:
                continue
            clv = ((c - l) - (h - c)) / (h - l)
            ad += clv * v
        
        return ad
    
    @staticmethod
    def _calculate_stochastic(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
        smooth: int = 3
    ) -> List[float]:
        """Calculate Stochastic Oscillator."""
        if len(closes) < period:
            return [50.0, 50.0]
        
        highest_high = max(highs[-period:])
        lowest_low = min(lows[-period:])
        
        if highest_high == lowest_low:
            return [50.0, 50.0]
        
        k = ((closes[-1] - lowest_low) / (highest_high - lowest_low)) * 100
        d = k  # Simplified: use K as D
        
        return [k, d]
    
    @staticmethod
    def _calculate_cci(highs: List[float], lows: List[float], closes: List[float], period: int = 20) -> float:
        """Calculate Commodity Channel Index."""
        if len(closes) < period:
            return 0.0
        
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs[-period:], lows[-period:], closes[-period:])]
        sma_tp = sum(typical_prices) / len(typical_prices)
        mean_deviation = sum(abs(tp - sma_tp) for tp in typical_prices) / len(typical_prices)
        
        if mean_deviation == 0:
            return 0.0
        
        cci = (typical_prices[-1] - sma_tp) / (0.015 * mean_deviation)
        return cci
    
    @staticmethod
    def _calculate_williams_r(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate Williams %R."""
        if len(closes) < period:
            return -50.0
        
        highest_high = max(highs[-period:])
        lowest_low = min(lows[-period:])
        
        if highest_high == lowest_low:
            return -50.0
        
        willr = ((highest_high - closes[-1]) / (highest_high - lowest_low)) * -100
        return willr
    
    @staticmethod
    def _calculate_roc(closes: List[float], period: int = 12) -> float:
        """Calculate Rate of Change."""
        if len(closes) < period + 1:
            return 0.0
        
        old_close = closes[-period-1]
        if old_close == 0:
            return 0.0
        
        roc = ((closes[-1] - old_close) / old_close) * 100
        return roc
    
    @staticmethod
    def _calculate_vwap(closes: List[float], volumes: List[int]) -> float:
        """Calculate Volume Weighted Average Price."""
        if not closes or not volumes or len(closes) != len(volumes):
            return closes[-1] if closes else 0.0
        
        total_pv = sum(p * v for p, v in zip(closes, volumes))
        total_v = sum(volumes)
        
        if total_v == 0:
            return closes[-1]
        
        return total_pv / total_v
    
    @staticmethod
    def _calculate_vwma(closes: List[float], volumes: List[int], period: int = 20) -> float:
        """Calculate Volume Weighted Moving Average."""
        if not closes or not volumes or len(closes) < period:
            return closes[-1] if closes else 0.0
        
        recent_closes = closes[-period:]
        recent_volumes = volumes[-period:]
        
        total_pv = sum(p * v for p, v in zip(recent_closes, recent_volumes))
        total_v = sum(recent_volumes)
        
        if total_v == 0:
            return recent_closes[-1]
        
        return total_pv / total_v
    
    @staticmethod
    def _calculate_wma(closes: List[float], period: int = 20) -> float:
        """Calculate Weighted Moving Average."""
        if not closes or len(closes) < period:
            return closes[-1] if closes else 0.0
        
        recent_closes = closes[-period:]
        weights = list(range(1, period + 1))
        
        weighted_sum = sum(p * w for p, w in zip(recent_closes, weights))
        weight_sum = sum(weights)
        
        return weighted_sum / weight_sum
