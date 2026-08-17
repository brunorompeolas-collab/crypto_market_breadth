import ccxt
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple
from database import save_breadth_snapshot
from quantitative import determine_data_status

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

def get_required_limit(timeframe: str, display_days: int) -> int:
    """Correction 3: Calculate required candles."""
    ema_warmup = 200
    if timeframe == '1d':
        return display_days + ema_warmup
    elif timeframe == '4h':
        return (display_days * 6) + ema_warmup
    elif timeframe == '1w':
        return (display_days // 7) + ema_warmup
    return display_days + ema_warmup

def fetch_all_ohlcv(exchange, symbol: str, timeframe: str, required_candles: int) -> list:
    """Correction 3: Paginated historical fetch if API limit is reached."""
    # En la mayoría de exchanges (ej. Binance), el límite por llamada es 1000.
    # Si pedimos menos de 1000, basta con una llamada `limit=required_candles`.
    # Para ser robustos implementamos paginación si se requieren más.
    limit_per_call = 1000
    all_ohlcv = []
    
    if required_candles <= limit_per_call:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=required_candles)
        return ohlcv
        
    since = None
    #ccxt fetch_ohlcv pagination requires loop. Since we just need up to required_candles,
    # we can fetch backwards by timestamp or simply use fetch_ohlcv limit=1000.
    # A simple loop reading backwards:
    current_end = exchange.milliseconds()
    while len(all_ohlcv) < required_candles:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit_per_call, params={'endTime': current_end})
        if not ohlcv:
            break
        all_ohlcv = ohlcv + all_ohlcv
        current_end = ohlcv[0][0] - 1
        
    return all_ohlcv[-required_candles:] if len(all_ohlcv) >= required_candles else all_ohlcv

def calculate_emas_for_symbol(exchange, symbol: str, timeframe: str = '1d', display_days: int = 1) -> Dict[str, Any]:
    try:
        required_candles = get_required_limit(timeframe, display_days)
        ohlcv = fetch_all_ohlcv(exchange, symbol, timeframe, required_candles)
        
        if not ohlcv or len(ohlcv) < 20:
            return None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Correction 7: Filter out incomplete candles (the last one is usually open)
        # However, for live Data, the user WANTS the live price. 
        # Wait: "Los snapshots históricos deben representar velas cerradas. Para v1: utilizar únicamente velas completadas"
        # OK, we will drop the last candle ALWAYS to ensure it is closed.
        df = df.iloc[:-1] 
        if df.empty:
            return None
        
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean() if len(df) >= 50 else None
        
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
            'df': df
        }
    except Exception as e:
        logging.warning(f"Error fetching candles ({timeframe}) for {symbol}: {e}")
        return None

def get_crypto_breadth_data(ecosystem: str = 'binance', timeframe: str = '1d') -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Collects live data strictly following Universe v1.
    Correction 12: Return strict Error Contract (`DATA_UNAVAILABLE`, `reason`) from collector if API fails.
    """
    try:
        exchange = get_exchange(ecosystem)
    except Exception as e:
        return None, {"status": "DATA_UNAVAILABLE", "exchange": ecosystem, "reason": str(e)}
        
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
        data = calculate_emas_for_symbol(exchange, symbol, timeframe=timeframe, display_days=1)
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
        return None, {"status": "DATA_UNAVAILABLE", "exchange": ecosystem, "reason": "No valid assets retrieved."}
        
    pct_above_ema20 = (above_20_count / assets_ema20_valid * 100) if assets_ema20_valid > 0 else 0
    pct_above_ema50 = (above_50_count / assets_ema50_valid * 100) if assets_ema50_valid > 0 else 0
    pct_above_ema200 = (above_200_count / assets_ema200_valid * 100) if assets_ema200_valid > 0 else 0
    
    breadth_score = (0.20 * pct_above_ema20) + (0.30 * pct_above_ema50) + (0.50 * pct_above_ema200)
    
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
        'data_status': determine_data_status(len(results), len(BR1_BREADTH_UNIVERSE_V1), assets_ema20_valid, assets_ema50_valid, assets_ema200_valid),
        'status': "SUCCESS"
    }
    
    save_breadth_snapshot(snapshot)
    
    df_assets = pd.DataFrame(results)
    return df_assets, snapshot

def run_backfill(ecosystem: str = 'binance', timeframe: str = '1d', display_days: int = 365):
    """
    P0.9: Robust historical backfill logic generating exact snapshots.
    Correction 3: display_history + ema_warmup
    """
    logging.info(f"Iniciando BACKFILL estricto con {ecosystem} para {timeframe}...")
    try:
        exchange = get_exchange(ecosystem)
        history_map = {}
        
        required_candles = get_required_limit(timeframe, display_days)
        
        for symbol in BR1_BREADTH_UNIVERSE_V1:
            try:
                ohlcv = fetch_all_ohlcv(exchange, symbol, timeframe, required_candles)
                if not ohlcv or len(ohlcv) < 50:
                    continue
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                # Correction 7: Filter out incomplete candle
                df = df.iloc[:-1]
                if df.empty:
                    continue
                    
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                
                if len(df) >= 200:
                    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
                else:
                    df['ema200'] = np.nan
                
                # Iterar SOLO las velas de la ventana de visualización, no el warmup!
                # Si no, sobrescribimos toda la base de datos perdiendo el tiempo.
                # display_days + warmup = required_candles.
                # Las primeras `warmup` velas no deben guardarse porque sus EMA no son precisas.
                df_to_save = df.tail(display_days)
                
                for _, row in df_to_save.iterrows():
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
                'data_status': determine_data_status(hm['assets_total'], len(BR1_BREADTH_UNIVERSE_V1), hm['ema20_valid'], hm['ema50_valid'], hm['ema200_valid']),
                'status': 'SUCCESS'
            }
            
            save_breadth_snapshot(snapshot)
            saved_count += 1
            
        return True, saved_count
    except Exception as e:
        logging.error(f"Error global en backfill: {e}")
        return False, str(e)
