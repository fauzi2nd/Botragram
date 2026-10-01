"""Outcomes of one authoritative LIVE portfolio recovery pass."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["LivePortfolioRecoveryStatus"]


@unique
class LivePortfolioRecoveryStatus(BaseEnum):
    """Classify whether a LIVE portfolio is protected and runtime-manageable."""

    NO_POSITIONS = "no_positions"
    SINGLE_POSITION_SAFE = "single_position_safe"
    MULTIPLE_POSITIONS_SAFE = "multiple_positions_safe"
    UNSAFE = "unsafe"
