"""LIVE incomplete entry order-recovery tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.models import Order, SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository
from botragram.services import (
    LiveSubmissionRecoveryResult,
    LiveSubmissionRecoveryService,
)

_NOW = datetime(2026, 8, 18, tzinfo=UTC)
_CLIENT_ORDER_ID = "btg-00000000000000000000000000000000"


def _attempt(*, status: SubmissionAttemptStatus) -> SubmissionAttempt:
    """Build one durable entry attempt."""
    return SubmissionAttempt(
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=None,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _order(*, status: OrderStatus, client_order_id: str = _CLIENT_ORDER_ID) -> Order:
    """Build one authoritative Futures order."""
    return Order(
        order_id="42",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        status=status,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        created_at=_NOW,
        updated_at=_NOW,
        client_order_id=client_order_id,
    )


@dataclass(slots=True)
class FakeAttemptRepository(SubmissionAttemptRepository):
    """Store attempts and expose observable persistence transitions."""

    incomplete: tuple[SubmissionAttempt, ...] = ()
    saved: list[SubmissionAttempt] = field(default_factory=list[SubmissionAttempt])

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Record one state transition."""
        self.saved.append(attempt)
        self.incomplete = tuple(
            attempt if item.client_order_id == attempt.client_order_id else item
            for item in self.incomplete
        )

    async def resolve_no_exposure(
        self,
        *,
        symbol: str,
        attempt: SubmissionAttempt,
    ) -> None:
        """Exercise the repository-owned no-exposure terminal transition."""
        del symbol
        self.saved.append(
            replace(attempt, status=SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE)
        )
        self.incomplete = tuple(
            item
            for item in self.incomplete
            if item.client_order_id != attempt.client_order_id
        )

    async def get_by_client_order_id(
        self, *, client_order_id: str
    ) -> SubmissionAttempt | None:
        """Return one attempt when present."""
        return next(
            (
                item
                for item in self.incomplete
                if item.client_order_id == client_order_id
            ),
            None,
        )

    async def get_unresolved(self) -> tuple[SubmissionAttempt, ...]:
        """Return incomplete unresolved intents."""
        return tuple(
            item
            for item in self.incomplete
            if item.status
            in (SubmissionAttemptStatus.PREPARED, SubmissionAttemptStatus.UNRESOLVED)
        )

    async def get_incomplete(self) -> tuple[SubmissionAttempt, ...]:
        """Return configured recovery candidates."""
        return self.incomplete


@dataclass(slots=True)
class FakeOrderRecovery:
    """Expose only the authoritative client-ID GET boundary."""

    response: Order | BaseException
    calls: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Record one GET-only recovery lookup."""
        self.calls.append((symbol, client_order_id))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _service(
    *,
    attempts: tuple[SubmissionAttempt, ...] = (),
    response: Order | BaseException | None = None,
) -> tuple[LiveSubmissionRecoveryService, FakeAttemptRepository, FakeOrderRecovery]:
    """Build the service and its GET-only fakes."""
    repository = FakeAttemptRepository(incomplete=attempts)
    order_recovery = FakeOrderRecovery(
        response=response or _order(status=OrderStatus.FILLED)
    )
    return (
        LiveSubmissionRecoveryService(
            submission_attempt_repository=repository,
            order_service=order_recovery,
        ),
        repository,
        order_recovery,
    )


@pytest.mark.asyncio
async def test_nothing_and_multiple_incomplete_attempts_never_query() -> None:
    """Return explicit no-op/fail-closed outcomes without any remote request."""
    service, _, orders = _service()
    assert (
        await service.recover_incomplete()
        is LiveSubmissionRecoveryResult.NOTHING_TO_RECOVER
    )
    assert orders.calls == []

    service, _, orders = _service(
        attempts=(
            _attempt(status=SubmissionAttemptStatus.PREPARED),
            replace(
                _attempt(status=SubmissionAttemptStatus.UNRESOLVED),
                client_order_id="btg-1",
            ),
        )
    )
    assert (
        await service.recover_incomplete()
        is LiveSubmissionRecoveryResult.MULTIPLE_INCOMPLETE
    )
    assert orders.calls == []


@pytest.mark.asyncio
async def test_acknowledged_attempt_requires_later_post_entry_recovery() -> None:
    """Do not re-query or mutate an already acknowledged entry order."""
    service, repository, orders = _service(
        attempts=(_attempt(status=SubmissionAttemptStatus.ACKNOWLEDGED),)
    )
    assert (
        await service.recover_incomplete()
        is LiveSubmissionRecoveryResult.ORDER_ACKNOWLEDGED
    )
    assert repository.saved == []
    assert orders.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [SubmissionAttemptStatus.PREPARED, SubmissionAttemptStatus.UNRESOLVED]
)
async def test_filled_order_acknowledges_same_attempt(
    status: SubmissionAttemptStatus,
) -> None:
    """Resolve prepared or unresolved intent through its exact client identity."""
    service, repository, orders = _service(attempts=(_attempt(status=status),))
    assert (
        await service.recover_incomplete()
        is LiveSubmissionRecoveryResult.ORDER_ACKNOWLEDGED
    )
    assert orders.calls == [("BTCUSDT", _CLIENT_ORDER_ID)]
    assert repository.saved[0].status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert repository.saved[0].exchange_order_id == "42"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [OrderStatus.REJECTED, OrderStatus.CANCELED, OrderStatus.EXPIRED]
)
async def test_terminal_non_executed_order_is_rejected(status: OrderStatus) -> None:
    """Persist a terminal rejection without further recovery work."""
    service, repository, orders = _service(
        attempts=(_attempt(status=SubmissionAttemptStatus.PREPARED),),
        response=_order(status=status),
    )
    assert (
        await service.recover_incomplete()
        is LiveSubmissionRecoveryResult.TERMINALLY_REJECTED
    )
    assert orders.calls == [("BTCUSDT", _CLIENT_ORDER_ID)]
    assert repository.saved[0].status is SubmissionAttemptStatus.REJECTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _order(status=OrderStatus.NEW),
        _order(status=OrderStatus.PARTIALLY_FILLED),
        ExchangeOrderNotFoundError("not found"),
        ExchangeOrderOutcomeUnknownError("unknown"),
        _order(status=OrderStatus.FILLED, client_order_id="foreign"),
    ],
)
async def test_uncertain_order_state_remains_incomplete(
    response: Order | BaseException,
) -> None:
    """Fail closed on non-final, unavailable, or mismatched exchange state."""
    service, repository, orders = _service(
        attempts=(_attempt(status=SubmissionAttemptStatus.PREPARED),),
        response=response,
    )
    assert (
        await service.recover_incomplete()
        is LiveSubmissionRecoveryResult.STILL_INCOMPLETE
    )
    assert orders.calls == [("BTCUSDT", _CLIENT_ORDER_ID)]
    assert repository.saved == []


@pytest.mark.asyncio
async def test_cancellation_propagates_without_order_submission() -> None:
    """Keep cancellation distinct from a durable recovery result."""
    service, repository, orders = _service(
        attempts=(_attempt(status=SubmissionAttemptStatus.PREPARED),),
        response=asyncio.CancelledError(),
    )
    with pytest.raises(asyncio.CancelledError):
        await service.recover_incomplete()
    assert orders.calls == [("BTCUSDT", _CLIENT_ORDER_ID)]
    assert repository.saved == []
