"""
Botragram

Description:
    Persistence boundary for durable runtime settings.

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
from abc import ABC, abstractmethod

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import StrategyType

__all__ = ["RuntimeSettingsRepository"]


# =============================================================================
# Repository Interface
# =============================================================================
class RuntimeSettingsRepository(ABC):
    """Persist and restore runtime settings across process restarts."""

    __slots__ = ()

    @abstractmethod
    async def get_strategy(self) -> StrategyType | None:
        """Return the latest durable runtime strategy, if configured."""

    @abstractmethod
    async def save_strategy(self, *, strategy_type: StrategyType) -> None:
        """Atomically persist the active runtime strategy."""
