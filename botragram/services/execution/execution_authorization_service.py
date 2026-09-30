"""
Botragram

Description:
    PAPER-only human execution authorization boundary.

Python:
    3.14+
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from uuid import uuid4

from botragram.enums import AuthorizationStatus, SignalType, TradeMode
from botragram.models import (
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
    Signal,
    TradingResult,
)
from botragram.repositories import ExecutionAuthorizationRepository

__all__ = ["ExecutionAuthorizationService"]

_DEFAULT_AUTHORIZATION_TTL: Final[timedelta] = timedelta(minutes=5)
_ACTIONABLE_SIGNAL_TYPES: Final[frozenset[SignalType]] = frozenset(
    {SignalType.BUY, SignalType.SELL},
)
_UNKNOWN_AUTHORIZATION_REASON: Final[str] = "Execution authorization was not found"
_ALREADY_CONSUMED_REASON: Final[str] = "Execution authorization is no longer pending"
_EXPIRED_AUTHORIZATION_REASON: Final[str] = "Execution authorization has expired"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class PaperSignalExecutionProvider(Protocol):
    """Execute one signal through the authoritative PAPER boundary."""

    async def execute(self, *, signal: Signal) -> TradingResult:
        """Revalidate and execute one PAPER signal."""
        ...


class ExecutionAuthorizationPublisher(Protocol):
    """Publish a prepared authorization through an external adapter."""

    async def publish_execution_authorization(
        self,
        *,
        authorization: ExecutionAuthorization,
    ) -> None:
        """Publish one immutable pending authorization."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class ExecutionAuthorizationService:
    """Prepare and consume bounded human approvals for PAPER signals."""

    authorization_repository: ExecutionAuthorizationRepository
    paper_trading_service: PaperSignalExecutionProvider
    trade_mode: TradeMode
    authorization_ttl: timedelta = _DEFAULT_AUTHORIZATION_TTL
    authorization_publisher: ExecutionAuthorizationPublisher | None = None

    def __post_init__(self) -> None:
        """Require a finite PAPER-only authorization lifecycle."""
        if self.trade_mode is not TradeMode.PAPER:
            raise ValueError(
                "Human execution authorization is supported only in paper mode"
            )

        if self.authorization_ttl <= timedelta():
            raise ValueError("Execution authorization TTL must be greater than zero")

    async def prepare(
        self,
        *,
        signal: Signal,
        now: datetime | None = None,
    ) -> ExecutionAuthorization:
        """Create a pending authorization for one actionable signal.

        Args:
            signal: Exact discovery candidate requiring human approval.
            now: Optional UTC time used for deterministic application tests.

        Returns:
            Immutable pending authorization with an opaque identifier.

        Raises:
            ValueError: If the signal is not an actionable entry or the time is
                not timezone aware.
        """
        if signal.signal_type not in _ACTIONABLE_SIGNAL_TYPES:
            raise ValueError("Execution authorization requires a BUY or SELL signal")

        created_at = self._resolve_now(now=now)
        authorization = ExecutionAuthorization(
            authorization_id=uuid4().hex,
            signal=signal,
            status=AuthorizationStatus.PENDING,
            created_at=created_at,
            expires_at=created_at + self.authorization_ttl,
        )
        await self.authorization_repository.create(authorization=authorization)
        await self._publish_prepared(authorization=authorization)
        return authorization

    async def get(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorization | None:
        """Return the current process-local authorization state."""
        return await self.authorization_repository.get(
            authorization_id=authorization_id
        )

    async def prepare_if_no_equivalent_pending(
        self,
        *,
        signal: Signal,
        now: datetime | None = None,
    ) -> ExecutionAuthorization | None:
        """Prepare and publish only when no equivalent opportunity is pending.

        An equivalent pending candidate has the same symbol, entry direction,
        and strategy. The repository performs this check atomically so repeated
        confirmation cycles cannot flood the human approval channel.
        """
        if signal.signal_type not in _ACTIONABLE_SIGNAL_TYPES:
            raise ValueError("Execution authorization requires a BUY or SELL signal")

        created_at = self._resolve_now(now=now)
        authorization = ExecutionAuthorization(
            authorization_id=uuid4().hex,
            signal=signal,
            status=AuthorizationStatus.PENDING,
            created_at=created_at,
            expires_at=created_at + self.authorization_ttl,
        )
        created = await self.authorization_repository.create_if_no_equivalent_pending(
            authorization=authorization,
        )

        if not created:
            return None

        await self._publish_prepared(authorization=authorization)
        return authorization

    async def approve(
        self,
        *,
        authorization_id: str,
        now: datetime | None = None,
    ) -> ExecutionAuthorizationOutcome:
        """Consume one pending authorization and execute through PAPER.

        The authorization is atomically marked approved before execution. This
        deliberately makes cancellation or execution failure non-retriable,
        preventing a duplicate fill from a repeated human action.
        """
        authorization = await self.authorization_repository.consume_pending(
            authorization_id=authorization_id,
            status=AuthorizationStatus.APPROVED,
            now=self._resolve_now(now=now),
        )
        if authorization is None:
            return self._without_execution(
                authorization=await self.authorization_repository.get(
                    authorization_id=authorization_id,
                )
            )

        if authorization.status is not AuthorizationStatus.APPROVED:
            return self._without_execution(authorization=authorization)

        result = await self.paper_trading_service.execute(signal=authorization.signal)
        return ExecutionAuthorizationOutcome(
            authorization=authorization,
            trading_result=result,
            reason=result.reason,
        )

    async def reject(
        self,
        *,
        authorization_id: str,
        now: datetime | None = None,
    ) -> ExecutionAuthorizationOutcome:
        """Consume one pending authorization without a trading side effect."""
        authorization = await self.authorization_repository.consume_pending(
            authorization_id=authorization_id,
            status=AuthorizationStatus.REJECTED,
            now=self._resolve_now(now=now),
        )
        return self._without_execution(authorization=authorization)

    @staticmethod
    def _resolve_now(*, now: datetime | None) -> datetime:
        """Return a timezone-aware current UTC time."""
        resolved_now = datetime.now(UTC) if now is None else now

        if resolved_now.tzinfo is None:
            raise ValueError("Execution authorization time must be timezone aware")

        return resolved_now.astimezone(UTC)

    @staticmethod
    def _without_execution(
        *,
        authorization: ExecutionAuthorization | None,
    ) -> ExecutionAuthorizationOutcome:
        """Return a safe non-executed outcome for an authorization state."""
        if authorization is None:
            return ExecutionAuthorizationOutcome(
                authorization=None,
                trading_result=None,
                reason=_UNKNOWN_AUTHORIZATION_REASON,
            )

        if authorization.status is AuthorizationStatus.EXPIRED:
            reason = _EXPIRED_AUTHORIZATION_REASON
        elif authorization.status is AuthorizationStatus.PENDING:
            reason = "Execution authorization is still pending"
        else:
            reason = _ALREADY_CONSUMED_REASON

        return ExecutionAuthorizationOutcome(
            authorization=authorization,
            trading_result=None,
            reason=reason,
        )

    async def _publish_prepared(
        self,
        *,
        authorization: ExecutionAuthorization,
    ) -> None:
        """Publish one prepared authorization without affecting its lifecycle."""
        publisher = self.authorization_publisher

        if publisher is None:
            return

        try:
            await publisher.publish_execution_authorization(
                authorization=authorization,
            )
        except Exception:
            _LOGGER.exception(
                "Execution authorization notification failed: authorization_id=%s",
                authorization.authorization_id,
            )
