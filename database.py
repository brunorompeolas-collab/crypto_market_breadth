import sqlite3
import os
import logging
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "breadth_data.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates breadth_snapshots table if it does not exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS breadth_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candle_time TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                exchange TEXT NOT NULL,
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
                
                UNIQUE(exchange, timeframe, universe_version, candle_time) ON CONFLICT REPLACE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_breadth_query ON breadth_snapshots (exchange, timeframe, universe_version, candle_time)")
        conn.commit()
    logging.info(f"Database initialized at {DB_PATH}")

def save_breadth_snapshot(snapshot: Dict[str, Any]) -> bool:
    """
    Saves a single market breadth snapshot to SQLite using the clean data model.
    """
    try:
        init_db()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO breadth_snapshots 
                (candle_time, collected_at, exchange, timeframe, universe_version, 
                 breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, 
                 btc_price, eth_price, assets_total, assets_ema20_valid, 
                 assets_ema50_valid, assets_ema200_valid, data_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.get('candle_time'),
                snapshot.get('collected_at', datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
                snapshot.get('exchange', 'unknown'),
                snapshot.get('timeframe', '1d'),
                snapshot.get('universe_version', 'BR1-BREADTH-UNIVERSE-v1'),
                snapshot.get('breadth_score', 0.0),
                snapshot.get('pct_above_ema20', 0.0),
                snapshot.get('pct_above_ema50', 0.0),
                snapshot.get('pct_above_ema200', 0.0),
                snapshot.get('btc_price', 0.0),
                snapshot.get('eth_price', 0.0),
                snapshot.get('assets_total', 0),
                snapshot.get('assets_ema20_valid', 0),
                snapshot.get('assets_ema50_valid', 0),
                snapshot.get('assets_ema200_valid', 0),
                snapshot.get('data_status', 'UNKNOWN')
            ))
            conn.commit()
        return True
    except Exception as e:
        logging.error(f"Failed to save breadth snapshot to DB: {e}")
        return False

def get_historical_breadth(timeframe: str = '1d', days: int = 365, exchange: str = 'binance', universe: str = 'BR1-BREADTH-UNIVERSE-v1') -> pd.DataFrame:
    """
    Queries historical breadth metrics. No synthetic data fallback.
    """
    init_db()
    
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days > 0 else "1970-01-01 00:00:00"
    
    query = """
        SELECT candle_time as timestamp, timeframe, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, btc_price, eth_price
        FROM breadth_snapshots
        WHERE timeframe = ? AND exchange = ? AND universe_version = ? AND candle_time >= ?
        ORDER BY candle_time ASC
    """
    
    try:
        with get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(timeframe, exchange, universe, cutoff_date))
            return df
    except Exception as e:
        logging.error(f"Error querying historical breadth: {e}")
        return pd.DataFrame()

def get_recent_snapshots_trend(timeframe: str = '1d', limit: int = 7, exchange: str = 'binance', universe: str = 'BR1-BREADTH-UNIVERSE-v1') -> List[Dict[str, Any]]:
    """
    Retrieves the last N snapshots in ascending chronological order for trend analysis.
    """
    init_db()
    
    query = """
        SELECT candle_time as timestamp, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, btc_price, eth_price
        FROM breadth_snapshots
        WHERE timeframe = ? AND exchange = ? AND universe_version = ?
        ORDER BY candle_time DESC
        LIMIT ?
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (timeframe, exchange, universe, limit))
            rows = cursor.fetchall()
            
        results = [dict(row) for row in reversed(rows)]
        return results
    except Exception as e:
        logging.error(f"Error fetching recent snapshots trend: {e}")
        return []

if __name__ == "__main__":
    init_db()
