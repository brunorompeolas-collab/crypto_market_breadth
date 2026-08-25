from decimal import Decimal

from crypto_breadth_v2.breadth import MemberSignals, calculate_breadth
from crypto_breadth_v2.cohort import FrozenCohort
from crypto_breadth_v2.domain import Availability, ScannerState, scanner_state
from crypto_breadth_v2.quality import QualityLabel, calculate_data_quality


def signals(s20, s50, s200):
    return MemberSignals(s20, s50, s200)


def test_scanner_equality_is_below_and_unavailable_is_distinct():
    assert scanner_state(Decimal("10"), Decimal("10")) is ScannerState.BELOW
    assert scanner_state(Decimal("10.0001"), Decimal("10")) is ScannerState.ABOVE
    assert scanner_state(None, Decimal("10")) is ScannerState.UNAVAILABLE
    assert scanner_state(Decimal("10"), None) is ScannerState.UNAVAILABLE
    assert ScannerState.UNAVAILABLE is not ScannerState.BELOW


def test_hand_calculated_breadth_uses_20_30_50_weights():
    cohort = FrozenCohort.create(universe_size=5, asset_ids=("a", "b", "c", "d"))
    state = {
        "a": signals(ScannerState.ABOVE, ScannerState.ABOVE, ScannerState.ABOVE),
        "b": signals(ScannerState.ABOVE, ScannerState.ABOVE, ScannerState.BELOW),
        "c": signals(ScannerState.BELOW, ScannerState.ABOVE, ScannerState.BELOW),
        "d": signals(ScannerState.BELOW, ScannerState.BELOW, ScannerState.BELOW),
    }
    result = calculate_breadth(cohort, state)
    assert result.status is Availability.AVAILABLE
    assert result.denominator == 4
    assert result.numerators == {20: 2, 50: 3, 200: 1}
    assert result.percentages == {
        20: Decimal("50"),
        50: Decimal("75"),
        200: Decimal("25"),
    }
    assert result.score == Decimal("45.00")


def test_missing_component_makes_entire_composite_unavailable_not_zero():
    cohort = FrozenCohort.create(universe_size=2, asset_ids=("a", "b"))
    state = {
        "a": signals(ScannerState.ABOVE, ScannerState.ABOVE, ScannerState.ABOVE),
        "b": signals(ScannerState.ABOVE, ScannerState.UNAVAILABLE, ScannerState.BELOW),
    }
    result = calculate_breadth(cohort, state)
    assert result.status is Availability.UNAVAILABLE
    assert result.numerators is None
    assert result.percentages is None
    assert result.score is None
    assert result.unavailable_assets == ("b",)


def test_missing_member_does_not_reduce_frozen_denominator():
    cohort = FrozenCohort.create(universe_size=5, asset_ids=("a", "b", "c", "d"))
    state = {
        asset: signals(ScannerState.ABOVE, ScannerState.ABOVE, ScannerState.ABOVE)
        for asset in ("a", "b", "c")
    }
    result = calculate_breadth(cohort, state)
    assert result.denominator == 4
    assert result.status is Availability.UNAVAILABLE
    assert result.unavailable_assets == ("d",)


def test_data_quality_accepts_complete_80_percent_structural_cohort():
    result = calculate_data_quality(
        universe_size=50,
        cohort_size=40,
        valid_ema20=40,
        valid_ema50=40,
        valid_ema200=40,
        fresh=True,
        aligned=True,
        last_known_good_exists=False,
    )
    assert result.structural_coverage == Decimal("0.8")
    assert result.component_coverage == Decimal("1")
    assert result.score == Decimal("80.0")
    assert result.publishable
    assert result.label is QualityLabel.ACCEPTABLE


def test_data_quality_requires_100_percent_runtime_component_coverage():
    result = calculate_data_quality(
        universe_size=50,
        cohort_size=40,
        valid_ema20=40,
        valid_ema50=40,
        valid_ema200=39,
        fresh=True,
        aligned=True,
        last_known_good_exists=True,
    )
    assert result.score == Decimal("78.0")
    assert not result.publishable
    assert result.label is QualityLabel.DEGRADED


def test_stale_or_misaligned_quality_is_zero_and_unavailable_without_last_good():
    stale = calculate_data_quality(
        universe_size=50,
        cohort_size=50,
        valid_ema20=50,
        valid_ema50=50,
        valid_ema200=50,
        fresh=False,
        aligned=True,
        last_known_good_exists=False,
    )
    assert stale.score == Decimal("0.0")
    assert stale.label is QualityLabel.UNAVAILABLE
