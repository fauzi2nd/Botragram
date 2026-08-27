"""Durable process-wide runtime canary-limit authority."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from botragram.models import RuntimeRiskLimits
from botragram.repositories import RuntimeRiskLimitRepository

__all__ = ["RuntimeRiskLimitService"]


class RuntimeRiskLimitChangeGuard(Protocol):
    """Serialize a risk-limit change against runtime resume and active cycles."""

    def begin_risk_limit_change(self) -> None:
        """Reserve one paused runtime configuration change."""
        ...

    def end_risk_limit_change(self) -> None:
        """Release one runtime configuration change reservation."""
        ...


@dataclass(slots=True, kw_only=True)
class RuntimeRiskLimitService:
    """Persist and publish one authoritative entry-limit snapshot."""

    repository: RuntimeRiskLimitRepository
    runtime_guard: RuntimeRiskLimitChangeGuard
    initial_max_open_positions: int
    initial_max_position_size_usdt: Decimal
    hard_max_open_positions: int
    hard_max_position_size_usdt: Decimal
    _current: RuntimeRiskLimits = field(init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate configured ceilings and build the initial snapshot."""
        self._validate_within_hard_limits(
            max_open_positions=self.initial_max_open_positions,
            max_position_size_usdt=self.initial_max_position_size_usdt,
        )
        self._current = RuntimeRiskLimits(
            max_open_positions=self.initial_max_open_positions,
            max_position_size_usdt=self.initial_max_position_size_usdt,
            updated_at=datetime.now(UTC),
            updated_by="environment",
        )

    async def initialize(self) -> None:
        """Load durable limits or persist the environment-defined initial values."""
        async with self._lock:
            persisted = await self.repository.get()
            if persisted is None:
                await self.repository.save(limits=self._current)
                return

            self._validate_within_hard_limits(
                max_open_positions=persisted.max_open_positions,
                max_position_size_usdt=persisted.max_position_size_usdt,
            )
            self._current = persisted

    def get_snapshot(self) -> RuntimeRiskLimits:
        """Return the current immutable runtime limit snapshot."""
        return self._current

    async def update(
        self,
        *,
        max_open_positions: int,
        max_position_size_usdt: Decimal,
        updated_by: str,
    ) -> RuntimeRiskLimits:
        """Durably update entry limits while runtime execution is paused."""
        self._validate_within_hard_limits(
            max_open_positions=max_open_positions,
            max_position_size_usdt=max_position_size_usdt,
        )
        candidate = RuntimeRiskLimits(
            max_open_positions=max_open_positions,
            max_position_size_usdt=max_position_size_usdt,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
        )

        async with self._lock:
            self.runtime_guard.begin_risk_limit_change()
            try:
                await self.repository.save(limits=candidate)
                self._current = candidate
            finally:
                self.runtime_guard.end_risk_limit_change()
        return candidate

    def _validate_within_hard_limits(
        self,
        *,
        max_open_positions: int,
        max_position_size_usdt: Decimal,
    ) -> None:
        """Reject invalid values and all attempts to exceed environment ceilings."""
        if isinstance(self.hard_max_open_positions, bool) or (
            self.hard_max_open_positions <= 0
        ):
            raise ValueError("Hard maximum open positions must be positive")
        if (
            not self.hard_max_position_size_usdt.is_finite()
            or self.hard_max_position_size_usdt <= Decimal("0")
        ):
            raise ValueError("Hard maximum position size must be finite and positive")
        if isinstance(max_open_positions, bool) or max_open_positions <= 0:
            raise ValueError("Runtime maximum open positions must be positive")
        if max_open_positions > self.hard_max_open_positions:
            raise ValueError("Runtime maximum open positions exceeds hard limit")
        if (
            not max_position_size_usdt.is_finite()
            or max_position_size_usdt <= Decimal("0")
        ):
            raise ValueError("Runtime maximum position size must be finite and positive")
        if max_position_size_usdt > self.hard_max_position_size_usdt:
            raise ValueError("Runtime maximum position size exceeds hard limit")
