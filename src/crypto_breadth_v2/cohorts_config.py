"""Frozen v2-40 cohort identity used by the stateless production reconciler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .contracts import ContractError


COHORT_CONTRACT_VERSION = "BR1-LIVE-v2-40-COHORTS"


def load_frozen_cohorts(path: Path, *, series_version: str) -> Mapping[str, frozenset[str]]:
    """Load the immutable cohort decision without deriving membership at runtime."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"Cannot load frozen cohort contract {path}: {exc}") from exc
    if document.get("version") != COHORT_CONTRACT_VERSION or document.get("series_version") != series_version:
        raise ContractError("Frozen cohort series does not match the candidate series")
    excluded = set(document.get("weekly_excluded_asset_ids", []))
    expected = {"4h": 40, "1d": 40, "1w": 35}
    if document.get("expected_denominators") != expected or len(excluded) != 5:
        raise ContractError("Frozen v2-40 cohort contract has unexpected denominators")
    return {
        "4h": frozenset(),
        "1d": frozenset(),
        "1w": frozenset(excluded),
    }


def included_asset_ids(
    asset_ids: tuple[str, ...],
    exclusions: Mapping[str, frozenset[str]],
    timeframe: str,
) -> tuple[str, ...]:
    excluded = exclusions[timeframe]
    return tuple(asset_id for asset_id in asset_ids if asset_id not in excluded)
