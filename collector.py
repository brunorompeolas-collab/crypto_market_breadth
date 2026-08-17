import ccxt
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple
from database import save_breadth_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

UNIVERSE_VERSION = "BR1-BREADTH-UNIVERSE-v1"
BR1_BREADTH_UNIVERSE_V1 = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "TON/USDT",
    "ADA/USDT", "SHIB/USDT", "AVAX/USDT", "TRX/USDT", "DOT/USDT", "BCH/USDT", "LINK/USDT",
    "MATIC/USDT", "NEAR/USDT", "LTC/USDT", "ICP/USDT", "LEO/USDT", "FET/USDT", "PEPE/USDT",
    "XLM/USDT", "APT/USDT", "STX/USDT", "UNI/USDT", "XMR/USDT", "MNT/USDT", "ETC/USDT",
    "RENDER/USDT", "INJ/USDT", "AR/USDT", "FIL/USDT", "ATOM/USDT", "IMX/USDT", "MKR/USDT",
    "VET/USDT", "OP/USDT", "GRT/USDT", "TAO/USDT", "SUI/USDT", "WIF/USDT", "FLOKI/USDT",
    "THETA/USDT", "AAVE/USDT", "TIA/USDT", "FTM/USDT", "RUNE/USDT", "ALGO/USDT", "LDO/USDT",
    "SEI/USDT"
]

def get_exchange(ecosystem: str):
    """Initialize public exchange client."""
    ecosystem = ecosystem.lower()
    config = {'enableRateLimit': True, 'timeout': 15000}
    if ecosystem == 'kraken':
        return ccxt.kraken(config)
    elif ecosystem == 'kucoin':
        return ccxt.kucoin(config)
    elif ecosystem == 'okx':
        return ccxt.okx(config)
    else:
        config['options'] = {'defaultType': 'spot'}
        return ccxt.binance(config)

def calculate_emas_for_symbol(exchange, symbol: str, timeframe: str = '1d') -> Dict[str, Any]:
    try:
        # P0.10 - Fetch 300 candles to warm up EMAs
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=300)
        if not ohlcv or len(ohlcv) < 20:
            return None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean() if len(df) >= 50 else None
        
        # P0.11 - Strict EMA200 behavior
        if len(df) >= 200:
            df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        else:
            df['ema200'] = None
            
        last_row = df.iloc[-1]
        current_price = float(last_row['close'])
        candle_time_str = pd.to_datetime(last_row['timestamp'], unit='ms').strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            'symbol': symbol,
            'price': current_price,
            'candle_time': candle_time_str,
            'ema20_valid': True,
            'ema50_valid': not pd.isna(last_row['ema50']),
            'ema200_valid': not pd.isna(last_row['ema200']),
            'above_ema20': bool(current_price > last_row['ema20']) if True else False,
            'above_ema50': bool(current_price > last_row['ema50']) if not pd.isna(last_row['ema50']) else False,
            'above_ema200': bool(current_price > last_row['ema200']) if not pd.isna(last_row['ema200']) else False,
            'df': df # Para uso en backfill si se requiere
        }
    except Exception as e:
        logging.warning(f"Error fetching candles ({timeframe}) for {symbol}: {e}")
        return None

def determine_data_status(pct_coverage: float) -> str:
    if pct_coverage >= 90: return "HIGH"
    if pct_coverage >= 75: return "GOOD"
    if pct_coverage >= 50: return "LIMITED"
    return "LOW"

