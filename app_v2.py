"""Read-only Streamlit v2 product shell.

The presentation deliberately follows the established Crypto Breadth Terminal
language while keeping the data path strictly Firestore-reader-only.  Gate,
writer credentials, ingestion and all legacy persistence remain outside this
module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import os
from pathlib import Path
import sys
from typing import Iterable, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.firestore import FirestoreSnapshotStore
from crypto_breadth_v2.firestore_query import FirestoreReadOnlyQueryService
from crypto_breadth_v2.view_models import DashboardView, ScannerView, SnapshotView


UTC = timezone.utc
REGIME_COLORS = {
    "panic": "#FF3366",
    "fear": "#FF8A00",
    "neutral": "#FACC15",
    "expansion": "#00F59B",
    "euphoria": "#00B87A",
}
DISPLAY_QUANTUM = Decimal("0.1")


def canonical_display_decimal(value: Decimal | None) -> Decimal | None:
    """Round product-facing breadth/percentage values without changing storage."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise TypeError("canonical display values must be Decimal")
    return value.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)


def _metric_number(value: Decimal | None, suffix: str = "") -> str:
    """Render a complete value without truncation or binary-float conversion."""
    rounded = canonical_display_decimal(value)
    if rounded is None:
        return "—"
    return f"{rounded:.1f}{suffix}"


def _regime(value: Decimal | None) -> tuple[str, str]:
    if value is None:
        return "UNAVAILABLE", "#94a3b8"
    numeric = float(value)
    if numeric < 20:
        return "Pánico", REGIME_COLORS["panic"]
    if numeric < 40:
        return "Miedo", REGIME_COLORS["fear"]
    if numeric < 60:
        return "Neutral", REGIME_COLORS["neutral"]
    if numeric < 80:
        return "Expansión", REGIME_COLORS["expansion"]
    return "Euforia", REGIME_COLORS["euphoria"]


def _age(view: DashboardView) -> str:
    if view.age is None:
        return "—"
    seconds = max(0, int(view.age.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    return f"{hours}h {remainder // 60:02d}m"


def _state_message(view: DashboardView) -> str:
    return {
        "CURRENT": "Publicación candidata actual",
        "STALE": "Último fallo; mostrando último dato válido",
        "DEGRADED": "Publicación candidata degradada",
        "UNAVAILABLE": "No hay publicación candidata utilizable",
    }.get(view.ui_state, "Estado no disponible")


def _status_caption(view: DashboardView) -> None:
    text = f"{view.ui_state} · {_state_message(view)} · cierre esperado {view.expected_boundary.isoformat()}"
    if view.ui_state in {"STALE", "DEGRADED"}:
        st.warning(text)
    else:
        st.caption(text)


def _metric_card_html(label: str, value: str, subtitle: str, *, value_color: str | None = None) -> str:
    """Return one complete card; no Streamlit widget is nested in raw HTML."""
    color = f";color:{escape(value_color)}" if value_color else ""
    return (
        '<div class="v2-metric-card">'
        f'<div class="v2-metric-title">{escape(label)}</div>'
        f'<div class="v2-metric-value" style="white-space:nowrap;overflow:visible{color}">{escape(value)}</div>'
        f'<div class="v2-metric-sub">{escape(subtitle)}</div>'
        "</div>"
    )


def _metric_cards(snapshot: SnapshotView | None) -> None:
    score = snapshot.breadth_score if snapshot else None
    regime, color = _regime(score)
    metrics = (
        ("Breadth Score", _metric_number(score, " / 100"), "Salud Global"),
        ("> EMA20 (Corto)", _metric_number(snapshot.pct_above_ema20 if snapshot else None, "%"), "Momento Inmediato"),
        ("> EMA50 (Medio)", _metric_number(snapshot.pct_above_ema50 if snapshot else None, "%"), "Estructura Tendencial"),
        ("> EMA200 (Largo)", _metric_number(snapshot.pct_above_ema200 if snapshot else None, "%"), "Régimen Macro"),
    )
    st.markdown(
        "<style>"
        ".v2-metric-card{background:rgba(22,27,34,.70);border:1px solid rgba(255,255,255,.08);"
        "border-radius:12px;padding:14px 12px;text-align:center;min-height:108px}"
        ".v2-metric-title{font-size:.78rem;text-transform:uppercase;color:#94a3b8;margin-bottom:6px}"
        ".v2-metric-value{font-size:clamp(1.15rem,2.1vw,1.8rem);font-weight:700;color:#f8fafc;line-height:1.3}"
        ".v2-metric-sub{font-size:.75rem;color:#64748b;margin-top:5px}"
        "</style>",
        unsafe_allow_html=True,
    )
    columns = st.columns(4)
    for column, (label, value, subtitle) in zip(columns, metrics):
        with column:
            st.markdown(_metric_card_html(label, value, subtitle, value_color=color if label == "Breadth Score" else None), unsafe_allow_html=True)
    if score is not None:
        st.caption(f"Régimen: {regime}")


def build_regime_gauge(snapshot: SnapshotView | None) -> go.Figure | None:
    """Build the legacy 0–100 regime gauge without writing or fetching data."""
    rounded_score = canonical_display_decimal(snapshot.breadth_score) if snapshot is not None else None
    if rounded_score is None:
        return None
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(rounded_score),
            number={"font": {"size": 42, "color": "#f8fafc"}, "suffix": "/100"},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "rgba(255,255,255,.2)"},
                "bar": {"color": "rgba(255,255,255,.9)", "thickness": .15},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 20], "color": REGIME_COLORS["panic"]},
                    {"range": [20, 40], "color": REGIME_COLORS["fear"]},
                    {"range": [40, 60], "color": REGIME_COLORS["neutral"]},
                    {"range": [60, 80], "color": REGIME_COLORS["expansion"]},
                    {"range": [80, 100], "color": REGIME_COLORS["euphoria"]},
                ],
            },
        )
    )
    figure.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=280, margin=dict(l=10, r=10, t=10, b=10))
    return figure


