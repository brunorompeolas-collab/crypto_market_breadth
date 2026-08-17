import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple

from database import save_breadth_snapshot
from quantitative import determine_data_status
from normalizer import resample_provider_prices
from providers import get_provider
from universe import BR1_BREADTH_UNIVERSE_V1

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
UNIVERSE_VERSION = "BR1-BREADTH-UNIVERSE-v1"

def calculate_emas_for_asset(df: pd.DataFrame, display_days: int) -> pd.DataFrame:
    """Calculates EMAs and returns only the required display window."""
    if df.empty or len(df) < 20:
        return pd.DataFrame()
        
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean() if len(df) >= 50 else np.nan
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean() if len(df) >= 200 else np.nan
    
    # We only return the display_days length. The warm-up portion is discarded.
    return df.tail(display_days)

def build_snapshot_state(assets_data: Dict[str, pd.DataFrame], benchmarks_data: Dict[str, pd.DataFrame], timeframe: str, provider_id: str) -> List[Dict[str, Any]]:
    """Builds snapshots from the calculated EMA DataFrames."""
    history_map = {}
    
    # Process assets
    for asset_id, df in assets_data.items():
        if df.empty: continue
        for _, row in df.iterrows():
            dt_str = row['datetime'].strftime('%Y-%m-%d %H:%M:%S')
            price = float(row['close'])
            
            if dt_str not in history_map:
                history_map[dt_str] = {
                    'assets_total': 0, 'ema20_valid': 0, 'ema50_valid': 0, 'ema200_valid': 0,
                    'above20': 0, 'above50': 0, 'above200': 0,
                    'btc_price': 0.0, 'eth_price': 0.0
                }
                
            hm = history_map[dt_str]
            hm['assets_total'] += 1
            hm['ema20_valid'] += 1
            if price > row['ema20']: hm['above20'] += 1
            
            if not pd.isna(row['ema50']):
                hm['ema50_valid'] += 1
                if price > row['ema50']: hm['above50'] += 1
                
            if not pd.isna(row['ema200']):
                hm['ema200_valid'] += 1
                if price > row['ema200']: hm['above200'] += 1

    # Inject benchmark prices directly, even if they aren't in universe (they are in v1, but for safety)
    for b_key, b_df in benchmarks_data.items():
        if b_df.empty: continue
        b_field = 'btc_price' if b_key == 'BTC' else 'eth_price'
        for _, row in b_df.iterrows():
            dt_str = row['datetime'].strftime('%Y-%m-%d %H:%M:%S')
            if dt_str in history_map:
                history_map[dt_str][b_field] = float(row['close'])

    # Build final snapshots
    snapshots = []
    last_btc, last_eth = 60000.0, 3000.0
    
    for dt_str in sorted(history_map.keys()):
        hm = history_map[dt_str]
        if hm['assets_total'] < 10: continue
        
        if hm['btc_price'] > 0: last_btc = hm['btc_price']
        if hm['eth_price'] > 0: last_eth = hm['eth_price']
        
        pct20 = (hm['above20'] / hm['ema20_valid'] * 100) if hm['ema20_valid'] > 0 else 0
        pct50 = (hm['above50'] / hm['ema50_valid'] * 100) if hm['ema50_valid'] > 0 else 0
        pct200 = (hm['above200'] / hm['ema200_valid'] * 100) if hm['ema200_valid'] > 0 else 0
        
        breadth_score = (0.20 * pct20) + (0.30 * pct50) + (0.50 * pct200)
        
        snap = {
            'candle_time': dt_str,
            'collected_at': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            'provider': provider_id,
            'timeframe': timeframe,
            'universe_version': UNIVERSE_VERSION,
            'breadth_score': breadth_score,
            'pct_above_ema20': pct20,
            'pct_above_ema50': pct50,
            'pct_above_ema200': pct200,
            'btc_price': hm['btc_price'] or last_btc,
            'eth_price': hm['eth_price'] or last_eth,
            'assets_total': hm['assets_total'],
            'assets_ema20_valid': hm['ema20_valid'],
            'assets_ema50_valid': hm['ema50_valid'],
            'assets_ema200_valid': hm['ema200_valid'],
            'data_status': determine_data_status(hm['assets_total'], len(BR1_BREADTH_UNIVERSE_V1), hm['ema20_valid'], hm['ema50_valid'], hm['ema200_valid']),
            'status': 'SUCCESS'
        }
        snapshots.append(snap)
        
    return snapshots

