import ccxt
import pandas as pd
import numpy as np

# Top activos con formato estándar
TOP_SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
    'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'LTC/USDT', 'UNI/USDT',
    'ATOM/USDT', 'FIL/USDT', 'ICP/USDT', 'TRX/USDT', 'BCH/USDT'
]

def calculate_emas(closes):
    if len(closes) < 30:
        return None, None, None
    s = pd.Series(closes)
    ema20 = s.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = s.ewm(span=50, adjust=False).mean().iloc[-1] if len(closes) >= 50 else s.ewm(span=len(closes), adjust=False).mean().iloc[-1]
    ema200 = s.ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else s.ewm(span=len(closes), adjust=False).mean().iloc[-1]
    return ema20, ema50, ema200

def get_crypto_breadth_data():
    # Exchanges sin bloqueo geográfico de IP en servidores cloud
    exchanges = [
        ('Kraken', ccxt.kraken({'enableRateLimit': True, 'timeout': 5000})),
        ('KuCoin', ccxt.kucoin({'enableRateLimit': True, 'timeout': 5000})),
        ('OKX', ccxt.okx({'enableRateLimit': True, 'timeout': 5000}))
    ]
    
    records = []
    used_exchange = None

    for name, exchange in exchanges:
        records = []
        try:
            exchange.load_markets()
            for sym in TOP_SYMBOLS:
                # Adaptar símbolo si el exchange usa USD en lugar de USDT (ej. Kraken)
                target_sym = sym
                if sym not in exchange.markets:
                    usd_sym = sym.replace('/USDT', '/USD')
                    if usd_sym in exchange.markets:
                        target_sym = usd_sym
                    else:
                        continue
                
                try:
                    ohlcv = exchange.fetch_ohlcv(target_sym, timeframe='1d', limit=205)
                    if not ohlcv or len(ohlcv) < 30:
                        continue
                    
                    closes = [c[4] for c in ohlcv]
                    last_price = closes[-1]
                    prev_price = closes[-2] if len(closes) > 1 else last_price
                    change_24h = ((last_price - prev_price) / prev_price) * 100
                    
                    ema20, ema50, ema200 = calculate_emas(closes)
                    if ema20 is None:
                        continue
                    
                    records.append({
                        'Activo': sym.split('/')[0],
                        'Precio ($)': f"${last_price:,.4f}" if last_price < 1 else f"${last_price:,.2f}",
                        'Var 24h': round(change_24h, 2),
                        'EMA 20': "🟢 Superada" if last_price > ema20 else "🔴 Por debajo",
                        'EMA 50': "🟢 Superada" if last_price > ema50 else "🔴 Por debajo",
                        'EMA 200': "🟢 Superada" if last_price > ema200 else "🔴 Por debajo",
                        'raw_above_ema20': last_price > ema20,
                        'raw_above_ema50': last_price > ema50,
                        'raw_above_ema200': last_price > ema200,
                    })
                except Exception:
                    continue
            
            if len(records) >= 8:
                used_exchange = name
                break
        except Exception:
            continue

    if not records:
        df_empty = pd.DataFrame(columns=['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200'])
        return df_empty, 0.0, 0.0, 0.0, 0.0, "Sin conexión con exchanges"

    df = pd.DataFrame(records)
    total = len(df)
    
    ema20_pct = (df['raw_above_ema20'].sum() / total) * 100
    ema50_pct = (df['raw_above_ema50'].sum() / total) * 100
    ema200_pct = (df['raw_above_ema200'].sum() / total) * 100
    breadth_score = (ema20_pct * 0.2) + (ema50_pct * 0.3) + (ema200_pct * 0.5)
    data_quality = f"Datos en vivo ({used_exchange}) - {total} activos procesados"

    return df, breadth_score, ema20_pct, ema50_pct, ema200_pct, data_quality