def _filtered_history(history: Sequence[SnapshotView], history_filter: str) -> list[SnapshotView]:
    rows = sorted(history, key=lambda item: item.candle_time)
    if history_filter == "Total" or not rows:
        return rows
    days = {"1d": 1, "1w": 7, "1m": 30, "6m": 180, "1y": 365}[history_filter]
    cutoff = rows[-1].candle_time.timestamp() - days * 86400
    return [row for row in rows if row.candle_time.timestamp() >= cutoff]


def build_history_figure(history: Sequence[SnapshotView], benchmark: str, history_filter: str = "Total") -> go.Figure | None:
    """Return the historical model with breadth on the left and price right."""
    rows = _filtered_history(history, history_filter)
    if not rows:
        return None
    benchmark = benchmark.upper()
    if benchmark not in {"BTC", "ETH"}:
        raise ValueError("benchmark must be BTC or ETH")
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    x = [row.candle_time for row in rows]
    series = (
        ("Breadth Score", "breadth_score", "#00F59B", "solid"),
        ("> EMA20 (Corto)", "pct_above_ema20", "#A78BFA", "dot"),
        ("> EMA50 (Medio)", "pct_above_ema50", "#38BDF8", "dash"),
        ("> EMA200 (Largo)", "pct_above_ema200", "#F43F5E", "dashdot"),
    )
    for name, attribute, color, dash in series:
        values = [getattr(row, attribute) for row in rows]
        figure.add_trace(go.Scatter(x=x, y=[float(value) if value is not None else None for value in values], name=name, mode="lines+markers", line={"color": color, "dash": dash}), secondary_y=False)
    prices = [row.btc_close if benchmark == "BTC" else row.eth_close for row in rows]
    if any(value is not None for value in prices):
        figure.add_trace(go.Scatter(x=x, y=[float(value) if value is not None else None for value in prices], name=f"{benchmark} Precio", mode="lines", line={"color": "#F59E0B", "width": 2}), secondary_y=True)
    figure.update_yaxes(title_text="Amplitud (%)", range=[0, 100], secondary_y=False, gridcolor="rgba(255,255,255,.08)")
    figure.update_yaxes(title_text=f"{benchmark} precio", secondary_y=True, showgrid=False)
    figure.update_layout(template="plotly_dark", height=440, margin=dict(l=12, r=12, t=30, b=12), legend=dict(orientation="h", y=1.08), paper_bgcolor="#0b0e14", plot_bgcolor="#0b0e14", hovermode="x unified")
    return figure


def _scanner_state(value: str) -> str:
    return {"ABOVE": "🟢 ABOVE", "BELOW": "🔴 BELOW", "UNAVAILABLE": "⚪ UNAVAILABLE"}.get(value, "⚪ UNAVAILABLE")


def _scanner_table(rows: Iterable[ScannerView]) -> list[dict[str, object]]:
    return [
        {
            "Símbolo": row.symbol,
            "Activo": row.display_name,
            "Precio": str(row.price) if row.price is not None else "—",
            "> EMA20": _scanner_state(row.state20),
            "> EMA50": _scanner_state(row.state50),
            "> EMA200": _scanner_state(row.state200),
            "Incluido": "Sí" if row.included_in_breadth else "No",
            "Cierre": row.candle_time.isoformat(),
        }
        for row in rows
    ]


def _history_gap_text(timeframe: str, history_filter: str) -> str:
    granularity = {"4h": "6 cierres por día", "1d": "1 cierre UTC por día", "1w": "1 cierre derivado por lunes UTC"}[timeframe]
    requested = {
        "1d": "la ventana de 1 día",
        "1w": "la ventana de 7 días",
        "1m": "la ventana de 30 días",
        "6m": "la ventana de 180 días",
        "1y": "la ventana de 365 días",
        "Total": "todo el historial disponible",
    }[history_filter]
    return f"Para {timeframe}, Firestore debe contener snapshots PUBLISHED reales ({granularity}) para {requested}; no se interpolan ni fabrican observaciones. Se necesitan al menos 2 puntos para dibujar una serie; el resto se mostrará cuando exista backfill histórico."


