"""Database and exchange health checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["HealthReport", "HealthService"]


class DatabaseHealthProvider(Protocol):
    """Minimal database health contract."""

    @property
    def is_connected(self) -> bool:
        """Return whether a connection exists."""
        ...

    async def fetch_one(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> object | None:
        """Fetch one health probe row."""
        ...


class ExchangeHealthProvider(Protocol):
    """Minimal exchange health contract."""

    async def ping(self) -> bool:
        """Return whether the exchange is reachable."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class HealthReport:
    """Immutable dependency health snapshot."""

    database_healthy: bool
    exchange_healthy: bool

    @property
    def healthy(self) -> bool:
        """Return whether all required dependencies are healthy."""
        return self.database_healthy and self.exchange_healthy


@dataclass(slots=True, kw_only=True, frozen=True)
class HealthService:
    """Probe required runtime dependencies without mutating them."""

    database: DatabaseHealthProvider
    exchange: ExchangeHealthProvider

    async def check(self) -> HealthReport:
        """Return current database and exchange health."""
        database_healthy = await self._check_database()
        exchange_healthy = await self._check_exchange()

        return HealthReport(
            database_healthy=database_healthy,
            exchange_healthy=exchange_healthy,
        )

    async def _check_database(self) -> bool:
        """Probe the active SQLite connection."""
        if not self.database.is_connected:
            return False

        try:
            row = await self.database.fetch_one(statement="SELECT 1 AS health_value;")
            return row is not None
        except Exception:
            return False

    async def _check_exchange(self) -> bool:
        """Probe the public exchange endpoint."""
        try:
            return await self.exchange.ping()
        except Exception:
            return False
