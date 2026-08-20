"""Shared immutable value objects for the pure v2 core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    WARMUP = "WARMUP"
    UNAVAILABLE = "UNAVAILABLE"
    GAP_BLOCKED = "GAP_BLOCKED"


class ScannerState(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class PricePoint:
    open_time: datetime
    close: Optional[Decimal]


def scanner_state(close: Optional[Decimal], ema: Optional[Decimal]) -> ScannerState:
    if close is None or ema is None:
        return ScannerState.UNAVAILABLE
    return ScannerState.ABOVE if close > ema else ScannerState.BELOW
