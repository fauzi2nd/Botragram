"""Transient network-scoped autonomous LIVE entry-intent domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from botragram.enums import (
    AutonomousLiveEntryIntentStatus,
    Interval,
    OrderSide,
    SignalType,
    StrategyType,
)
from botragram.models.risk import RiskResult
from botragram.models.signal import Signal

__all__ = [
    "AutonomousLiveEntryIntent",
    "AutonomousLiveEntryIntentResult",
]


_ENTRY_SIGNAL_TYPES = frozenset({SignalType.BUY, SignalType.SELL})


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveEntryIntent:
    """Represent a risk-approved candidate before any LIVE submission begins.

    The value is transient only. It intentionally holds no submission identity,
    order, exchange reference, or authorization capability.
    """

    signal: Signal
    risk_result: RiskResult
    interval: Interval
    strategy_type: StrategyType

    def __post_init__(self) -> None:
        """Reject intent construction without an actionable approved decision."""
        if self.signal.signal_type not in _ENTRY_SIGNAL_TYPES:
            raise ValueError("Autonomous LIVE entry intent requires BUY or SELL")

        if not self.risk_result.approved:
            raise ValueError("Autonomous LIVE entry intent requires approved risk")

        if self.signal.strategy_name != self.strategy_type.value:
            raise ValueError(
                "Autonomous LIVE entry intent strategy must match its signal"
            )

    @property
    def symbol(self) -> str:
        """Return the normalized candidate symbol from the strategy signal."""
        return self.signal.symbol

    @property
    def side(self) -> OrderSide:
        """Return the Futures entry side represented by the signal."""
        return (
            OrderSide.BUY
            if self.signal.signal_type is SignalType.BUY
            else OrderSide.SELL
        )

    @property
    def signal_generated_at(self) -> datetime:
        """Return the immutable strategy-signal timestamp."""
        return self.signal.generated_at

    @property
    def quantity(self) -> Decimal:
        """Return the already-approved risk sizing quantity."""
        return self.risk_result.position.quantity


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveEntryIntentResult:
    """Return one explicit non-mutating autonomous entry-intent outcome."""

    status: AutonomousLiveEntryIntentStatus
    intent: AutonomousLiveEntryIntent | None

    def __post_init__(self) -> None:
        """Keep authorization status and the optional intent consistent."""
        has_intent = self.intent is not None
        is_authorized = self.status is AutonomousLiveEntryIntentStatus.AUTHORIZED

        if has_intent is not is_authorized:
            raise ValueError(
                "Autonomous LIVE entry intent result must contain an intent "
                "only when authorized"
            )
