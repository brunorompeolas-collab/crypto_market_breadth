from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.candles import CanonicalCandle
from crypto_breadth_v2.firestore import (
    InMemorySnapshotStore,
    SnapshotConflictError,
    document_path,
    snapshot_document,
)
from crypto_breadth_v2.firestore_query import FirestoreReadOnlyQueryService
from crypto_breadth_v2.reconcile import Reconciler
from crypto_breadth_v2.providers.gate import GateCandleEnvelope, load_gate_mappings
from crypto_breadth_v2.timeframes import Timeframe, close_time, duration


UTC = timezone.utc
BUNDLE = load_contract_bundle(__import__("pathlib").Path("config/v2"), bundle="v2-40")
EXCLUSIONS = {"4h": frozenset(), "1d": frozenset(), "1w": frozenset({"the-open-network", "bittensor", "sui", "hyperliquid", "ondo-finance"})}


def published(boundary):
    return {
        "boundary": boundary,
        "computed_at": boundary,
        "series_version": "BR1-LIVE-v2-40-CANDIDATE",
        "timeframe": "4h",
        "status": "PUBLISHED",
    }


def test_snapshot_key_and_decimal_payload_are_exact_and_idempotent():
    store = InMemorySnapshotStore()
    boundary = datetime(2026, 8, 24, 8, tzinfo=UTC)
    document = snapshot_document(
        boundary=boundary,
        computed_at=boundary,
        series_version="BR1-LIVE-v2-40-CANDIDATE",
        universe_version="BR1-BREADTH-UNIVERSE-v2-40",
        source_policy_version="BR1-SOURCE-POLICY-v2-GATE-ONLY",
        formula_version="BR1-BREADTH-FORMULA-v1",
        normalizer_version="BR1-CANDLE-NORMALIZER-v2",
        timeframe="4h",
        status="PUBLISHED",
        breadth_score=Decimal("62.500000"),
        pct_above_ema20=Decimal("70.000000"),
        pct_above_ema50=Decimal("60.000000"),
        pct_above_ema200=Decimal("50.000000"),
        data_quality_score=Decimal("100.0"),
        data_quality_label="HIGH",
        structural_coverage=Decimal("1"),
        component_coverage=Decimal("1"),
        btc_close=Decimal("100.123456789012345678"),
        eth_close=Decimal("10"),
        universe_size=40,
        cohort_denominator=40,
        members=[{"asset_id": "bitcoin", "state20": "ABOVE"}],
        source={"source_id": "gate-spot-usdt"},
        job_sha="test",
    )
    path = store.put(document)
    assert path == document_path("BR1-LIVE-v2-40-CANDIDATE", "4h", boundary)
    assert store.put(document) == path
    assert store.get("BR1-LIVE-v2-40-CANDIDATE", "4h", boundary)["btc_close"] == "100.123456789012345678"
    conflict = dict(document, breadth_score=Decimal("62.6"))
    with pytest.raises(SnapshotConflictError):
        store.put(conflict)


def test_reconcile_plans_multiple_missing_boundaries_in_order():
    store = InMemorySnapshotStore()
    store.put(published(datetime(2026, 8, 24, 0, tzinfo=UTC)))
    fake = SimpleNamespace(stats=SimpleNamespace(http_calls=0))
    reconciler = Reconciler(
        store,
        fake,
        BUNDLE,
        cohort_exclusions=EXCLUSIONS,
        now=datetime(2026, 8, 24, 12, 1, tzinfo=UTC),
        job_sha="test",
    )
    assert reconciler.due_boundaries(Timeframe.FOUR_HOUR) == (
        datetime(2026, 8, 24, 4, tzinfo=UTC),
        datetime(2026, 8, 24, 8, tzinfo=UTC),
        datetime(2026, 8, 24, 12, tzinfo=UTC),
    )


def test_provider_failure_writes_no_partial_snapshot():
    class FailingGate:
        stats = SimpleNamespace(http_calls=0)

        def fetch_range(self, *args, **kwargs):
            self.stats.http_calls += 1
            raise RuntimeError("simulated Gate outage")

    store = InMemorySnapshotStore()
    report = Reconciler(
        store,
        FailingGate(),
        BUNDLE,
        cohort_exclusions=EXCLUSIONS,
        now=datetime(2026, 8, 24, 12, 37, tzinfo=UTC),
        job_sha="test",
    ).run(max_boundaries=1, timeframes=[Timeframe.FOUR_HOUR])
    assert report.results[0].status == "FAILED"
    assert store.history("BR1-LIVE-v2-40-CANDIDATE", "4h") == ()


