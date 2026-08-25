from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from crypto_breadth_v2.query import DashboardView, ScannerView, SnapshotView


UTC = timezone.utc


def _snapshot(*, status="PUBLISHED", candle_time=None):
    candle_time = candle_time or datetime(2026, 8, 21, 8, tzinfo=UTC)
    return SnapshotView(
        snapshot_id="snapshot-1", timeframe="4h", candle_time=candle_time,
        status=status, breadth_score=Decimal("62.5"), pct_above_ema20=Decimal("70"),
        pct_above_ema50=Decimal("60"), pct_above_ema200=Decimal("50"),
        data_quality_score=Decimal("100.0"), data_quality_label="HIGH",
        structural_coverage=Decimal("1"), component_coverage=Decimal("1"),
        btc_close=Decimal("100"), eth_close=Decimal("10"), universe_size=40,
        cohort_size=40, rejection_reason=None, computed_at=candle_time,
        provenance={"series_version": "BR1-LIVE-v2-40-CANDIDATE"},
    )


def test_query_service_module_has_no_provider_dependency():
    source = Path("src/crypto_breadth_v2/query.py").read_text(encoding="utf-8")
    assert "providers" not in source
    ui_source = Path("app_v2.py").read_text(encoding="utf-8")
    assert "providers" not in ui_source
    assert "GateClient" not in ui_source


def test_streamlit_app_test_current_weekly_scanner_and_no_network():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    source = '''
from datetime import datetime, timezone
from crypto_breadth_v2.query import DashboardView, ScannerView
from app_v2 import render_app
class Fake:
    series_version = "BR1-LIVE-v2-40-CANDIDATE"
    universe_version = "BR1-BREADTH-UNIVERSE-v2-40"
    source_policy_version = "BR1-SOURCE-POLICY-v2-GATE-ONLY"
    formula_version = "BR1-BREADTH-FORMULA-v1"
    normalizer_version = "BR1-CANDLE-NORMALIZER-v2"
    def dashboard(self, timeframe, now=None):
        now = datetime(2026, 8, 21, 8, tzinfo=timezone.utc)
        snap = __import__('tests_v2.test_query_and_app_v2', fromlist=['_snapshot'])._snapshot(candle_time=now)
        rows = tuple(ScannerView(str(i), f"A{i}", f"Asset {i}", now, None, None, None, None, "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", i < 35) for i in range(40))
        return DashboardView(timeframe, now, "CURRENT", snap, snap, now-now, None, (snap,), rows)
render_app(Fake(), now=datetime(2026, 8, 21, 8, tzinfo=timezone.utc))
'''
    with patch("urllib.request.urlopen", side_effect=AssertionError("UI attempted network access")):
        app = AppTest.from_string(source).run(timeout=10)
    assert not app.exception
    assert any("Breadth Score" in metric.label for metric in app.metric)
    assert len(app.dataframe) == 1
    assert "Asset scanner" in [heading.value for heading in app.subheader]
