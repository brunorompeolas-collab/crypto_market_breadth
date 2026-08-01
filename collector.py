import ccxt
import pandas as pd
import numpy as np
import logging
import random
from typing import Dict, Any, List
from database import save_breadth_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_binance_exchange() -> ccxt.binance:
    """Initialize public Binance exchange client."""
    return ccxt.binance({
        'enableRateLimit': True,
        'timeout': 10000,
        'options': {'defaultType': 'spot'}
    })

def fetch_top_usdt_pairs(exchange: ccxt.binance, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch top USDT spot trading pairs on Binance sorted by 24h volume.
    Excludes leveraged/derivative tokens like UP, DOWN, BEAR, BULL.
    """
    logging.info("Fetching market tickers from Binance spot...")
    tickers = exchange.fetch_tickers()
    
    usdt_pairs = []
    excluded_keywords = ['UP/', 'DOWN/', 'BEAR/', 'BULL/', 'FDUSD/', 'USDC/', 'TUSD/', 'BUSD/', 'EUR/']
    
    for symbol, ticker in tickers.items():
        if not symbol.endswith('/USDT'):
            continue
        if any(keyword in symbol for keyword in excluded_keywords):
            continue
        
        quote_volume = ticker.get('quoteVolume') or 0
        if quote_volume > 0 and ticker.get('close') is not None:
            usdt_pairs.append({
                'symbol': symbol,
                'quote_volume': quote_volume,
                'price': ticker.get('close'),
                'percentage_24h': ticker.get('percentage', 0.0)
            })
            
    sorted_pairs = sorted(usdt_pairs, key=lambda x: x['quote_volume'], reverse=True)
    return sorted_pairs[:limit]

def calculate_emas_for_symbol(exchange: ccxt.binance, symbol: str, timeframe: str = '1d') -> Dict[str, Any]:
    """
    Fetch OHLCV candles for a symbol on timeframe ('4h', '1d', '1w') and calculate EMA20, EMA50, EMA200.
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=250)
        if len(ohlcv) < 50:
            return None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean() if len(df) >= 200 else df['close'].ewm(span=len(df), adjust=False).mean()
        
        last_row = df.iloc[-1]
        current_price = float(last_row['close'])
        
        return {
            'symbol': symbol,
            'price': current_price,
            'ema20': float(last_row['ema20']),
            'ema50': float(last_row['ema50']),
            'ema200': float(last_row['ema200']),
            'above_ema20': bool(current_price > last_row['ema20']),
            'above_ema50': bool(current_price > last_row['ema50']),
            'above_ema200': bool(current_price > last_row['ema200'])
        }
    except Exception as e:
        logging.warning(f"Error fetching candles ({timeframe}) for {symbol}: {e}")
        return None

def generate_fallback_market_data(limit: int = 50, timeframe: str = '1d') -> Dict[str, Any]:
    """Generates realistic fallback data if Binance API is unreachable."""
    logging.warning(f"Generating fallback market breadth data for timeframe: {timeframe}...")
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", 
               "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "NEAR/USDT", "SUI/USDT", 
               "MATIC/USDT", "LTC/USDT", "UNI/USDT", "APT/USDT", "FET/USDT", "PEPE/USDT",
               "SHIB/USDT", "RNDR/USDT", "INJ/USDT", "OP/USDT", "ARB/USDT", "TIA/USDT"]
    
    results = []
    btc_price = 64500.0
    
    for i, sym in enumerate(symbols[:limit]):
        base_price = 100.0 if "BTC" not in sym else btc_price
        if "ETH" in sym: base_price = 3400.0
        if "SOL" in sym: base_price = 180.0
        
        change_24h = round(random.uniform(-4.5, 6.5), 2)
        price = round(base_price * (1 + change_24h / 100), 2)
        if "BTC" in sym:
            btc_price = price
            
        above_20 = random.choice([True, True, False])
        above_50 = random.choice([True, False])
        above_200 = random.choice([True, False, False])
        
        results.append({
            'symbol': sym,
            'price': price,
            'ema20': round(price * 0.98, 2) if above_20 else round(price * 1.03, 2),
            'ema50': round(price * 0.95, 2) if above_50 else round(price * 1.05, 2),
            'ema200': round(price * 0.90, 2) if above_200 else round(price * 1.10, 2),
            'above_ema20': above_20,
            'above_ema50': above_50,
            'above_ema200': above_200,
            'quote_volume': random.randint(10000000, 500000000),
            'change_24h': change_24h
        })
        
    total_valid = len(results)
    cnt_above_ema20 = sum(1 for r in results if r['above_ema20'])
    cnt_above_ema50 = sum(1 for r in results if r['above_ema50'])
    cnt_above_ema200 = sum(1 for r in results if r['above_ema200'])
    
    pct_above_ema20 = round((cnt_above_ema20 / total_valid) * 100, 1)
    pct_above_ema50 = round((cnt_above_ema50 / total_valid) * 100, 1)
    pct_above_ema200 = round((cnt_above_ema200 / total_valid) * 100, 1)
    
    breadth_score = round(
        (0.20 * pct_above_ema20) + (0.30 * pct_above_ema50) + (0.50 * pct_above_ema200), 1
    )
    
    payload = {
        'total_assets_analyzed': total_valid,
        'pct_above_ema20': pct_above_ema20,
        'pct_above_ema50': pct_above_ema50,
        'pct_above_ema200': pct_above_ema200,
        'market_breadth_score': breadth_score,
        'btc_price': btc_price,
        'timeframe': timeframe,
        'assets_detail': results,
        'is_fallback': True
    }
    
    save_breadth_snapshot(payload, timeframe=timeframe)
    return payload

