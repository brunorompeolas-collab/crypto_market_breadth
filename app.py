import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from collector import get_crypto_breadth_data
from database import init_db, save_breadth_snapshot, get_historical_breadth
from analyzer import analyze_market_with_gemini

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
</style>
""", unsafe_allow_html=True)

init_db()

st.markdown("<h2 style='text-align: center; margin-bottom: 4px;'>⚡ CRYPTO BREADTH TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 20px;'>Monitor de Amplitud de Mercado & Diagnóstico Cuantitativo</p>", unsafe_allow_html=True)

metrics_container = st.container()
gauge_container = st.container()

st.write("") # spacer

# Selectores justo encima del gráfico
col_eco, col_tf, col_btn = st.columns([2, 2, 1])
with col_eco:
    ecosystem = st.radio("Ecosistema", ["Auto", "Binance", "KuCoin", "OKX", "Kraken"], horizontal=True)
with col_tf:
    timeframe = st.radio("Temporalidad", ["1d", "4h", "1w"], horizontal=True)
with col_btn:
    st.write("") # spacer
    st.write("")
    refresh = st.button("🔄 Refrescar Datos")

if refresh:
    st.cache_data.clear()

with st.spinner("Conectando y procesando EMAs..."):
    df_assets, breadth_score, ema20_pct, ema50_pct, ema200_pct = get_crypto_breadth_data(ecosystem=ecosystem, timeframe=timeframe)
    btc_price = 0.0
    if not df_assets.empty:
        btc_row = df_assets[df_assets['symbol'].str.contains('BTC/USDT', na=False)]
        if not btc_row.empty:
            btc_price = float(btc_row.iloc[0]['price'])
    save_breadth_snapshot({
        'total_assets_analyzed': len(df_assets),
        'pct_above_ema20': ema20_pct,
        'pct_above_ema50': ema50_pct,
        'pct_above_ema200': ema200_pct,
        'market_breadth_score': breadth_score,
        'btc_price': btc_price,
        'timeframe': timeframe
    }, timeframe=timeframe)

# Llenar los contenedores superiores
with metrics_container:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        color = "#00F59B" if breadth_score >= 60 else ("#FF3366" if breadth_score <= 40 else "#FACC15")
        st.markdown(f'<div class="metric-card"><div class="metric-title">Breadth Score</div><div class="metric-value" style="color: {color};">{breadth_score:.1f} / 100</div><div class="metric-sub">Salud Global</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><div class="metric-title">> EMA 20 (Corto)</div><div class="metric-value">{ema20_pct:.1f}%</div><div class="metric-sub">Momento Inmediato</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><div class="metric-title">> EMA 50 (Medio)</div><div class="metric-value">{ema50_pct:.1f}%</div><div class="metric-sub">Estructura Tendencial</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><div class="metric-title">> EMA 200 (Largo)</div><div class="metric-value">{ema200_pct:.1f}%</div><div class="metric-sub">Régimen Macro</div></div>', unsafe_allow_html=True)

with gauge_container:
    st.markdown("### 🌡️ Termómetro de Régimen")
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
                {'range': [0, 20], 'color': "#FF3366"},   # Pánico
                {'range': [20, 40], 'color': "#FF8A00"},  # Miedo
                {'range': [40, 60], 'color': "#FACC15"},  # Neutral
                {'range': [60, 80], 'color': "#00F59B"},  # Expansión
                {'range': [80, 100], 'color': "#00B87A"}  # Euforia
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

st.markdown("### 📈 Histórico de Amplitud vs Precio BTC")

time_window = st.radio(
    "Filtro temporal:",
    options=["1d", "1w", "1m", "6m", "1y", "Total"],
    index=5,
    horizontal=True,
    label_visibility="collapsed"
)

df_hist = get_historical_breadth(timeframe=timeframe)

if not df_hist.empty:
    import pandas as pd
    from streamlit_lightweight_charts import renderLightweightCharts
    
    # Asegurar el formato datetime correcto y ordenar cronológicamente de verdad
    df_hist['datetime'] = pd.to_datetime(df_hist['timestamp'])
    df_hist = df_hist.sort_values('datetime', ascending=True)
    
    # Eliminar posibles valores nulos que rompan el gráfico de TradingView
    df_hist = df_hist.dropna(subset=['breadth_score', 'pct_above_ema50', 'pct_above_ema200', 'btc_price'])
    
    # Filter by time_window
    if time_window != "Total":
        last_date = df_hist['datetime'].max()
        if time_window == "1d":
            start_date = last_date - pd.Timedelta(days=1)
        elif time_window == "1w":
            start_date = last_date - pd.Timedelta(weeks=1)
        elif time_window == "1m":
            start_date = last_date - pd.Timedelta(days=30)
        elif time_window == "6m":
            start_date = last_date - pd.Timedelta(days=180)
        elif time_window == "1y":
            start_date = last_date - pd.Timedelta(days=365)
        
        df_hist = df_hist[df_hist['datetime'] >= start_date]
    
    def format_time(ts):
        try:
            if timeframe in ["1d", "1w"]:
                return ts.strftime('%Y-%m-%d')
            else:
                return int(ts.timestamp())
        except:
            return str(ts)
            
    df_hist['time'] = df_hist['datetime'].apply(format_time)
    
    breadth_data = df_hist[['time', 'breadth_score']].rename(columns={'breadth_score': 'value'}).to_dict('records')
    ema50_data = df_hist[['time', 'pct_above_ema50']].rename(columns={'pct_above_ema50': 'value'}).to_dict('records')
    ema200_data = df_hist[['time', 'pct_above_ema200']].rename(columns={'pct_above_ema200': 'value'}).to_dict('records')
    btc_data = df_hist[['time', 'btc_price']].rename(columns={'btc_price': 'value'}).to_dict('records')
    
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
            "data": btc_data,
            "options": {
                "color": "#F59E0B",
                "lineWidth": 2,
                "priceScaleId": "right",
                "title": "BTC Price"
            }
        },
        {
            "type": "Area",
            "data": breadth_data,
            "options": {
                "topColor": "rgba(0, 245, 155, 0.2)",
                "bottomColor": "rgba(0, 245, 155, 0.0)",
                "lineColor": "#00F59B",
                "lineWidth": 2,
                "priceScaleId": "left",
                "title": "Breadth Score"
            }
        },
        {
            "type": "Line",
            "data": ema50_data,
            "options": {
                "color": "#38BDF8",
                "lineWidth": 1,
                "lineStyle": 2,
                "priceScaleId": "left",
                "title": "> EMA 50"
            }
        },
        {
            "type": "Line",
            "data": ema200_data,
            "options": {
                "color": "#F43F5E",
                "lineWidth": 1,
                "lineStyle": 2,
                "priceScaleId": "left",
                "title": "> EMA 200"
            }
        }
    ]
    
    renderLightweightCharts([{"chart": chartOptions, "series": series}], key="lw_chart")
else:
    st.info("Registrando primeras muestras para construir el histórico temporal...")

st.markdown("### 🤖 Diagnóstico IA Cuantitativo (Gemini)")
with st.expander("Ver Análisis Táctico & Divergencias", expanded=True):
    with st.spinner("Generando informe con Gemini..."):
        ai_report = analyze_market_with_gemini(breadth_score, ema20_pct, ema50_pct, ema200_pct, df_assets)
        st.markdown(ai_report)
        st.download_button(
            label="Descargar Análisis (TXT)",
            data=ai_report,
            file_name="diagnostico_gemini.txt",
            mime="text/plain"
        )

st.markdown("### 📋 Escáner de Activos")
if not df_assets.empty:
    def style_dataframe(df):
        def color_change(val):
            try:
                numeric_val = float(str(val).replace('%', '').strip())
                if numeric_val > 0: return 'color: #00F59B'
                elif numeric_val < 0: return 'color: #FF3366'
                return 'color: #FACC15'
            except:
                return ''
                
        styled = df.style.map(color_change, subset=['change_24h'])
        return styled
        
    df_to_show = df_assets[['symbol', 'price', 'change_24h', 'above_ema20', 'above_ema50', 'above_ema200']].copy()
    
    # Reemplazar booleanos por círculos verde/rojo
    for col in ['above_ema20', 'above_ema50', 'above_ema200']:
        df_to_show[col] = df_to_show[col].apply(
            lambda x: '🟢' if str(x).lower().strip() in ['true', 'yes', '1', 'sí'] or x is True else ('🔴' if str(x).lower().strip() in ['false', 'no', '0'] or x is False else x)
        )
        
    st.dataframe(style_dataframe(df_to_show), use_container_width=True, hide_index=True)
else:
    st.warning("No se obtuvieron datos de activos en esta extracción.")