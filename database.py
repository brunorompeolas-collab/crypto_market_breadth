import sqlite3
import pandas as pd
from datetime import datetime

DB_NAME = "breadth_data.db"

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS breadth_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        breadth_score REAL,
        pct_above_ema20 REAL,
        pct_above_ema50 REAL,
        pct_above_ema200 REAL
    )
    """)
    conn.commit()
    conn.close()

def save_breadth_snapshot(breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO breadth_snapshots (breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200)
    VALUES (?, ?, ?, ?)
    """, (breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200))
    conn.commit()
    conn.close()

def get_breadth_history(limit=100):
    conn = get_connection()
    try:
        query = """
        SELECT timestamp, breadth_score, pct_above_ema20, pct_above_ema50, pct_above_ema200
        FROM breadth_snapshots
        ORDER BY id DESC
        LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))
        conn.close()
        if not df.empty:
            df = df.iloc[::-1].reset_index(drop=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception:
        conn.close()
        return pd.DataFrame(columns=['timestamp', 'breadth_score', 'pct_above_ema20', 'pct_above_ema50', 'pct_above_ema200'])
    seed_mock_history_if_empty()
    df_1d = get_historical_breadth(timeframe='1d', days=30)
    print(f"Retrieved {len(df_1d)} historical records for 1d timeframe:")
    print(df_1d.tail(5))