def fetch_market_breadth_data(top_n: int = 50, timeframe: str = '1d') -> Dict[str, Any]:
    """
    Collect data for top N USDT pairs for timeframe ('4h', '1d', '1w').
    Computes EMAs, aggregates Market Breadth metrics, extracts BTC price, and saves snapshot into SQLite.
    """
    try:
        exchange = get_binance_exchange()
        top_pairs = fetch_top_usdt_pairs(exchange, limit=top_n)
        
        results = []
        btc_price = 65000.0
        
        for item in top_pairs:
            symbol = item['symbol']
            ema_data = calculate_emas_for_symbol(exchange, symbol, timeframe=timeframe)
            if ema_data:
                ema_data['quote_volume'] = item['quote_volume']
                ema_data['change_24h'] = item['percentage_24h']
                results.append(ema_data)
                if symbol == "BTC/USDT":
                    btc_price = ema_data['price']
                
        if not results:
            return generate_fallback_market_data(limit=top_n, timeframe=timeframe)
            
        total_valid = len(results)
        cnt_above_ema20 = sum(1 for r in results if r['above_ema20'])
        cnt_above_ema50 = sum(1 for r in results if r['above_ema50'])
        cnt_above_ema200 = sum(1 for r in results if r['above_ema200'])
        
        pct_above_ema20 = round((cnt_above_ema20 / total_valid) * 100, 1)
        pct_above_ema50 = round((cnt_above_ema50 / total_valid) * 100, 1)
        pct_above_ema200 = round((cnt_above_ema200 / total_valid) * 100, 1)
        
        breadth_score = round(
            (0.20 * pct_above_ema20) + 
            (0.30 * pct_above_ema50) + 
            (0.50 * pct_above_ema200), 
            1
        )
        
        payload = {
            'total_assets_analyzed': total_valid,
            'pct_above_ema20': pct_above_ema20,
            'pct_above_ema50': pct_above_ema50,
            'pct_above_ema200': pct_above_ema200,
            'market_breadth_score': breadth_score,
            'btc_price': btc_price,
            'timeframe': timeframe,
            'assets_detail': results,
            'is_fallback': False
        }
        
        save_breadth_snapshot(payload, timeframe=timeframe)
        return payload
    except Exception as err:
        logging.error(f"Error fetching live data from Binance: {err}")
        return generate_fallback_market_data(limit=top_n, timeframe=timeframe)

if __name__ == "__main__":
    print("Testing Binance Market Breadth Collector with SQLite persistence...")
    data = fetch_market_breadth_data(top_n=10, timeframe='1d')
    print(f"Analyzed Assets: {data['total_assets_analyzed']}")
    print(f"Breadth Score: {data['market_breadth_score']}")
    print(f"BTC Price: ${data['btc_price']:,.2f}")
