"""Natural-exit cleanup must not steal an operator-close lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from botragram.services import LiveNaturalExitRecoveryService
from botragram.services.live_natural_exit_recovery_service import (
    LiveNaturalExitExchange,
)
from botragram.storage.memory import (
    MemoryPositionRepository,
    MemorySubmissionAttemptRepository,
)


@dataclass(slots=True)
class _OperatorState:
    async def get_incomplete_attempts(self) -> tuple[object, ...]:
        return (object(),)


@dataclass(slots=True)
class _UnexpectedExchange:
    calls: int = 0

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[object, ...]:
        del symbol
        self.calls += 1
        raise AssertionError("natural-exit exchange reads must be blocked")


@pytest.mark.asyncio
async def test_incomplete_operator_close_blocks_natural_exit_reconciliation() -> None:
    exchange = _UnexpectedExchange()
    service = LiveNaturalExitRecoveryService(
        exchange_client=cast(LiveNaturalExitExchange, exchange),
        position_repository=MemoryPositionRepository(),
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
        operator_exit_repository=_OperatorState(),
    )

    with pytest.raises(RuntimeError, match="Incomplete LIVE operator exit"):
        await service.reconcile()

    assert exchange.calls == 0
