"""
Botragram

Description:
    In-memory persistence for runtime settings.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import StrategyType
from botragram.repositories import RuntimeSettingsRepository

__all__ = ["MemoryRuntimeSettingsRepository"]


# =============================================================================
# Memory Repository
# =============================================================================
class MemoryRuntimeSettingsRepository(RuntimeSettingsRepository):
    """In-memory runtime settings repository for testing."""

    __slots__ = ("_strategy_type", "_leverage", "_trailing_stop")

    def __init__(
        self,
        *,
        strategy_type: StrategyType | None = None,
        leverage: int | None = None,
        trailing_stop: tuple[bool, Decimal, Decimal] | None = None,
    ) -> None:
        """Initialize the repository with optional initial settings."""
        self._strategy_type = strategy_type
        self._leverage = leverage
        self._trailing_stop = trailing_stop

    async def get_strategy(self) -> StrategyType | None:
        """Return the current in-memory strategy, if configured."""
        return self._strategy_type

    async def save_strategy(self, *, strategy_type: StrategyType) -> None:
        """Persist the active runtime strategy in memory."""
        self._strategy_type = strategy_type

    async def get_leverage(self) -> int | None:
        """Return the current in-memory leverage, if configured."""
        return self._leverage

    async def save_leverage(self, *, leverage: int) -> None:
        """Persist the active runtime leverage in memory."""
        if isinstance(leverage, bool) or leverage <= 0:
            raise ValueError("Runtime leverage must be a positive integer")
        self._leverage = leverage

    async def get_trailing_stop(self) -> tuple[bool, Decimal, Decimal] | None:
        """Return the current in-memory trailing stop settings."""
        return self._trailing_stop

    async def save_trailing_stop(
        self,
        *,
        enabled: bool,
        trigger_pct: Decimal,
        distance_pct: Decimal,
    ) -> None:
        """Persist trailing stop settings in memory."""
        if not (Decimal("0") < trigger_pct < Decimal("1")):
            raise ValueError("Trailing stop trigger must be between 0 and 1 exclusive")
        if not (Decimal("0") < distance_pct < Decimal("1")):
            raise ValueError("Trailing stop distance must be between 0 and 1 exclusive")
        if distance_pct >= trigger_pct:
            raise ValueError(
                "Trailing stop distance must be strictly less than trigger"
            )
        self._trailing_stop = (enabled, trigger_pct, distance_pct)
