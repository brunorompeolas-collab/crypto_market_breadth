"""Compatibility exports for the read-only v2 UI view models.

The deployed dashboard uses :mod:`firestore_query`; this module deliberately
contains no provider or PostgreSQL imports and exists only for stable imports
used by UI tests and downstream v2 consumers.
"""

from .view_models import DashboardView, ScannerView, SnapshotView

__all__ = ["DashboardView", "ScannerView", "SnapshotView"]
