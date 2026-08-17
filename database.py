import sqlite3
import os
import pandas as pd
from typing import Dict, Any, List
import logging

DB_PATH = os.path.join(os.path.dirname(__file__), 'crypto_breadth.db')

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    """
    A5. Database Provider Migration.
    Drop old schema and create the new one with 'provider' replacing 'exchange'.
    """
    conn = get_connection()
    c = conn.cursor()
    
    # HF1: Never drop history on start
    # c.execute("DROP TABLE IF EXISTS breadth_snapshots")
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS breadth_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candle_time TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            provider TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            universe_version TEXT NOT NULL,
            breadth_score REAL NOT NULL,
            pct_above_ema20 REAL NOT NULL,
            pct_above_ema50 REAL NOT NULL,
            pct_above_ema200 REAL NOT NULL,
            btc_price REAL NOT NULL,
            eth_price REAL NOT NULL,
            assets_total INTEGER NOT NULL,
            assets_ema20_valid INTEGER NOT NULL,
            assets_ema50_valid INTEGER NOT NULL,
            assets_ema200_valid INTEGER NOT NULL,
            data_status TEXT NOT NULL,
            UNIQUE(provider, timeframe, universe_version, candle_time)
        )
    ''')
    
    # Index for fast historical queries
    c.execute('CREATE INDEX IF NOT EXISTS idx_breadth_query ON breadth_snapshots(provider, timeframe, universe_version, candle_time)')
    
    conn.commit()
    conn.close()

def reset_db():
    """
    HF1: Explicitly drop and recreate the database schema.
    NEVER call this from app.py. Used only for manual dev resets.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS breadth_snapshots")
    conn.commit()
    conn.close()
    init_db()

def save_breadth_snapshot(snapshot: Dict[str, Any]):
    """
    P0.3 / A5 - Clean save API using UPSERT (REPLACE)
    """
    if snapshot.get("status") != "SUCCESS":
        # Do not save failed snapshots
        return
        
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO breadth_snapshots (
            candle_time, collected_at, provider, timeframe, universe_version,
            breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200,
            btc_price, eth_price, assets_total, assets_ema20_valid,
            assets_ema50_valid, assets_ema200_valid, data_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        snapshot['candle_time'],
        snapshot['collected_at'],
        snapshot['provider'],
        snapshot['timeframe'],
        snapshot['universe_version'],
        float(snapshot['breadth_score']),
        float(snapshot['pct_above_ema20']),
        float(snapshot['pct_above_ema50']),
        float(snapshot['pct_above_ema200']),
        float(snapshot['btc_price']),
        float(snapshot['eth_price']),
        int(snapshot['assets_total']),
        int(snapshot['assets_ema20_valid']),
        int(snapshot['assets_ema50_valid']),
        int(snapshot['assets_ema200_valid']),
        snapshot['data_status']
    ))
    conn.commit()
    conn.close()

def get_historical_breadth(timeframe: str = '1d', days: int = 30, provider: str = 'coingecko') -> pd.DataFrame:
    """
    Retrieves history for chart rendering.
    If days == 0, fetch ALL history (Total).
    HF2: `days` represents physical days, not number of snapshots.
    """
    conn = get_connection()
    
    if days > 0:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
        
        query = '''
            SELECT candle_time as timestamp, breadth_score, pct_above_ema50, pct_above_ema200, btc_price, eth_price
            FROM breadth_snapshots
            WHERE timeframe = ? AND provider = ? AND candle_time >= ?
            ORDER BY candle_time DESC
        '''
        df = pd.read_sql_query(query, conn, params=(timeframe, provider, cutoff_str))
    else:
        query = '''
            SELECT candle_time as timestamp, breadth_score, pct_above_ema50, pct_above_ema200, btc_price, eth_price
            FROM breadth_snapshots
            WHERE timeframe = ? AND provider = ?
            ORDER BY candle_time DESC
        '''
        df = pd.read_sql_query(query, conn, params=(timeframe, provider))
        
    conn.close()
    
    if not df.empty:
        # Reverse to chronological order for charts
        df = df.sort_values('timestamp').reset_index(drop=True)
        
    return df

def get_recent_snapshots_trend(timeframe: str, limit: int = 7, provider: str = 'coingecko', universe: str = 'BR1-BREADTH-UNIVERSE-v1') -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT candle_time, breadth_score, btc_price, eth_price, data_status
        FROM breadth_snapshots
        WHERE timeframe = ? AND provider = ? AND universe_version = ?
        ORDER BY candle_time DESC
        LIMIT ?
    ''', (timeframe, provider, universe, limit))
    
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return []
        
    results = []
    for r in rows:
        results.append({
            "candle_time": r[0],
            "breadth_score": float(r[1]),
            "btc_price": float(r[2]),
            "eth_price": float(r[3]),
            "data_status": r[4]
        })
        
    # Return chronologically ascending (oldest to newest)
    results.reverse()
    return results