def test_gate_fixture_to_firestore_snapshot_and_indicator_compute():
    mappings = load_gate_mappings(BUNDLE)

    class FixtureGate:
        def __init__(self):
            self.stats = SimpleNamespace(http_calls=0)

        def fetch_range(self, symbol, *, timeframe, start, end, as_of):
            self.stats.http_calls += 1
            mapping = mappings[symbol]
            values = []
            cursor = start
            while cursor < end:
                close = Decimal("100") + Decimal(len(values)) / Decimal("10")
                candle = CanonicalCandle(
                    asset_id=mapping.canonical_id,
                    timeframe=timeframe,
                    open_time=cursor,
                    close_time=close_time(cursor, timeframe),
                    open=close,
                    high=close + Decimal("1"),
                    low=close - Decimal("1"),
                    close=close,
                    base_volume=Decimal("1"),
                    quote_volume=Decimal("1"),
                    trade_count=1,
                    provider_complete=True,
                )
                values.append(GateCandleEnvelope(mapping, candle, f"fixture-{symbol}-{cursor.isoformat()}", ()))
                cursor += duration(timeframe)
            return tuple(values)

    store = InMemorySnapshotStore()
    boundary = datetime(2026, 8, 24, 12, tzinfo=UTC)
    gate = FixtureGate()
    report = Reconciler(
        store,
        gate,
        BUNDLE,
        cohort_exclusions=EXCLUSIONS,
        now=datetime(2026, 8, 24, 12, 37, tzinfo=UTC),
        job_sha="fixture-sha",
    ).run(start=boundary, max_boundaries=1, timeframes=[Timeframe.FOUR_HOUR])
    assert report.results[0].status == "PUBLISHED"
    document = store.get("BR1-LIVE-v2-40-CANDIDATE", "4h", boundary)
    assert document["cohort_denominator"] == 40
    assert document["data_quality_score"] == "100.0"
    assert len(document["members"]) == 40
    assert all(member["state200"] in {"ABOVE", "BELOW"} for member in document["members"])
    calls = gate.stats.http_calls
    replay = Reconciler(
        store,
        gate,
        BUNDLE,
        cohort_exclusions=EXCLUSIONS,
        now=datetime(2026, 8, 24, 12, 37, tzinfo=UTC),
        job_sha="fixture-sha",
    ).run(start=boundary, max_boundaries=1, timeframes=[Timeframe.FOUR_HOUR])
    assert replay.results[0].status == "SKIPPED"
    assert gate.stats.http_calls == calls


def test_replay_skips_existing_boundary_without_provider_call():
    class NoCalls:
        stats = SimpleNamespace(http_calls=0)

        def fetch_range(self, *args, **kwargs):
            raise AssertionError("provider must not be called for a replay")

    store = InMemorySnapshotStore()
    boundary = datetime(2026, 8, 24, 8, tzinfo=UTC)
    store.put(published(boundary))
    report = Reconciler(
        store,
        NoCalls(),
        BUNDLE,
        cohort_exclusions=EXCLUSIONS,
        now=datetime(2026, 8, 24, 8, 37, tzinfo=UTC),
        job_sha="test",
    ).run(start=boundary, max_boundaries=1, timeframes=[Timeframe.FOUR_HOUR])
    assert report.results[0].status == "SKIPPED"
    assert report.results[0].skipped_existing is True


def test_firestore_query_exposes_stale_last_known_good_and_scanner():
    store = InMemorySnapshotStore()
    boundary = datetime(2026, 8, 24, 8, tzinfo=UTC)
    store.put(dict(published(boundary), computed_at=boundary, universe_version="BR1-BREADTH-UNIVERSE-v2-40", source_policy_version="BR1-SOURCE-POLICY-v2-GATE-ONLY", formula_version="BR1-BREADTH-FORMULA-v1", normalizer_version="BR1-CANDLE-NORMALIZER-v2", data_quality_score="100.0", data_quality_label="HIGH", structural_coverage="1", component_coverage="1", breadth_score="62.5", pct_above_ema20="70", pct_above_ema50="60", pct_above_ema200="50", btc_close="100", eth_close="10", universe_size=40, cohort_denominator=40, members=[], scanner=[]))
    view = FirestoreReadOnlyQueryService(store, BUNDLE).dashboard("4h", now=datetime(2026, 8, 24, 12, 37, tzinfo=UTC))
    assert view.ui_state == "STALE"
    assert view.last_known_good is not None
    assert view.last_known_good.breadth_score == Decimal("62.5")
