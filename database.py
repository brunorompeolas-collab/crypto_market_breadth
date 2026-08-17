import sqlite3
import os
import logging
import random
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "breadth_data.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates daily_breadth table and indices if they do not exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_breadth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '1d',
                breadth_score REAL NOT NULL,
                pct_above_ema20 REAL NOT NULL,
                pct_above_ema50 REAL NOT NULL,
                pct_above_ema200 REAL NOT NULL,
                btc_price REAL NOT NULL,
                UNIQUE(timestamp, timeframe) ON CONFLICT REPLACE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeframe_ts ON daily_breadth (timeframe, timestamp)")
        conn.commit()
    logging.info(f"Database initialized at {DB_PATH}")

def save_breadth_snapshot(data: Dict[str, Any], timeframe: str = '1d') -> bool:
    """
    Saves a market breadth snapshot to SQLite.
    Returns True if successfully inserted/updated.
    """
    try:
        init_db()
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        breadth_score = float(data.get('market_breadth_score', 0.0))
        pct_ema20 = float(data.get('pct_above_ema20', 0.0))
        pct_ema50 = float(data.get('pct_above_ema50', 0.0))
        pct_ema200 = float(data.get('pct_above_ema200', 0.0))
        btc_price = float(data.get('btc_price', 65000.0))
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_breadth 
                (timestamp, timeframe, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, btc_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, timeframe, breadth_score, pct_ema20, pct_ema50, pct_ema200, btc_price))
            conn.commit()
            
        logging.info(f"Saved breadth snapshot [{timeframe}]: Score={breadth_score}, BTC=${btc_price:,.2f}")
        return True
    except Exception as e:
        logging.error(f"Failed to save breadth snapshot to DB: {e}")
        return False

def get_historical_breadth(timeframe: str = '1d', days: int = 30) -> pd.DataFrame:
    """
    Queries historical breadth metrics for a specific timeframe over the last N days.
    Returns a pandas DataFrame sorted by timestamp ascending.
    """
    init_db()
    seed_mock_history_if_empty()
    
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    query = """
        SELECT timestamp, timeframe, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, btc_price
        FROM daily_breadth
        WHERE timeframe = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    """
    
    try:
        with get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(timeframe, cutoff_date))
            if df.empty:
                query_all = "SELECT * FROM daily_breadth WHERE timeframe = ? ORDER BY timestamp ASC"
                df = pd.read_sql_query(query_all, conn, params=(timeframe,))
            return df
    except Exception as e:
        logging.error(f"Error querying historical breadth: {e}")
        return pd.DataFrame()

def get_recent_snapshots_trend(timeframe: str = '1d', limit: int = 7) -> List[Dict[str, Any]]:
    """
    Retrieves the last N snapshots for a given timeframe, returned in ascending chronological order.
    Useful for trend analysis and divergence detection between BTC price and Market Breadth.
    """
    init_db()
    seed_mock_history_if_empty()
    
    query = """
        SELECT timestamp, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, btc_price
        FROM daily_breadth
        WHERE timeframe = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (timeframe, limit))
            rows = cursor.fetchall()
            
        results = [dict(row) for row in reversed(rows)]
        return results
    except Exception as e:
        logging.error(f"Error fetching recent snapshots trend: {e}")
        return []

def seed_mock_history_if_empty():
    """Populates synthetic historical data for 4h, 1d, and 1w if table is empty."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM daily_breadth")
        row = cursor.fetchone()
        if row and row['count'] > 0:
            return

    logging.info("Seeding realistic historical market breadth data for testing...")
    
    now = datetime.utcnow()
    timeframes_days = [('1d', 90), ('4h', 30), ('1w', 180)]
    
    records = []
    base_btc = 58000.0
    
    for tf, max_days in timeframes_days:
        step_hours = 24 if tf == '1d' else (4 if tf == '4h' else 168)
        num_steps = int((max_days * 24) / step_hours)
        
        current_btc = base_btc
        current_score = 55.0
        
        for i in range(num_steps, 0, -1):
            dt = now - timedelta(hours=i * step_hours)
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            
            price_change_pct = random.uniform(-2.5, 2.8)
            current_btc = round(max(30000.0, current_btc * (1 + price_change_pct / 100)), 2)
            
            score_delta = (price_change_pct * 3.5) + random.uniform(-4.0, 4.0)
            current_score = round(max(10.0, min(95.0, current_score + score_delta)), 1)
            
            ema20 = round(max(5.0, min(100.0, current_score * 1.1 + random.uniform(-5, 5))), 1)
            ema50 = round(max(5.0, min(100.0, current_score * 1.0 + random.uniform(-4, 4))), 1)
            ema200 = round(max(5.0, min(100.0, current_score * 0.85 + random.uniform(-3, 3))), 1)
            
            records.append((ts_str, tf, current_score, ema20, ema50, ema200, current_btc))
            
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR REPLACE INTO daily_breadth 
            (timestamp, timeframe, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200, btc_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
        
    logging.info(f"Seeded {len(records)} historical breadth records into SQLite.")

if __name__ == "__main__":
    print("Initializing Database...")
    init_db()
    seed_mock_history_if_empty()
    df_1d = get_historical_breadth(timeframe='1d', days=30)
    print(f"Retrieved {len(df_1d)} historical records for 1d timeframe:")
    print(df_1d.tail(5))