def render_app(query_service: FirestoreReadOnlyQueryService, *, now: datetime | None = None) -> None:
    st.set_page_config(page_title="Crypto Market Breadth Terminal", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")
    st.markdown("<style>.stApp{background:#0b0e14;color:#e2e8f0} header[data-testid=stHeader]{background:transparent} #MainMenu,footer{visibility:hidden}</style>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;margin-bottom:2px'>⚡ CRYPTO BREADTH TERMINAL</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#64748b;font-size:.85rem;margin-bottom:14px'>Monitor de Amplitud de Mercado &amp; Diagnóstico Cuantitativo</p>", unsafe_allow_html=True)

    control_columns = st.columns([1.25, 1.1, 2.5, 2.0])
    with control_columns[0]:
        timeframe = st.radio("Temporalidad", ["1d", "4h", "1w"], index=0, horizontal=True, key="v2_timeframe")
    with control_columns[1]:
        benchmark = st.radio("Benchmark", ["BTC", "ETH"], index=0, horizontal=True, key="v2_benchmark")
    with control_columns[2]:
        history_filter = st.radio("Histórico", ["1d", "1w", "1m", "6m", "1y", "Total"], index=5, horizontal=True, key="v2_history")
    with control_columns[3]:
        st.caption("Fuente: Gate")
        st.caption("Solo lectura · serie candidata")

    view = query_service.dashboard(timeframe, now=now)
    _status_caption(view)
    snapshot = view.latest if view.ui_state == "CURRENT" else view.last_known_good or view.latest
    if snapshot:
        st.caption(f"Calidad: {snapshot.data_quality_label} · {snapshot.data_quality_score}")
    else:
        st.caption("Calidad: UNAVAILABLE")
    _metric_cards(snapshot)

    st.markdown("### 🌡️ Termómetro de Régimen")
    gauge = build_regime_gauge(snapshot)
    if gauge is None:
        st.info("UNAVAILABLE — el termómetro aparecerá al publicarse un snapshot válido.")
    else:
        st.plotly_chart(gauge, use_container_width=True, config={"displayModeBar": False})

    st.markdown(f"### 📈 Histórico de Amplitud vs {benchmark}")
    history = _filtered_history(view.history, history_filter)
    if len(history) < 2:
        st.info(f"Histórico en construcción: hay {len(history)} snapshot(s) PUBLISHED para {timeframe}. {_history_gap_text(timeframe, history_filter)}")
    else:
        figure = build_history_figure(history, benchmark, "Total")
        if figure is not None:
            st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
    with st.expander("Necesidades de histórico Firestore"):
        st.write(_history_gap_text(timeframe, history_filter))
        st.write("Filtros: 1d = 24h; 1w = 7 días; 1m = 30 días; 6m = 180 días; 1y = 365 días; Total = todo lo retenido. Cada filtro usa únicamente cierres publicados de la temporalidad seleccionada.")

    st.subheader("📋 Escáner de Activos")
    scanner = _scanner_table(view.scanner)
    if scanner:
        st.dataframe(scanner, use_container_width=True, hide_index=True)
    else:
        st.info("El escáner aparecerá cuando exista un snapshot publicado para esta temporalidad.")

    with st.expander("Proveniencia y versiones"):
        provenance = snapshot.provenance if snapshot else {
            "series_version": query_service.series_version,
            "universe_version": query_service.universe_version,
            "source_policy_version": query_service.source_policy_version,
            "formula_version": query_service.formula_version,
            "normalizer_version": query_service.normalizer_version,
        }
        st.json(dict(provenance))
        if snapshot:
            st.caption(f"Calidad de datos: {snapshot.data_quality_label} ({snapshot.data_quality_score}) · edad {_age(view)} · cohorte {snapshot.cohort_size}/{snapshot.universe_size}")
    if view.latest_failure:
        st.warning(f"Último fallo: {view.latest_failure.get('message') or 'publicación no disponible'}")


def main() -> None:
    project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    reader_credentials = os.environ.get("FIREBASE_READER_SERVICE_ACCOUNT_JSON")
    if (not project_id or not reader_credentials) and not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        st.set_page_config(page_title="Crypto Market Breadth Terminal", page_icon="⚡")
        st.error("UNAVAILABLE — configura FIREBASE_PROJECT_ID y FIREBASE_READER_SERVICE_ACCOUNT_JSON.")
        return
    try:
        bundle = load_contract_bundle(ROOT / "config" / "v2", bundle="v2-40")
        store = FirestoreSnapshotStore.from_environment(credentials_env="FIREBASE_READER_SERVICE_ACCOUNT_JSON")
        render_app(FirestoreReadOnlyQueryService(store, bundle))
    except Exception as exc:
        st.set_page_config(page_title="Crypto Market Breadth Terminal", page_icon="⚡")
        st.error(f"UNAVAILABLE — consulta Firestore de solo lectura fallida: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
