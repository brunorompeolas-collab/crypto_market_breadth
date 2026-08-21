from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.providers.gate import (
    GATE_MAX_CANDLES,
    GateCatalogueMismatch,
    GateCandleValidationError,
    GateClient,
    GateHttpResponse,
    GateInstrumentUnavailableError,
    GateMappingError,
    GateRateLimitError,
    GateRetryPolicy,
    GateSchemaError,
    GateServerError,
    GateTimeoutError,
    load_gate_mappings,
    verify_gate_catalogue,
)
from crypto_breadth_v2.timeframes import Timeframe


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests_v2" / "fixtures" / "gate"
UTC = timezone.utc


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def response(payload, *, status=200, headers=None):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return GateHttpResponse(status=status, headers=headers or {}, body=body)


class QueueTransport:
    def __init__(self, *items):
        self.items = deque(items)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, dict(params), timeout))
        item = self.items.popleft()
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture()
def mappings():
    bundle = load_contract_bundle(ROOT / "config" / "v2", bundle="v2-40")
    return load_gate_mappings(bundle)


def test_closed_4h_fixture_maps_exact_decimals_and_utc_boundaries(mappings):
    transport = QueueTransport(response(load_fixture("candles_4h_closed.json")))
    rows = GateClient(mappings, transport=transport).fetch_candles(
        "BTC",
        timeframe=Timeframe.FOUR_HOUR,
        as_of=datetime(2025, 1, 1, 4, tzinfo=UTC),
        limit=1,
    )
    assert len(rows) == 1
    candle = rows[0].candle
    assert candle.open_time == datetime(2025, 1, 1, 0, tzinfo=UTC)
    assert candle.close_time == datetime(2025, 1, 1, 4, tzinfo=UTC)
    assert candle.open == Decimal("12341.111111111111111111")
    assert candle.close == Decimal("12345.678901234567890123")
    assert candle.base_volume == Decimal("20.000000000000000001")
    assert candle.quote_volume == Decimal("246913.578024691357802468")


def test_closed_daily_fixture_uses_exclusive_midnight_close(mappings):
    transport = QueueTransport(response(load_fixture("candles_1d_closed.json")))
    candle = GateClient(mappings, transport=transport).fetch_candles(
        "BTC",
        timeframe=Timeframe.DAILY,
        as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
        limit=1,
    )[0].candle
    assert candle.open_time == datetime(2025, 1, 1, 0, tzinfo=UTC)
    assert candle.close_time == datetime(2025, 1, 2, 0, tzinfo=UTC)


def test_incomplete_candle_is_rejected_even_if_time_boundary_has_passed(mappings):
    transport = QueueTransport(response(load_fixture("candles_incomplete.json")))
    with pytest.raises(GateCandleValidationError, match="incomplete"):
        GateClient(mappings, transport=transport).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )


def test_future_candle_and_non_boundary_timestamp_are_rejected(mappings):
    row = load_fixture("candles_4h_closed.json")[0]
    future_transport = QueueTransport(response([row]))
    with pytest.raises(GateCandleValidationError, match="not completed"):
        GateClient(mappings, transport=future_transport).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 1, 3, 59, tzinfo=UTC),
            limit=1,
        )
    misaligned = row.copy()
    misaligned[0] = str(int(misaligned[0]) + 60)
    with pytest.raises(GateCandleValidationError, match="boundary"):
        GateClient(mappings, transport=QueueTransport(response([misaligned]))).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )


def test_ohlc_validation_rejects_impossible_high(mappings):
    row = load_fixture("candles_4h_closed.json")[0].copy()
    row[3] = "1"
    with pytest.raises(GateCandleValidationError, match="High"):
        GateClient(mappings, transport=QueueTransport(response([row]))).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )


def test_schema_change_malformed_json_and_empty_instrument_are_explicit(mappings):
    with pytest.raises(GateSchemaError, match="eight-string"):
        GateClient(mappings, transport=QueueTransport(response([["too", "short"]]))).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )
    with pytest.raises(GateSchemaError, match="UTF-8 JSON"):
        GateClient(mappings, transport=QueueTransport(response(b"not-json"))).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )
    with pytest.raises(GateInstrumentUnavailableError, match="no candles"):
        GateClient(mappings, transport=QueueTransport(response([]))).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )


