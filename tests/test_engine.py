import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from collector import get_crypto_breadth_data, calculate_emas_for_symbol, determine_data_status
from database import get_historical_breadth

@patch('collector.get_exchange')
def test_p0_1_exchange_unavailable(mock_get_exchange):
    # Test 1: All exchanges unavailable -> Returns None, None
    mock_get_exchange.side_effect = Exception("Network Error")
    df, snap = get_crypto_breadth_data(ecosystem='binance', timeframe='1d')
    assert df is None
    assert snap is None

def test_p0_3_empty_database_no_fake_data():
    # Test 2: Empty database -> no synthetic history
    # Simply querying history for an unknown timeframe should return empty DF
    df = get_historical_breadth(timeframe='invalid_tf', days=30)
    assert df.empty

@patch('collector.get_exchange')
def test_p0_6_insufficient_candles_for_ema200(mock_get_exchange):
    # Test 3: Asset has fewer than 200 candles -> EMA200 unavailable
    mock_exchange = MagicMock()
    # Mocking fetch_ohlcv to return only 150 candles
    mock_ohlcv = [[1600000000000 + i*86400000, 100, 105, 95, 100 + i, 1000] for i in range(150)]
    mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
    
    data = calculate_emas_for_symbol(mock_exchange, "BTC/USDT", "1d")
    
    assert data['ema20_valid'] is True
    assert data['ema50_valid'] is True
    assert data['ema200_valid'] is False
    assert data['above_ema200'] is False

def test_p0_13_data_quality_logic():
    # Test 18: Data Quality deterministic score
    assert determine_data_status(95) == "HIGH"
    assert determine_data_status(80) == "GOOD"
    assert determine_data_status(60) == "LIMITED"
    assert determine_data_status(40) == "LOW"

@patch('collector.calculate_emas_for_symbol')
@patch('collector.get_exchange')
def test_p0_14_breadth_formula_correctness(mock_get_exchange, mock_calc):
    # Test 17: Breadth formula 0.2 EMA20 + 0.3 EMA50 + 0.5 EMA200
    mock_exchange = MagicMock()
    mock_get_exchange.return_value = mock_exchange
    
    def fake_calc(exchange, symbol, timeframe):
        if symbol == 'BTC/USDT':
            return {
                'symbol': 'BTC/USDT', 'price': 50000, 'candle_time': '2026-08-01 00:00:00',
                'ema20_valid': True, 'ema50_valid': True, 'ema200_valid': True,
                'above_ema20': True, 'above_ema50': True, 'above_ema200': False
            }
        elif symbol == 'ETH/USDT':
            return {
                'symbol': 'ETH/USDT', 'price': 3000, 'candle_time': '2026-08-01 00:00:00',
                'ema20_valid': True, 'ema50_valid': True, 'ema200_valid': True,
                'above_ema20': False, 'above_ema50': False, 'above_ema200': True
            }
        return None
        
    mock_calc.side_effect = fake_calc
    
    df, snap = get_crypto_breadth_data()
    
    # We mocked 2 assets. 
    # above_ema20 = 1/2 (50%)
    # above_ema50 = 1/2 (50%)
    # above_ema200 = 1/2 (50%)
    # Expected score: 0.2*50 + 0.3*50 + 0.5*50 = 50.0
    assert snap is not None
    assert snap['pct_above_ema20'] == 50.0
    assert snap['pct_above_ema50'] == 50.0
    assert snap['pct_above_ema200'] == 50.0
    assert snap['breadth_score'] == 50.0
