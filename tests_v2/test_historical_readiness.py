from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from app_v2 import history_since_for_filter, history_window_days_for_filter
from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.firestore import FirestoreSnapshotStore, InMemorySnapshotStore
from crypto_breadth_v2.firestore_query import FirestoreReadOnlyQueryService


UTC = timezone.utc
SERIES = "BR1-LIVE-v2-40-CANDIDATE"


def _row(boundary: datetime, status: str = "PUBLISHED"):
    return {"boundary": boundary, "computed_at": boundary, "series_version": SERIES, "timeframe": "1d", "status": status}


def test_in_memory_history_since_until_and_limit_are_chronological_and_inclusive():
    store = InMemorySnapshotStore()
    points = [datetime(2026, 8, day, tzinfo=UTC) for day in (1, 2, 3, 4)]
    for point in points:
        store.put(_row(point))
    assert [row["boundary"] for row in store.history(SERIES, "1d", since=points[1])] == [
        "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"
    ]
    assert [row["boundary"] for row in store.history(SERIES, "1d", until=points[2])] == [
        "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"
    ]
    assert len(store.history(SERIES, "1d", since=points[0], limit=2)) == 2


class _Snapshot:
    def __init__(self, row):
        self.row = row

    def to_dict(self):
        return dict(self.row)


class _RecordingQuery:
    def __init__(self, rows):
        self.rows = rows
        self.operations = []

    def where(self, field, operator, value):
        self.operations.append(("where", field, operator, value))
        return self

    def order_by(self, field, **kwargs):
        self.operations.append(("order_by", field, kwargs))
        return self

    def limit(self, value):
        self.operations.append(("limit", value))
        return self

    def stream(self):
        return [_Snapshot(row) for row in self.rows]


class _RecordingClient:
    def __init__(self, rows):
        self.query = _RecordingQuery(rows)

    def collection(self, name):
        return self if name == "breadth_series" else self.query

    def document(self, name):
        return self


def test_firestore_history_pushes_bounds_and_limit_to_server_query():
    start = datetime(2026, 8, 2, tzinfo=UTC)
    end = datetime(2026, 8, 3, tzinfo=UTC)
    client = _RecordingClient([_row(start, "FAILED"), _row(end), _row(datetime(2026, 8, 4, tzinfo=UTC))])
    rows = FirestoreSnapshotStore(client).history(SERIES, "1d", since=start, until=end, limit=1)
    assert [row["boundary"] for row in rows] == [end]
    assert ("where", "boundary", ">=", "2026-08-02T00:00:00Z") in client.query.operations
    assert ("where", "boundary", "<=", "2026-08-03T00:00:00Z") in client.query.operations
    assert not any(op[0] == "limit" for op in client.query.operations)
    assert not any(op[0] == "where" and op[1] == "status" for op in client.query.operations)
    assert any(op[0] == "order_by" and op[1] == "boundary" for op in client.query.operations)


def test_ui_window_translates_to_bounded_query_and_total_is_explicitly_unbounded():
    anchor = datetime(2026, 8, 21, 12, tzinfo=UTC)
    assert history_window_days_for_filter("1m") == 30
    assert history_since_for_filter(anchor, "1m") == anchor - timedelta(days=30)
    assert history_window_days_for_filter("Total") is None
    assert history_since_for_filter(anchor, "Total") is None


def _dashboard_row(boundary: datetime, status: str = "PUBLISHED"):
    return {
        **_row(boundary, status),
        "universe_version": "BR1-BREADTH-UNIVERSE-v2-40",
        "source_policy_version": "BR1-SOURCE-POLICY-v2-GATE-ONLY",
        "formula_version": "BR1-BREADTH-FORMULA-v1",
        "normalizer_version": "BR1-CANDLE-NORMALIZER-v2",
        "cohort_version": "BR1-COHORT-v2-40-1D",
        "breadth_score": "62.5",
        "pct_above_ema20": "70",
        "pct_above_ema50": "60",
        "pct_above_ema200": "50",
        "data_quality_score": "100",
        "data_quality_label": "HIGH",
        "structural_coverage": "1",
        "component_coverage": "1",
        "btc_close": "100",
        "eth_close": "10",
        "universe_size": 40,
        "cohort_denominator": 40,
        "scanner": [],
    }


def test_dashboard_history_is_anchored_to_latest_published_boundary_not_page_clock():
    bundle = load_contract_bundle(Path("config/v2"), bundle="v2-40")
    store = InMemorySnapshotStore()
    sep2 = datetime(2026, 9, 2, tzinfo=UTC)
    sep3 = datetime(2026, 9, 3, tzinfo=UTC)
    store.put(_dashboard_row(sep2))
    store.put(_dashboard_row(sep3))
    reader = FirestoreReadOnlyQueryService(store, bundle)
    view = reader.dashboard("1d", now=datetime(2026, 9, 3, 21, 30, tzinfo=UTC), history_window_days=1)
    assert [row.candle_time for row in view.history] == [sep2, sep3]
    # Freshness is still evaluated against the real page clock's expected
    # completed daily boundary, independently of the historical anchor.
    assert view.expected_boundary == sep3
    assert view.ui_state == "CURRENT"


def test_readiness_path_does_not_add_research_writes_or_change_live_identity():
    source = Path("app_v2.py").read_text(encoding="utf-8")
    assert ".put(" not in source
    series = json.loads(Path("config/v2/series/br1-live-v2-40-candidate.yaml").read_text(encoding="utf-8"))
    assert series["series_version"] == "BR1-LIVE-v2-40-CANDIDATE"
    assert "RETROSPECTIVE" not in source
