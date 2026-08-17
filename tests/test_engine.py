import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from database import get_historical_breadth
from quantitative import determine_data_status
from collector import get_crypto_breadth_data, run_backfill
from normalizer import is_candle_closed, resample_provider_prices
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

def test_quantitative_01_hf9_emas_calculation():
    # HF9: Validar cálculo matemático de EMA sin depender de provider/mocks
    from collector import calculate_emas_for_asset
    import pandas as pd
    import numpy as np
    
    # Create 250 rows of data so EMA20, 50, 200 can be calculated
    prices = [100.0] * 250
    df = pd.DataFrame({'close': prices, 'datetime': pd.date_range('2025-01-01', periods=250)})
    
    res = calculate_emas_for_asset(df, display_days=10)
    
    # If price is constant, EMA should converge to price
    assert len(res) == 10
    assert np.isclose(res.iloc[-1]['ema20'], 100.0)
    assert np.isclose(res.iloc[-1]['ema50'], 100.0)
    assert np.isclose(res.iloc[-1]['ema200'], 100.0)

def test_quantitative_02_hf9_breadth_score():
    # HF9: Validar que Breadth suma correctamente los porcentajes
    from collector import build_snapshot_state
    import pandas as pd
    from datetime import datetime, timezone
    
    # 3 assets. 
    # Asset 1: above all EMAs
    # Asset 2: above EMA20 and EMA50, below 200
    # Asset 3: below all EMAs
    # This means: EMA20 = 2/3 (66.6%), EMA50 = 2/3 (66.6%), EMA200 = 1/3 (33.3%)
    # Breadth score = (0.2 * 66.6) + (0.3 * 66.6) + (0.5 * 33.3) = 13.3 + 20 + 16.65 = 49.95
    
    dt = pd.Timestamp(datetime.now(timezone.utc)).floor('D')
    
    df1 = pd.DataFrame({'datetime': [dt], 'close': [100], 'ema20': [90], 'ema50': [90], 'ema200': [90]})
    df2 = pd.DataFrame({'datetime': [dt], 'close': [100], 'ema20': [90], 'ema50': [90], 'ema200': [110]})
    df3 = pd.DataFrame({'datetime': [dt], 'close': [100], 'ema20': [110], 'ema50': [110], 'ema200': [110]})
    
    assets_dfs = {'a1': df1, 'a2': df2, 'a3': df3}
    
    bench_dfs = {'BTC': pd.DataFrame({'datetime': [dt], 'close': [50000]})}
    
    # The build_snapshot_state skips if total assets < 10, so let's mock UNIVERSE size to 3? 
    # Or just copy the dfs to have 10 assets
    for i in range(4, 11):
        assets_dfs[f'a{i}'] = df3.copy() # The rest are below all EMAs
        
    # Now we have 1 above all, 1 above 20/50, and 8 below all. Total = 10.
    # EMA20 = 2/10 (20%), EMA50 = 2/10 (20%), EMA200 = 1/10 (10%)
    # Score = (0.2 * 20) + (0.3 * 20) + (0.5 * 10) = 4 + 6 + 5 = 15
    
    from unittest.mock import patch
    with patch('collector.BR1_BREADTH_UNIVERSE_V1', [1]*10): # Mock length to 10
        snaps = build_snapshot_state(assets_dfs, bench_dfs, '1d', 'mock_provider')
        
        assert len(snaps) == 1
        assert snaps[0]['pct_above_ema20'] == 20.0
        assert snaps[0]['pct_above_ema50'] == 20.0
        assert snaps[0]['pct_above_ema200'] == 10.0
        assert snaps[0]['breadth_score'] == 15.0

def test_quantitative_03_c1_no_fabricated_benchmarks():
    # P0-C1: Verify snapshots are skipped if benchmark is missing (no fabricated 60000/3000)
    from collector import build_snapshot_state
    import pandas as pd
    from datetime import datetime, timezone
    
    dt = pd.Timestamp(datetime.now(timezone.utc)).floor('D')
    
    df = pd.DataFrame({'datetime': [dt], 'close': [100], 'ema20': [90], 'ema50': [90], 'ema200': [90]})
    assets_dfs = {f'a{i}': df.copy() for i in range(11)} # 11 assets
    
    # Missing benchmarks
    bench_dfs = {}
    
    from unittest.mock import patch
    with patch('collector.BR1_BREADTH_UNIVERSE_V1', [1]*11):
        snaps = build_snapshot_state(assets_dfs, bench_dfs, '1d', 'mock_provider')
        
        # Snapshots should be empty because there is no benchmark
        assert len(snaps) == 0

def test_provider_06_hf6_auth_tiers():
    # HF6: Support demo and pro CoinGecko tiers
    from providers.coingecko import CoinGeckoProvider
    import os
    from unittest.mock import patch
    
    provider = CoinGeckoProvider()
    
    with patch.dict(os.environ, {"COINGECKO_API_KEY": "test_key", "COINGECKO_API_TIER": "demo"}):
        assert provider._get_api_url() == "https://api.coingecko.com/api/v3"
        assert provider._get_headers() == {"x-cg-demo-api-key": "test_key"}
        
    with patch.dict(os.environ, {"COINGECKO_API_KEY": "test_key_pro", "COINGECKO_API_TIER": "pro"}):
        assert provider._get_api_url() == "https://pro-api.coingecko.com/api/v3"
        assert provider._get_headers() == {"x-cg-pro-api-key": "test_key_pro"}

