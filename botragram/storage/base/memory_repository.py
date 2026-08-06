"""
Botragram

Description:
    Shared infrastructure for in-memory repositories.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import asyncio
from datetime import datetime

__all__ = [
    "BaseMemoryRepository",
]


# =============================================================================
# Constants
# =============================================================================
_LIMIT_ERROR_TEMPLATE = "{label} limit must be greater than zero"
_TIME_RANGE_ERROR_TEMPLATE = "{label} start time must not be after end time"
_SYMBOL_ERROR = "Trading symbol must not be empty"
_IDENTIFIER_ERROR_TEMPLATE = "{label} identifier must not be empty"


# =============================================================================
# Base Repository Classes
# =============================================================================
class BaseMemoryRepository:
    """Provide shared infrastructure for in-memory repositories.

    This class intentionally contains no CRUD behavior because each repository
    has a different identity key, filtering model, and persistence contract.
    """

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        """Initialize repository synchronization infrastructure."""
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Normalized uppercase symbol.

        Raises:
            ValueError: If the symbol is empty.
        """
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError(_SYMBOL_ERROR)

        return normalized_symbol

    @staticmethod
    def _normalize_identifier(
        identifier: str,
        *,
        label: str,
    ) -> str:
        """Normalize and validate an identifier.

        Args:
            identifier: Identifier value.
            label: Human-readable identifier category.

        Returns:
            Normalized identifier.

        Raises:
            ValueError: If the identifier or label is empty.
        """
        normalized_label = label.strip()

        if not normalized_label:
            raise ValueError("Identifier label must not be empty")

        normalized_identifier = identifier.strip()

        if not normalized_identifier:
            raise ValueError(
                _IDENTIFIER_ERROR_TEMPLATE.format(
                    label=normalized_label,
                )
            )

        return normalized_identifier

    @staticmethod
    def _validate_limit(
        limit: int,
        *,
        label: str,
    ) -> None:
        """Validate a repository query limit.

        Args:
            limit: Maximum number of records.
            label: Human-readable record category.

        Raises:
            ValueError: If the limit is not positive or the label is empty.
        """
        normalized_label = label.strip()

        if not normalized_label:
            raise ValueError("Limit label must not be empty")

        if limit <= 0:
            raise ValueError(
                _LIMIT_ERROR_TEMPLATE.format(
                    label=normalized_label,
                )
            )

    @staticmethod
    def _validate_time_range(
        *,
        start_time: datetime,
        end_time: datetime,
        label: str,
    ) -> None:
        """Validate an inclusive datetime range.

        Args:
            start_time: Inclusive starting boundary.
            end_time: Inclusive ending boundary.
            label: Human-readable record category.

        Raises:
            ValueError: If the range is invalid or the label is empty.
        """
        normalized_label = label.strip()

        if not normalized_label:
            raise ValueError("Time-range label must not be empty")

        if start_time > end_time:
            raise ValueError(
                _TIME_RANGE_ERROR_TEMPLATE.format(
                    label=normalized_label,
                )
            )
