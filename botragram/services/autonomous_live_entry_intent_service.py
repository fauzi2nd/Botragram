"""Pure network-scoped autonomous LIVE entry-intent authorization boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from botragram.enums import (
    AutonomousLiveEntryIntentStatus,
    ExchangeEnvironment,
    ExecutionPolicy,
    Interval,
    StrategyType,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryIntent,
    AutonomousLiveEntryIntentResult,
    TradingDecision,
)

__all__ = ["AutonomousLiveEntryIntentService"]


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveEntryIntentService:
    """Authorize transient network-scoped intents after an existing risk decision.

    This service is deliberately pure: it accepts completed decisions in their
    existing deterministic ranking order and creates no order, submission
    attempt, exchange request, task, or background workflow.
    """

    execution_policy: ExecutionPolicy
    environment: ExchangeEnvironment

    def __post_init__(self) -> None:
        """Restrict the boundary to the explicit autonomous LIVE workflow."""
        if self.execution_policy is not ExecutionPolicy.AUTONOMOUS_LIVE:
            raise ValueError("Autonomous LIVE entry intents require autonomous LIVE")

    def authorize(
        self,
        *,
        decision: TradingDecision,
        interval: Interval,
        strategy_type: StrategyType,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> AutonomousLiveEntryIntentResult:
        """Return an intent only for an approved decision and explicit capability."""
        risk_result = decision.risk_result

        if (
            not decision.should_execute
            or risk_result is None
            or not risk_result.approved
        ):
            return AutonomousLiveEntryIntentResult(
                status=AutonomousLiveEntryIntentStatus.RISK_REJECTED,
                intent=None,
            )

        if (
            authorization is None
            or not authorization.new_live_entry_allowed
            or authorization.environment is not self.environment
        ):
            return AutonomousLiveEntryIntentResult(
                status=AutonomousLiveEntryIntentStatus.AUTHORIZATION_REQUIRED,
                intent=None,
            )

        return AutonomousLiveEntryIntentResult(
            status=AutonomousLiveEntryIntentStatus.AUTHORIZED,
            intent=AutonomousLiveEntryIntent(
                signal=decision.signal,
                risk_result=risk_result,
                interval=interval,
                strategy_type=strategy_type,
            ),
        )

    def authorize_ranked(
        self,
        *,
        decisions: Sequence[TradingDecision],
        interval: Interval,
        strategy_type: StrategyType,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> tuple[AutonomousLiveEntryIntentResult, ...]:
        """Authorize candidates sequentially while preserving supplied ranking.

        The caller remains responsible for producing decisions from the
        authoritative portfolio and risk snapshot. This method performs no
        reordering and no concurrent work.
        """
        return tuple(
            self.authorize(
                decision=decision,
                interval=interval,
                strategy_type=strategy_type,
                authorization=authorization,
            )
            for decision in decisions
        )
