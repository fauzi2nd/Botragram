"""Authoritative provenance for closed Botragram LIVE position lifecycles."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["ClosedPositionProvenance"]


@unique
class ClosedPositionProvenance(BaseEnum):
    """Identify the exchange evidence used to prove one lifecycle closure."""

    PROTECTION_ORDER = "protection_order"
    MANUAL_ORDER = "manual_order"
    RECOVERY_EMERGENCY_ORDER = "recovery_emergency_order"
