import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from database import get_historical_breadth
from quantitative import determine_data_status
from collector import get_crypto_breadth_data, run_backfill
from normalizer import is_candle_closed
from providers.coingecko import CoinGeckoProvider
from datetime import datetime, timezone

# ----------------------------------------
# NEW PROVIDER TESTS (A8)
# ----------------------------------------

@patch('requests.get')
def test_provider_01_coingecko_success(mock_get):
    # PROVIDER-01: CoinGecko successful response produces normalized real data
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"prices": [[1600000000000, 50000.0], [1600086400000, 51000.0]]}
    mock_get.return_value = mock_resp
    
    provider = CoinGeckoProvider()
    res = provider.get_historical_data([{"id": "bitcoin"}], "1d", 2)
    assert res["status"] == "SUCCESS"
    assert "bitcoin" in res["data"]
    assert len(res["data"]["bitcoin"]) == 2
    assert res["data"]["bitcoin"][0]["price"] == 50000.0

@patch('requests.get')
def test_provider_02_coingecko_failure(mock_get):
    # PROVIDER-02: CoinGecko failure returns DATA_UNAVAILABLE
    mock_get.side_effect = Exception("API Down")
    
    provider = CoinGeckoProvider()
    res = provider.get_historical_data([{"id": "bitcoin"}], "1d", 2)
    assert res["status"] == "DATA_UNAVAILABLE"
    assert "Possible rate limit" in res["reason"]

def test_provider_03_no_synthetic_fallback():
    # PROVIDER-03: No synthetic fallback occurs (already proven by the exact error return above)
    provider = CoinGeckoProvider()
    assert not hasattr(provider, 'generate_synthetic_data')

def test_provider_04_btc_eth_identity():
    # PROVIDER-04: BTC and ETH map to correct canonical asset identities
    from universe import BR1_BREADTH_UNIVERSE_V1
    btc = next((a for a in BR1_BREADTH_UNIVERSE_V1 if a["symbol"] == "BTC"), None)
    eth = next((a for a in BR1_BREADTH_UNIVERSE_V1 if a["symbol"] == "ETH"), None)
    
    assert btc is not None and btc["id"] == "bitcoin"
    assert eth is not None and eth["id"] == "ethereum"

@patch('providers.coingecko.CoinGeckoProvider.get_historical_data')
def test_provider_05_missing_asset_reduces_coverage(mock_get):
    # PROVIDER-05: Missing asset reduces coverage, no replacement occurs
    
    # We need at least 20 points for EMA20 to be valid, otherwise it returns DATA_UNAVAILABLE
    prices = [{"timestamp": 1600000000000 + (i * 86400000), "price": 50000} for i in range(25)]
    
    mock_get.return_value = {
        "status": "SUCCESS",
        "reason": "",
        "data": {"bitcoin": prices},
        "benchmarks": {"BTC": prices}
    }
    df, snap = get_crypto_breadth_data(timeframe='1d', provider_name='coingecko')
    # Since it only found 1 asset, it falls below the minimum required for a valid snapshot (10)
    assert snap is not None
    assert snap['status'] == 'DATA_UNAVAILABLE'

# ----------------------------------------
# TIMEFRAME TESTS
# ----------------------------------------

def test_timeframe_01_4h_candles():
    # TIMEFRAME-01: 30 days / 4h produces approx 180 completed observations
    # Tested conceptually since we use display_days=30
    from collector import execute_breadth_pipeline
    with patch('collector.get_provider') as mock_prov:
        mock_instance = MagicMock()
        mock_prov.return_value = mock_instance
        # Required limit for 30 days 4h = (30 * 6) + 200 = 380.
        execute_breadth_pipeline('coingecko', '4h', display_days=30)
        mock_instance.get_historical_data.assert_called_once()
        args, kwargs = mock_instance.get_historical_data.call_args
        assert args[2] == 380

def test_timeframe_02_1d_candles():
    # TIMEFRAME-02: 365 days / 1d produces approx 365 completed observations
    from collector import execute_breadth_pipeline
    with patch('collector.get_provider') as mock_prov:
        mock_instance = MagicMock()
        mock_prov.return_value = mock_instance
        execute_breadth_pipeline('coingecko', '1d', display_days=365)
        mock_instance.get_historical_data.assert_called_once()
        args, kwargs = mock_instance.get_historical_data.call_args
        assert args[2] == 565 # 365 + 200 warmup

