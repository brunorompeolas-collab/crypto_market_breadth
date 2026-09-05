from datetime import datetime, timezone
from decimal import Decimal

from crypto_breadth_v2.research_validation import (
    CandidateSpec,
    compare_overlap,
    freeze_period,
)
from crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc


def test_freeze_period_uses_completed_boundary_and_exact_ema_warmup():
    as_of = datetime(2026, 9, 5, 10, 30, tzinfo=UTC)
    period = freeze_period(CandidateSpec("daily", Timeframe.DAILY, 365), as_of=as_of)
    assert period.latest_boundary == datetime(2026, 9, 5, tzinfo=UTC)
    assert period.output_start == datetime(2025, 9, 5, tzinfo=UTC)
    assert period.ema_warmup_start == datetime(2025, 2, 17, tzinfo=UTC)
    assert period.raw_close_start == datetime(2025, 2, 18, tzinfo=UTC)
    assert period.expected_output_count == 366
    assert period.expected_raw_count == 565


def test_freeze_period_uses_native_four_hour_count():
    as_of = datetime(2026, 9, 5, 10, 30, tzinfo=UTC)
    period = freeze_period(CandidateSpec("4h", Timeframe.FOUR_HOUR, 365), as_of=as_of)
    assert period.latest_boundary == datetime(2026, 9, 5, 8, tzinfo=UTC)
    assert period.output_start == datetime(2025, 9, 5, 8, tzinfo=UTC)
    assert period.expected_output_count == 2191
    assert period.expected_raw_count == 2390


def test_overlap_comparison_is_decimal_and_reports_regime_disagreement():
    a = [
        {"boundary": "2026-01-01T00:00:00Z", "breadth_score": "60", "pct_above_ema20": "50", "pct_above_ema50": "40", "pct_above_ema200": "30", "regime": "EXPANSION"},
        {"boundary": "2026-01-02T00:00:00Z", "breadth_score": "61", "pct_above_ema20": "51", "pct_above_ema50": "41", "pct_above_ema200": "31", "regime": "EXPANSION"},
    ]
    b = [
        {"boundary": "2026-01-01T00:00:00Z", "breadth_score": "59", "pct_above_ema20": "49", "pct_above_ema50": "39", "pct_above_ema200": "29", "regime": "NEUTRAL"},
        {"boundary": "2026-01-02T00:00:00Z", "breadth_score": "61", "pct_above_ema20": "51", "pct_above_ema50": "41", "pct_above_ema200": "31", "regime": "EXPANSION"},
    ]
    result = compare_overlap(a, b)
    assert result["common_observation_count"] == 2
    assert result["mean_absolute_breadth_score_difference"] == "0.5"
    assert result["maximum_absolute_breadth_score_difference"] == "1"
    assert result["regime_disagreement_count"] == 1
    assert Decimal(result["regime_disagreement_percentage"]) == Decimal("50")
