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

    __slots__ = ("_strategy_type", "_leverage", "_dynamic_leverage")

    def __init__(
        self,
        *,
        strategy_type: StrategyType | None = None,
        leverage: int | None = None,
        dynamic_leverage: bool | None = None,
    ) -> None:
        """Initialize the repository with optional initial settings."""
        self._strategy_type = strategy_type
        self._leverage = leverage
        self._dynamic_leverage = dynamic_leverage

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

    async def get_dynamic_leverage(self) -> bool | None:
        """Return the current in-memory dynamic leverage setting."""
        return self._dynamic_leverage

    async def save_dynamic_leverage(self, *, enabled: bool) -> None:
        """Persist dynamic leverage setting in memory."""
        self._dynamic_leverage = enabled
