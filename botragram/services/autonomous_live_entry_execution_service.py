"""TESTNET autonomous adapter for the protected LIVE entry boundary."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    ExchangeEnvironment,
    Interval,
    OrderType,
    SignalType,
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
    Ticker,
    TradingDecision,
)

__all__ = ["AutonomousLiveEntryExecutionService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC execution time."""
    return datetime.now(UTC)


class _LiveEntryRiskEvaluator(Protocol):
    """Return one fresh authoritative LIVE entry decision."""

    async def evaluate(
        self,
        *,
        signal: Signal,
        entry_price_override: Decimal | None = None,
    ) -> LiveEntryRiskEvaluation:
        """Evaluate an exact signal against current LIVE state."""
        ...


class _LiveMarketTickerProvider(Protocol):
    """Provide one current normalized market ticker."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return the current ticker for an exact trading symbol."""
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
    market_service: _LiveMarketTickerProvider
    live_futures_entry_service: _ProtectedLiveEntryExecutor
    environment: ExchangeEnvironment
    utc_now: Callable[[], datetime] = _utc_now

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

        ticker = await self.market_service.get_ticker(symbol=intent.signal.symbol)
        entry_price_override = self._get_entry_price_override(
            ticker=ticker,
            signal=intent.signal,
        )
        if entry_price_override is None:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.MARKET_REFERENCE_REJECTED,
                decision=self._market_reference_rejected_decision(signal=intent.signal),
            )

        evaluation = await self.risk_evaluation_service.evaluate(
            signal=intent.signal,
            entry_price_override=entry_price_override,
        )
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

        if self._is_stale_signal(intent=intent):
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.STALE_SIGNAL,
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

    @staticmethod
    def _get_entry_price_override(*, ticker: Ticker, signal: Signal) -> Decimal | None:
        """Return a valid side-aware execution reference for an entry signal."""
        if ticker.symbol.strip().upper() != signal.symbol.strip().upper():
            return None

        match signal.signal_type:
            case SignalType.BUY:
                entry_price = ticker.ask_price
            case SignalType.SELL:
                entry_price = ticker.bid_price
            case _:
                return None

        if not entry_price.is_finite() or entry_price <= Decimal("0"):
            return None

        return entry_price

    @staticmethod
    def _market_reference_rejected_decision(*, signal: Signal) -> TradingDecision:
        """Return a safe decision when no executable market reference exists."""
        return TradingDecision(
            should_execute=False,
            signal=signal,
            risk_result=None,
            reason=AutonomousLiveEntryExecutionStatus.MARKET_REFERENCE_REJECTED.value,
        )

    def _is_stale_signal(self, *, intent: AutonomousLiveEntryIntent) -> bool:
        """Return whether the signal no longer represents the latest interval.

        Args:
            intent: Authorized autonomous entry carrying closed-candle provenance.

        Returns:
            True when execution reaches or exceeds the next expected close.

        Raises:
            ValueError: If the configured clock or signal timestamp is naive.
        """
        as_of = self._normalize_utc_datetime(
            value=self.utc_now(),
            name="Autonomous LIVE execution time",
        )
        signal_generated_at = self._normalize_utc_datetime(
            value=intent.signal.generated_at,
            name="Autonomous LIVE signal generated_at",
        )
        return as_of >= intent.interval.next_close_time(
            close_time=signal_generated_at,
        )

    @staticmethod
    def _normalize_utc_datetime(*, value: datetime, name: str) -> datetime:
        """Require an aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")

        return value.astimezone(UTC)
