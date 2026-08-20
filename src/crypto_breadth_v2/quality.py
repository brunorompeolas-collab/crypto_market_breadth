"""Exact Data Quality and publication-gate calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from enum import Enum


class QualityLabel(str, Enum):
    HIGH = "HIGH"
    ACCEPTABLE = "ACCEPTABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class DataQualityResult:
    score: Decimal
    structural_coverage: Decimal
    component_coverage: Decimal
    publishable: bool
    label: QualityLabel


def calculate_data_quality(
    *,
    universe_size: int,
    cohort_size: int,
    valid_ema20: int,
    valid_ema50: int,
    valid_ema200: int,
    fresh: bool,
    aligned: bool,
    last_known_good_exists: bool,
    minimum_structural_coverage: Decimal = Decimal("0.80"),
) -> DataQualityResult:
    if universe_size <= 0 or cohort_size <= 0 or cohort_size > universe_size:
        raise ValueError("Universe and cohort sizes are inconsistent")
    counts = (valid_ema20, valid_ema50, valid_ema200)
    if any(count < 0 or count > cohort_size for count in counts):
        raise ValueError("Valid component counts must be within the frozen cohort")

    with localcontext() as context:
        context.prec = 50
        structural = Decimal(cohort_size) / Decimal(universe_size)
        component = Decimal(min(counts)) / Decimal(cohort_size)
        freshness = Decimal("1") if fresh else Decimal("0")
        alignment = Decimal("1") if aligned else Decimal("0")
        score = (
            Decimal("100") * structural * component * freshness * alignment
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    publishable = (
        structural >= minimum_structural_coverage
        and component == Decimal("1")
        and fresh
        and aligned
    )
    if publishable and score == Decimal("100.0"):
        label = QualityLabel.HIGH
    elif publishable:
        label = QualityLabel.ACCEPTABLE
    elif last_known_good_exists:
        label = QualityLabel.DEGRADED
    else:
        label = QualityLabel.UNAVAILABLE
    return DataQualityResult(score, structural, component, publishable, label)
