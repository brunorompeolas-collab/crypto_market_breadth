import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from collector import get_crypto_breadth_data
from analyzer import analyze_market_with_gemini

# Configuración de página
st.set_page_config(
    page_title="Crypto Market Breadth Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilos CSS Limpios
st.markdown("""
<style>
    .stApp {
        background-color: #0b0e14;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    header[data-testid="stHeader"] { background: transparent; }
    #MainMenu, footer { visibility: hidden; }
    
    .metric-card {
        background: rgba(22, 27, 34, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 14px;
        text-align: center;
        backdrop-filter: blur(10px);
        margin-top: 6px;
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
    .stButton>button {
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 8px 16px;
        width: 100%;
        margin-top: 28px;
        transition: all 0.2s ease;
    }
</style>
""", unsafe_allow_html=True)

# Título de Cabecera
st.markdown("<h2 style='text-align: center; margin-bottom: 2px;'>⚡ CRYPTO BREADTH TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 15px;'>Monitor Cuantitativo de Amplitud de Mercado y Divergencias</p>", unsafe_allow_html=True)

# Barra de Control y Selectores
col1, col2, col3, col4 = st.columns([2.2, 1.4, 1.4, 1.0])
with col1:
    ecosystem = st.selectbox(
        "Cesta / Ecosistema:",
        [
            "Mercado Global (Top)",
            "Ecosistema Bitcoin / PoW",
            "Ecosistema Ethereum / L2 / DeFi",
            "Ecosistema Solana / L1s Alternativas"
        ],
        index=0
    )
with col2:
    timeframe = st.selectbox(
        "Velas / Frecuencia:",
        ["Diario (1D)", "Semanal (1W)", "Mensual (1M)"],
        index=0
    )
with col3:
    history_range = st.selectbox(
        "Rango Histórico:",
        ["1 Mes", "3 Meses", "6 Meses", "1 Año", "4 Años", "10 Años / Histórico"],
        index=1
    )
with col4:
    refresh = st.button("🔄 Actualizar")

# Carga de Datos
with st.spinner(f"Analizando amplitud ({timeframe} | {history_range})..."):
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
        <div class="metric-sub">{ecosystem.split('/')[0]}</div>
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

# Gráfica Histórica con Doble Eje (Amplitud + BTC)
st.markdown(f"### 📈 Histórico de Amplitud & Precio BTC ({history_range})")

if not df_history.empty:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Curva de Breadth Score (Eje Primario)
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['breadth_score'],
            mode='lines',
            name='Breadth Score (0-100)',
            line=dict(color='#00F59B', width=2.5),
            fill='tozeroy',
            fillcolor='rgba(0, 245, 155, 0.06)'
        ),
        secondary_y=False
    )
    
    # % sobre EMA 50
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
    
    # % sobre EMA 200
    fig.add_trace(
        go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pct_above_ema200'],
            mode='lines',
            name='% > EMA 200',
            line=dict(color='#F43F5E', width=1.5, dash='dash')
        ),
        secondary_y=False
    )
    
    # Superposición de Precio BTC (Eje Secundario - Y2)
    if 'btc_price' in df_history.columns and df_history['btc_price'].dropna().any():
        fig.add_trace(
            go.Scatter(
                x=df_history['timestamp'],
                y=df_history['btc_price'],
                mode='lines',
                name='Precio BTC ($)',
                line=dict(color='#F59E0B', width=1.8)
            ),
            secondary_y=True
        )

    # Zonas de referencia de Amplitud
    fig.add_hline(y=80, line_dash="dash", line_color="rgba(255,255,255,0.18)", annotation_text="Euforia (80)", secondary_y=False)
    fig.add_hline(y=20, line_dash="dash", line_color="rgba(255,255,255,0.18)", annotation_text="Pánico (20)", secondary_y=False)
    
    # Estilizado oscuro profesional
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        margin=dict(l=10, r=10, t=25, b=20),
        height=360,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(showgrid=True, gridcolor="rgba(255, 255, 255, 0.05)"),
        yaxis=dict(title="Amplitud (%)", range=[0, 100], showgrid=True, gridcolor="rgba(255, 255, 255, 0.05)"),
        yaxis2=dict(title="Precio BTC ($)", showgrid=False, overlaying='y', side='right')
    )
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': False})
else:
    st.info("Cargando serie temporal histórica...")

# Diagnóstico IA Gemini
st.markdown("### 🤖 Diagnóstico IA Cuantitativo (Gemini)")
with st.expander("Ver Análisis Táctico & Divergencias", expanded=True):
    with st.spinner("Generando informe táctico con Gemini..."):
        ai_report = analyze_market_with_gemini(breadth_score, ema20_pct, ema50_pct, ema200_pct, df_assets, data_quality)
        st.markdown(ai_report)
        
        st.download_button(
            label="📥 Descargar Informe Táctico (.txt)",
            data=ai_report,
            file_name=f"informe_{ecosystem.replace(' ', '_')}_{timeframe}.txt",
            mime="text/plain"
        )

# Escáner de Activos
st.markdown("### 📋 Escáner de Activos del Ecosistema")
display_cols = ['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200']
if all(col in df_assets.columns for col in display_cols):
    st.dataframe(df_assets[display_cols], use_container_width=True, hide_index=True)
else:
    st.dataframe(df_assets, use_container_width=True, hide_index=True)
