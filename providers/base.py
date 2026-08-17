from abc import ABC, abstractmethod
from typing import Dict, Any, List

class MarketDataProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Return the canonical provider identifier, e.g. 'coingecko'."""
        pass

    @abstractmethod
    def get_historical_data(self, universe: List[Dict[str, str]], timeframe: str, required_candles: int) -> Dict[str, Any]:
        """
        Fetch historical data for the universe.
        Returns normalized structure:
        {
            "status": "SUCCESS" | "DATA_UNAVAILABLE",
            "reason": str,
            "data": {
                "asset_id": [
                    {"timestamp": int, "price": float}, ...
                ],
                ...
            },
            "benchmarks": {
                "BTC": [{"timestamp": int, "price": float}, ...],
                "ETH": [{"timestamp": int, "price": float}, ...]
            }
        }
        """
        pass
