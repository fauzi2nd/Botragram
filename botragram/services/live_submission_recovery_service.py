"""Recover durable LIVE entry order state without creating an order."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import unique
from typing import Final, Protocol

from botragram.enums import OrderStatus, SubmissionAttemptStatus
from botragram.enums.base import BaseEnum
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.models import Order, SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository

__all__ = ["LiveSubmissionRecoveryResult", "LiveSubmissionRecoveryService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_TERMINAL_NON_EXECUTED_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {OrderStatus.REJECTED, OrderStatus.CANCELED, OrderStatus.EXPIRED}
)


@unique
class LiveSubmissionRecoveryResult(BaseEnum):
    """Outcome of one durable LIVE submission-order recovery pass."""

    NOTHING_TO_RECOVER = "nothing_to_recover"
    ORDER_ACKNOWLEDGED = "order_acknowledged"
    TERMINALLY_REJECTED = "terminally_rejected"
    STILL_INCOMPLETE = "still_incomplete"
    MULTIPLE_INCOMPLETE = "multiple_incomplete"


class LiveOrderRecovery(Protocol):
    """Read an authoritative order without exposing entry submission."""

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Return the persisted authoritative order snapshot."""
        ...


class LiveIncompleteSubmissionRecovery(Protocol):
    """Recover incomplete durable entries without exposing mutation methods."""

    async def recover_incomplete(self) -> LiveSubmissionRecoveryResult:
        """Return the authoritative incomplete-entry recovery result."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveSubmissionRecoveryService:
    """Reconcile one incomplete LIVE entry using authoritative GET only."""

    submission_attempt_repository: SubmissionAttemptRepository
    order_service: LiveOrderRecovery

    async def recover_incomplete(self) -> LiveSubmissionRecoveryResult:
        """Recover the sole incomplete attempt, if one exists."""
        attempts: Sequence[
            SubmissionAttempt
        ] = await self.submission_attempt_repository.get_incomplete()

        if not attempts:
            return LiveSubmissionRecoveryResult.NOTHING_TO_RECOVER

        if len(attempts) > 1:
            _LOGGER.critical(
                "LIVE submission recovery blocked by multiple incomplete attempts: "
                "count=%d",
                len(attempts),
            )
            return LiveSubmissionRecoveryResult.MULTIPLE_INCOMPLETE

        attempt = attempts[0]
        if attempt.status is SubmissionAttemptStatus.ACKNOWLEDGED:
            return LiveSubmissionRecoveryResult.ORDER_ACKNOWLEDGED

        if attempt.status not in {
            SubmissionAttemptStatus.PREPARED,
            SubmissionAttemptStatus.UNRESOLVED,
        }:
            raise RuntimeError("Submission recovery received a terminal attempt")

        try:
            order = await self.order_service.get_by_client_order_id(
                symbol=attempt.symbol,
                client_order_id=attempt.client_order_id,
            )
        except ExchangeOrderNotFoundError, ExchangeOrderOutcomeUnknownError:
            return LiveSubmissionRecoveryResult.STILL_INCOMPLETE

        if order.client_order_id != attempt.client_order_id:
            return LiveSubmissionRecoveryResult.STILL_INCOMPLETE

        if order.status is OrderStatus.FILLED:
            await self.submission_attempt_repository.save(
                attempt=replace(
                    attempt,
                    status=SubmissionAttemptStatus.ACKNOWLEDGED,
                    exchange_order_id=order.order_id,
                )
            )
            return LiveSubmissionRecoveryResult.ORDER_ACKNOWLEDGED

        if order.status in _TERMINAL_NON_EXECUTED_STATUSES:
            await self.submission_attempt_repository.save(
                attempt=replace(attempt, status=SubmissionAttemptStatus.REJECTED)
            )
            return LiveSubmissionRecoveryResult.TERMINALLY_REJECTED

        return LiveSubmissionRecoveryResult.STILL_INCOMPLETE
