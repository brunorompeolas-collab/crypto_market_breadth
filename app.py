import sys
sys.dont_write_bytecode = True

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import os

from collector import fetch_market_breadth_data
from analyzer import analyze_market_breadth
from database import get_historical_breadth
from bot_alerts import send_breadth_alert, test_telegram_connection

# Clear Streamlit cache to purge old responses from memory if requested
st.cache_data.clear()

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Crypto Market Intelligence Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Stitch Design System CSS (#0b0e14 Dark Terminal Theme + Mobile Responsive Queries) ---
st.markdown("""
    <head>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Geist:wght@600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700;800&display=swap" rel="stylesheet">
    </head>
    <style>
    .stApp {
        background-color: #0b0e14 !important;
        color: #e1e2eb !important;
        font-family: 'Inter', sans-serif;
    }
    
    h1, h2, h3, .headline {
        font-family: 'Geist', sans-serif !important;
        letter-spacing: -0.02em;
    }
    
    .data-mono, .metric-value, .stDataFrame, code {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    /* Header Container */
    .main-header {
        background: linear-gradient(180deg, #161b22 0%, #10131a 100%);
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 20px 24px;
        margin-bottom: 20px;
    }
    
    .main-title {
        font-family: 'Geist', sans-serif;
        font-size: 2.0rem;
        font-weight: 800;
        color: #e0fdff;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .title-accent {
        color: #00f2fe;
    }
    
    .subtitle {
        color: #849495;
        font-family: 'Inter', sans-serif;
        font-size: 0.88rem;
        margin-top: 4px;
    }
    
    /* Metric Cards */
    .metric-card {
        background-color: #10131a;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 16px;
        text-align: left;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
        transition: border-color 0.15s ease-in-out;
        margin-bottom: 12px;
    }
    
    .metric-card:hover {
        border-color: #00f2fe;
    }
    
    .metric-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #849495;
        margin-bottom: 6px;
        font-weight: 600;
    }
    
    .metric-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 2.1rem;
        font-weight: 700;
        color: #ffffff;
        line-height: 1.2;
    }
    
    .metric-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 2px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.70rem;
        font-weight: 600;
        margin-top: 8px;
        text-transform: uppercase;
    }
    
    /* Stitch Status Badge Tints */
    .badge-oversold { background-color: rgba(255, 77, 77, 0.12); color: #ff4d4d; border: 1px solid rgba(255, 77, 77, 0.4); }
    .badge-weak { background-color: rgba(255, 170, 0, 0.12); color: #ffaa00; border: 1px solid rgba(255, 170, 0, 0.4); }
    .badge-neutral { background-color: rgba(0, 204, 255, 0.12); color: #00ccff; border: 1px solid rgba(0, 204, 255, 0.4); }
    .badge-strong { background-color: rgba(0, 242, 254, 0.12); color: #00f2fe; border: 1px solid rgba(0, 242, 254, 0.4); }
    .badge-extreme { background-color: rgba(186, 104, 200, 0.12); color: #ba68c8; border: 1px solid rgba(186, 104, 200, 0.4); }
    
    /* Gemini AI Card Box */
    .gemini-card {
        background: #10131a;
        border: 1px solid #30363d;
        border-left: 3px solid #00f2fe;
        border-radius: 6px;
        padding: 20px 24px;
        margin-top: 16px;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #0b0e14 !important;
        border-right: 1px solid #30363d !important;
    }
    
    /* Data Table Styling */
    .stDataFrame {
        border: 1px solid #30363d !important;
        border-radius: 6px;
        background-color: #10131a;
    }
    
    /* Button & Touch Optimizations */
    .stButton>button, .stDownloadButton>button {
        background-color: transparent;
        color: #00f2fe;
        border: 1px solid #00f2fe;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
        min-height: 44px !important;
        transition: all 0.2s ease;
    }
    
    .stButton>button:hover, .stDownloadButton>button:hover {
        background-color: rgba(0, 242, 254, 0.15);
        color: #ffffff;
        border-color: #00f2fe;
    }

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid #30363d;
        background-color: #0b0e14;
    }

    .stTabs [data-baseweb="tab"] {
        height: 48px;
        white-space: pre;
        border-radius: 6px 6px 0px 0px;
        color: #849495;
        font-family: 'Geist', sans-serif;
        font-weight: 600;
        padding: 0px 20px;
        background-color: #10131a;
        border: 1px solid #30363d;
        border-bottom: none;
    }

    .stTabs [aria-selected="true"] {
        color: #00f2fe !important;
        border-color: #00f2fe !important;
        background-color: #161b22 !important;
    }

    /* Mobile Responsive Media Queries (<768px) */
    @media (max-width: 768px) {
        .main-header {
            padding: 14px 16px !important;
            margin-bottom: 12px !important;
        }
        .main-title {
            font-size: 1.4rem !important;
            flex-wrap: wrap;
        }
        .subtitle {
            font-size: 0.78rem !important;
        }
        .metric-card {
            padding: 12px !important;
            margin-bottom: 8px !important;
        }
        .metric-value {
            font-size: 1.6rem !important;
        }
        .metric-label {
            font-size: 0.68rem !important;
        }
        .gemini-card {
            padding: 14px 16px !important;
        }
        .stButton>button, .stDownloadButton>button {
            padding: 8px 12px !important;
            font-size: 0.82rem !important;
            width: 100% !important;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 0px 10px !important;
            font-size: 0.82rem !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# --- Sidebar Configuration ---
with st.sidebar:
    st.markdown("<h3 style='font-family: Geist; color: #00f2fe; margin-bottom: 0;'>⚡ STITCH TERMINAL</h3>", unsafe_allow_html=True)
    st.caption("Crypto Market Intelligence Engine v4.5 (Mobile Responsive)")
    
    st.markdown("---")
    st.markdown("<span style='font-family: Inter; font-size: 0.8rem; font-weight: 600; color: #849495;'>PARAMETROS DE BUSQUEDA</span>", unsafe_allow_html=True)
    
    timeframe = st.selectbox(
        "TEMPORALIDAD (OHLCV):",
        options=["1d", "4h", "1w"],
        index=0,
        help="Selecciona el marco temporal de las velas para el cálculo de las EMAs"
    )
    
    top_n = st.slider("Pares USDT (por Vol 24h):", min_value=10, max_value=50, value=50, step=5)
    
    st.markdown("---")
    st.markdown("<span style='font-family: Inter; font-size: 0.8rem; font-weight: 600; color: #849495;'>🔄 MONITOR EN VIVO</span>", unsafe_allow_html=True)
    auto_refresh = st.checkbox("🔄 Auto-refrescar (cada 5 min)", value=False, help="Recarga las métricas automáticamente en segundo plano cada 300 segundos.")
    
    if auto_refresh:
        st.caption("⏱️ Monitor activo. Actualizando cada 5 min...")
        st.markdown("""
            <script>
                setTimeout(function(){
                    window.location.reload();
                }, 300000);
            </script>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<span style='font-family: Inter; font-size: 0.8rem; font-weight: 600; color: #849495;'>CREDENCIALES GEMINI AI</span>", unsafe_allow_html=True)
    saved_gemini_key = st.session_state.get("gemini_api_key", "")
    user_api_key = st.text_input("GEMINI_API_KEY:", value=saved_gemini_key, type="password", help="Opcional si ya está configurado en el archivo .env")
    
    if user_api_key:
        st.session_state["gemini_api_key"] = user_api_key.strip()
        os.environ["GEMINI_API_KEY"] = user_api_key.strip()
        st.success("API Key vinculada")
        
    st.markdown("---")
    st.markdown("<span style='font-family: Inter; font-size: 0.8rem; font-weight: 600; color: #849495;'>🔔 ALERTAS TELEGRAM</span>", unsafe_allow_html=True)
    
    saved_token = st.session_state.get("telegram_token", os.getenv("TELEGRAM_BOT_TOKEN", ""))
    saved_chat = st.session_state.get("telegram_chat", os.getenv("TELEGRAM_CHAT_ID", ""))
    
    tg_token_input = st.text_input("Bot Token:", value=saved_token, type="password")
    tg_chat_input = st.text_input("Chat ID:", value=saved_chat)
    
    if tg_token_input:
        st.session_state["telegram_token"] = tg_token_input.strip()
        os.environ["TELEGRAM_BOT_TOKEN"] = tg_token_input.strip()
    if tg_chat_input:
        st.session_state["telegram_chat"] = tg_chat_input.strip()
        os.environ["TELEGRAM_CHAT_ID"] = tg_chat_input.strip()
        
    if st.button("🚀 PROBAR ALERTA DE TELEGRAM", use_container_width=True):
        if not tg_token_input or not tg_chat_input:
            st.error("Por favor completa el Bot Token y Chat ID.")
        else:
            with st.spinner("Conectando con Telegram..."):
                test_res = test_telegram_connection(tg_token_input, tg_chat_input)
                if test_res.get("success"):
                    st.success(test_res["message"])
                else:
                    st.error(test_res["message"])

    st.markdown("<br>", unsafe_allow_html=True)
    refresh_btn = st.button("🔄 ACTUALIZAR DATOS EN VIVO", use_container_width=True)

# --- Header ---
st.markdown(f"""
    <div class="main-header">
        <div class="main-title">
            <span>SYNTHETIC INTELLIGENCE</span>
            <span class="title-accent">TERMINAL [{timeframe.upper()}]</span>
        </div>
        <div class="subtitle">Análisis Cuantitativo, Escáner de Divergencias IA, SQLite, Alertas Telegram & Mobile Ready</div>
    </div>
""", unsafe_allow_html=True)

# --- Fetch Data ---
@st.cache_data(ttl=120, show_spinner=False)
def load_data(n_assets: int, tf: str):
    return fetch_market_breadth_data(top_n=n_assets, timeframe=tf)

with st.spinner(f"⚡ Conectando con Binance Spot API ({timeframe.upper()}) y calculando divergencias..."):
    data = load_data(top_n, timeframe)

if data.get('is_fallback'):
    st.info("ℹ️ **Modo Demostración Activo:** Se han cargado métricas simuladas de alta fidelidad mientras se restablece la conexión en tiempo real con Binance API.")

# --- Navigation Tabs ---
tab_live, tab_history = st.tabs(["⚡ TERMINAL EN VIVO", "📈 HISTÓRICO DE AMPLITUD"])

# ==========================================
# TAB 1: TERMINAL EN VIVO
# ==========================================
with tab_live:
    score = data['market_breadth_score']

    def get_score_badge(s):
        if s < 20:
            return ('SOBREVENTA EXTREMA', 'badge-oversold')
        elif s < 40:
            return ('DEBILIDAD ESTRUCTURAL', 'badge-weak')
        elif s < 60:
            return ('RÉGIMEN NEUTRO', 'badge-neutral')
        elif s < 80:
            return ('SALUD ALCISTA', 'badge-strong')
        else:
            return ('SOBRECOMPRA / EUFORIA', 'badge-extreme')

    badge_text, badge_class = get_score_badge(score)

    # Extreme Zone Banner Notice
    if score < 20 or score > 80:
        st.warning(f"⚠️ **ALERTA DE ZONA EXTREMA DE MERCADO:** El Breadth Index Score está en `{score}/100` ({badge_text}). Se recomienda enviar una notificación de riesgo.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">BREADTH INDEX SCORE</div>
                <div class="metric-value">{score}<span style="font-size:1.1rem; color:#849495;">/100</span></div>
                <div class="metric-badge {badge_class}">{badge_text}</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        ema20_val = data['pct_above_ema20']
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">CORTO PLAZO (> EMA 20)</div>
                <div class="metric-value">{ema20_val}%</div>
                <div class="metric-badge {'badge-strong' if ema20_val >= 50 else 'badge-oversold'}">
                    {ema20_val}% ACTIVOS
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        ema50_val = data['pct_above_ema50']
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">MEDIANO PLAZO (> EMA 50)</div>
                <div class="metric-value">{ema50_val}%</div>
                <div class="metric-badge {'badge-strong' if ema50_val >= 50 else 'badge-weak'}">
                    {ema50_val}% ACTIVOS
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col4:
        ema200_val = data['pct_above_ema200']
        btc_price_display = data.get('btc_price', 65000.0)
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">LARGO PLAZO (> EMA 200)</div>
                <div class="metric-value">{ema200_val}%</div>
                <div class="metric-badge badge-neutral">
                    BTC: ${btc_price_display:,.0f}
                </div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- Visual Charts Section ---
    chart_col1, chart_col2 = st.columns([1, 1])

    with chart_col1:
        st.markdown("<h3 style='font-family: Geist; font-size: 1.1rem; color: #e1e2eb;'>🎯 VELOCÍMETRO DE AMPLITUD</h3>", unsafe_allow_html=True)
        
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = score,
            domain = {'x': [0, 1], 'y': [0, 1]},
            number = {'font': {'color': '#ffffff', 'family': 'JetBrains Mono', 'size': 42}},
            gauge = {
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#849495"},
                'bar': {'color': "#00f2fe", 'thickness': 0.22},
                'bgcolor': "#10131a",
                'borderwidth': 1,
                'bordercolor': "#30363d",
                'steps': [
                    {'range': [0, 20], 'color': 'rgba(255, 77, 77, 0.25)'},
                    {'range': [20, 40], 'color': 'rgba(255, 170, 0, 0.2)'},
                    {'range': [40, 60], 'color': 'rgba(0, 204, 255, 0.15)'},
                    {'range': [60, 80], 'color': 'rgba(0, 242, 254, 0.25)'},
                    {'range': [80, 100], 'color': 'rgba(186, 104, 200, 0.3)'}
                ]
            }
        ))
        fig_gauge.update_layout(
            paper_bgcolor='#10131a',
            plot_bgcolor='#10131a',
            font={'color': "#e1e2eb", 'family': 'JetBrains Mono'},
            height=300,
            margin=dict(l=10, r=10, t=30, b=10)
        )
        st.plotly_chart(fig_gauge, use_container_width=True)

    with chart_col2:
        st.markdown("<h3 style='font-family: Geist; font-size: 1.1rem; color: #e1e2eb;'>📊 ESTRUCTURA DE MEDIAS MÓVILES</h3>", unsafe_allow_html=True)
        
        ema_df = pd.DataFrame({
            'Temporalidad': ['EMA 20 (Corto)', 'EMA 50 (Medio)', 'EMA 200 (Macro)'],
            'Porcentaje': [data['pct_above_ema20'], data['pct_above_ema50'], data['pct_above_ema200']]
        })
        
        fig_bar = px.bar(
            ema_df,
            x='Temporalidad',
            y='Porcentaje',
            text_auto='.1f',
            color='Porcentaje',
            color_continuous_scale=['#ff4d4d', '#ffaa00', '#00f2fe']
        )
        
        fig_bar.update_layout(
            paper_bgcolor='#10131a',
            plot_bgcolor='#10131a',
            font={'color': "#e1e2eb", 'family': 'JetBrains Mono'},
            yaxis=dict(range=[0, 100], gridcolor='#1e2638'),
            xaxis=dict(gridcolor='#1e2638'),
            coloraxis_showscale=False,
            height=300,
            margin=dict(l=10, r=10, t=30, b=10)
        )
        fig_bar.update_traces(
            textposition='outside',
            textfont=dict(family='JetBrains Mono', size=13),
            marker_line_color='#0b0e14',
            marker_line_width=1
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # --- Gemini AI Intelligence Container ---
    st.markdown("<br>", unsafe_allow_html=True)
    
    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.markdown("<h3 style='font-family: Geist; font-size: 1.2rem; color: #00f2fe; margin:0;'>🤖 INFORME DE INTELIGENCIA DE MERCADO & DIVERGENCIAS (GEMINI AI)</h3>", unsafe_allow_html=True)
    with head_col2:
        send_tg_btn = st.button("📲 ENVIAR A TELEGRAM", use_container_width=True)

    active_key = st.session_state.get("gemini_api_key") or user_api_key or os.getenv("GEMINI_API_KEY")
    gemini_report = analyze_market_breadth(data, api_key=active_key)

    if send_tg_btn:
        active_tg_token = st.session_state.get("telegram_token") or tg_token_input
        active_tg_chat = st.session_state.get("telegram_chat") or tg_chat_input
        if not active_tg_token or not active_tg_chat:
            st.error("⚠️ Ingrese el Bot Token y Chat ID en la barra lateral para enviar el informe.")
        else:
            with st.spinner("Enviando informe a Telegram..."):
                tg_res = send_breadth_alert(data, gemini_report.get("report"), active_tg_token, active_tg_chat)
                if tg_res.get("success"):
                    st.success(tg_res["message"])
                else:
                    st.error(tg_res["message"])

    st.markdown('<div class="gemini-card">', unsafe_allow_html=True)
    if gemini_report.get("success"):
        if gemini_report.get("model_used"):
            st.caption(f"⚡ Generado exitosamente con: `{gemini_report['model_used']}`")
        st.markdown(gemini_report["report"])
    else:
        st.markdown(gemini_report.get("report"))
    st.markdown('</div>', unsafe_allow_html=True)

    # Download AI Report Button
    report_text = gemini_report.get("report", "")
    st.markdown("<br>", unsafe_allow_html=True)
    st.download_button(
        label="📄 Descargar Informe Completo (.md)",
        data=report_text,
        file_name=f"informe_inteligencia_cripto_{timeframe}.md",
        mime="text/markdown",
        help="Guarda el informe ejecutivo generado en tu disco local.",
        use_container_width=True
    )

    # --- Detailed Asset Table ---
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"<h3 style='font-family: Geist; font-size: 1.2rem; color: #e1e2eb;'>📋 MATRIZ DE ACTIVOS ANALIZADOS (TOP {len(data['assets_detail'])})</h3>", unsafe_allow_html=True)

    df_assets = pd.DataFrame(data['assets_detail'])
    df_assets = df_assets.rename(columns={
        'symbol': 'PAR',
        'price': 'PRECIO (USDT)',
        'change_24h': 'VAR 24H',
        'quote_volume': 'VOLUMEN 24H',
        'above_ema20': '> EMA 20',
        'above_ema50': '> EMA 50',
        'above_ema200': '> EMA 200'
    })

    df_assets['PRECIO (USDT)'] = df_assets['PRECIO (USDT)'].apply(lambda x: f"${x:,.4f}" if x < 1 else f"${x:,.2f}")
    df_assets['VAR 24H'] = df_assets['VAR 24H'].apply(lambda x: f"{x:+.2f}%")
    df_assets['VOLUMEN 24H'] = df_assets['VOLUMEN 24H'].apply(lambda x: f"${x:,.0f}")
    df_assets['> EMA 20'] = df_assets['> EMA 20'].apply(lambda x: "🟢 SÍ" if x else "🔴 NO")
    df_assets['> EMA 50'] = df_assets['> EMA 50'].apply(lambda x: "🟢 SÍ" if x else "🔴 NO")
    df_assets['> EMA 200'] = df_assets['> EMA 200'].apply(lambda x: "🟢 SÍ" if x else "🔴 NO")

    st.dataframe(
        df_assets[['PAR', 'PRECIO (USDT)', 'VAR 24H', 'VOLUMEN 24H', '> EMA 20', '> EMA 50', '> EMA 200']],
        use_container_width=True,
        hide_index=True
    )

# ==========================================
# TAB 2: HISTÓRICO DE AMPLITUD (SQLITE)
# ==========================================
with tab_history:
    st.markdown("<h3 style='font-family: Geist; font-size: 1.3rem; color: #00f2fe;'>📈 EVOLUCIÓN HISTÓRICA DE AMPLITUD & PRECIO DE BITCOIN</h3>", unsafe_allow_html=True)
    st.caption(f"Base de datos SQLite activa (`breadth_data.db`) — Registro histórico para temporalidad: `{timeframe.upper()}`")

    hist_col1, hist_col2 = st.columns([1, 3])
    with hist_col1:
        days_range = st.radio(
            "Rango de tiempo:",
            options=[30, 60, 90, 180],
            format_func=lambda x: f"Últimos {x} días",
            index=0
        )

    df_hist = get_historical_breadth(timeframe=timeframe, days=days_range)

    if not df_hist.empty:
        # Create Plotly Chart with Dual Y-Axis
        fig_hist = make_subplots(specs=[[{"secondary_y": True}]])

        # Trace 1: Breadth Index Score (Left Y-Axis)
        fig_hist.add_trace(
            go.Scatter(
                x=df_hist['timestamp'],
                y=df_hist['breadth_score'],
                name="Breadth Score (0-100)",
                line=dict(color="#00f2fe", width=2.5),
                mode='lines+markers',
                marker=dict(size=4)
            ),
            secondary_y=False
        )

        # Trace 2: BTC Price (Right Y-Axis)
        fig_hist.add_trace(
            go.Scatter(
                x=df_hist['timestamp'],
                y=df_hist['btc_price'],
                name="Precio BTC (USDT)",
                line=dict(color="#ffaa00", width=2, dash='dot'),
                mode='lines'
            ),
            secondary_y=True
        )

        # Extreme Bands (Overbought > 80, Oversold < 20)
        fig_hist.add_hrect(y0=80, y1=100, fillcolor="rgba(186, 104, 200, 0.12)", line_width=0, secondary_y=False)
        fig_hist.add_hrect(y0=0, y1=20, fillcolor="rgba(255, 77, 77, 0.12)", line_width=0, secondary_y=False)

        fig_hist.update_layout(
            paper_bgcolor='#10131a',
            plot_bgcolor='#10131a',
            font=dict(color='#e1e2eb', family='JetBrains Mono'),
            height=400,
            hovermode='x unified',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            margin=dict(l=10, r=10, t=30, b=10)
        )

        fig_hist.update_xaxes(gridcolor='#1e2638', title_text="Fecha / Hora")
        fig_hist.update_yaxes(title_text="Breadth Score", range=[0, 105], gridcolor='#1e2638', secondary_y=False)
        fig_hist.update_yaxes(title_text="Precio BTC ($)", gridcolor='#1e2638', secondary_y=True)

        st.plotly_chart(fig_hist, use_container_width=True)

        # Summary Statistics Row
        max_score = df_hist['breadth_score'].max()
        min_score = df_hist['breadth_score'].min()
        avg_score = round(df_hist['breadth_score'].mean(), 1)
        latest_btc = df_hist['btc_price'].iloc[-1]

        hcol1, hcol2, hcol3, hcol4 = st.columns(4)
        with hcol1:
            st.metric("SCORE MÁXIMO", f"{max_score}/100")
        with hcol2:
            st.metric("SCORE MÍNIMO", f"{min_score}/100")
        with hcol3:
            st.metric("SCORE PROMEDIO", f"{avg_score}/100")
        with hcol4:
            st.metric("ÚLTIMO PRECIO BTC", f"${latest_btc:,.2f}")

        # Data Table & Export Button Header
        st.markdown("<br>", unsafe_allow_html=True)
        tbl_col1, tbl_col2 = st.columns([2, 2])
        with tbl_col1:
            st.markdown("<h4 style='font-family: Geist; color: #e1e2eb; margin: 0;'>📜 REGISTROS HISTÓRICOS EN SQLITE</h4>", unsafe_allow_html=True)
        with tbl_col2:
            csv_bytes = df_hist.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Descargar Historial (CSV)",
                data=csv_bytes,
                file_name=f"breadth_history_{timeframe}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        df_display = df_hist.sort_values(by='timestamp', ascending=False).copy()
        df_display = df_display.rename(columns={
            'timestamp': 'FECHA / HORA',
            'timeframe': 'TEMPORALIDAD',
            'breadth_score': 'BREADTH SCORE',
            'pct_above_ema20': '% > EMA20',
            'pct_above_ema50': '% > EMA50',
            'pct_above_ema200': '% > EMA200',
            'btc_price': 'PRECIO BTC (USDT)'
        })
        df_display['PRECIO BTC (USDT)'] = df_display['PRECIO BTC (USDT)'].apply(lambda x: f"${x:,.2f}")
        
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.warning("No hay registros históricos disponibles para esta temporalidad en la base de datos.")

st.caption("⚡ Terminal de Inteligencia Cuantitativa de Amplitud de Mercado (#0b0e14 Obsidian Theme - Responsive Optimized)")
