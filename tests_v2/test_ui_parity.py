from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess

from crypto_breadth_v2.firestore import InMemorySnapshotStore
from crypto_breadth_v2.firestore_query import FirestoreReadOnlyQueryService
from crypto_breadth_v2.query import DashboardView, ScannerView, SnapshotView
from crypto_breadth_v2.contracts import load_contract_bundle

from app_v2 import _metric_number, _scanner_table, build_history_figure


UTC = timezone.utc
BUNDLE = load_contract_bundle(Path("config/v2"), bundle="v2-40")


def _snapshot(timeframe: str, hour: int, *, btc: str = "100", eth: str = "10") -> SnapshotView:
    candle_time = datetime(2026, 8, 21, hour, tzinfo=UTC)
    return SnapshotView(
        snapshot_id=f"{timeframe}-{hour}", timeframe=timeframe, candle_time=candle_time,
        status="PUBLISHED", breadth_score=Decimal("62.5"),
        pct_above_ema20=Decimal("70"), pct_above_ema50=Decimal("60"), pct_above_ema200=Decimal("50"),
        data_quality_score=Decimal("100"), data_quality_label="HIGH", structural_coverage=Decimal("1"),
        component_coverage=Decimal("1"), btc_close=Decimal(btc), eth_close=Decimal(eth), universe_size=40,
        cohort_size=40, rejection_reason=None, computed_at=candle_time, provenance={"source_id": "gate"},
    )


def test_selected_benchmark_is_a_distinct_right_scale_chart_series():
    rows = (_snapshot("1d", 8, btc="100", eth="10"), _snapshot("1d", 12, btc="110", eth="11"))
    btc = build_history_figure(rows, "BTC")
    eth = build_history_figure(rows, "ETH")
    assert btc is not None and eth is not None
    btc_trace = next(trace for trace in btc.data if trace.name == "BTC Precio")
    eth_trace = next(trace for trace in eth.data if trace.name == "ETH Precio")
    assert list(btc_trace.y) == [100.0, 110.0]
    assert list(eth_trace.y) == [10.0, 11.0]
    assert btc_trace.name != eth_trace.name
    assert btc_trace.yaxis == "y2" and eth_trace.yaxis == "y2"


def test_metric_values_are_complete_and_scanner_tri_state_is_readable():
    assert _metric_number(Decimal("100"), "%") == "100.0%"
    assert _metric_number(Decimal("62.5"), " / 100") == "62.5 / 100"
    rows = [
        ScannerView("a", "A", "Above", datetime(2026, 8, 21, tzinfo=UTC), Decimal("1"), None, None, None, "ABOVE", "BELOW", "UNAVAILABLE", True),
    ]
    table = _scanner_table(rows)
    assert table[0]["> EMA20"] == "🟢 ABOVE"
    assert table[0]["> EMA50"] == "🔴 BELOW"
    assert table[0]["> EMA200"] == "⚪ UNAVAILABLE"


def test_firestore_reader_selects_snapshot_for_each_timeframe_without_writes():
    store = InMemorySnapshotStore()
    for timeframe, hour in (("4h", 4), ("1d", 8), ("1w", 12)):
        row = _snapshot(timeframe, hour)
        store.put({"boundary": row.candle_time, "computed_at": row.computed_at, "series_version": "BR1-LIVE-v2-40-CANDIDATE", "timeframe": timeframe, "status": "PUBLISHED", "breadth_score": row.breadth_score, "pct_above_ema20": row.pct_above_ema20, "pct_above_ema50": row.pct_above_ema50, "pct_above_ema200": row.pct_above_ema200, "data_quality_score": row.data_quality_score, "data_quality_label": row.data_quality_label, "structural_coverage": row.structural_coverage, "component_coverage": row.component_coverage, "btc_close": row.btc_close, "eth_close": row.eth_close, "universe_size": 40, "cohort_denominator": 40, "scanner": []})
    reader = FirestoreReadOnlyQueryService(store, BUNDLE)
    assert reader.latest_snapshot("4h").timeframe == "4h"
    assert reader.latest_snapshot("1d").timeframe == "1d"
    assert reader.latest_snapshot("1w").timeframe == "1w"
    assert not hasattr(reader, "put")


def test_ui_has_no_provider_or_writer_path_and_legacy_files_are_unchanged():
    source = Path("app_v2.py").read_text(encoding="utf-8")
    assert "GateClient" not in source and "FIREBASE_WRITER_SERVICE_ACCOUNT_JSON" not in source
    assert "FirestoreSnapshotStore" in source and "FirestoreReadOnlyQueryService" in source
    assert subprocess.check_output(["git", "hash-object", "app.py"]).strip() == subprocess.check_output(["git", "rev-parse", "origin/main:app.py"]).strip()
    assert subprocess.check_output(["git", "hash-object", "requirements.txt"]).strip() == subprocess.check_output(["git", "rev-parse", "origin/main:requirements.txt"]).strip()
