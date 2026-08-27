"""Typed outcomes for network-scoped autonomous protected-entry execution."""

from __future__ import annotations

from dataclasses import dataclass

from botragram.enums import AutonomousLiveEntryExecutionStatus
from botragram.models.order import Order
from botragram.models.trading import TradingDecision

__all__ = ["AutonomousLiveEntryExecutionResult"]


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveEntryExecutionResult:
    """Describe one autonomous execution result without retaining exceptions."""

    status: AutonomousLiveEntryExecutionStatus
    decision: TradingDecision | None = None
    order: Order | None = None

    def __post_init__(self) -> None:
        """Keep protected-success state consistent with returned data."""
        is_success = (
            self.status is AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        )

        if is_success and (
            self.order is None
            or self.decision is None
            or not self.decision.should_execute
        ):
            raise ValueError(
                "Protected autonomous execution requires an order and approved decision"
            )

        if not is_success and self.order is not None:
            raise ValueError(
                "Non-successful autonomous execution must not return an order"
            )
