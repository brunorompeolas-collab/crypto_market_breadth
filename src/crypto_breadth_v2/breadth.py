"""Breadth Formula v1 with a fixed denominator and atomic availability."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Mapping, Optional

from .cohort import FrozenCohort
from .domain import Availability, ScannerState


WEIGHTS = {20: Decimal("0.20"), 50: Decimal("0.30"), 200: Decimal("0.50")}


@dataclass(frozen=True)
class MemberSignals:
    ema20: ScannerState
    ema50: ScannerState
    ema200: ScannerState

    def for_period(self, period: int) -> ScannerState:
        return {20: self.ema20, 50: self.ema50, 200: self.ema200}[period]


@dataclass(frozen=True)
class BreadthResult:
    status: Availability
    denominator: int
    numerators: Optional[Mapping[int, int]]
    percentages: Optional[Mapping[int, Decimal]]
    score: Optional[Decimal]
    unavailable_assets: tuple[str, ...]


def calculate_breadth(
    cohort: FrozenCohort, signals: Mapping[str, MemberSignals]
) -> BreadthResult:
    unavailable = []
    for asset_id in cohort.asset_ids:
        member = signals.get(asset_id)
        if member is None or any(
            member.for_period(period) is ScannerState.UNAVAILABLE
            for period in WEIGHTS
        ):
            unavailable.append(asset_id)
    if unavailable:
        return BreadthResult(
            status=Availability.UNAVAILABLE,
            denominator=cohort.denominator,
            numerators=None,
            percentages=None,
            score=None,
            unavailable_assets=tuple(unavailable),
        )

    numerators = {
        period: sum(
            1
            for asset_id in cohort.asset_ids
            if signals[asset_id].for_period(period) is ScannerState.ABOVE
        )
        for period in WEIGHTS
    }
    with localcontext() as context:
        context.prec = 50
        percentages = {
            period: Decimal(count) * Decimal("100") / Decimal(cohort.denominator)
            for period, count in numerators.items()
        }
        score = sum(
            (percentages[period] * weight for period, weight in WEIGHTS.items()),
            Decimal("0"),
        )
    return BreadthResult(
        status=Availability.AVAILABLE,
        denominator=cohort.denominator,
        numerators=numerators,
        percentages=percentages,
        score=score,
        unavailable_assets=(),
    )
