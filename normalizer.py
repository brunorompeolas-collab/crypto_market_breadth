import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List

def is_candle_closed(candle_time: pd.Timestamp, timeframe: str) -> bool:
    """
    P0-A11: Determine completeness based on timeframe, current UTC time, and candle boundaries.
    candle_time is the start of the candle boundary.
    """
    now = datetime.now(timezone.utc)
    if timeframe == '4h':
        # 4h candle is closed if now >= candle_time + 4 hours
        return now >= candle_time + pd.Timedelta(hours=4)
    elif timeframe == '1d':
        return now >= candle_time + pd.Timedelta(days=1)
    elif timeframe == '1w':
        return now >= candle_time + pd.Timedelta(days=7)
    return True

def resample_provider_prices(prices: List[Dict[str, float]], timeframe: str) -> pd.DataFrame:
    """
    A4: Normalized Timeframe / Resampling.
    Takes [{"timestamp": ms, "price": float}] and resamples to target timeframe.
    """
    if not prices:
        return pd.DataFrame()
        
    df = pd.DataFrame(prices)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('datetime')
    
    # Resampling rule
    rule = '4h' if timeframe == '4h' else '1d' if timeframe == '1d' else 'W-MON'
    
    # For Breadth we only strictly need the closing price of the period
    # We take the last price in the period bucket as the 'close'
    resampled = df['price'].resample(rule).last().dropna().reset_index()
    resampled = resampled.rename(columns={'price': 'close'})
    
    # Filter out the open (incomplete) candle
    closed_candles = []
    for _, row in resampled.iterrows():
        if is_candle_closed(row['datetime'], timeframe):
            closed_candles.append(row)
            
    if not closed_candles:
        return pd.DataFrame()
        
    return pd.DataFrame(closed_candles)
