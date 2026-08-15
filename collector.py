import ccxt
import pandas as pd
import numpy as np

def fetch_top_crypto_symbols(limit=50):
    exchange = ccxt.binance({'enableRateLimit': True})
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = [
            s for s, t in tickers.items() 
            if s.endswith('/USDT') and not any(x in s for x in ['UP/', 'DOWN/', 'BEAR/', 'BULL/'])
        ]
        sorted_pairs = sorted(
            usdt_pairs, 
            key=lambda s: tickers[s].get('quoteVolume', 0) or 0, 
            reverse=True
        )
        return sorted_pairs[:limit]
    except Exception as e:
        # Lista de respaldo en caso de fallo de red
        return [
            'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT',
            'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT'
        ]

def calculate_emas(closes):
    if len(closes) < 200:
        return None, None, None
    s = pd.Series(closes)
    ema20 = s.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = s.ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = s.ewm(span=200, adjust=False).mean().iloc[-1]
    return ema20, ema50, ema200

def get_crypto_breadth_data():
    exchange = ccxt.binance({'enableRateLimit': True})
    symbols = fetch_top_crypto_symbols(50)
    
    records = []
    for sym in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(sym, timeframe='1d', limit=210)
            if not ohlcv or len(ohlcv) < 200:
                continue
            
            closes = [c[4] for c in ohlcv]
            last_price = closes[-1]
            prev_price = closes[-2]
            change_24h = ((last_price - prev_price) / prev_price) * 100
            
            ema20, ema50, ema200 = calculate_emas(closes)
            if ema20 is None:
                continue
                
            records.append({
                'symbol': sym,
                'price': last_price,
                'change_24h': round(change_24h, 2),
                'above_ema20': last_price > ema20,
                'above_ema50': last_price > ema50,
                'above_ema200': last_price > ema200
            })
        except Exception:
            continue

    df = pd.DataFrame(records)
    
    if df.empty:
        # Estructura por defecto si falla la conexión
        df = pd.DataFrame(columns=['symbol', 'price', 'change_24h', 'above_ema20', 'above_ema50', 'above_ema200'])
        return df, 50.0, 50.0, 50.0, 50.0

    total = len(df)
    ema20_pct = (df['above_ema20'].sum() / total) * 100
    ema50_pct = (df['above_ema50'].sum() / total) * 100
    ema200_pct = (df['above_ema200'].sum() / total) * 100
    
    # Score ponderado de amplitud (0 a 100)
    breadth_score = (ema20_pct * 0.2) + (ema50_pct * 0.3) + (ema200_pct * 0.5)
    
    return df, breadth_score, ema20_pct, ema50_pct, ema200_pct
