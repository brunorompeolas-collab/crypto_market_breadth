import ccxt
import pandas as pd
import numpy as np
import streamlit as st

ECOSYSTEMS = {
    "Global": [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
        'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
        'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'LTC/USDT', 'UNI/USDT',
        'ATOM/USDT', 'FIL/USDT', 'ICP/USDT', 'TRX/USDT', 'BCH/USDT'
    ],
    "Bitcoin": [
        'BTC/USDT', 'BCH/USDT', 'LTC/USDT', 'DOGE/USDT', 'ETC/USDT', 'STX/USDT'
    ],
    "Ethereum": [
        'ETH/USDT', 'UNI/USDT', 'LINK/USDT', 'AAVE/USDT', 'OP/USDT', 
        'ARB/USDT', 'MATIC/USDT', 'LDO/USDT', 'MKR/USDT', 'CRV/USDT'
    ],
    "Solana": [
        'SOL/USDT', 'RAY/USDT', 'JTO/USDT', 'PYTH/USDT', 'BONK/USDT',
        'AVAX/USDT', 'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'SEI/USDT'
    ]
}

TIMEFRAME_CONFIG = {
    "1D": {"tf": "1d", "limits": {"1M": 30, "3M": 90, "6M": 180, "1A": 365, "4A": 1460, "Todo": 2000}},
    "1W": {"tf": "1w", "limits": {"1M": 4, "3M": 13, "6M": 26, "1A": 52, "4A": 208, "Todo": 520}},
    "1M": {"tf": "1M", "limits": {"1M": 1, "3M": 3, "6M": 6, "1A": 12, "4A": 48, "Todo": 120}}
}

