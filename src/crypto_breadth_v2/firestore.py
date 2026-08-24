"""Small Firestore result-store boundary for the production dashboard.

Firestore is deliberately used only for immutable calculated snapshots.  The
Gate adapter and all quantitative work stay outside this module, which keeps
the Streamlit reader incapable of making provider calls or mutating state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from threading import RLock
from typing import Any, Iterable, Mapping, Protocol


UTC = timezone.utc


class SnapshotConflictError(RuntimeError):
    """The deterministic key already contains a different immutable payload."""


class SnapshotStore(Protocol):
    def get(self, series_version: str, timeframe: str, boundary: datetime) -> Mapping[str, Any] | None: ...
    def put(self, document: Mapping[str, Any]) -> str: ...
    def latest(self, series_version: str, timeframe: str, *, status: str | None = None) -> Mapping[str, Any] | None: ...
    def history(self, series_version: str, timeframe: str) -> tuple[Mapping[str, Any], ...]: ...


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("Firestore snapshot timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


def boundary_key(boundary: datetime) -> str:
    return require_utc(boundary).strftime("%Y%m%dT%H%M%SZ")


def collection_name(timeframe: str) -> str:
    if timeframe not in {"4h", "1d", "1w"}:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return f"snapshots_{timeframe}"


def document_path(series_version: str, timeframe: str, boundary: datetime) -> str:
    return f"breadth_series/{series_version}/{collection_name(timeframe)}/{boundary_key(boundary)}"


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return require_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def canonical_payload(value: Mapping[str, Any]) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalise_document(document: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(_canonical(document))
    boundary = result.get("boundary")
    if not isinstance(boundary, str):
        raise ValueError("snapshot boundary is required")
    if not result.get("series_version") or result.get("timeframe") not in {"4h", "1d", "1w"}:
        raise ValueError("snapshot series_version and timeframe are required")
    result["document_id"] = boundary_key(datetime.fromisoformat(boundary.replace("Z", "+00:00")))
    result["document_path"] = document_path(result["series_version"], result["timeframe"], datetime.fromisoformat(boundary.replace("Z", "+00:00")))
    return result


@dataclass
class InMemorySnapshotStore:
    """Isolated Firestore-compatible store used by tests and local dry runs."""

    _documents: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self._documents is None:
            self._documents = {}
        self._lock = RLock()

    @property
    def documents(self) -> dict[str, dict[str, Any]]:
        return self._documents

    def get(self, series_version: str, timeframe: str, boundary: datetime) -> Mapping[str, Any] | None:
        path = document_path(series_version, timeframe, boundary)
        with self._lock:
            value = self._documents.get(path)
            return deepcopy(value) if value is not None else None

    def put(self, document: Mapping[str, Any]) -> str:
        normalised = _normalise_document(document)
        path = normalised["document_path"]
        with self._lock:
            existing = self._documents.get(path)
            if existing is not None:
                if canonical_payload(existing) != canonical_payload(normalised):
                    raise SnapshotConflictError(f"conflicting immutable snapshot at {path}")
                return path
            self._documents[path] = deepcopy(normalised)
        return path

    def latest(self, series_version: str, timeframe: str, *, status: str | None = None) -> Mapping[str, Any] | None:
        rows = [
            row for row in self._documents.values()
            if row.get("series_version") == series_version
            and row.get("timeframe") == timeframe
            and (status is None or row.get("status") == status)
        ]
        if not rows:
            return None
        return deepcopy(max(rows, key=lambda row: row["boundary"]))

    def history(self, series_version: str, timeframe: str) -> tuple[Mapping[str, Any], ...]:
        rows = [
            deepcopy(row) for row in self._documents.values()
            if row.get("series_version") == series_version and row.get("timeframe") == timeframe and row.get("status") == "PUBLISHED"
        ]
        return tuple(sorted(rows, key=lambda row: row["boundary"]))


class FirestoreSnapshotStore:
    """Production adapter backed by ``google-cloud-firestore``.

    The dependency is imported lazily so quantitative tests and local UI tests
    do not require Google credentials or a network connection.
    """

    def __init__(self, client: Any):
        self.client = client

    @classmethod
    def from_environment(cls) -> "FirestoreSnapshotStore":
        try:
            from google.cloud import firestore
        except ImportError as exc:  # pragma: no cover - exercised in deployment only
            raise RuntimeError("google-cloud-firestore is required for production reconciliation") from exc

        project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        credentials_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        kwargs: dict[str, Any] = {}
        if project_id:
            kwargs["project"] = project_id
        if credentials_json and not os.environ.get("FIRESTORE_EMULATOR_HOST"):
            from google.oauth2 import service_account
            kwargs["credentials"] = service_account.Credentials.from_service_account_info(json.loads(credentials_json))
        return cls(firestore.Client(**kwargs))

    def _reference(self, series_version: str, timeframe: str, boundary: datetime) -> Any:
        parts = document_path(series_version, timeframe, boundary).split("/")
        return self.client.collection(parts[0]).document(parts[1]).collection(parts[2]).document(parts[3])

    def get(self, series_version: str, timeframe: str, boundary: datetime) -> Mapping[str, Any] | None:
        snapshot = self._reference(series_version, timeframe, boundary).get()
        return snapshot.to_dict() if snapshot.exists else None

    def put(self, document: Mapping[str, Any]) -> str:
        normalised = _normalise_document(document)
        reference = self._reference(normalised["series_version"], normalised["timeframe"], datetime.fromisoformat(normalised["boundary"].replace("Z", "+00:00")))
        existing = reference.get()
        if existing.exists:
            current = existing.to_dict() or {}
            if canonical_payload(current) != canonical_payload(normalised):
                raise SnapshotConflictError(f"conflicting immutable snapshot at {normalised['document_path']}")
            return normalised["document_path"]
        # create() makes a concurrent first write fail instead of silently
        # replacing an immutable result.  Replay remains a no-op above.
        try:
            reference.create(normalised)
        except Exception as exc:  # google.api_core.exceptions.AlreadyExists without hard dependency
            if exc.__class__.__name__ != "AlreadyExists":
                raise
            current = reference.get().to_dict() or {}
            if canonical_payload(current) != canonical_payload(normalised):
                raise SnapshotConflictError(f"conflicting immutable snapshot at {normalised['document_path']}") from exc
        return normalised["document_path"]

    def latest(self, series_version: str, timeframe: str, *, status: str | None = None) -> Mapping[str, Any] | None:
        query = self.client.collection("breadth_series").document(series_version).collection(collection_name(timeframe)).order_by("boundary", direction="DESCENDING").limit(50)
        for snapshot in query.stream():
            row = snapshot.to_dict() or {}
            if status is None or row.get("status") == status:
                return row
        return None

    def history(self, series_version: str, timeframe: str) -> tuple[Mapping[str, Any], ...]:
        query = self.client.collection("breadth_series").document(series_version).collection(collection_name(timeframe)).order_by("boundary")
        return tuple((snapshot.to_dict() or {}) for snapshot in query.stream() if (snapshot.to_dict() or {}).get("status") == "PUBLISHED")


def snapshot_document(
    *,
    boundary: datetime,
    computed_at: datetime,
    series_version: str,
    universe_version: str,
    source_policy_version: str,
    formula_version: str,
    normalizer_version: str,
    timeframe: str,
    status: str,
    breadth_score: Decimal | None,
    pct_above_ema20: Decimal | None,
    pct_above_ema50: Decimal | None,
    pct_above_ema200: Decimal | None,
    data_quality_score: Decimal,
    data_quality_label: str,
    structural_coverage: Decimal,
    component_coverage: Decimal,
    btc_close: Decimal | None,
    eth_close: Decimal | None,
    universe_size: int,
    cohort_denominator: int,
    members: Iterable[Mapping[str, Any]],
    source: Mapping[str, Any],
    job_sha: str,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    """Build the canonical Firestore output document with exact decimal strings."""
    return {
        "boundary": require_utc(boundary),
        "computed_at": require_utc(computed_at),
        "series_version": series_version,
        "universe_version": universe_version,
        "source_policy_version": source_policy_version,
        "formula_version": formula_version,
        "normalizer_version": normalizer_version,
        "timeframe": timeframe,
        "status": status,
        "breadth_score": breadth_score,
        "pct_above_ema20": pct_above_ema20,
        "pct_above_ema50": pct_above_ema50,
        "pct_above_ema200": pct_above_ema200,
        "data_quality_score": data_quality_score,
        "data_quality_label": data_quality_label,
        "structural_coverage": structural_coverage,
        "component_coverage": component_coverage,
        "btc_close": btc_close,
        "eth_close": eth_close,
        "cohort_denominator": cohort_denominator,
        "universe_size": universe_size,
        "members": list(members),
        "scanner": list(members),
        "source": dict(source),
        "job_sha": job_sha,
        "rejection_reason": rejection_reason,
    }
