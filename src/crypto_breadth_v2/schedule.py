"""Operational shadow schedule declarations (no scheduler activation)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class ShadowSchedule:
    """Recommended post-boundary offsets for an external job runner."""

    four_hour_delay: timedelta = timedelta(minutes=10)
    daily_delay: timedelta = timedelta(minutes=15)
    weekly_delay: timedelta = timedelta(minutes=25)
    recovery_interval: timedelta = timedelta(hours=1)


SCHEDULE = ShadowSchedule()

