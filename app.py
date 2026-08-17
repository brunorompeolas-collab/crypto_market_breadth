import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from collector import get_crypto_breadth_data, run_backfill
from database import init_db, get_historical_breadth
from analyzer import analyze_market_with_gemini
from normalizer import get_expected_last_closed_candle
from universe import BR1_BREADTH_UNIVERSE_V1

# Configuración de página
st.set_page_config(
    page_title="Crypto Market Breadth Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Inyección CSS Ultra-Limpio
st.markdown("""
<style>
    .stApp { background-color: #0b0e14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
    header[data-testid="stHeader"] { background: transparent; }
    #MainMenu, footer {visibility: hidden;}
    .metric-card {
        background: rgba(22, 27, 34, 0.7); border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px; padding: 16px; text-align: center; margin-bottom: 12px;
    }
    .metric-title { font-size: 0.8rem; text-transform: uppercase; color: #94a3b8; margin-bottom: 4px; }
    .metric-value { font-size: 1.6rem; font-weight: 700; color: #f8fafc; }
    .metric-sub { font-size: 0.75rem; color: #64748b; }
    .status-badge { font-size: 0.85rem; padding: 4px 8px; border-radius: 4px; border: 1px solid #334155; background: #1e293b; color: #cbd5e1; }
</style>
""", unsafe_allow_html=True)

init_db()

st.markdown("<h2 style='text-align: center; margin-bottom: 4px;'>⚡ CRYPTO BREADTH TERMINAL v1</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 20px;'>Monitor Cuantitativo & Integridad de Datos (CoinGecko Canonical Provider)</p>", unsafe_allow_html=True)

metrics_container = st.container()
gauge_container = st.container()

st.write("") # spacer

# Selectores principales
col_tf, col_bench, col_btn = st.columns([2, 2, 1])
with col_tf:
    timeframe = st.radio("Temporalidad", ["4h", "1d", "1w"], index=1, horizontal=True)
with col_bench:
    benchmark = st.radio("Benchmark", ["BTC", "ETH"], horizontal=True)
with col_btn:
    st.write("")
    st.write("")
    refresh = st.button("🔄 Refrescar")

with st.sidebar:
    st.markdown("### ⚙️ Mantenimiento")
    st.markdown("Backfill usando el Canonical Provider (CoinGecko).")
    bf_timeframe = st.radio("Temporalidad Backfill", ["4h", "1d", "1w"], index=1)
    
    # HF4: Days mapping based on timeframe
    if bf_timeframe == "4h":
        display_days = 30 # 30 days = 180 candles
        st.caption("30 días (aprox 180 velas 4h)")
    elif bf_timeframe == "1w":
        display_days = 365
        st.caption("1 año (aprox 52 velas semanales)")
    else:
        display_days = 365
        st.caption("1 año (aprox 365 velas diarias)")
        
    if st.button("Generar Histórico"):
        with st.spinner("Procesando histórico seguro vía CoinGecko API... (Esto puede tardar unos minutos debido a Rate Limits)"):
            success, msg = run_backfill(timeframe=bf_timeframe, display_days=display_days, provider_name='coingecko')
            if success:
                st.success(f"¡Backfill completado! {msg}")
                st.cache_data.clear()
            else:
                st.error(f"Error en backfill: {msg}")

if refresh:
    st.cache_data.clear()

@st.cache_data
def cached_get_breadth_data(tf, expected_time, provider_name='coingecko'):
    # The expected_time argument acts as a cache invalidation key.
    # When a new candle closes, expected_time changes, triggering a fresh fetch.
    return get_crypto_breadth_data(timeframe=tf, provider_name=provider_name)

expected_candle_time = get_expected_last_closed_candle(timeframe)

with st.spinner("Conectando con CoinGecko y procesando Market Breadth..."):
    df_assets, snapshot = cached_get_breadth_data(timeframe, expected_candle_time, 'coingecko')

# P0-HF3: Correct DATA_UNAVAILABLE handling
if not snapshot or snapshot.get('status') != "SUCCESS":
    reason = snapshot.get("reason", "Unknown Error") if snapshot else "Null Snapshot"
    st.error(f"🚨 **DATA UNAVAILABLE**\n\nNo se ha podido recuperar la información del proveedor. (Razón: {reason})")
    st.stop()

# Info adicional de calidad
st.markdown(f"""
<div style="display: flex; justify-content: center; gap: 15px; margin-bottom: 20px;">
    <span class="status-badge">📡 Provider: <b>{snapshot['provider'].upper()}</b></span>
    <span class="status-badge">📦 Universe: <b>{snapshot['universe_version']}</b></span>
    <span class="status-badge">✅ Coverage: <b>{snapshot['assets_total']} / {len(BR1_BREADTH_UNIVERSE_V1)}</b></span>
    <span class="status-badge">🎯 Quality: <b>{snapshot['data_status']}</b></span>
    <span class="status-badge">🕒 Last Closed Candle: <b>{snapshot['candle_time']}</b></span>
</div>
""", unsafe_allow_html=True)

breadth_score = snapshot['breadth_score']
ema20_pct = snapshot['pct_above_ema20']
ema50_pct = snapshot['pct_above_ema50']
ema200_pct = snapshot['pct_above_ema200']

# Llenar los contenedores superiores
with metrics_container:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        color = "#00F59B" if breadth_score >= 60 else ("#FF3366" if breadth_score <= 40 else "#FACC15")
        st.markdown(f'<div class="metric-card"><div class="metric-title">Breadth Score</div><div class="metric-value" style="color: {color};">{breadth_score:.1f} / 100</div><div class="metric-sub">Salud Global</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><div class="metric-title">> EMA 20 (Corto)</div><div class="metric-value">{ema20_pct:.1f}%</div><div class="metric-sub">{snapshot["assets_ema20_valid"]} activos válidos</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><div class="metric-title">> EMA 50 (Medio)</div><div class="metric-value">{ema50_pct:.1f}%</div><div class="metric-sub">{snapshot["assets_ema50_valid"]} activos válidos</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><div class="metric-title">> EMA 200 (Largo)</div><div class="metric-value">{ema200_pct:.1f}%</div><div class="metric-sub">{snapshot["assets_ema200_valid"]} activos válidos</div></div>', unsafe_allow_html=True)

with gauge_container:
    fig_gauge = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = float(breadth_score),
        domain = {'x': [0, 1], 'y': [0, 1]},
        number = {'font': {'size': 42, 'color': '#f8fafc'}, 'suffix': "/100"},
        gauge = {
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "rgba(255,255,255,0.2)"},
            'bar': {'color': "rgba(255,255,255,0.9)", 'thickness': 0.15},
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 0,
            'steps': [
                {'range': [0, 20], 'color': "#FF3366"},
                {'range': [20, 40], 'color': "#FF8A00"},
                {'range': [40, 60], 'color': "#FACC15"},
                {'range': [60, 80], 'color': "#00F59B"},
                {'range': [80, 100], 'color': "#00B87A"}
            ],
        }
    ))
    fig_gauge.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin=dict(l=10, r=10, t=10, b=10)
    )
    st.plotly_chart(fig_gauge, use_container_width=True, config={'displayModeBar': False})

