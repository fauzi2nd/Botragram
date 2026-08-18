"""Typed causes for an unsafe LIVE portfolio recovery result."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["LivePortfolioRecoveryUnsafeReason"]


@unique
class LivePortfolioRecoveryUnsafeReason(BaseEnum):
    """Identify the known safety boundary that stopped portfolio recovery."""

    PORTFOLIO_SYNC_FAILED = "portfolio_sync_failed"
    UNKNOWN_POSITION_METADATA = "unknown_position_metadata"
    POSITION_PERSISTENCE_FAILED = "position_persistence_failed"
    PROTECTION_FAILED = "protection_failed"
