from .base import MarketDataProvider
from .coingecko import CoinGeckoProvider

def get_provider(name: str) -> MarketDataProvider:
    if name.lower() == 'coingecko':
        return CoinGeckoProvider()
    raise ValueError(f"Provider {name} not supported.")
