"""TESTNET autonomous adapter for the protected LIVE entry boundary."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    ExchangeEnvironment,
    Interval,
    OrderType,
)
from botragram.exceptions import (
    ExchangeOrderRejectedError,
    LiveSubmissionBlockedError,
    VenueRuleValidationError,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryExecutionResult,
    AutonomousLiveEntryIntent,
    LiveEntryRiskEvaluation,
    Order,
    RiskResult,
    Signal,
)

__all__ = ["AutonomousLiveEntryExecutionService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class _LiveEntryRiskEvaluator(Protocol):
    """Return one fresh authoritative LIVE entry decision."""

    async def evaluate(self, *, signal: Signal) -> LiveEntryRiskEvaluation:
        """Evaluate an exact signal against current LIVE state."""
        ...


class _ProtectedLiveEntryExecutor(Protocol):
    """Execute one already revalidated protected LIVE entry."""

    async def execute(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        interval: Interval,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Submit and complete one protected LIVE Futures entry."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveEntryExecutionService:
    """Revalidate and delegate one TESTNET autonomous protected entry.

    The adapter owns no submission identity, POST retry, reconciliation, or
    protection workflow. It performs fresh authoritative risk validation for
    each intent and delegates the sole mutation to LiveFuturesEntryService.
    """

    risk_evaluation_service: _LiveEntryRiskEvaluator
    live_futures_entry_service: _ProtectedLiveEntryExecutor
    environment: ExchangeEnvironment

    def __post_init__(self) -> None:
        """Normalize static TESTNET execution configuration."""
        if self.environment is not ExchangeEnvironment.TESTNET:
            raise ValueError("Autonomous LIVE execution requires TESTNET")

    async def execute(
        self,
        *,
        intent: AutonomousLiveEntryIntent,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> AutonomousLiveEntryExecutionResult:
        """Freshly revalidate one intent before protected LIVE execution."""
        if not self._is_authorized(authorization=authorization):
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.AUTHORIZATION_REJECTED,
            )

        evaluation = await self.risk_evaluation_service.evaluate(signal=intent.signal)
        decision = evaluation.decision

        if evaluation.has_existing_position:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.EXISTING_POSITION,
                decision=decision,
            )

        if not decision.should_execute or decision.risk_result is None:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.RISK_REJECTED,
                decision=decision,
            )

        try:
            order = await self.live_futures_entry_service.execute(
                signal=intent.signal,
                risk_result=decision.risk_result,
                interval=intent.interval,
                order_type=OrderType.MARKET,
                price=None,
            )
        except LiveSubmissionBlockedError:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.SUBMISSION_BLOCKED,
                decision=decision,
            )
        except VenueRuleValidationError:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.VENUE_RULE_REJECTED,
                decision=decision,
            )
        except ExchangeOrderRejectedError:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.EXCHANGE_REJECTED,
                decision=decision,
            )
        except Exception:
            _LOGGER.exception(
                "Autonomous LIVE protected entry is unsafe: symbol=%s",
                intent.symbol,
            )
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.EXECUTION_UNSAFE,
                decision=decision,
            )

        return AutonomousLiveEntryExecutionResult(
            status=AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
            decision=decision,
            order=order,
        )

    async def execute_many(
        self,
        *,
        intents: Sequence[AutonomousLiveEntryIntent],
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> tuple[AutonomousLiveEntryExecutionResult, ...]:
        """Execute intents sequentially and stop after uncertain mutation state."""
        results: list[AutonomousLiveEntryExecutionResult] = []

        for intent in intents:
            result = await self.execute(
                intent=intent,
                authorization=authorization,
            )
            results.append(result)

            if result.status in {
                AutonomousLiveEntryExecutionStatus.SUBMISSION_BLOCKED,
                AutonomousLiveEntryExecutionStatus.EXECUTION_UNSAFE,
            }:
                break

        return tuple(results)

    def _is_authorized(
        self,
        *,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> bool:
        """Require the exact explicit TESTNET new-entry capability."""
        return (
            authorization is not None
            and authorization.new_live_entry_allowed
            and authorization.environment is ExchangeEnvironment.TESTNET
            and authorization.environment is self.environment
        )
