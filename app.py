import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from collector import get_crypto_breadth_data
from database import init_db, save_breadth_snapshot, get_breadth_history
from analyzer import analyze_market_with_gemini

# Configuración de página
st.set_page_config(
    page_title="Crypto Market Breadth Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilos CSS
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
        padding: 16px;
        text-align: center;
        backdrop-filter: blur(10px);
        margin-bottom: 12px;
    }
    .metric-title {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .metric-sub {
        font-size: 0.75rem;
        color: #64748b;
    }
    .stButton>button {
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 8px 18px;
        width: 100%;
        transition: all 0.2s ease;
    }
</style>
""", unsafe_allow_html=True)

# Inicializar DB
init_db()

# Título
st.markdown("<h2 style='text-align: center; margin-bottom: 4px;'>⚡ CRYPTO BREADTH TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 20px;'>Monitor de Amplitud de Mercado & Diagnóstico Cuantitativo</p>", unsafe_allow_html=True)

# Botón de actualización
col_btn, _ = st.columns([1, 3])
with col_btn:
    refresh = st.button("🔄 Actualizar Datos de Mercado")

# Carga de datos
with st.spinner("Procesando datos multi-exchange y calculando EMAs..."):
    df_assets, breadth_score, ema20_pct, ema50_pct, ema200_pct, data_quality = get_crypto_breadth_data()
    save_breadth_snapshot(breadth_score, ema20_pct, ema50_pct, ema200_pct)
    st.caption(f"🛡️ **Control de Calidad:** {data_quality}")

# Métricas Principales
c1, c2, c3, c4 = st.columns(4)
with c1:
    color = "#00F59B" if breadth_score >= 60 else ("#FF3366" if breadth_score <= 40 else "#FACC15")
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Breadth Score</div>
        <div class="metric-value" style="color: {color};">{breadth_score:.1f} / 100</div>
        <div class="metric-sub">Salud Global</div>
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

# Gráfica Histórica
st.markdown("### 📈 Histórico de Amplitud de Mercado")
df_hist = get_breadth_history()

if not df_hist.empty:
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'],
        y=df_hist['breadth_score'],
        mode='lines+markers',
        name='Breadth Score',
        line=dict(color='#00F59B', width=2.5),
        marker=dict(size=6),
        fill='tozeroy',
        fillcolor='rgba(0, 245, 155, 0.05)'
    ))
    
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'],
        y=df_hist['pct_above_ema50'],
        mode='lines+markers',
        name='% > EMA 50',
        line=dict(color='#38BDF8', width=1.5, dash='dot'),
        marker=dict(size=4)
    ))
    
    fig.add_trace(go.Scatter(
        x=df_hist['timestamp'],
        y=df_hist['pct_above_ema200'],
        mode='lines+markers',
        name='% > EMA 200',
        line=dict(color='#F43F5E', width=1.5, dash='dash'),
        marker=dict(size=4)
    ))
    
    fig.add_hline(y=80, line_dash="dash", line_color="rgba(255,255,255,0.15)", annotation_text="Euforia (80)")
    fig.add_hline(y=20, line_dash="dash", line_color="rgba(255,255,255,0.15)", annotation_text="Pánico (20)")
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        margin=dict(l=10, r=10, t=20, b=20),
        height=320,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(showgrid=True, gridcolor="rgba(255, 255, 255, 0.05)"),
        yaxis=dict(range=[0, 100], showgrid=True, gridcolor="rgba(255, 255, 255, 0.05)")
    )
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': False})

# Diagnóstico IA Gemini con Descarga
st.markdown("### 🤖 Diagnóstico IA Cuantitativo (Gemini)")
with st.expander("Ver Análisis Táctico & Divergencias", expanded=True):
    with st.spinner("Generando informe táctico con Gemini..."):
        ai_report = analyze_market_with_gemini(breadth_score, ema20_pct, ema50_pct, ema200_pct, df_assets, data_quality)
        st.markdown(ai_report)
        
        st.download_button(
            label="📥 Descargar Informe Táctico (.txt)",
            data=ai_report,
            file_name="informe_tactico_breadth.txt",
            mime="text/plain"
        )

# Escáner de Activos
st.markdown("### 📋 Escáner de Activos del Mercado")
display_cols = ['Activo', 'Precio ($)', 'Var 24h', 'EMA 20', 'EMA 50', 'EMA 200']
if all(col in df_assets.columns for col in display_cols):
    st.dataframe(df_assets[display_cols], use_container_width=True, hide_index=True)
else:
    st.dataframe(df_assets, use_container_width=True, hide_index=True)
