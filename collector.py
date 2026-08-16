import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

# Cestas por ecosistema
ECOSYSTEMS = {
    "Mercado Global (Top)": [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
        'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
        'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'LTC/USDT', 'UNI/USDT',
        'ATOM/USDT', 'FIL/USDT', 'ICP/USDT', 'TRX/USDT', 'BCH/USDT'
    ],
    "Ecosistema Bitcoin / PoW": [
        'BTC/USDT', 'BCH/USDT', 'LTC/USDT', 'DOGE/USDT', 'ETC/USDT', 'STX/USDT'
    ],
    "Ecosistema Ethereum / L2 / DeFi": [
        'ETH/USDT', 'UNI/USDT', 'LINK/USDT', 'AAVE/USDT', 'OP/USDT', 
        'ARB/USDT', 'MATIC/USDT', 'LDO/USDT', 'MKR/USDT', 'CRV/USDT'
    ],
    "Ecosistema Solana / L1s Alternativas": [
        'SOL/USDT', 'RAY/USDT', 'JTO/USDT', 'PYTH/USDT', 'BONK/USDT',
        'AVAX/USDT', 'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'SEI/USDT'
    ]
}

TIMEFRAME_MAP = {
    "Diario (1D)": "1d",
    "Semanal (1W)": "1w",
    "Mensual (1M)": "1M"
}

RANGE_LIMIT_MAP = {
    "1 Mes": 30,
    "3 Meses": 90,
    "6 Meses": 180,
    "1 Año": 365,
    "4 Años": 1460,
    "10 Años / Histórico": 2000
}

def get_crypto_breadth_data(selected_ecosystem="Mercado Global (Top)", timeframe_label="Diario (1D)", range_label="3 Meses"):
    symbols_to_fetch = ECOSYSTEMS.get(selected_ecosystem, ECOSYSTEMS["Mercado Global (Top)"])
    tf = TIMEFRAME_MAP.get(timeframe_label, "1d")
    history_window = RANGE_LIMIT_MAP.get(range_label, 90)
    
    # Necesitamos al menos 200 velas previas para estabilizar la EMA 200
    fetch_limit = min(2000, history_window + 220)
    
    exchanges = [
        ('Kraken', ccxt.kraken({'enableRateLimit': True, 'timeout': 6000})),
        ('KuCoin', ccxt.kucoin({'enableRateLimit': True, 'timeout': 6000})),
        ('OKX', ccxt.okx({'enableRateLimit': True, 'timeout': 6000}))
    ]
    
    used_exchange = None
    candles_by_symbol = {}
    timestamps = []

    for name, exchange in exchanges:
        candles_by_symbol = {}
        try:
            exchange.load_markets()
            for sym in symbols_to_fetch:
                target_sym = sym
                if sym not in exchange.markets:
                    usd_sym = sym.replace('/USDT', '/USD')
                    if usd_sym in exchange.markets:
                        target_sym = usd_sym
                    else:
                        continue
                
                try:
                    ohlcv = exchange.fetch_ohlcv(target_sym, timeframe=tf, limit=fetch_limit)
                    if ohlcv and len(ohlcv) >= 30:
                        df_c = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df_c['timestamp'] = pd.to_datetime(df_c['timestamp'], unit='ms')
                        candles_by_symbol[sym.split('/')[0]] = df_c
                except Exception:
                    continue
            
            if len(candles_by_symbol) >= max(3, len(symbols_to_fetch) // 3):
                used_exchange = name
                # Obtener también BTC para superposición de precio de referencia
                if 'BTC' not in candles_by_symbol and 'BTC/USDT' in exchange.markets:
                    try:
                        btc_ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe=tf, limit=fetch_limit)
                        df_btc = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df_btc['timestamp'] = pd.to_datetime(df_btc['timestamp'], unit='ms')
                        candles_by_symbol['BTC'] = df_btc
                    except Exception:
                        pass
                break
        except Exception:
            continue

    if not candles_by_symbol:
        df_empty = pd.DataFrame(columns=['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200'])
        df_hist_empty = pd.DataFrame(columns=['timestamp', 'breadth_score', 'pct_above_ema20', 'pct_above_ema50', 'pct_above_ema200', 'btc_price'])
        return df_empty, 0.0, 0.0, 0.0, 0.0, df_hist_empty, "Sin conexión con exchanges"

    # Procesar métricas actuales por activo
    records = []
    series_above_ema20 = {}
    series_above_ema50 = {}
    series_above_ema200 = {}
    common_dates = None

    for sym, df_c in candles_by_symbol.items():
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

        # Series booleanas históricas alineadas por fecha
        df_indexed = df_c.set_index('timestamp')
        series_above_ema20[sym] = (df_indexed['close'] > df_indexed['ema20']).astype(int)
        series_above_ema50[sym] = (df_indexed['close'] > df_indexed['ema50']).astype(int)
        series_above_ema200[sym] = (df_indexed['close'] > df_indexed['ema200']).astype(int)

    df_assets = pd.DataFrame(records)
    total = len(df_assets)
    ema20_pct = (df_assets['raw_above_ema20'].sum() / total) * 100
    ema50_pct = (df_assets['raw_above_ema50'].sum() / total) * 100
    ema200_pct = (df_assets['raw_above_ema200'].sum() / total) * 100
    breadth_score = (ema20_pct * 0.2) + (ema50_pct * 0.3) + (ema200_pct * 0.5)

    # Construir histórico continuo retrospectivo
    df_ema20_all = pd.DataFrame(series_above_ema20).dropna(how='all')
    df_ema50_all = pd.DataFrame(series_above_ema50).dropna(how='all')
    df_ema200_all = pd.DataFrame(series_above_ema200).dropna(how='all')

    hist_dates = df_ema20_all.index[-history_window:]
    hist_records = []

    btc_df_idx = candles_by_symbol['BTC'].set_index('timestamp') if 'BTC' in candles_by_symbol else None

    for dt in hist_dates:
        row20 = df_ema20_all.loc[dt].dropna() if dt in df_ema20_all.index else pd.Series()
        row50 = df_ema50_all.loc[dt].dropna() if dt in df_ema50_all.index else pd.Series()
        row200 = df_ema200_all.loc[dt].dropna() if dt in df_ema200_all.index else pd.Series()

        if len(row20) > 0:
            p20 = (row20.sum() / len(row20)) * 100
            p50 = (row50.sum() / len(row50)) * 100 if len(row50) > 0 else p20
            p200 = (row200.sum() / len(row200)) * 100 if len(row200) > 0 else p50
            b_score = (p20 * 0.2) + (p50 * 0.3) + (p200 * 0.5)
            
            btc_price = btc_df_idx.loc[dt]['close'] if (btc_df_idx is not None and dt in btc_df_idx.index) else None

            hist_records.append({
                'timestamp': dt,
                'breadth_score': round(b_score, 1),
                'pct_above_ema20': round(p20, 1),
                'pct_above_ema50': round(p50, 1),
                'pct_above_ema200': round(p200, 1),
                'btc_price': btc_price
            })

    df_history = pd.DataFrame(hist_records)
    data_quality = f"Datos en vivo ({used_exchange}) - {total} activos | Temporalidad: {timeframe_label} | Rango: {range_label}"

    return df_assets, breadth_score, ema20_pct, ema50_pct, ema200_pct, df_history, data_quality
