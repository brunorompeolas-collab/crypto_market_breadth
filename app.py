import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from collector import get_crypto_breadth_data
from analyzer import analyze_market_with_gemini

st.set_page_config(
    page_title="Crypto Market Breadth Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilos CSS Profesionales estilo TradingView Terminal
st.markdown("""
<style>
    .stApp {
        background-color: #0b0e14;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    header[data-testid="stHeader"] { background: transparent; }
    #MainMenu, footer { visibility: hidden; }

    /* Estilo de Píldoras Segmentadas */
    div[role="radiogroup"] {
        display: inline-flex !important;
        flex-direction: row !important;
        align-items: center !important;
        background: #161b22 !important;
        padding: 3px !important;
        border-radius: 8px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        gap: 2px !important;
    }
    div[role="radiogroup"] > label {
        margin: 0 !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        background: transparent !important;
        color: #94a3b8 !important;
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        cursor: pointer !important;
        transition: all 0.15s ease-in-out !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    /* Ocultar el círculo nativo de radio */
    div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }
    div[role="radiogroup"] > label:has(input:checked) {
        background: #2563eb !important;
        color: #ffffff !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4) !important;
    }

    .metric-card {
        background: rgba(22, 27, 34, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 14px;
        text-align: center;
        backdrop-filter: blur(10px);
        margin-bottom: 14px;
    }
    .metric-title {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.55rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .metric-sub {
        font-size: 0.72rem;
        color: #64748b;
    }
</style>
""", unsafe_allow_html=True)

# Cabecera
st.markdown("<h2 style='text-align: center; margin-bottom: 2px;'>⚡ CRYPTO BREADTH TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 12px;'>Monitor Cuantitativo de Amplitud & Divergencias de Mercado</p>", unsafe_allow_html=True)

# Selector de Ecosistema Superior
col_eco, col_empty, col_btn = st.columns([3, 3, 1])
with col_eco:
    ecosystem = st.radio(
        "Ecosistema",
        ["Global", "Bitcoin", "Ethereum", "Solana"],
        index=0,
        horizontal=True,
        label_visibility="collapsed"
    )
with col_btn:
    if st.button("🔄 Refrescar"):
        st.cache_data.clear()

# Barra Integrada de Controles del Gráfico
st.markdown("---")
g_col1, g_col2, g_col3 = st.columns([2.5, 1.5, 2.5])
with g_col1:
    st.markdown("<span style='font-size: 0.85rem; font-weight: 700; color: #f8fafc;'>📈 Amplitud de Mercado & Precio Superpuesto</span>", unsafe_allow_html=True)
with g_col2:
    timeframe = st.radio(
        "Velas",
        ["1D", "1W", "1M"],
        index=0,
        horizontal=True,
        label_visibility="collapsed"
    )
with g_col3:
    history_range = st.radio(
        "Rango",
        ["1M", "3M", "6M", "1A", "4A", "Todo"],
        index=1,
        horizontal=True,
        label_visibility="collapsed"
    )

# Carga de datos con caché
df_assets, breadth_score, ema20_pct, ema50_pct, ema200_pct, df_history, data_quality = get_crypto_breadth_data(
    ecosystem, timeframe, history_range
)
st.caption(f"🛡️ **Control de Calidad:** {data_quality}")

# Tarjetas de Métricas en Fila
c1, c2, c3, c4 = st.columns(4)
with c1:
    color = "#00F59B" if breadth_score >= 60 else ("#FF3366" if breadth_score <= 40 else "#FACC15")
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Breadth Score</div>
        <div class="metric-value" style="color: {color};">{breadth_score:.1f} / 100</div>
        <div class="metric-sub">{ecosystem}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">> EMA 20 (Corto Plazo)</div>
        <div class="metric-value">{ema20_pct:.1f}%</div>
        <div class="metric-sub">Momento Inmediato</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">> EMA 50 (Medio Plazo)</div>
        <div class="metric-value">{ema50_pct:.1f}%</div>
        <div class="metric-sub">Estructura Tendencial</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">> EMA 200 (Largo Plazo)</div>
        <div class="metric-value">{ema200_pct:.1f}%</div>
        <div class="metric-sub">Régimen Macro</div>
    </div>
    """, unsafe_allow_html=True)

# Gráfico Unificado con Doble Eje Y (Amplitud en Y1, BTC en Y2)
if not df_history.empty:
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 1. Breadth Score Principal (Y1)
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['breadth_smooth'],
            mode='lines',
            name='Breadth Score',
            line=dict(color='#00F59B', width=2.5),
            fill='tozeroy',
            fillcolor='rgba(0, 245, 155, 0.05)'
        ),
        secondary_y=False
    )

    # 2. % > EMA 20 (Y1)
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pct_above_ema20'],
            mode='lines',
            name='% > EMA 20',
            line=dict(color='#A855F7', width=1.4, dash='dot')
        ),
        secondary_y=False
    )

    # 3. % > EMA 50 (Y1)
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pct_above_ema50'],
            mode='lines',
            name='% > EMA 50',
            line=dict(color='#38BDF8', width=1.5, dash='dot')
        ),
        secondary_y=False
    )

    # 4. % > EMA 200 (Y1)
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pct_above_ema200'],
            mode='lines',
            name='% > EMA 200',
            line=dict(color='#F43F5E', width=1.6, dash='dash')
        ),
        secondary_y=False
    )

    # 5. Precio BTC Referencia (Y2 - Eje Derecho)
    if 'btc_price' in df_history.columns and df_history['btc_price'].dropna().any():
        fig.add_trace(
            go.Scatter(
                x=df_history['timestamp'],
                y=df_history['btc_price'],
                mode='lines',
                name='Precio BTC ($)',
                line=dict(color='#F59E0B', width=2.0)
            ),
            secondary_y=True
        )

    # Líneas de referencia de Pánico y Euforia
    fig.add_hline(y=80, line_dash="dash", line_color="rgba(239, 68, 68, 0.35)", annotation_text="Euforia (80)", secondary_y=False)
    fig.add_hline(y=20, line_dash="dash", line_color="rgba(34, 197, 94, 0.35)", annotation_text="Pánico (20)", secondary_y=False)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        margin=dict(l=10, r=10, t=20, b=10),
        height=450,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)")
    )
    
    fig.update_yaxes(title_text="Amplitud (%)", range=[0, 100], secondary_y=False, showgrid=True, gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(title_text="Precio BTC ($)", secondary_y=True, showgrid=False)
    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")

    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': False})
else:
    st.info("Cargando histórico...")

# Informe Gemini IA
st.markdown("### 🤖 Diagnóstico IA Cuantitativo (Gemini)")
with st.expander("Ver Análisis Táctico & Divergencias", expanded=True):
    with st.spinner("Generando informe táctico..."):
        ai_report = analyze_market_with_gemini(breadth_score, ema20_pct, ema50_pct, ema200_pct, df_assets, data_quality)
        st.markdown(ai_report)
        
        st.download_button(
            label="📥 Descargar Informe Táctico (.txt)",
            data=ai_report,
            file_name=f"informe_{ecosystem}_{timeframe}.txt",
            mime="text/plain"
        )

# Escáner de Activos
st.markdown("### 📋 Escáner de Activos del Ecosistema")
display_cols = ['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200']
if all(col in df_assets.columns for col in display_cols):
    st.dataframe(df_assets[display_cols], use_container_width=True, hide_index=True)
else:
    st.dataframe(df_assets, use_container_width=True, hide_index=True)
