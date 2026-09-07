from datetime import datetime, timezone
from decimal import Decimal

from crypto_breadth_v2.canonical_genesis_freeze import _invariance, _sequence
from crypto_breadth_v2.ema_genesis_audit import MemberSeries
from crypto_breadth_v2.timeframes import Timeframe


def test_sequence_inclusive_utc_boundaries():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 3, tzinfo=timezone.utc)
    assert len(_sequence(start, end, Timeframe.DAILY)) == 3


def test_history_views_slice_one_canonical_ema_sequence():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    boundaries = _sequence(start, datetime(2026, 1, 1, tzinfo=timezone.utc), Timeframe.DAILY)
    closes = {boundary: Decimal("100") for boundary in boundaries}
    emas = {period: {boundary - __import__("datetime").timedelta(days=1): Decimal("100") for boundary in boundaries} for period in (20, 50, 200)}
    series = {"bitcoin": MemberSeries(closes=closes, emas=emas)}
    result = _invariance(series, boundaries, ("1m", "6m", "1y", "Total"), timeframe=Timeframe.DAILY)
    assert all(item["ema_differences"] == 0 and item["state_disagreements"] == 0 for item in result.values())
