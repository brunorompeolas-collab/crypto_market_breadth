from datetime import datetime, timezone
from decimal import Decimal

from crypto_breadth_v2.ema_genesis_audit import (
    MemberSeries,
    per_asset_genesis_sensitivity,
)
from crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc


def _series(ema: str) -> MemberSeries:
    boundary = datetime(2026, 1, 2, tzinfo=UTC)
    target_open = datetime(2026, 1, 1, tzinfo=UTC)
    value = Decimal(ema)
    return MemberSeries(
        closes={boundary: Decimal("10")},
        emas={20: {target_open: value}, 50: {target_open: value}, 200: {target_open: value}},
    )


def test_per_asset_genesis_summary_reports_absolute_relative_and_state_changes():
    boundary = datetime(2026, 1, 2, tzinfo=UTC)
    summaries, ranked = per_asset_genesis_sensitivity(
        {"asset": _series("9")},
        {"asset": _series("11")},
        asset_ids=("asset",),
        boundaries=(boundary,),
        timeframe=Timeframe.DAILY,
    )
    row = summaries[0]
    assert row["periods"]["20"]["mean_absolute_difference"] == "2"
    assert row["periods"]["20"]["mean_relative_difference"] == str(Decimal(2) / Decimal(11))
    assert row["state_changes"]["20"] == 1
    assert row["state_changes"]["50"] == 1
    assert row["state_changes"]["200"] == 1
    assert ranked[0]["asset_id"] == "asset"