def get_crypto_breadth_data(ecosystem: str = 'binance', timeframe: str = '1d') -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Collects live data strictly following Universe v1.
    P0.1: No synthetic fallback. Returns (None, None) if unavailable.
    """
    try:
        exchange = get_exchange(ecosystem)
    except Exception:
        return None, None
        
    results = []
    assets_ema20_valid = 0
    assets_ema50_valid = 0
    assets_ema200_valid = 0
    
    above_20_count = 0
    above_50_count = 0
    above_200_count = 0
    
    btc_price = 0.0
    eth_price = 0.0
    
    common_candle_time = None
    
    for symbol in BR1_BREADTH_UNIVERSE_V1:
        data = calculate_emas_for_symbol(exchange, symbol, timeframe=timeframe)
        if data:
            results.append(data)
            if symbol == 'BTC/USDT': btc_price = data['price']
            if symbol == 'ETH/USDT': eth_price = data['price']
            
            if data['ema20_valid']:
                assets_ema20_valid += 1
                if data['above_ema20']: above_20_count += 1
            if data['ema50_valid']:
                assets_ema50_valid += 1
                if data['above_ema50']: above_50_count += 1
            if data['ema200_valid']:
                assets_ema200_valid += 1
                if data['above_ema200']: above_200_count += 1
                
            if not common_candle_time:
                common_candle_time = data['candle_time']

    if not results:
        return None, None
        
    pct_above_ema20 = (above_20_count / assets_ema20_valid * 100) if assets_ema20_valid > 0 else 0
    pct_above_ema50 = (above_50_count / assets_ema50_valid * 100) if assets_ema50_valid > 0 else 0
    pct_above_ema200 = (above_200_count / assets_ema200_valid * 100) if assets_ema200_valid > 0 else 0
    
    breadth_score = (0.20 * pct_above_ema20) + (0.30 * pct_above_ema50) + (0.50 * pct_above_ema200)
    
    coverage_pct = (len(results) / len(BR1_BREADTH_UNIVERSE_V1)) * 100
    
    snapshot = {
        'candle_time': common_candle_time,
        'collected_at': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        'exchange': ecosystem,
        'timeframe': timeframe,
        'universe_version': UNIVERSE_VERSION,
        'breadth_score': breadth_score,
        'pct_above_ema20': pct_above_ema20,
        'pct_above_ema50': pct_above_ema50,
        'pct_above_ema200': pct_above_ema200,
        'btc_price': btc_price,
        'eth_price': eth_price,
        'assets_total': len(results),
        'assets_ema20_valid': assets_ema20_valid,
        'assets_ema50_valid': assets_ema50_valid,
        'assets_ema200_valid': assets_ema200_valid,
        'data_status': determine_data_status(coverage_pct)
    }
    
    # Save snapshot. The DB layer handles uniqueness via REPLACE
    save_breadth_snapshot(snapshot)
    
    df_assets = pd.DataFrame(results)
    return df_assets, snapshot

def run_backfill(ecosystem: str = 'binance', timeframe: str = '1d'):
    """
    P0.9: Robust historical backfill logic generating exact snapshots.
    """
    logging.info(f"Iniciando BACKFILL estricto con {ecosystem} para {timeframe}...")
    try:
        exchange = get_exchange(ecosystem)
        history_map = {}
        
        for symbol in BR1_BREADTH_UNIVERSE_V1:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=300)
                if not ohlcv or len(ohlcv) < 50:
                    continue
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                
                if len(df) >= 200:
                    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
                else:
                    df['ema200'] = np.nan
                
                for _, row in df.iterrows():
                    dt_str = row['datetime'].strftime('%Y-%m-%d %H:%M:%S')
                    price = float(row['close'])
                    
                    if dt_str not in history_map:
                        history_map[dt_str] = {
                            'assets_total': 0,
                            'ema20_valid': 0, 'ema50_valid': 0, 'ema200_valid': 0,
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
                        
                    if symbol == 'BTC/USDT': hm['btc_price'] = price
                    if symbol == 'ETH/USDT': hm['eth_price'] = price
                        
            except Exception as e:
                logging.warning(f"Error backfill {symbol}: {e}")
                continue
                
        saved_count = 0
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
            coverage_pct = (hm['assets_total'] / len(BR1_BREADTH_UNIVERSE_V1)) * 100
            
            snapshot = {
                'candle_time': dt_str,
                'collected_at': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                'exchange': ecosystem,
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
                'data_status': determine_data_status(coverage_pct)
            }
            
            save_breadth_snapshot(snapshot)
            saved_count += 1
            
        return True, saved_count
    except Exception as e:
        logging.error(f"Error global en backfill: {e}")
        return False, str(e)
