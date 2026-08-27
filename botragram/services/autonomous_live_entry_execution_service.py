"""Network-scoped autonomous adapter for the protected LIVE entry boundary."""

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
)
from botragram.exceptions import (
    ExchangeOrderRejectedError,
    LiveEntryExistingPositionError,
    LiveEntryPortfolioCapacityError,
    LiveEntryPreflightError,
    LiveEntryRiskLimitError,
    LiveEntrySymbolReadinessError,
    LiveSubmissionBlockedError,
    VenueRuleValidationError,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryExecutionResult,
    AutonomousLiveEntryIntent,
    ExecutableQuote,
    LiveEntryRiskEvaluation,
    Order,
    RiskResult,
    Signal,
    TradingDecision,
)
from botragram.services.live_executable_quote_service import (
    get_executable_entry_price,
    is_signal_stale,
)

__all__ = ["AutonomousLiveEntryExecutionService"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC execution time."""
    return datetime.now(UTC)


class _LiveEntryRiskEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        signal: Signal,
        entry_price_override: Decimal | None = None,
    ) -> LiveEntryRiskEvaluation:
        """Evaluate an exact signal against current LIVE state."""
        ...


class _LiveExecutableQuoteProvider(Protocol):
    async def get_executable_quote(self, *, symbol: str) -> ExecutableQuote:
        """Return the current executable quote for an exact trading symbol."""
        ...


class _ProtectedLiveEntryExecutor(Protocol):
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
    """Revalidate and delegate one network-scoped autonomous protected entry."""

    risk_evaluation_service: _LiveEntryRiskEvaluator
    market_service: _LiveExecutableQuoteProvider
    live_futures_entry_service: _ProtectedLiveEntryExecutor
    environment: ExchangeEnvironment
    max_executable_quote_age_ms: int = 1_000
    max_spread_bps: Decimal = Decimal("20")
    utc_now: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        if self.max_executable_quote_age_ms <= 0:
            raise ValueError("Maximum executable quote age must be greater than zero")
        if not self.max_spread_bps.is_finite() or self.max_spread_bps <= Decimal("0"):
            raise ValueError("Maximum executable spread must be greater than zero")

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

        quote = await self.market_service.get_executable_quote(
            symbol=intent.signal.symbol
        )
        entry_price_override = self._get_entry_price_override(
            quote=quote,
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
        except LiveEntryExistingPositionError:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.EXISTING_POSITION,
                decision=decision,
            )
        except LiveEntryPortfolioCapacityError, LiveEntryRiskLimitError:
            return AutonomousLiveEntryExecutionResult(
                status=AutonomousLiveEntryExecutionStatus.RISK_REJECTED,
                decision=decision,
            )
        except LiveEntrySymbolReadinessError:
            return AutonomousLiveEntryExecutionResult(
                status=(AutonomousLiveEntryExecutionStatus.SYMBOL_READINESS_REJECTED),
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
        except LiveEntryPreflightError:
            raise
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
        return (
            authorization is not None
            and authorization.new_live_entry_allowed
            and authorization.environment is self.environment
        )

    def _get_entry_price_override(
        self,
        *,
        quote: ExecutableQuote,
        signal: Signal,
    ) -> Decimal | None:
        return get_executable_entry_price(
            quote=quote,
            signal=signal,
            as_of=self.utc_now(),
            max_quote_age_ms=self.max_executable_quote_age_ms,
            max_spread_bps=self.max_spread_bps,
        )

    @staticmethod
    def _market_reference_rejected_decision(*, signal: Signal) -> TradingDecision:
        return TradingDecision(
            should_execute=False,
            signal=signal,
            risk_result=None,
            reason=AutonomousLiveEntryExecutionStatus.MARKET_REFERENCE_REJECTED.value,
        )

    def _is_stale_signal(self, *, intent: AutonomousLiveEntryIntent) -> bool:
        return is_signal_stale(
            signal=intent.signal,
            interval=intent.interval,
            as_of=self.utc_now(),
        )