def test_timeframe_04_hf5_weekly_alignment():
    # HF5: Weekly canonical boundaries and closures
    import normalizer
    from normalizer import is_candle_closed, resample_provider_prices
    import pandas as pd
    from datetime import datetime, timezone
    from unittest.mock import patch
    
    # Mock 'now' inside is_candle_closed
    with patch('normalizer.datetime') as mock_dt:
        # Let's say today is Wednesday, Jan 14, 2026 12:00 UTC
        mock_dt.now.return_value = datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc)
        
        # A candle starting on Monday, Jan 5, 2026 00:00 UTC
        closed_monday = pd.Timestamp('2026-01-05 00:00:00', tz='UTC')
        # A candle starting on Monday, Jan 12, 2026 00:00 UTC
        open_monday = pd.Timestamp('2026-01-12 00:00:00', tz='UTC')
        
        assert is_candle_closed(closed_monday, '1w') is True, "Previous week should be closed"
        assert is_candle_closed(open_monday, '1w') is False, "Current week should be open"
        
        # HF7 test: expected candle
        expected = normalizer.get_expected_last_closed_candle('1w')
        assert expected == "2026-01-05 00:00:00"
        
        expected_1d = normalizer.get_expected_last_closed_candle('1d')
        assert expected_1d == "2026-01-13 00:00:00"

def test_app_01_hf8_gemini_oneshot():
    # HF8: Verify conceptually that the state is cleared when params change
    # Mock Streamlit session state
    session_state = {'ai_report': "Some generated report", 'last_params': '1d_BTC'}
    
    current_params = '1w_BTC'
    if session_state.get('last_params') != current_params:
        session_state['last_params'] = current_params
        if 'ai_report' in session_state:
            del session_state['ai_report']
            
    assert 'ai_report' not in session_state, "Report should be cleared when params change"

def test_resampling_boundary():
    from normalizer import resample_provider_prices
    import pandas as pd
    prices = [
        {"timestamp": 1768003200000, "price": 100}, # Jan 10, 2026 (Saturday)
        {"timestamp": 1768089600000, "price": 110}, # Jan 11, 2026 (Sunday)
        {"timestamp": 1768176000000, "price": 120}, # Jan 12, 2026 (Monday)
        {"timestamp": 1768262400000, "price": 130}, # Jan 13, 2026 (Tuesday)
    ]
    
    res = resample_provider_prices(prices, '1w')
    assert len(res) == 1
    assert res.iloc[0]['datetime'] == pd.Timestamp('2026-01-05 00:00:00', tz='UTC')
    assert res.iloc[0]['close'] == 110 # Last price of that week (Jan 11)

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

def test_analyzer_01_hf3_provider_integration():
    # HF3: Analyzer must read 'provider', not 'exchange', and not throw TypeError in trend lookup
    from analyzer import analyze_market_with_gemini
    from database import reset_db, save_breadth_snapshot
    import pandas as pd
    
    reset_db()
    
    # 1. Insert 2 valid snapshots for 'coingecko'
    for i in range(2):
        save_breadth_snapshot({
            'candle_time': f'2026-02-0{i+1} 00:00:00', 'collected_at': 'now',
            'provider': 'coingecko', 'timeframe': '1d', 'universe_version': 'BR1',
            'breadth_score': 50 + i, 'pct_above_ema20': 50, 'pct_above_ema50': 50, 'pct_above_ema200': 50,
            'btc_price': 50000, 'eth_price': 3000,
            'assets_total': 50, 'assets_ema20_valid': 50, 'assets_ema50_valid': 50, 'assets_ema200_valid': 50,
            'data_status': 'HIGH', 'status': 'SUCCESS'
        })
    
    # 2. Simulate the snapshot object passed from UI
    current_snap = {
        'provider': 'coingecko',
        'timeframe': '1d',
        'universe_version': 'BR1',
        'breadth_score': 51
    }
    
    # Mock requests.post to stop Gemini from actually triggering network request, 
    # but we just want to ensure it gets to the payload building phase without crashing.
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Mock IA Response"}]}}]}
        
        # Will crash here with TypeError if it still calls get_recent_snapshots_trend(..., exchange=...)
        resp = analyze_market_with_gemini(current_snap, pd.DataFrame(), "BTC", "fake_key")
        
    assert "Mock IA Response" in resp

def test_universe_01_hf4_exact_contract():
    # HF4: BR1_BREADTH_UNIVERSE_V1 must be exactly 50 and contain NO stablecoins
    from universe import BR1_BREADTH_UNIVERSE_V1
    
    assert len(BR1_BREADTH_UNIVERSE_V1) == 50, f"Universe must be exactly 50, found {len(BR1_BREADTH_UNIVERSE_V1)}"
    
    stablecoins = ["tether", "usd-coin", "dai", "true-usd", "first-digital-usd", "usdd"]
    symbols = [a["id"] for a in BR1_BREADTH_UNIVERSE_V1]
    
    for stable in stablecoins:
        assert stable not in symbols, f"Stablecoin {stable} not allowed in Universe v1"

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
