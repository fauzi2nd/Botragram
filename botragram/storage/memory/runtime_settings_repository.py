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
from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    StrategyType,
)
from botragram.repositories import RuntimeSettingsRepository

__all__ = ["MemoryRuntimeSettingsRepository"]


# =============================================================================
# Memory Repository
# =============================================================================
class MemoryRuntimeSettingsRepository(RuntimeSettingsRepository):
    """In-memory runtime settings repository for testing."""

    __slots__ = (
        "_dynamic_leverage",
        "_exchange_type",
        "_execution_policy",
        "_leverage",
        "_market_type",
        "_strategy_type",
    )

    def __init__(
        self,
        *,
        strategy_type: StrategyType | None = None,
        leverage: int | None = None,
        dynamic_leverage: bool | None = None,
        market_type: MarketType | None = None,
        exchange_type: ExchangeType | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        """Initialize the repository with optional initial settings."""
        self._strategy_type = strategy_type
        self._leverage = leverage
        self._dynamic_leverage = dynamic_leverage
        self._market_type = market_type
        self._exchange_type = exchange_type
        self._execution_policy = execution_policy

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

    async def get_market_type(self) -> MarketType | None:
        """Return the current in-memory market type, if configured."""
        return self._market_type

    async def save_market_type(self, *, market_type: MarketType) -> None:
        """Persist the active runtime market type in memory."""
        self._market_type = market_type

    async def get_exchange(self) -> ExchangeType | None:
        """Return the current in-memory exchange, if configured."""
        return self._exchange_type

    async def save_exchange(self, *, exchange_type: ExchangeType) -> None:
        """Persist the active runtime exchange in memory."""
        self._exchange_type = exchange_type

    async def get_execution_policy(self) -> ExecutionPolicy | None:
        """Return the current in-memory execution policy, if configured."""
        return self._execution_policy

    async def save_execution_policy(self, *, execution_policy: ExecutionPolicy) -> None:
        """Persist the active runtime execution policy in memory."""
        self._execution_policy = execution_policy
