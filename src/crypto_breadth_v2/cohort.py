"""Frozen structural cohort contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class FrozenCohort:
    universe_size: int
    asset_ids: tuple[str, ...]
    minimum_structural_coverage: Decimal = Decimal("0.80")

    @classmethod
    def create(
        cls,
        *,
        universe_size: int,
        asset_ids: Iterable[str],
        minimum_structural_coverage: Decimal = Decimal("0.80"),
    ) -> "FrozenCohort":
        frozen_ids = tuple(asset_ids)
        cohort = cls(universe_size, frozen_ids, minimum_structural_coverage)
        cohort.validate()
        return cohort

    @property
    def denominator(self) -> int:
        return len(self.asset_ids)

    @property
    def structural_coverage(self) -> Decimal:
        return Decimal(self.denominator) / Decimal(self.universe_size)

    def validate(self) -> None:
        if self.universe_size <= 0:
            raise ValueError("Universe size must be positive")
        if not self.asset_ids or len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("Cohort asset IDs must be present and unique")
        if self.denominator > self.universe_size:
            raise ValueError("Cohort cannot exceed its universe")
        if self.structural_coverage < self.minimum_structural_coverage:
            raise ValueError("Cohort does not meet minimum structural coverage")