def execute_breadth_pipeline(provider_name: str, timeframe: str, display_days: int) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame]]:
    provider = get_provider(provider_name)
    
    # 1. Fetch raw data via Provider
    # display_days + warmup. Using 200 candles for EMA warm-up.
    required_candles = display_days + 200
    if timeframe == '4h': required_candles = (display_days * 6) + 200
    if timeframe == '1w': required_candles = (display_days // 7) + 200
    
    resp = provider.get_historical_data(BR1_BREADTH_UNIVERSE_V1, timeframe, required_candles)
    if resp["status"] != "SUCCESS":
        return [{"status": resp["status"], "reason": resp["reason"], "provider": provider.provider_id}], {}
        
    raw_data = resp["data"]
    raw_bench = resp["benchmarks"]
    
    # 2. Normalize and Resample
    assets_dfs = {}
    for asset_id, prices in raw_data.items():
        resampled_df = resample_provider_prices(prices, timeframe)
        # 3. Calculate EMAs
        final_df = calculate_emas_for_asset(resampled_df, display_days if timeframe == '1d' else (display_days*6 if timeframe=='4h' else display_days//7))
        if not final_df.empty:
            assets_dfs[asset_id] = final_df
            
    bench_dfs = {}
    for b_key, b_prices in raw_bench.items():
        resampled_b = resample_provider_prices(b_prices, timeframe)
        b_final = resampled_b.tail(display_days if timeframe == '1d' else (display_days*6 if timeframe=='4h' else display_days//7))
        bench_dfs[b_key] = b_final

    if not assets_dfs:
        return [{"status": "DATA_UNAVAILABLE", "reason": "No valid data after resampling", "provider": provider.provider_id}], {}

    # 4. Build Snapshots
    snapshots = build_snapshot_state(assets_dfs, bench_dfs, timeframe, provider.provider_id)
    return snapshots, assets_dfs

def get_crypto_breadth_data(timeframe: str = '1d', provider_name: str = 'coingecko') -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Live snapshot path (fetch just enough for 1 candle)."""
    snapshots, assets_dfs = execute_breadth_pipeline(provider_name, timeframe, display_days=1)
    
    if not snapshots or snapshots[-1].get("status") != "SUCCESS":
        return None, snapshots[0] if snapshots else {"status": "DATA_UNAVAILABLE", "reason": "Unknown Error"}
        
    snap = snapshots[-1]
    save_breadth_snapshot(snap)
    
    # Build df_assets for the UI scanner
    results = []
    for asset in BR1_BREADTH_UNIVERSE_V1:
        asset_id = asset["id"]
        if asset_id in assets_dfs and not assets_dfs[asset_id].empty:
            row = assets_dfs[asset_id].iloc[-1]
            price = float(row['close'])
            results.append({
                'symbol': asset['symbol'],
                'price': price,
                'above_ema20': bool(price > row['ema20']) if not pd.isna(row['ema20']) else False,
                'above_ema50': bool(price > row['ema50']) if not pd.isna(row['ema50']) else False,
                'above_ema200': bool(price > row['ema200']) if not pd.isna(row['ema200']) else False,
            })
            
    df_assets = pd.DataFrame(results)
    return df_assets, snap

def run_backfill(timeframe: str = '1d', display_days: int = 365, provider_name: str = 'coingecko') -> Tuple[bool, str]:
    """Historical backfill path."""
    try:
        snapshots, _ = execute_breadth_pipeline(provider_name, timeframe, display_days)
        if not snapshots or snapshots[-1].get("status") != "SUCCESS":
            return False, snapshots[0].get("reason", "Unknown Error")
            
        count = 0
        for snap in snapshots:
            save_breadth_snapshot(snap)
            count += 1
            
        return True, f"{count} snapshots guardados"
    except Exception as e:
        return False, str(e)
