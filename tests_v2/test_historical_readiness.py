from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from app_v2 import history_since_for_filter
from crypto_breadth_v2.firestore import FirestoreSnapshotStore, InMemorySnapshotStore


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
    client = _RecordingClient([_row(start), _row(end)])
    rows = FirestoreSnapshotStore(client).history(SERIES, "1d", since=start, until=end, limit=10)
    assert len(rows) == 2
    assert ("where", "boundary", ">=", "2026-08-02T00:00:00Z") in client.query.operations
    assert ("where", "boundary", "<=", "2026-08-03T00:00:00Z") in client.query.operations
    assert ("limit", 10) in client.query.operations
    assert any(op[0] == "order_by" and op[1] == "boundary" for op in client.query.operations)


def test_ui_window_translates_to_bounded_query_and_total_is_explicitly_unbounded():
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    assert history_since_for_filter(now, "1m") == now - timedelta(days=30)
    assert history_since_for_filter(now, "Total") is None


def test_readiness_path_does_not_add_research_writes_or_change_live_identity():
    source = Path("app_v2.py").read_text(encoding="utf-8")
    assert ".put(" not in source
    series = json.loads(Path("config/v2/series/br1-live-v2-40-candidate.yaml").read_text(encoding="utf-8"))
    assert series["series_version"] == "BR1-LIVE-v2-40-CANDIDATE"
    assert "RETROSPECTIVE" not in source
