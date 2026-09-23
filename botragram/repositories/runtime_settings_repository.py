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
from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    StrategyType,
)

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
    async def get_dynamic_leverage(self) -> bool | None:
        """Return the latest durable dynamic leverage setting, if configured."""

    @abstractmethod
    async def save_dynamic_leverage(self, *, enabled: bool) -> None:
        """Atomically persist the active dynamic leverage setting."""

    @abstractmethod
    async def get_market_type(self) -> MarketType | None:
        """Return the latest durable runtime market type, if configured."""

    @abstractmethod
    async def save_market_type(self, *, market_type: MarketType) -> None:
        """Atomically persist the active runtime market type."""

    @abstractmethod
    async def get_exchange(self) -> ExchangeType | None:
        """Return the latest durable runtime exchange, if configured."""

    @abstractmethod
    async def save_exchange(self, *, exchange_type: ExchangeType) -> None:
        """Atomically persist the active runtime exchange."""

    @abstractmethod
    async def get_execution_policy(self) -> ExecutionPolicy | None:
        """Return the latest durable runtime execution policy, if configured."""

    @abstractmethod
    async def save_execution_policy(self, *, execution_policy: ExecutionPolicy) -> None:
        """Atomically persist the active runtime execution policy."""
