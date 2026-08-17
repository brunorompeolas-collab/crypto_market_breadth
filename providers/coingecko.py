import os
import time
import logging
import requests
from typing import Dict, Any, List
from .base import MarketDataProvider

class CoinGeckoProvider(MarketDataProvider):
    @property
    def provider_id(self) -> str:
        return "coingecko"

    def _get_api_url(self) -> str:
        # HF6: Explicitly support Demo/Pro tiers
        tier = os.getenv("COINGECKO_API_TIER", "demo").lower()
        if tier == "pro":
            return "https://pro-api.coingecko.com/api/v3"
        return "https://api.coingecko.com/api/v3"

    def _get_headers(self) -> dict:
        key = os.getenv("COINGECKO_API_KEY", "")
        tier = os.getenv("COINGECKO_API_TIER", "demo").lower()
        if key:
            if tier == "pro":
                return {"x-cg-pro-api-key": key}
            return {"x-cg-demo-api-key": key}
        return {}
        
    def _fetch_asset_history(self, asset_id: str, days: int) -> List[Dict[str, float]]:
        url = f"{self._get_api_url()}/coins/{asset_id}/market_chart"
        params = {
            "vs_currency": "usd",
            "days": str(days)
        }
        
        try:
            resp = requests.get(url, params=params, headers=self._get_headers(), timeout=10)
            if resp.status_code == 429:
                logging.warning("CoinGecko Rate Limit Hit. Sleeping 10s...")
                time.sleep(10)
                resp = requests.get(url, params=params, headers=self._get_headers(), timeout=10)
                
            resp.raise_for_status()
            data = resp.json()
            prices = data.get("prices", [])
            
            # Format: [[timestamp_ms, price], ...]
            # We normalize to {"timestamp": ms, "price": float}
            return [{"timestamp": int(p[0]), "price": float(p[1])} for p in prices]
            
        except Exception as e:
            logging.error(f"CoinGecko fetch failed for {asset_id}: {e}")
            return []

    def get_historical_data(self, universe: List[Dict[str, str]], timeframe: str, required_candles: int) -> Dict[str, Any]:
        """
        CoinGecko resolves granularity by 'days'.
        If we need 1d candles: days = required_candles. >90 days returns daily data.
        If we need 4h candles: days = (required_candles * 4) / 24. Must be <= 90 to get hourly data.
        If we need 1w candles: days = required_candles * 7. >90 returns daily.
        """
        # Calculate days to request
        if timeframe == '4h':
            days_to_request = max(2, int((required_candles * 4) / 24) + 1)
            # CoinGecko only gives hourly for days <= 90. 
            if days_to_request > 90:
                logging.warning(f"CoinGecko hourly limit is 90 days. Capping 4h history to 90 days.")
                days_to_request = 90
        elif timeframe == '1w':
            days_to_request = required_candles * 7
            if days_to_request < 91:
                days_to_request = 91 # Force daily resolution
        else: # 1d
            days_to_request = required_candles
            if days_to_request < 91:
                days_to_request = 91 # Force daily resolution so we don't get hourly by mistake
        
        normalized_data = {}
        
        for asset in universe:
            asset_id = asset["id"]
            prices = self._fetch_asset_history(asset_id, days=days_to_request)
            if prices:
                normalized_data[asset_id] = prices
            time.sleep(1) # Simple backoff for public API (1 req/sec)
            
        if not normalized_data:
            return {
                "status": "DATA_UNAVAILABLE",
                "reason": "Failed to fetch any data from CoinGecko. Possible rate limit.",
                "data": {},
                "benchmarks": {}
            }
            
        # Also fetch benchmarks explicitly just in case they aren't in the universe (they should be)
        btc_prices = normalized_data.get("bitcoin")
        if not btc_prices:
            btc_prices = self._fetch_asset_history("bitcoin", days_to_request)
            time.sleep(1)
            
        eth_prices = normalized_data.get("ethereum")
        if not eth_prices:
            eth_prices = self._fetch_asset_history("ethereum", days_to_request)
            time.sleep(1)
            
        return {
            "status": "SUCCESS",
            "reason": "",
            "data": normalized_data,
            "benchmarks": {
                "BTC": btc_prices,
                "ETH": eth_prices
            }
        }