st.markdown(f"### 📈 Histórico de Amplitud vs {benchmark}")

time_window = st.radio(
    "Filtro temporal:",
    options=["1d", "1w", "1m", "6m", "1y", "Total"],
    index=5,
    horizontal=True,
    label_visibility="collapsed"
)

days_map = {"1d": 1, "1w": 7, "1m": 30, "6m": 180, "1y": 365, "Total": 0}
df_hist = get_historical_breadth(timeframe=timeframe, days=days_map[time_window], provider='coingecko')

if df_hist.empty or len(df_hist) == 0:
    st.warning("No historical observations available. (Ejecuta el Backfill en el panel lateral)")
elif len(df_hist) == 1:
    st.warning("Insufficient historical data: 1 observation available. (Ejecuta el Backfill)")
else:
    if len(df_hist) < 10:
        st.info(f"Limited historical coverage: {len(df_hist)} observations.")
        
    from streamlit_lightweight_charts import renderLightweightCharts
    
    df_hist['datetime'] = pd.to_datetime(df_hist['timestamp'])
    
    def format_time(ts):
        try:
            if timeframe in ["1d", "1w"]: return ts.strftime('%Y-%m-%d')
            else: return int(ts.timestamp())
        except:
            return str(ts)
            
    df_hist['time'] = df_hist['datetime'].apply(format_time)
    df_hist = df_hist.drop_duplicates(subset=['time'], keep='last')
    
    breadth_data = df_hist[['time', 'breadth_score']].rename(columns={'breadth_score': 'value'}).to_dict('records')
    ema50_data = df_hist[['time', 'pct_above_ema50']].rename(columns={'pct_above_ema50': 'value'}).to_dict('records')
    ema200_data = df_hist[['time', 'pct_above_ema200']].rename(columns={'pct_above_ema200': 'value'}).to_dict('records')
    
    benchmark_key = 'btc_price' if benchmark == 'BTC' else 'eth_price'
    bench_data = df_hist[['time', benchmark_key]].rename(columns={benchmark_key: 'value'}).to_dict('records')
    
    chartOptions = {
        "height": 450,
        "layout": {
            "background": {"type": "solid", "color": "#0e1117"},
            "textColor": "#d1d4dc"
        },
        "grid": {
            "vertLines": {"color": "rgba(255,255,255,0.05)"},
            "horzLines": {"color": "rgba(255,255,255,0.05)"}
        },
        "rightPriceScale": {
            "scaleMargins": {"top": 0.1, "bottom": 0.1},
            "borderVisible": False,
        },
        "leftPriceScale": {
            "visible": True,
            "scaleMargins": {"top": 0.1, "bottom": 0.1},
            "borderVisible": False,
        },
        "timeScale": {
            "borderVisible": False,
            "timeVisible": True if timeframe not in ["1d", "1w"] else False
        },
        "crosshair": {
            "mode": 1
        }
    }
    
    series = [
        {
            "type": "Line",
            "options": {
                "color": "#FACC15",
                "lineWidth": 2,
                "priceScaleId": "left",
                "title": "Breadth Score"
            },
            "data": breadth_data
        },
        {
            "type": "Line",
            "options": {
                "color": "#00F59B",
                "lineWidth": 1,
                "lineStyle": 2,
                "priceScaleId": "left",
                "title": "> EMA 50"
            },
            "data": ema50_data
        },
        {
            "type": "Line",
            "options": {
                "color": "#94a3b8",
                "lineWidth": 1,
                "lineStyle": 2,
                "priceScaleId": "left",
                "title": "> EMA 200"
            },
            "data": ema200_data
        },
        {
            "type": "Line",
            "options": {
                "color": "#3b82f6",
                "lineWidth": 2,
                "priceScaleId": "right",
                "title": f"Precio {benchmark}"
            },
            "data": bench_data
        }
    ]
    
    renderLightweightCharts([{"chart": chartOptions, "series": series}], "breadth_chart")

st.write("---")

col_ai1, col_ai2 = st.columns([1, 4])
with col_ai1:
    if st.button("🤖 Generar Análisis IA"):
        st.session_state['generate_ai'] = True

if st.session_state.get('generate_ai', False):
    with st.spinner("Gemini está evaluando los datos de Market Breadth..."):
        ai_report = analyze_market_with_gemini(snapshot, df_assets, benchmark)
        st.markdown(ai_report)

st.write("---")
st.markdown("### Escáner de Activos (Universo v1)")

if not df_assets.empty:
    def format_bool_color(val):
        return f'<span style="color: {"#00F59B" if val else "#FF3366"};">{"🟢" if val else "🔴"}</span>'

    df_display = df_assets.copy()
    
    df_display['above_ema20'] = df_display['above_ema20'].apply(format_bool_color)
    df_display['above_ema50'] = df_display['above_ema50'].apply(format_bool_color)
    df_display['above_ema200'] = df_display['above_ema200'].apply(format_bool_color)
    
    df_display = df_display[['symbol', 'price', 'above_ema20', 'above_ema50', 'above_ema200']]
    df_display.columns = ['Activo', 'Precio ($)', '> EMA 20', '> EMA 50', '> EMA 200']
    
    st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)
