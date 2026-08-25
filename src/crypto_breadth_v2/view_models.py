"""UI-neutral immutable view models shared by PostgreSQL and Firestore readers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class SnapshotView:
    snapshot_id: str
    timeframe: str
    candle_time: datetime
    status: str
    breadth_score: Decimal | None
    pct_above_ema20: Decimal | None
    pct_above_ema50: Decimal | None
    pct_above_ema200: Decimal | None
    data_quality_score: Decimal
    data_quality_label: str
    structural_coverage: Decimal
    component_coverage: Decimal
    btc_close: Decimal | None
    eth_close: Decimal | None
    universe_size: int
    cohort_size: int
    rejection_reason: str | None
    computed_at: datetime
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class ScannerView:
    asset_id: str
    symbol: str
    display_name: str
    candle_time: datetime
    price: Decimal | None
    ema20: Decimal | None
    ema50: Decimal | None
    ema200: Decimal | None
    state20: str
    state50: str
    state200: str
    included_in_breadth: bool


@dataclass(frozen=True)
class DashboardView:
    timeframe: str
    expected_boundary: datetime
    ui_state: str
    latest: SnapshotView | None
    last_known_good: SnapshotView | None
    age: timedelta | None
    latest_failure: Mapping[str, Any] | None
    history: tuple[SnapshotView, ...]
    scanner: tuple[ScannerView, ...]
