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
df_hist = get_historical_breadth(timeframe=timeframe)

if not df_hist.empty:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'], y=df_hist['breadth_score'], mode='lines', name='Breadth Score',
        line=dict(color='#00F59B', width=2.5), fill='tozeroy', fillcolor='rgba(0, 245, 155, 0.05)'
    ), secondary_y=False)
    
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'], y=df_hist['pct_above_ema50'], mode='lines', name='% > EMA 50',
        line=dict(color='#38BDF8', width=1.5, dash='dot')
    ), secondary_y=False)
    
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'], y=df_hist['pct_above_ema200'], mode='lines', name='% > EMA 200',
        line=dict(color='#F43F5E', width=1.5, dash='dash')
    ), secondary_y=False)
    
    # Eje secundario para BTC
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'], y=df_hist['btc_price'], mode='lines', name='BTC Price',
        line=dict(color='#F59E0B', width=2)
    ), secondary_y=True)
    
    fig.add_hline(y=80, line_dash="dash", line_color="rgba(255,255,255,0.15)", secondary_y=False)
    fig.add_hline(y=20, line_dash="dash", line_color="rgba(255,255,255,0.15)", secondary_y=False)
    
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        margin=dict(l=10, r=10, t=20, b=20), height=400, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_yaxes(title_text="Amplitud (%)", range=[0, 100], showgrid=True, gridcolor="rgba(255,255,255,0.05)", secondary_y=False)
    fig.update_yaxes(title_text="BTC Price (USDT)", showgrid=False, secondary_y=True)
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Registrando primeras muestras para construir el histórico temporal...")

st.markdown("### 🤖 Diagnóstico IA Cuantitativo (Gemini)")
with st.expander("Ver Análisis Táctico & Divergencias", expanded=True):
    with st.spinner("Generando informe con Gemini..."):
        ai_report = analyze_market_with_gemini(breadth_score, ema20_pct, ema50_pct, ema200_pct, df_assets)
        st.markdown(ai_report)

st.markdown("### 📋 Escáner de Activos")
if not df_assets.empty:
    st.dataframe(df_assets[['symbol', 'price', 'change_24h', 'above_ema20', 'above_ema50', 'above_ema200']], use_container_width=True, hide_index=True)
else:
    st.warning("No se obtuvieron datos de activos en esta extracción.")