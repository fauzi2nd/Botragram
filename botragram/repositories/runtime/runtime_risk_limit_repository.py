"""Persistence boundary for durable runtime canary limits."""

from __future__ import annotations

from abc import ABC, abstractmethod

from botragram.models import RuntimeRiskLimits

__all__ = ["RuntimeRiskLimitRepository"]


class RuntimeRiskLimitRepository(ABC):
    """Persist the current runtime limits and their audit history."""

    __slots__ = ()

    @abstractmethod
    async def get(self) -> RuntimeRiskLimits | None:
        """Return the latest durable runtime limits, if configured."""

    @abstractmethod
    async def save(self, *, limits: RuntimeRiskLimits) -> None:
        """Atomically replace current limits and append one audit event."""
