"""Protected LIVE Futures MARKET-entry workflow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Protocol
from uuid import uuid4

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.engine import PortfolioEngine
from botragram.enums import (
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
    LiveEntryExistingPositionError,
    LiveEntryPortfolioCapacityError,
    LiveEntryPreflightError,
    LiveSubmissionBlockedError,
    VenueRuleValidationError,
)
from botragram.models import Order, Position, RiskResult, Signal, SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository

__all__ = ["LiveFuturesEntryService"]


_DECIMAL_ZERO = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_CLIENT_ORDER_ID_PREFIX: Final[str] = "btg-"
_RECONCILIATION_MAX_ATTEMPTS: Final[int] = 2
_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05


class LiveOrderSubmission(Protocol):
    """Submit one already-approved exchange entry order."""

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit and persist one exchange order."""
        ...

    async def normalize_futures_market_quantity(
        self,
        *,
        symbol: str,
        quantity: Decimal,
    ) -> Decimal:
        """Return a venue-valid quantity before durable submission intent."""
        ...

    async def get_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Fetch and persist one exchange order by client identity."""
        ...


class LivePositionSynchronization(Protocol):
    """Synchronize and persist an exchange position snapshot."""

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return one optionally synchronized position."""
        ...

    async def get_all(self, *, synchronize: bool) -> Sequence[Position]:
        """Return the optionally synchronized authoritative portfolio."""
        ...

    async def save(self, *, position: Position) -> None:
        """Persist one position with runtime metadata."""
        ...