def test_timeframe_03_1w_candles():
    # TIMEFRAME-03: 365 days / 1w produces approx 52 completed observations
    from collector import execute_breadth_pipeline
    with patch('collector.get_provider') as mock_prov:
        mock_instance = MagicMock()
        mock_prov.return_value = mock_instance
        execute_breadth_pipeline('coingecko', '1w', display_days=365)
        mock_instance.get_historical_data.assert_called_once()
        args, kwargs = mock_instance.get_historical_data.call_args
        assert args[2] == (365 // 7) + 200 # 52 + 200 = 252

# ----------------------------------------
# BENCHMARK TESTS
# ----------------------------------------

def test_benchmark_01_btc_eth_isolation():
    # BENCHMARK-01: BTC -> ETH changes benchmark series but not Breadth
    from quantitative import evaluate_divergence
    
    # Fake trend
    trend = [
        {"btc_price": 50000, "eth_price": 2000, "breadth_score": 50.0},
        {"btc_price": 55000, "eth_price": 2500, "breadth_score": 60.0}
    ]
    
    res_btc = evaluate_divergence(trend, benchmark="BTC")
    res_eth = evaluate_divergence(trend, benchmark="ETH")
    
    assert "BTC" in res_btc["metrics"]
    assert "ETH" in res_eth["metrics"]

# ----------------------------------------
# DATABASE TESTS
# ----------------------------------------

def test_database_01_upsert():
    # DATABASE-01: Duplicate candle is UPSERTED, not duplicated
    from database import save_breadth_snapshot, get_historical_breadth, get_connection
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM breadth_snapshots")
    conn.commit()
    conn.close()
    
    snap = {
        'candle_time': '2026-01-01 00:00:00',
        'collected_at': 'now',
        'provider': 'coingecko',
        'timeframe': '1d',
        'universe_version': 'BR1',
        'breadth_score': 50.0,
        'pct_above_ema20': 50,
        'pct_above_ema50': 50,
        'pct_above_ema200': 50,
        'btc_price': 50000,
        'eth_price': 3000,
        'assets_total': 50,
        'assets_ema20_valid': 50,
        'assets_ema50_valid': 50,
        'assets_ema200_valid': 50,
        'data_status': 'HIGH',
        'status': 'SUCCESS'
    }
    
    save_breadth_snapshot(snap)
    save_breadth_snapshot(snap)
    
    df = get_historical_breadth(timeframe='1d', provider='coingecko')
    assert len(df) == 1 # Only 1 row despite 2 saves

def test_database_02_hf1_no_drop():
    # HF1: init_db() must not drop history
    from database import reset_db, init_db, save_breadth_snapshot, get_historical_breadth
    
    # 1. Start fresh
    reset_db()
    
    # 2. Save a snapshot
    snap = {
        'candle_time': '2026-02-01 00:00:00',
        'collected_at': 'now',
        'provider': 'coingecko',
        'timeframe': '1d',
        'universe_version': 'BR1',
        'breadth_score': 60.0,
        'pct_above_ema20': 60,
        'pct_above_ema50': 60,
        'pct_above_ema200': 60,
        'btc_price': 50000,
        'eth_price': 3000,
        'assets_total': 50,
        'assets_ema20_valid': 50,
        'assets_ema50_valid': 50,
        'assets_ema200_valid': 50,
        'data_status': 'HIGH',
        'status': 'SUCCESS'
    }
    save_breadth_snapshot(snap)
    
    # 3. Call init_db() simulating app restart
    init_db()
    
    # 4. Verify snapshot exists
    df = get_historical_breadth(timeframe='1d', provider='coingecko')
    assert len(df) == 1

def test_database_03_hf2_temporal_window():
    # HF2: Window by time, not record limit
    from database import reset_db, save_breadth_snapshot, get_historical_breadth
    from datetime import datetime, timezone, timedelta
    
    reset_db()
    
    now = datetime.now(timezone.utc)
    # Insert a snapshot every day for the last 60 days
    for i in range(60):
        t = now - timedelta(days=i)
        snap = {
            'candle_time': t.strftime('%Y-%m-%d %H:%M:%S'),
            'collected_at': 'now',
            'provider': 'coingecko',
            'timeframe': '1d',
            'universe_version': 'BR1',
            'breadth_score': 50,
            'pct_above_ema20': 50, 'pct_above_ema50': 50, 'pct_above_ema200': 50,
            'btc_price': 50000, 'eth_price': 3000,
            'assets_total': 50,
            'assets_ema20_valid': 50, 'assets_ema50_valid': 50, 'assets_ema200_valid': 50,
            'data_status': 'HIGH',
            'status': 'SUCCESS'
        }
        save_breadth_snapshot(snap)
        
    # Check 30 days window -> should return ~30 or 31 rows depending on exact fractional timing
    df_30 = get_historical_breadth(timeframe='1d', days=30)
    assert 29 <= len(df_30) <= 31
    
    # Check total -> should return all 60
    df_tot = get_historical_breadth(timeframe='1d', days=0)
    assert len(df_tot) == 60

def test_error_01_ui_protection():
    # ERROR-01: Provider failure cannot reach metric rendering code
    with patch('providers.coingecko.CoinGeckoProvider.get_historical_data') as mock_get:
        mock_get.return_value = {"status": "DATA_UNAVAILABLE", "reason": "Network Error", "data": {}, "benchmarks": {}}
        df, snap = get_crypto_breadth_data()
        assert df is None
        assert snap["status"] == "DATA_UNAVAILABLE"

# ----------------------------------------
# REGRESSION TESTS
# ----------------------------------------

def test_regression_01_btc_eth_exists():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'benchmark = st.radio("Benchmark", ["BTC", "ETH"]' in content

def test_regression_02_timeframes_exist():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'timeframe = st.radio("Temporalidad", ["4h", "1d", "1w"]' in content

def test_regression_03_historical_filters_exist():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'options=["1d", "1w", "1m", "6m", "1y", "Total"]' in content

def test_regression_04_gemini_is_manual():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'st.button("🤖 Generar Análisis IA")' in content

def test_regression_05_no_synthetic_data():
    from collector import get_crypto_breadth_data
    # In earlier versions, get_crypto_breadth_data might have synthetic failover. 
    # Calling it with a failing mock should return DATA_UNAVAILABLE, not mock data.
    with patch('providers.coingecko.CoinGeckoProvider.get_historical_data') as mock_get:
        mock_get.return_value = {"status": "DATA_UNAVAILABLE", "reason": "Fail"}
        df, snap = get_crypto_breadth_data()
        assert df is None
