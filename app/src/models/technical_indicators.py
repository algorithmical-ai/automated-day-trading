import json
from typing import Any, Dict, Tuple

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover - lightweight fallback for test envs without pydantic

    class BaseModel:  # type: ignore
        pass


class TechnicalIndicators(BaseModel):
    # Trend indicators
    rsi: float
    macd: Tuple[float, float, float]  # macd, signal, hist
    bollinger: Tuple[float, float, float]  # upper, middle, lower
    adx: float
    ema_fast: float
    ema_slow: float

    # Volume indicators
    volume_sma: float
    obv: float
    mfi: float
    ad: float

    # Momentum indicators
    stoch: Tuple[float, float]
    cci: float
    atr: float
    willr: float
    roc: float
    vwap: float
    vwma: float
    wma: float
    volume: float
    close_price: float
    datetime_price: Tuple

    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a dictionary."""
        return {
            # Trend indicators
            "rsi": self.rsi,
            "macd": {
                "macd": self.macd[0],
                "signal": self.macd[1],
                "hist": self.macd[2],
            },
            "bollinger": {
                "upper": self.bollinger[0],
                "middle": self.bollinger[1],
                "lower": self.bollinger[2],
            },
            "adx": self.adx,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            # Volume indicators
            "volume_sma": self.volume_sma,
            "obv": self.obv,
            "mfi": self.mfi,
            "ad": self.ad,
            # Momentum indicators
            "stoch": {"k": self.stoch[0], "d": self.stoch[1]},
            "cci": self.cci,
            "atr": self.atr,
            "willr": self.willr,
            "roc": self.roc,
            "vwap": self.vwap,
            "vwma": self.vwma,
            "wma": self.wma,
            "volume": self.volume,
            "close_price": self.close_price,
            "datetime_price": self.datetime_price,
        }

    def to_json(self) -> str:
        """Convert the model to a JSON string."""
        return json.dumps(self.to_dict())

    def __str__(self) -> str:
        """Return a string representation of the model."""
        return self.to_json()