class LiveProtectionReconciliation(Protocol):
    """Reconcile and verify SL/TP protection for one position."""

    async def ensure(self, *, position: Position) -> Position:
        """Return a position whose SL/TP coverage is exchange-verified."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveFuturesEntryService:
    """Submit one LIVE Futures entry only through verified protection state."""

    market_type: MarketType
    order_service: LiveOrderSubmission
    position_service: LivePositionSynchronization
    protection_service: LiveProtectionReconciliation
    runtime_control: TradingRuntimeControl
    submission_attempt_repository: SubmissionAttemptRepository
    portfolio_engine: PortfolioEngine
    max_open_positions: int

    async def execute(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        interval: Interval,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Submit a MARKET entry, synchronize it, and verify full protection.

        The submission is deliberately single-attempt. Any exception after the
        protection gate closes is unsafe and propagates to the runtime boundary.
        """
        self._validate_entry(order_type=order_type)
        try:
            if await self.submission_attempt_repository.get_unresolved():
                raise LiveSubmissionBlockedError(
                    "An unresolved LIVE submission attempt blocks entry"
                )
            normalized_quantity = (
                await self.order_service.normalize_futures_market_quantity(
                    symbol=signal.symbol,
                    quantity=risk_result.position.quantity,
                )
            )
        except asyncio.CancelledError:
            raise
        except LiveSubmissionBlockedError, VenueRuleValidationError:
            raise
        except Exception as error:
            raise LiveEntryPreflightError(
                "LIVE entry preflight failed before protected mutation"
            ) from error

        client_order_id = f"{_CLIENT_ORDER_ID_PREFIX}{uuid4().hex}"
        now = datetime.now(UTC)
        attempt = SubmissionAttempt(
            client_order_id=client_order_id,
            symbol=signal.symbol,
            side=(
                OrderSide.BUY if signal.signal_type.value == "buy" else OrderSide.SELL
            ),
            order_type=order_type,
            quantity=normalized_quantity,
            signal_generated_at=signal.generated_at,
            interval=interval,
            strategy_type=self._resolve_strategy_type(signal.strategy_name),
            status=SubmissionAttemptStatus.PREPARED,
            created_at=now,
            updated_at=now,
        )
        try:
            reserved = await self.submission_attempt_repository.reserve(attempt=attempt)
        except BaseException:
            self.runtime_control.set_position_protection_ready(False)
            raise
        if not reserved:
            raise LiveSubmissionBlockedError(
                "An incomplete LIVE submission attempt blocks entry"
            )
        self.runtime_control.set_position_protection_ready(False)
        _LOGGER.info(
            "Live Futures entry submission started: symbol=%s signal=%s",
            signal.symbol,
            signal.signal_type.value,
        )

        positions = await self.position_service.get_all(
            synchronize=True,
        )
        if self.portfolio_engine.has_position(
            positions=positions,
            symbol=signal.symbol,
        ):
            await self._persist_attempt(
                attempt=attempt,
                status=SubmissionAttemptStatus.BLOCKED_BY_EXISTING_POSITION,
            )
            self.runtime_control.set_position_protection_ready(True)
            raise LiveEntryExistingPositionError(
                "An active LIVE position blocks a new entry for the same symbol"
            )
        if not self.portfolio_engine.can_open_position(
            positions=positions,
            max_open_positions=self.max_open_positions,
        ):
            await self._persist_attempt(
                attempt=attempt,
                status=SubmissionAttemptStatus.BLOCKED_BY_PORTFOLIO_CAPACITY,
            )
            self.runtime_control.set_position_protection_ready(True)
            raise LiveEntryPortfolioCapacityError(
                "The active LIVE portfolio has reached its position capacity"
            )

        try:
            order = await self.order_service.submit(
                signal=signal,
                risk_result=replace(
                    risk_result,
                    position=replace(
                        risk_result.position,
                        quantity=normalized_quantity,
                        notional=(
                            normalized_quantity * risk_result.metrics.entry_price
                        ),
                    ),
                ),
                order_type=order_type,
                price=price,
                client_order_id=client_order_id,
            )
            if order.client_order_id not in (None, client_order_id):
                raise RuntimeError("Exchange returned a mismatched client order ID")
        except ExchangeOrderRejectedError:
            await self._persist_attempt(
                attempt=attempt,
                status=SubmissionAttemptStatus.REJECTED,
            )
            raise
        except ExchangeOrderOutcomeUnknownError:
            await self._persist_unresolved_attempt(attempt=attempt)
            order = await self._reconcile_ambiguous_submission(attempt=attempt)
        except asyncio.CancelledError:
            await self._persist_unresolved_attempt(attempt=attempt)
            _LOGGER.warning("Live Futures entry cancelled while protection is unsafe")
            raise
        except Exception:
            await self._persist_unresolved_attempt(attempt=attempt)
            _LOGGER.exception(
                "Live Futures entry submission is unresolved; protection gate "
                "remains closed: symbol=%s",
                signal.symbol,
            )
            raise

        try:
            await self._persist_attempt(
                attempt=attempt,
                status=SubmissionAttemptStatus.ACKNOWLEDGED,
                exchange_order_id=order.order_id,
            )
        except Exception:
            await self._persist_unresolved_attempt(attempt=attempt)
            raise

        _LOGGER.info(
            "Live Futures entry acknowledged: symbol=%s order_id=%s",
            signal.symbol,
            order.order_id,
        )

        try:
            position = await self.position_service.get(
                symbol=signal.symbol,
                synchronize=True,
            )
            if position is None or position.quantity <= _DECIMAL_ZERO:
                raise RuntimeError("Exchange did not report an active entry position")

            persisted_position = replace(
                position,
                interval=interval,
                strategy_type=self._resolve_strategy_type(signal.strategy_name),
                entry_client_order_id=client_order_id,
            )
            await self.position_service.save(position=persisted_position)
            _LOGGER.info(
                "Live Futures entry position synchronized: symbol=%s quantity=%s "
                "entry_price=%s",
                persisted_position.symbol,
                persisted_position.quantity,
                persisted_position.entry_price,
            )
            await self.protection_service.ensure(position=persisted_position)
        except asyncio.CancelledError:
            _LOGGER.warning("Live Futures entry cancelled while protection is unsafe")
            raise
        except Exception as error:
            _LOGGER.exception(
                "Live Futures entry is unsafe; protection gate remains closed: "
                "symbol=%s",
                signal.symbol,
            )
            raise RuntimeError(
                f"Live Futures post-entry state is unsafe: {error}"
            ) from error

        try:
            await self._persist_attempt(
                attempt=attempt,
                status=SubmissionAttemptStatus.COMPLETED,
                exchange_order_id=order.order_id,
            )
        except Exception:
            _LOGGER.exception(
                "Live Futures entry protection is verified but durable completion "
                "failed: client_order_id=%s",
                attempt.client_order_id,
            )
            raise

        self.runtime_control.set_position_protection_ready(True)
        _LOGGER.info(
            "Live Futures entry completed safely: symbol=%s order_id=%s",
            signal.symbol,
            order.order_id,
        )
        return order

    def _validate_entry(self, *, order_type: OrderType) -> None:
        """Restrict Phase 5A protected execution to supported semantics."""
        if self.market_type is not MarketType.FUTURES:
            raise RuntimeError("Protected LIVE entry currently requires FUTURES")

        if order_type is not OrderType.MARKET:
            raise ValueError("Protected LIVE entry currently supports MARKET orders")

    async def _reconcile_ambiguous_submission(
        self,
        *,
        attempt: SubmissionAttempt,
    ) -> Order:
        """Resolve a single ambiguous entry using bounded GET-only lookup."""
        for reconciliation_attempt in range(_RECONCILIATION_MAX_ATTEMPTS):
            try:
                order = await self.order_service.get_by_client_order_id(
                    symbol=attempt.symbol,
                    client_order_id=attempt.client_order_id,
                )
            except ExchangeOrderNotFoundError, ExchangeOrderOutcomeUnknownError:
                if reconciliation_attempt + 1 >= _RECONCILIATION_MAX_ATTEMPTS:
                    break
                await asyncio.sleep(_RECONCILIATION_DELAY_SECONDS)
                continue

            if order.client_order_id != attempt.client_order_id:
                raise RuntimeError(
                    "Reconciled order returned a mismatched client order ID"
                )

            if order.status is OrderStatus.FILLED:
                return order

            if order.status in {
                OrderStatus.CANCELED,
                OrderStatus.EXPIRED,
                OrderStatus.REJECTED,
            }:
                await self._persist_attempt(
                    attempt=attempt,
                    status=SubmissionAttemptStatus.REJECTED,
                    exchange_order_id=order.order_id,
                )
                raise RuntimeError("Reconciled entry order was not executed")

            raise RuntimeError("Reconciled entry order has an unsafe execution status")

        raise RuntimeError("Ambiguous LIVE entry submission remains unresolved")

    async def _persist_unresolved_attempt(self, *, attempt: SubmissionAttempt) -> None:
        """Retain a conservatively unresolved intent after an unsafe outcome."""
        await self._persist_attempt(
            attempt=attempt,
            status=SubmissionAttemptStatus.UNRESOLVED,
            suppress_failure=True,
        )

    async def _persist_attempt(
        self,
        *,
        attempt: SubmissionAttempt,
        status: SubmissionAttemptStatus,
        exchange_order_id: str | None = None,
        suppress_failure: bool = False,
    ) -> None:
        """Persist one lifecycle transition without masking the primary failure."""
        try:
            await self.submission_attempt_repository.save(
                attempt=replace(
                    attempt,
                    status=status,
                    exchange_order_id=exchange_order_id,
                    updated_at=datetime.now(UTC),
                )
            )
        except Exception:
            _LOGGER.exception(
                "Live Futures submission attempt transition failed: "
                "client_order_id=%s status=%s",
                attempt.client_order_id,
                status.value,
            )
            if not suppress_failure:
                raise

    @staticmethod
    def _resolve_strategy_type(strategy_name: str) -> StrategyType | None:
        """Retain known strategy metadata without rejecting custom strategies."""
        try:
            return StrategyType(strategy_name)
        except ValueError:
            return None
