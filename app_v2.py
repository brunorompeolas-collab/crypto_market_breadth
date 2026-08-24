"""Read-only Streamlit v2 candidate dashboard.

This module intentionally imports only the Firestore query layer.  It has no
Gate/provider, ingestion, maintenance, Gemini, or activation controls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st

from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.firestore import FirestoreSnapshotStore
from crypto_breadth_v2.firestore_query import FirestoreReadOnlyQueryService


UTC = timezone.utc


def _decimal(value: object, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value}{suffix}"


def _age(view: DashboardView) -> str:
    if view.age is None:
        return "—"
    seconds = max(0, int(view.age.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes:02d}m"


def _state_message(view: DashboardView) -> str:
    messages = {
        "CURRENT": "Current candidate publication",
        "STALE": "Latest candidate failed; showing last-known-good",
        "DEGRADED": "Latest candidate publication is degraded",
        "UNAVAILABLE": "No usable candidate publication is available",
    }
    return messages[view.ui_state]


def render_app(query_service: FirestoreReadOnlyQueryService, *, now: datetime | None = None) -> None:
    """Render the UI from an injected read-only service.

    Injection keeps AppTest deterministic while production construction below
    remains PostgreSQL-only.
    """
    st.set_page_config(
        page_title="Crypto Market Breadth v2",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        "<style>.stApp{background:#0b0e14;color:#e2e8f0}.metric-card{padding:12px;border:1px solid #263244;border-radius:10px}</style>",
        unsafe_allow_html=True,
    )
    st.title("⚡ Crypto Market Breadth Terminal v2")
    st.caption("Read-only Breadth v2 · Firestore snapshots · Gate provenance")

    timeframe = st.radio("Timeframe", ["4h", "1d", "1w"], index=1, horizontal=True, key="v2_timeframe")
    benchmark = st.radio("Benchmark", ["BTC", "ETH"], horizontal=True, key="v2_benchmark")
    history_filter = st.radio("History", ["1d", "1w", "1m", "6m", "1y", "Total"], index=5, horizontal=True, key="v2_history")
    view = query_service.dashboard(timeframe, now=now)

    st.info(f"{view.ui_state}: {_state_message(view)} · expected boundary {view.expected_boundary.isoformat()}")
    snapshot = view.latest if view.ui_state == "CURRENT" else view.last_known_good
    if snapshot is None:
        st.error("UNAVAILABLE — no published candidate snapshot is available.")
    else:
        cols = st.columns(6)
        metrics = (
            ("Breadth Score", _decimal(snapshot.breadth_score, " / 100")),
            ("Above EMA20", _decimal(snapshot.pct_above_ema20, "%")),
            ("Above EMA50", _decimal(snapshot.pct_above_ema50, "%")),
            ("Above EMA200", _decimal(snapshot.pct_above_ema200, "%")),
            ("Data Quality", f"{snapshot.data_quality_label} ({snapshot.data_quality_score})"),
            ("Age", _age(view)),
        )
        for column, (label, value) in zip(cols, metrics):
            column.metric(label, value)
        st.caption(
            f"Snapshot {snapshot.candle_time.isoformat()} · BTC {_decimal(snapshot.btc_close)} · "
            f"ETH {_decimal(snapshot.eth_close)} · cohort {snapshot.cohort_size}/{snapshot.universe_size}"
        )

        history = list(view.history)
        if history_filter != "Total":
            days = {"1d": 1, "1w": 7, "1m": 30, "6m": 180, "1y": 365}[history_filter]
            cutoff = snapshot.candle_time.timestamp() - days * 86400
            history = [row for row in history if row.candle_time.timestamp() >= cutoff]
        if history:
            chart_rows = [
                {
                    "timestamp": row.candle_time,
                    "Breadth Score": float(row.breadth_score) if row.breadth_score is not None else None,
                    "EMA20": float(row.pct_above_ema20) if row.pct_above_ema20 is not None else None,
                    "EMA50": float(row.pct_above_ema50) if row.pct_above_ema50 is not None else None,
                    "EMA200": float(row.pct_above_ema200) if row.pct_above_ema200 is not None else None,
                    benchmark: float(row.btc_close if benchmark == "BTC" else row.eth_close) if (row.btc_close if benchmark == "BTC" else row.eth_close) is not None else None,
                }
                for row in history
            ]
            st.subheader(f"Historical breadth vs {benchmark}")
            st.line_chart(chart_rows, x="timestamp", y=["Breadth Score", "EMA20", "EMA50", "EMA200"])
        else:
            st.warning("No historical published observations for this filter.")

    if view.latest_failure:
        st.warning(f"Latest failure: {view.latest_failure.get('message') or 'publication unavailable'}")

    st.subheader("Asset scanner")
    scanner_rows = [
        {
            "Symbol": row.symbol,
            "Asset": row.display_name,
            "Price": row.price,
            "EMA20": row.state20,
            "EMA50": row.state50,
            "EMA200": row.state200,
            "Included in breadth": row.included_in_breadth,
            "Timestamp": row.candle_time,
        }
        for row in view.scanner
    ]
    st.dataframe(scanner_rows, use_container_width=True, hide_index=True)

    with st.expander("Provenance and versions"):
        provenance = (snapshot.provenance if snapshot else {
            "series_version": query_service.series_version,
            "universe_version": query_service.universe_version,
            "source_policy_version": query_service.source_policy_version,
            "formula_version": query_service.formula_version,
            "normalizer_version": query_service.normalizer_version,
        })
        st.json(dict(provenance))


def main() -> None:
    project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id and not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        st.set_page_config(page_title="Crypto Market Breadth v2", page_icon="⚡")
        st.error("UNAVAILABLE — FIREBASE_PROJECT_ID is not configured.")
        return
    try:
        bundle = load_contract_bundle(ROOT / "config" / "v2", bundle="v2-40")
        store = FirestoreSnapshotStore.from_environment()
        render_app(FirestoreReadOnlyQueryService(store, bundle))
    except Exception as exc:
        st.set_page_config(page_title="Crypto Market Breadth v2", page_icon="⚡")
        st.error(f"UNAVAILABLE — read-only Firestore query failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