def test_mapping_must_be_frozen_and_weekly_is_not_native_in_slice_3(mappings):
    client = GateClient(mappings, transport=QueueTransport())
    with pytest.raises(GateMappingError, match="No frozen"):
        client.fetch_candles(
            "NOT_A_SYMBOL",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )
    with pytest.raises(GateMappingError, match="only native 4h and 1d"):
        client.fetch_candles(
            "BTC",
            timeframe=Timeframe.WEEKLY,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )


def test_429_honors_retry_after_and_exhaustion_is_explicit(mappings):
    sleeps = []
    transport = QueueTransport(
        response({}, status=429, headers={"Retry-After": "2.5"}),
        response(load_fixture("candles_4h_closed.json")),
    )
    rows = GateClient(
        mappings,
        transport=transport,
        retry_policy=GateRetryPolicy(max_attempts=2),
        sleep=sleeps.append,
    ).fetch_candles(
        "BTC",
        timeframe=Timeframe.FOUR_HOUR,
        as_of=datetime(2025, 1, 2, tzinfo=UTC),
        limit=1,
    )
    assert len(rows) == 1
    assert sleeps == [2.5]

    exhausted = QueueTransport(response({}, status=429, headers={"Retry-After": "7"}))
    with pytest.raises(GateRateLimitError) as caught:
        GateClient(
            mappings,
            transport=exhausted,
            retry_policy=GateRetryPolicy(max_attempts=1),
        ).fetch_candles(
            "BTC",
            timeframe=Timeframe.FOUR_HOUR,
            as_of=datetime(2025, 1, 2, tzinfo=UTC),
            limit=1,
        )
    assert caught.value.retry_after == 7


def test_timeout_and_5xx_retry_then_fail(mappings):
    with pytest.raises(GateTimeoutError):
        GateClient(
            mappings,
            transport=QueueTransport(TimeoutError("fixture timeout")),
            retry_policy=GateRetryPolicy(max_attempts=1),
        ).fetch_candles(
            "BTC", timeframe=Timeframe.FOUR_HOUR, as_of=datetime(2025, 1, 2, tzinfo=UTC), limit=1
        )
    with pytest.raises(GateServerError, match="503"):
        GateClient(
            mappings,
            transport=QueueTransport(response({}, status=503)),
            retry_policy=GateRetryPolicy(max_attempts=1),
        ).fetch_candles(
            "BTC", timeframe=Timeframe.FOUR_HOUR, as_of=datetime(2025, 1, 2, tzinfo=UTC), limit=1
        )


def test_range_pagination_is_bounded_and_deduplicated(mappings):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    second_open = start + timedelta(hours=4 * GATE_MAX_CANDLES)

    def row(open_time, close):
        return [
            str(int(open_time.timestamp())),
            "10",
            close,
            "20",
            "1",
            "10",
            "1",
            "true",
        ]

    transport = QueueTransport(response([row(start, "11")]), response([row(second_open, "12")]))
    end = start + timedelta(hours=4 * (GATE_MAX_CANDLES + 1))
    rows = GateClient(mappings, transport=transport).fetch_range(
        "BTC",
        timeframe=Timeframe.FOUR_HOUR,
        start=start,
        end=end,
        as_of=end + timedelta(hours=4),
    )
    assert [item.candle.open_time for item in rows] == [start, second_open]
    assert len(transport.calls) == 2
    assert transport.calls[0][1]["from"] == int(start.timestamp())
    assert transport.calls[1][1]["from"] == int(second_open.timestamp())


def test_catalogue_fixture_covers_exact_40_and_detects_delisting(mappings):
    catalogue = load_fixture("catalogue_v2_40.json")
    instruments = verify_gate_catalogue(mappings, catalogue)
    assert len(instruments) == 40
    assert set(instruments) == {mapping.instrument for mapping in mappings.values()}

    changed = [dict(row) for row in catalogue]
    next(row for row in changed if row["id"] == "ZEC_USDT")["trade_status"] = "untradable"
    with pytest.raises(GateCatalogueMismatch, match="ZEC_USDT"):
        verify_gate_catalogue(mappings, changed)
