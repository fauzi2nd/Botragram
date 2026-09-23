"""
Botragram

Description:
    Unit tests for DiscoveryScanReport model validation.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import DiscoveryScanReport


def test_discovery_scan_report_creation() -> None:
    """Verify that DiscoveryScanReport holds truthful scan metadata."""
    report = DiscoveryScanReport(
        universe_size=184,
        scanned_count=184,
    )
    assert report.universe_size == 184
    assert report.scanned_count == 184
    assert report.signals == ()


def test_discovery_scan_report_rejects_negative_and_out_of_bounds() -> None:
    """Verify that DiscoveryScanReport rejects invalid bounds."""
    with pytest.raises(ValueError, match="non-negative integer"):
        DiscoveryScanReport(universe_size=-1, scanned_count=0)

    with pytest.raises(ValueError, match="non-negative integer"):
        DiscoveryScanReport(universe_size=10, scanned_count=-1)

    with pytest.raises(ValueError, match="cannot exceed universe size"):
        DiscoveryScanReport(universe_size=10, scanned_count=11)