# Caché en memoria para evitar descargas repetidas de internet
@st.cache_data(ttl=600, show_spinner=False)
def fetch_raw_market_candles(ecosystem_name, tf_code):
    symbols = ECOSYSTEMS.get(ecosystem_name, ECOSYSTEMS["Global"])
    exchanges = [
        ('Kraken', ccxt.kraken({'enableRateLimit': True, 'timeout': 6000})),
        ('KuCoin', ccxt.kucoin({'enableRateLimit': True, 'timeout': 6000})),
        ('OKX', ccxt.okx({'enableRateLimit': True, 'timeout': 6000}))
    ]
    
    candles = {}
    used_exchange = "Kraken"
    
    for name, exchange in exchanges:
        candles = {}
        try:
            exchange.load_markets()
            for sym in symbols:
                target_sym = sym
                if sym not in exchange.markets:
                    usd_sym = sym.replace('/USDT', '/USD')
                    if usd_sym in exchange.markets:
                        target_sym = usd_sym
                    else:
                        continue
                
                try:
                    ohlcv = exchange.fetch_ohlcv(target_sym, timeframe=tf_code, limit=1200)
                    if ohlcv and len(ohlcv) >= 20:
                        df_c = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df_c['timestamp'] = pd.to_datetime(df_c['timestamp'], unit='ms')
                        candles[sym.split('/')[0]] = df_c
                except Exception:
                    continue
            
            if len(candles) >= max(3, len(symbols) // 3):
                used_exchange = name
                # Descargar BTC de referencia
                if 'BTC' not in candles:
                    for btc_p in ['BTC/USDT', 'BTC/USD']:
                        if btc_p in exchange.markets:
                            try:
                                b_ohlcv = exchange.fetch_ohlcv(btc_p, timeframe=tf_code, limit=1200)
                                df_b = pd.DataFrame(b_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                                df_b['timestamp'] = pd.to_datetime(df_b['timestamp'], unit='ms')
                                candles['BTC'] = df_b
                                break
                            except Exception:
                                pass
                break
        except Exception:
            continue
            
    return candles, used_exchange

def get_crypto_breadth_data(selected_ecosystem="Global", timeframe_label="1D", range_label="3M"):
    tf_conf = TIMEFRAME_CONFIG.get(timeframe_label, TIMEFRAME_CONFIG["1D"])
    tf = tf_conf["tf"]
    display_limit = tf_conf["limits"].get(range_label, 90)
    
    # Obtiene datos cacheados instantáneamente
    candles_by_symbol, used_exchange = fetch_raw_market_candles(selected_ecosystem, tf)

    if not candles_by_symbol:
        df_empty = pd.DataFrame(columns=['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200'])
        df_hist_empty = pd.DataFrame(columns=['timestamp', 'breadth_score', 'pct_above_ema20', 'pct_above_ema50', 'pct_above_ema200', 'btc_price'])
        return df_empty, 0.0, 0.0, 0.0, 0.0, df_hist_empty, "Sin conexión"

    records = []
    series_above_ema20 = {}
    series_above_ema50 = {}
    series_above_ema200 = {}

    for sym, df_c in candles_by_symbol.items():
        df_c = df_c.copy()
        df_c['ema20'] = df_c['close'].ewm(span=20, adjust=False).mean()
        df_c['ema50'] = df_c['close'].ewm(span=50, adjust=False).mean() if len(df_c) >= 50 else df_c['close'].ewm(span=len(df_c), adjust=False).mean()
        df_c['ema200'] = df_c['close'].ewm(span=200, adjust=False).mean() if len(df_c) >= 200 else df_c['close'].ewm(span=len(df_c), adjust=False).mean()
        
        last_row = df_c.iloc[-1]
        prev_row = df_c.iloc[-2] if len(df_c) > 1 else last_row
        change = ((last_row['close'] - prev_row['close']) / prev_row['close']) * 100

        records.append({
            'Activo': sym,
            'Precio ($)': f"${last_row['close']:,.4f}" if last_row['close'] < 1 else f"${last_row['close']:,.2f}",
            'Var 24h': round(change, 2),
            'EMA 20': "🟢 Superada" if last_row['close'] > last_row['ema20'] else "🔴 Por debajo",
            'EMA 50': "🟢 Superada" if last_row['close'] > last_row['ema50'] else "🔴 Por debajo",
            'EMA 200': "🟢 Superada" if last_row['close'] > last_row['ema200'] else "🔴 Por debajo",
            'raw_above_ema20': last_row['close'] > last_row['ema20'],
            'raw_above_ema50': last_row['close'] > last_row['ema50'],
            'raw_above_ema200': last_row['close'] > last_row['ema200'],
        })

        df_idx = df_c.set_index('timestamp')
        series_above_ema20[sym] = (df_idx['close'] > df_idx['ema20']).astype(int)
        series_above_ema50[sym] = (df_idx['close'] > df_idx['ema50']).astype(int)
        series_above_ema200[sym] = (df_idx['close'] > df_idx['ema200']).astype(int)

    df_assets = pd.DataFrame(records)
    total = len(df_assets)
    ema20_pct = (df_assets['raw_above_ema20'].sum() / total) * 100
    ema50_pct = (df_assets['raw_above_ema50'].sum() / total) * 100
    ema200_pct = (df_assets['raw_above_ema200'].sum() / total) * 100
    breadth_score = (ema20_pct * 0.2) + (ema50_pct * 0.3) + (ema200_pct * 0.5)

    df_e20 = pd.DataFrame(series_above_ema20).dropna(how='all')
    df_e50 = pd.DataFrame(series_above_ema50).dropna(how='all')
    df_e200 = pd.DataFrame(series_above_ema200).dropna(how='all')

    hist_dates = df_e20.index[-display_limit:]
    btc_df_idx = candles_by_symbol['BTC'].set_index('timestamp') if 'BTC' in candles_by_symbol else None
    hist_records = []

    for dt in hist_dates:
        r20 = df_e20.loc[dt].dropna() if dt in df_e20.index else pd.Series()
        r50 = df_e50.loc[dt].dropna() if dt in df_e50.index else pd.Series()
        r200 = df_e200.loc[dt].dropna() if dt in df_e200.index else pd.Series()

        if len(r20) > 0:
            p20 = (r20.sum() / len(r20)) * 100
            p50 = (r50.sum() / len(r50)) * 100 if len(r50) > 0 else p20
            p200 = (r200.sum() / len(r200)) * 100 if len(r200) > 0 else p50
            b_score = (p20 * 0.2) + (p50 * 0.3) + (p200 * 0.5)
            btc_p = btc_df_idx.loc[dt]['close'] if (btc_df_idx is not None and dt in btc_df_idx.index) else None

            hist_records.append({
                'timestamp': dt,
                'breadth_score': round(b_score, 1),
                'pct_above_ema20': round(p20, 1),
                'pct_above_ema50': round(p50, 1),
                'pct_above_ema200': round(p200, 1),
                'btc_price': btc_p
            })

    df_history = pd.DataFrame(hist_records)
    if len(df_history) >= 4:
        df_history['breadth_smooth'] = df_history['breadth_score'].rolling(window=3, min_periods=1).mean().round(1)
    else:
        df_history['breadth_smooth'] = df_history['breadth_score']

    data_quality = f"En vivo ({used_exchange}) - {total} activos | {timeframe_label} | {range_label}"
    return df_assets, breadth_score, ema20_pct, ema50_pct, ema200_pct, df_history, data_quality

    df_history = pd.DataFrame(hist_records)
    data_quality = f"Datos en vivo ({used_exchange}) - {total} activos | Temporalidad: {timeframe_label} | Rango: {range_label}"

    return df_assets, breadth_score, ema20_pct, ema50_pct, ema200_pct, df_history, data_quality
