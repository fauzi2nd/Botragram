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
from decimal import Decimal

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

    @abstractmethod
    async def get_leverage(self) -> int | None:
        """Return the latest durable runtime leverage, if configured."""

    @abstractmethod
    async def save_leverage(self, *, leverage: int) -> None:
        """Atomically persist the active runtime leverage."""

    @abstractmethod
    async def get_trailing_stop(self) -> tuple[bool, Decimal, Decimal] | None:
        """Return the latest durable trailing stop settings (enabled, trigger, dist)."""

    @abstractmethod
    async def save_trailing_stop(
        self,
        *,
        enabled: bool,
        trigger_pct: Decimal,
        distance_pct: Decimal,
    ) -> None:
        """Atomically persist the active trailing stop settings."""
