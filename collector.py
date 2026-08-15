import ccxt
import pandas as pd
import numpy as np
import requests

TOP_SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
    'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'MATIC/USDT', 'LTC/USDT',
    'UNI/USDT', 'ATOM/USDT', 'FIL/USDT', 'ICP/USDT', 'NEAR/USDT'
]

def calculate_emas(closes):
    if len(closes) < 30:
        return None, None, None
    s = pd.Series(closes)
    ema20 = s.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = s.ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = s.ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else s.ewm(span=len(closes), adjust=False).mean().iloc[-1]
    return ema20, ema50, ema200

def fetch_exchange_candles(exchange_obj, symbol):
    try:
        ohlcv = exchange_obj.fetch_ohlcv(symbol, timeframe='1d', limit=205)
        if ohlcv and len(ohlcv) >= 30:
            return [c[4] for c in ohlcv]
    except Exception:
        pass
    return None

def get_crypto_breadth_data():
    binance = ccxt.binance({'enableRateLimit': True, 'timeout': 7000})
    bybit = ccxt.bybit({'enableRateLimit': True, 'timeout': 7000})
    
    records = []
    source_concordance = []

    for sym in TOP_SYMBOLS:
        closes_binance = fetch_exchange_candles(binance, sym)
        closes_bybit = fetch_exchange_candles(bybit, sym)
        
        # Validación de fuente: priorizar la mediana o la fuente disponible
        valid_series = [s for s in [closes_binance, closes_bybit] if s is not None]
        
        if not valid_series:
            continue

        # Si ambas fuentes responden, calcular discrepancia porcentual del último precio
        if len(valid_series) == 2:
            p_binance = closes_binance[-1]
            p_bybit = closes_bybit[-1]
            discrepancy = abs(p_binance - p_bybit) / ((p_binance + p_bybit) / 2) * 100
            source_concordance.append(discrepancy <= 1.0)
            # Usar promedio de cierres
            closes = list(np.mean([closes_binance, closes_bybit], axis=0))
        else:
            closes = valid_series[0]
            source_concordance.append(True)

        last_price = closes[-1]
        prev_price = closes[-2] if len(closes) > 1 else last_price
        change_24h = ((last_price - prev_price) / prev_price) * 100
        
        ema20, ema50, ema200 = calculate_emas(closes)
        if ema20 is None:
            continue

        records.append({
            'Activo': sym.replace('/USDT', ''),
            'Precio ($)': f"${last_price:,.4f}" if last_price < 1 else f"${last_price:,.2f}",
            'Var 24h': round(change_24h, 2),
            'EMA 20': "🟢 Superada" if last_price > ema20 else "🔴 Por debajo",
            'EMA 50': "🟢 Superada" if last_price > ema50 else "🔴 Por debajo",
            'EMA 200': "🟢 Superada" if last_price > ema200 else "🔴 Por debajo",
            'raw_above_ema20': last_price > ema20,
            'raw_above_ema50': last_price > ema50,
            'raw_above_ema200': last_price > ema200,
        })

    if not records:
        df_empty = pd.DataFrame(columns=['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200'])
        return df_empty, 50.0, 50.0, 50.0, 50.0, "Sin conexión con fuentes de datos"

    df = pd.DataFrame(records)
    total = len(df)
    
    ema20_pct = (df['raw_above_ema20'].sum() / total) * 100
    ema50_pct = (df['raw_above_ema50'].sum() / total) * 100
    ema200_pct = (df['raw_above_ema200'].sum() / total) * 100
    breadth_score = (ema20_pct * 0.2) + (ema50_pct * 0.3) + (ema200_pct * 0.5)
    
    # Nivel de confianza en los datos
    confidence_pct = (sum(source_concordance) / len(source_concordance)) * 100 if source_concordance else 100.0
    data_quality = f"Consenso Multi-Exchange: {confidence_pct:.1f}% de concordancia"

    return df, breadth_score, ema20_pct, ema50_pct, ema200_pct, data_quality
