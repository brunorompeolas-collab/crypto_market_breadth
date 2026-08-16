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

# CSS Profesional: Píldoras / Botones circulares con color activo
st.markdown("""
<style>
    .stApp {
        background-color: #0b0e14;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    header[data-testid="stHeader"] { background: transparent; }
    #MainMenu, footer { visibility: hidden; }

    /* Estilo de los selectores tipo Píldora / Radio Horizontal */
    div[role="radiogroup"] {
        display: flex;
        flex-direction: row;
        gap: 6px;
        background: rgba(22, 27, 34, 0.6);
        padding: 4px 6px;
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.06);
        width: fit-content;
    }
    div[role="radiogroup"] label {
        background: transparent !important;
        border: none !important;
        padding: 4px 12px !important;
        border-radius: 16px !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        color: #94a3b8 !important;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    /* Ocultar el circulito de radio nativo */
    div[role="radiogroup"] label div[data-testid="stMarkdownContainer"] {
        padding: 0px !important;
    }
    div[role="radiogroup"] label input {
        display: none !important;
    }
    div[role="radiogroup"] label span {
        display: none !important;
    }
    /* Elemento Activo en Neón/Azul */
    div[role="radiogroup"] label[data-checked="true"],
    div[role="radiogroup"] label:has(input:checked) {
        background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        box-shadow: 0 0 10px rgba(37, 99, 235, 0.4);
    }

    .metric-card {
        background: rgba(22, 27, 34, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 14px;
        text-align: center;
        backdrop-filter: blur(10px);
        margin-top: 8px;
        margin-bottom: 12px;
    }
    .metric-title {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .metric-sub {
        font-size: 0.72rem;
        color: #64748b;
    }
    .control-label {
        font-size: 0.75rem;
        color: #64748b;
        text-transform: uppercase;
        font-weight: 600;
        margin-bottom: 4px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("<h2 style='text-align: center; margin-bottom: 2px;'>⚡ CRYPTO BREADTH TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 16px;'>Terminal Cuantitativo de Amplitud y Régimen de Mercado</p>", unsafe_allow_html=True)

# Selectores en Píldoras / Botones Circulares
c_eco, c_tf, c_rng, c_ref = st.columns([1.8, 1.2, 2.0, 0.8])

with c_eco:
    st.markdown("<div class='control-label'>Ecosistema</div>", unsafe_allow_html=True)
    ecosystem = st.radio(
        "Ecosistema",
        ["Global", "Bitcoin", "Ethereum", "Solana"],
        index=0,
        horizontal=True,
        label_visibility="collapsed"
    )

with c_tf:
    st.markdown("<div class='control-label'>Velas</div>", unsafe_allow_html=True)
    timeframe = st.radio(
        "Temporalidad",
        ["1D", "1W", "1M"],
        index=0,
        horizontal=True,
        label_visibility="collapsed"
    )

with c_rng:
    st.markdown("<div class='control-label'>Rango Histórico</div>", unsafe_allow_html=True)
    history_range = st.radio(
        "Rango",
        ["1M", "3M", "6M", "1A", "4A", "Todo"],
        index=1,
        horizontal=True,
        label_visibility="collapsed"
    )

with c_ref:
    st.markdown("<div class='control-label'>Caché</div>", unsafe_allow_html=True)
    if st.button("🔄 Recargar"):
        st.cache_data.clear()

# Obtención de datos instantánea desde memoria caché
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

# Gráfico Estructurado en 2 Paneles Sincronizados
st.markdown(f"### 📈 Dinámica de Mercado: Precio BTC vs. Amplitud ({history_range})")

if not df_history.empty:
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.55, 0.45],
        subplot_titles=("Precio Bitcoin (Referencia Macro)", "Oscilador de Amplitud de Mercado (Breadth Score %)")
    )

    # Panel 1: Precio Bitcoin
    if 'btc_price' in df_history.columns and df_history['btc_price'].dropna().any():
        fig.add_trace(
            go.Scatter(
                x=df_history['timestamp'],
                y=df_history['btc_price'],
                mode='lines',
                name='Precio BTC ($)',
                line=dict(color='#F59E0B', width=2),
                fill='tozeroy',
                fillcolor='rgba(245, 158, 11, 0.04)'
            ),
            row=1, col=1
        )

    # Panel 2: Amplitud Suavizada
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['breadth_smooth'],
            mode='lines',
            name='Breadth Score',
            line=dict(color='#00F59B', width=2.5),
            fill='tozeroy',
            fillcolor='rgba(0, 245, 155, 0.06)'
        ),
        row=2, col=1
    )

    # % sobre EMA 200
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pct_above_ema200'],
            mode='lines',
            name='% > EMA 200',
            line=dict(color='#F43F5E', width=1.4, dash='dash')
        ),
        row=2, col=1
    )

    fig.add_hline(y=80, line_dash="dot", line_color="rgba(239, 68, 68, 0.4)", annotation_text="Euforia (80)", row=2, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color="rgba(34, 197, 94, 0.4)", annotation_text="Pánico (20)", row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        margin=dict(l=10, r=10, t=30, b=10),
        height=460,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)")
    )
    
    fig.update_yaxes(title_text="Precio ($)", row=1, col=1, showgrid=True, gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(title_text="Amplitud (%)", range=[0, 100], row=2, col=1, showgrid=True, gridcolor="rgba(255,255,255,0.05)")
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
