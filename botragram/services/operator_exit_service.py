"""Guarded PAPER/LIVE operator exit and flatten-and-switch workflow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol
from uuid import uuid4

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    ExchangeEnvironment,
    ExecutionPolicy,
    MarketType,
    OperatorExitAttemptStatus,
    OperatorExitStatus,
    OperatorExitType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.models import (
    OperatorExitAttempt,
    OperatorExitConfirmation,
    OperatorExitOperation,
    OperatorExitSnapshot,
    Order,
    Position,
    SubmissionAttempt,
    Ticker,
    TradingResult,
)
from botragram.repositories import (
    OperatorExitRepository,
    OrderRepository,
    PositionRepository,
    SubmissionAttemptRepository,
)
from botragram.services.closed_position_lifecycle_service import (
    ClosedPositionLifecycleService,
)
from botragram.services.live_position_lifecycle_coordinator import (
    LivePositionLifecycleCoordinator,
)
from botragram.utils.retry import CappedExponentialBackoff

__all__ = ["OperatorExitService"]


_CONFIRMATION_TTL: Final[timedelta] = timedelta(minutes=5)
_FLAT_PROOF_ATTEMPTS: Final[int] = 2
_FLAT_PROOF_DELAY_SECONDS: Final[float] = 0.05
_CLIENT_ORDER_ID_PREFIX: Final[str] = "bop-"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_TERMINAL_REJECTED_ORDER_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {OrderStatus.REJECTED, OrderStatus.CANCELED, OrderStatus.EXPIRED}
)


class _LivePositionAuthority(Protocol):
    """Read current exchange positions while preserving durable metadata."""

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return current positions, optionally synchronized from exchange."""
        ...

    async def observe(self, *, symbol: str) -> Position | None:
        """Read one authoritative position without mutating persistence."""
        ...


class _LiveOperatorExitExchange(Protocol):
    """Expose only exact LIVE close and GET reconciliation operations."""

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        """Submit one reduce-only close from the durable position snapshot."""
        ...

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return one exact close order without creating another order."""
        ...


class _PaperOperatorExit(Protocol):
    """Close PAPER positions through the existing accounting workflow."""

    async def close_position_for_operator(
        self,
        *,
        symbol: str,
        current_price: Decimal,
        closed_at: datetime,
    ) -> TradingResult | None:
        """Close one PAPER position or return None when already flat."""
        ...


class _MarketPriceProvider(Protocol):
    """Read a current price for PAPER operator-exit simulation."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return one current market ticker."""
        ...


class _RuntimePortfolioReconciler(Protocol):
    """Reconcile LIVE protection, lifecycle, and runtime ownership."""

    async def reconcile_context(self) -> object | None:
        """Return reconciled context or None when safety remains unresolved."""
        ...


class _MarketStreamOwner(Protocol):
    """Release process-local stream ownership before a session switch."""

    async def stop_all(self) -> None:
        """Stop every owned market stream."""
        ...


class _ExecutionPolicySwitcher(Protocol):
    """Validate and commit the existing guarded in-process soft restart."""

    @property
    def current_execution_policy(self) -> ExecutionPolicy:
        """Return the policy owned by the current runtime session."""
        ...

    def available_execution_policies(self) -> tuple[ExecutionPolicy, ...]:
        """Return policies inside the immutable boot capability envelope."""
        ...

    async def prepare_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
        allow_operator_exit: bool = False,
    ) -> bool:
        """Stage one target after fresh safety validation."""
        ...

    def commit_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> None:
        """Commit one already-staged target."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class _PendingConfirmation:
    """Bind one confirmation challenge to its requester and action."""

    challenge: OperatorExitConfirmation
    requested_by: str
    symbol: str | None


class _RecoveryPending(RuntimeError):
    """Indicate that durable GET-only recovery must continue."""


class _ExitRejected(RuntimeError):
    """Indicate a proven terminal close rejection without claiming success."""


@dataclass(slots=True, kw_only=True)
class OperatorExitService:
    """Own confirmations, durable LIVE close identity, and safe transitions."""

    trade_mode: TradeMode
    market_type: MarketType
    exchange_environment: ExchangeEnvironment
    runtime_control: TradingRuntimeControl
    operator_exit_repository: OperatorExitRepository
    position_repository: PositionRepository
    market_stream_owner: _MarketStreamOwner
    execution_policy_switcher: _ExecutionPolicySwitcher | None = None
    live_position_service: _LivePositionAuthority | None = None
    live_exchange: _LiveOperatorExitExchange | None = None
    submission_attempt_repository: SubmissionAttemptRepository | None = None
    closed_lifecycle_service: ClosedPositionLifecycleService | None = None
    live_runtime_reconciler: _RuntimePortfolioReconciler | None = None
    order_repository: OrderRepository | None = None
    lifecycle_coordinator: LivePositionLifecycleCoordinator | None = None
    paper_trading_service: _PaperOperatorExit | None = None
    market_price_provider: _MarketPriceProvider | None = None
    confirmation_ttl: timedelta = _CONFIRMATION_TTL
    _pending_confirmation: _PendingConfirmation | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _operation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )
    _recovery_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate mode-specific dependencies without widening capabilities."""
        if self.confirmation_ttl <= timedelta(0):
            raise ValueError("Operator-exit confirmation TTL must be positive")
        if self.trade_mode is TradeMode.LIVE and self.market_type is MarketType.FUTURES:
            if any(
                dependency is None
                for dependency in (
                    self.live_position_service,
                    self.live_exchange,
                    self.submission_attempt_repository,
                    self.closed_lifecycle_service,
                    self.live_runtime_reconciler,
                    self.lifecycle_coordinator,
                )
            ):
                raise ValueError(
                    "LIVE Futures operator-exit dependencies are incomplete"
                )
        if self.trade_mode is TradeMode.PAPER and (
            self.paper_trading_service is None or self.market_price_provider is None
        ):
            raise ValueError("PAPER operator-exit dependencies are incomplete")

    async def initialize(self) -> None:
        """Install the runtime gate before adapters can observe incomplete work."""
        operations = tuple(
            await self.operator_exit_repository.get_incomplete_operations()
        )
        if len(operations) > 1:
            raise RuntimeError("Multiple incomplete operator exits require recovery")
        if operations and not self.runtime_control.operator_exit_in_progress:
            self.runtime_control.pause()
            self.runtime_control.begin_operator_exit()

    async def close(self) -> None:
        """Cancel only the process-local recovery worker during provider shutdown."""
        task = self._recovery_task
        self._recovery_task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def has_incomplete_operation(self) -> bool:
        """Return whether durable operator work still owns the mutation boundary."""
        operations = tuple(
            await self.operator_exit_repository.get_incomplete_operations()
        )
        if len(operations) > 1:
            raise RuntimeError("Multiple incomplete operator exits require recovery")
        return bool(operations)

    async def get_positions(self) -> tuple[Position, ...]:
        """Return the mode-appropriate authoritative position snapshot."""
        if self.trade_mode is TradeMode.PAPER:
            return tuple(await self.position_repository.get_open_positions())
        self._require_live_futures()
        service = self._require(self.live_position_service, "LIVE position service")
        return tuple(await service.get_all(synchronize=True))

    async def get_snapshot(self) -> OperatorExitSnapshot:
        """Return current confirmation, durable recovery, and exposure state."""
        await self._expire_confirmation()
        positions = await self.get_positions()
        pending = self._pending_confirmation
        if pending is not None:
            challenge = pending.challenge
            return OperatorExitSnapshot(
                status=OperatorExitStatus.AWAITING_CONFIRMATION,
                trade_mode=self.trade_mode,
                exchange_environment=self.exchange_environment,
                positions=positions,
                closing_symbols=challenge.symbols,
                target_execution_policy=challenge.target_execution_policy,
            )

        operation = await self.operator_exit_repository.get_latest_operation()
        if operation is None:
            return OperatorExitSnapshot(
                status=OperatorExitStatus.IDLE,
                trade_mode=self.trade_mode,
                exchange_environment=self.exchange_environment,
                positions=positions,
            )
        attempts = tuple(await self.operator_exit_repository.get_incomplete_attempts())
        return OperatorExitSnapshot(
            status=operation.status,
            trade_mode=self.trade_mode,
            exchange_environment=self.exchange_environment,
            positions=positions,
            closing_symbols=tuple(attempt.symbol for attempt in attempts),
            target_execution_policy=operation.target_execution_policy,
            failure_reason=operation.failure_reason,
        )

    async def request_close_position(
        self,
        *,
        symbol: str,
        requested_by: str,
        auto_pause: bool = False,
    ) -> OperatorExitConfirmation:
        """Reserve a no-mutation confirmation for one current position."""
        self._require_supported_mode()
        normalized_symbol = self._normalize_symbol(symbol)
        requester = self._normalize_requester(requested_by)
        if auto_pause:
            self.runtime_control.pause()
        self.runtime_control.begin_operator_exit()
        try:
            positions = await self.get_positions()
            target = next(
                (
                    position
                    for position in positions
                    if position.symbol.upper() == normalized_symbol
                ),
                None,
            )
            if target is None:
                raise RuntimeError("The requested position is already flat")
            await self._preflight_positions(positions=positions)
            return self._set_confirmation(
                operation_type=OperatorExitType.CLOSE_POSITION,
                symbols=(normalized_symbol,),
                requested_by=requester,
                symbol=normalized_symbol,
                target_execution_policy=None,
            )
        except BaseException:
            self._release_runtime_gate()
            raise

    async def request_close_all(
        self,
        *,
        requested_by: str,
        target_execution_policy: ExecutionPolicy | None = None,
        auto_pause: bool = False,
    ) -> OperatorExitConfirmation:
        """Reserve an explicit flatten or flatten-and-switch confirmation."""
        self._require_supported_mode()
        requester = self._normalize_requester(requested_by)
        if target_execution_policy is not None:
            switcher = self._require(
                self.execution_policy_switcher,
                "execution-policy switch service",
            )
            if target_execution_policy is switcher.current_execution_policy:
                raise RuntimeError("Target execution policy is already active")
            if target_execution_policy not in switcher.available_execution_policies():
                raise RuntimeError(
                    "Target execution policy is outside the boot capability envelope"
                )
        if auto_pause:
            self.runtime_control.pause()
        self.runtime_control.begin_operator_exit()
        try:
            positions = tuple(
                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())
            )
            if not positions:
                raise RuntimeError("The authoritative portfolio is already flat")
            await self._preflight_positions(positions=positions)
            operation_type = (
                OperatorExitType.FLATTEN_AND_SWITCH
                if target_execution_policy is not None
                else OperatorExitType.CLOSE_ALL
            )
            return self._set_confirmation(
                operation_type=operation_type,
                symbols=tuple(position.symbol.upper() for position in positions),
                requested_by=requester,
                symbol=None,
                target_execution_policy=target_execution_policy,
            )
        except BaseException:
            self._release_runtime_gate()
            raise

    async def cancel_confirmation(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
    ) -> None:
        """Cancel a process-local challenge without any financial mutation."""
        self._require_pending(
            confirmation_id=confirmation_id,
            requested_by=requested_by,
        )
        self._pending_confirmation = None
        self._release_runtime_gate()

    async def confirm(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
        token: str | None = None,
    ) -> OperatorExitSnapshot:
        """Persist authorization, execute once, then recover without blind POSTs."""
        pending = self._require_pending(
            confirmation_id=confirmation_id,
            requested_by=requested_by,
        )
        challenge = pending.challenge
        supplied = "" if token is None else token.strip().upper()
        if supplied != challenge.required_token:
            raise RuntimeError(
                "The explicit operator-exit confirmation token is invalid"
            )

        now = datetime.now(UTC)
        operation = OperatorExitOperation(
            operation_id=challenge.confirmation_id,
            operation_type=challenge.operation_type,
            status=OperatorExitStatus.FLATTENING,
            requested_by=pending.requested_by,
            symbol=pending.symbol,
            target_execution_policy=challenge.target_execution_policy,
            created_at=now,
            updated_at=now,
        )
        if not await self.operator_exit_repository.reserve_operation(
            operation=operation
        ):
            raise RuntimeError("Another operator exit already owns the portfolio")
        self._pending_confirmation = None

        try:
            await self._run_operation(operation=operation)
        except asyncio.CancelledError:
            await self._mark_recovery_required(
                operation=operation,
                reason="Operator exit was cancelled during durable recovery",
            )
            raise
        except _ExitRejected as error:
            if not await self._handle_proven_rejection(
                operation=operation,
                reason=str(error),
            ):
                self._start_background_recovery()
        except Exception as error:
            try:
                await self._mark_recovery_required(
                    operation=operation,
                    reason=str(error),
                )
            finally:
                self._start_background_recovery()
        return await self.get_snapshot()

    async def recover_until_safe(self) -> None:
        """Recover confirmed work indefinitely with capped operational backoff."""
        backoff = CappedExponentialBackoff()
        recovery_attempt = 0
        while True:
            operations = tuple(
                await self.operator_exit_repository.get_incomplete_operations()
            )
            if not operations:
                return
            if len(operations) != 1:
                raise RuntimeError("Operator-exit recovery is not singular")
            if not self.runtime_control.operator_exit_in_progress:
                self.runtime_control.pause()
                self.runtime_control.begin_operator_exit()
            operation = operations[0]
            try:
                await self._run_operation(operation=operation)
            except asyncio.CancelledError:
                raise
            except _ExitRejected as error:
                if await self._handle_proven_rejection(
                    operation=operation,
                    reason=str(error),
                ):
                    return
                recovery_attempt += 1
            except Exception as error:
                recovery_attempt += 1
                await self._mark_recovery_required(
                    operation=operation,
                    reason=str(error),
                )
            else:
                latest = await self.operator_exit_repository.get_operation(
                    operation_id=operation.operation_id
                )
                if (
                    latest is not None
                    and latest.status is OperatorExitStatus.SWITCH_PENDING
                ):
                    return
                recovery_attempt = 0
                continue

            delay = backoff.get_delay(attempt=recovery_attempt)
            latest = await self.operator_exit_repository.get_operation(
                operation_id=operation.operation_id
            )
            reason = (
                latest.failure_reason
                if latest is not None and latest.failure_reason is not None
                else "operator exit recovery remains unresolved"
            )
            _LOGGER.warning(
                "Operator exit remains fail-closed; recovery will retry: "
                "operation_id=%s attempt=%d next_retry_seconds=%.3f reason=%s",
                operation.operation_id,
                recovery_attempt,
                delay,
                reason,
            )
            await asyncio.sleep(delay)

    async def _run_operation(self, *, operation: OperatorExitOperation) -> None:
        """Advance one confirmed operation under the process-local serializer."""
        async with self._operation_lock:
            latest = await self.operator_exit_repository.get_operation(
                operation_id=operation.operation_id
            )
            current = latest if latest is not None else operation
            if current.status is OperatorExitStatus.SWITCH_PENDING:
                await self._complete_operation(operation=current)
                return

            flattening = replace(
                current,
                status=OperatorExitStatus.FLATTENING,
                failure_reason=None,
                updated_at=datetime.now(UTC),
            )
            await self.operator_exit_repository.save_operation(operation=flattening)
            if self.trade_mode is TradeMode.PAPER:
                await self._run_paper_operation(operation=flattening)
            else:
                await self._run_live_operation(operation=flattening)
            reconciling = replace(
                flattening,
                status=OperatorExitStatus.RECONCILING,
                failure_reason=None,
                updated_at=datetime.now(UTC),
            )
            await self.operator_exit_repository.save_operation(operation=reconciling)
            await self._complete_operation(operation=reconciling)

    async def _run_paper_operation(self, *, operation: OperatorExitOperation) -> None:
        """Close PAPER positions sequentially through normal fill accounting."""
        paper_service = self._require(
            self.paper_trading_service,
            "PAPER trading service",
        )
        price_provider = self._require(
            self.market_price_provider,
            "PAPER price provider",
        )
        while True:
            positions = tuple(
                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())
            )
            targets = self._operation_targets(operation=operation, positions=positions)
            if not targets:
                return
            position = targets[0]
            ticker = await price_provider.get_ticker(symbol=position.symbol)
            await paper_service.close_position_for_operator(
                symbol=position.symbol,
                current_price=ticker.last_price,
                closed_at=ticker.timestamp,
            )

    async def _run_live_operation(self, *, operation: OperatorExitOperation) -> None:
        """Advance exact LIVE close attempts and canonical cleanup sequentially."""
        self._require_live_futures()
        incomplete_entries = tuple(
            await self._require(
                self.submission_attempt_repository,
                "submission attempt repository",
            ).get_incomplete()
        )
        if incomplete_entries:
            raise _RecoveryPending(
                "Incomplete LIVE entry recovery blocks operator exit"
            )

        attempts = tuple(await self.operator_exit_repository.get_incomplete_attempts())
        if len(attempts) > 1:
            raise _RecoveryPending(
                "Multiple LIVE operator-exit attempts are incomplete"
            )
        if attempts:
            await self._recover_live_attempt(attempt=attempts[0])
            await self._reconcile_live_runtime()

        while True:
            positions = tuple(
                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())
            )
            targets = self._operation_targets(operation=operation, positions=positions)
            if not targets:
                await self._reconcile_live_runtime()
                return
            await self._close_live_position(
                operation=operation,
                position=targets[0],
            )
            await self._reconcile_live_runtime()

    async def _close_live_position(
        self,
        *,
        operation: OperatorExitOperation,
        position: Position,
    ) -> None:
        """Reserve, submit once, and reconcile one exact LIVE close identity."""
        coordinator = self._require(
            self.lifecycle_coordinator,
            "LIVE lifecycle coordinator",
        )
        async with coordinator.hold(symbol=position.symbol):
            authority = self._require(
                self.live_position_service,
                "LIVE position service",
            )
            authoritative = await authority.observe(symbol=position.symbol)
            if authoritative is None:
                return
            await self._require_managed_live_position(position=authoritative)
            now = datetime.now(UTC)
            attempt = OperatorExitAttempt(
                client_order_id=f"{_CLIENT_ORDER_ID_PREFIX}{uuid4().hex}",
                operation_id=operation.operation_id,
                symbol=authoritative.symbol.upper(),
                position_side=authoritative.side,
                quantity=authoritative.quantity,
                status=OperatorExitAttemptStatus.PREPARED,
                created_at=now,
                updated_at=now,
            )
            if not await self.operator_exit_repository.reserve_attempt(attempt=attempt):
                raise _RecoveryPending(
                    "Another LIVE operator-exit attempt requires recovery"
                )
            self.runtime_control.set_position_protection_ready(False)
            exchange = self._require(self.live_exchange, "LIVE operator exchange")
            try:
                order = await exchange.close_position_exact(
                    position=authoritative,
                    client_order_id=attempt.client_order_id,
                )
            except ExchangeOrderRejectedError as error:
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        attempt,
                        status=OperatorExitAttemptStatus.REJECTED,
                        failure_reason="Exchange explicitly rejected operator close",
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _ExitRejected(
                    "Exchange explicitly rejected the operator close"
                ) from error
            except ExchangeOrderOutcomeUnknownError as error:
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        attempt,
                        status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                        failure_reason="Close POST outcome is unknown",
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _RecoveryPending(
                    "Close POST outcome is unknown; exact GET recovery is required"
                ) from error
            except asyncio.CancelledError:
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        attempt,
                        status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                        failure_reason="Close POST was cancelled with unknown outcome",
                        updated_at=datetime.now(UTC),
                    )
                )
                raise
            except Exception as error:
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        attempt,
                        status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                        failure_reason="Close POST did not return a proven outcome",
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _RecoveryPending(
                    "Close POST did not return a proven outcome"
                ) from error
            self._validate_exit_order(order=order, attempt=attempt)
            if order.status in _TERMINAL_REJECTED_ORDER_STATUSES:
                if order.executed_quantity != Decimal("0"):
                    await self.operator_exit_repository.save_attempt(
                        attempt=replace(
                            attempt,
                            status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                            exchange_order_id=order.order_id,
                            failure_reason="Terminal close has partial execution",
                            updated_at=datetime.now(UTC),
                        )
                    )
                    raise _RecoveryPending(
                        "Terminal operator close has partial execution"
                    )
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        attempt,
                        status=OperatorExitAttemptStatus.REJECTED,
                        exchange_order_id=order.order_id,
                        failure_reason=(
                            "Exact close order is terminal without execution"
                        ),
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _ExitRejected(
                    "Exact operator close was terminal without execution"
                )
            acknowledged = replace(
                attempt,
                status=OperatorExitAttemptStatus.ACKNOWLEDGED,
                exchange_order_id=order.order_id,
                updated_at=datetime.now(UTC),
            )
            await self.operator_exit_repository.save_attempt(attempt=acknowledged)
        await self._recover_live_attempt(attempt=acknowledged)

    async def _recover_live_attempt(self, *, attempt: OperatorExitAttempt) -> None:
        """Use exact GET and repeated zero exposure before lifecycle staging."""
        coordinator = self._require(
            self.lifecycle_coordinator,
            "LIVE lifecycle coordinator",
        )
        async with coordinator.hold(symbol=attempt.symbol):
            reconciling = replace(
                attempt,
                status=OperatorExitAttemptStatus.RECONCILING,
                updated_at=datetime.now(UTC),
            )
            await self.operator_exit_repository.save_attempt(attempt=reconciling)
            exchange = self._require(self.live_exchange, "LIVE operator exchange")
            try:
                order = await exchange.get_order_by_client_order_id(
                    symbol=attempt.symbol,
                    client_order_id=attempt.client_order_id,
                )
            except (
                ExchangeOrderNotFoundError,
                ExchangeOrderOutcomeUnknownError,
            ) as error:
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        reconciling,
                        status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                        failure_reason="Exact close identity is not authoritative",
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _RecoveryPending(
                    "Exact operator close identity is not yet authoritative"
                ) from error
            self._validate_exit_order(order=order, attempt=attempt)
            if order.status in _TERMINAL_REJECTED_ORDER_STATUSES:
                if order.executed_quantity != Decimal("0"):
                    await self.operator_exit_repository.save_attempt(
                        attempt=replace(
                            reconciling,
                            status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                            exchange_order_id=order.order_id,
                            failure_reason="Terminal close has partial execution",
                            updated_at=datetime.now(UTC),
                        )
                    )
                    raise _RecoveryPending(
                        "Terminal operator close has partial execution"
                    )
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        reconciling,
                        status=OperatorExitAttemptStatus.REJECTED,
                        exchange_order_id=order.order_id,
                        failure_reason=(
                            "Exact close order is terminal without execution"
                        ),
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _ExitRejected(
                    "Exact operator close was terminal without execution"
                )
            if order.status is not OrderStatus.FILLED:
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        reconciling,
                        status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                        exchange_order_id=order.order_id,
                        failure_reason="Exact close order is not FILLED",
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _RecoveryPending("Exact operator close is not FILLED")
            if not await self._prove_flat(symbol=attempt.symbol):
                await self.operator_exit_repository.save_attempt(
                    attempt=replace(
                        reconciling,
                        status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,
                        exchange_order_id=order.order_id,
                        failure_reason=(
                            "FILLED close has not produced stable zero exposure"
                        ),
                        updated_at=datetime.now(UTC),
                    )
                )
                raise _RecoveryPending(
                    "FILLED operator close has not produced stable zero exposure"
                )

            stored_position = await self.position_repository.get_by_symbol(
                symbol=attempt.symbol,
            )
            if stored_position is None:
                raise _RecoveryPending(
                    "Durable position identity is unavailable for exit lifecycle"
                )
            entry_attempt = await self._get_completed_entry(position=stored_position)
            lifecycle = self._require(
                self.closed_lifecycle_service,
                "closed lifecycle service",
            )
            if not await lifecycle.has_durable_ownership(
                entry_client_order_id=entry_attempt.client_order_id,
            ):
                await lifecycle.stage(
                    position=stored_position,
                    attempt=entry_attempt,
                    exit_order=order,
                    close_reason=ClosedPositionReason.OPERATOR_EXIT,
                    provenance=ClosedPositionProvenance.OPERATOR_EXIT_ORDER,
                )
            order_repository = self.order_repository
            if order_repository is not None:
                await order_repository.save(order=order)
            await self.operator_exit_repository.save_attempt(
                attempt=replace(
                    reconciling,
                    status=OperatorExitAttemptStatus.COMPLETED,
                    exchange_order_id=order.order_id,
                    failure_reason=None,
                    updated_at=datetime.now(UTC),
                )
            )

    async def _reconcile_live_runtime(self) -> None:
        """Require canonical protection cleanup and runtime ownership convergence."""
        reconciler = self._require(
            self.live_runtime_reconciler,
            "LIVE runtime reconciler",
        )
        if await reconciler.reconcile_context() is None:
            raise _RecoveryPending(
                "LIVE protection/runtime reconciliation remains incomplete"
            )
        if not self.runtime_control.is_position_protection_ready:
            raise _RecoveryPending("LIVE protection state is not READY")

    async def _complete_operation(self, *, operation: OperatorExitOperation) -> None:
        """Freshly verify safety, then durably hand off an optional soft restart."""
        positions = await self.get_positions()
        targets = self._operation_targets(operation=operation, positions=positions)
        if targets:
            raise _RecoveryPending("Authoritative target exposure remains open")

        target_policy = operation.target_execution_policy
        switcher = self.execution_policy_switcher
        if target_policy is not None:
            if switcher is None:
                raise _RecoveryPending("Execution-policy switch service is unavailable")
            switch_pending = replace(
                operation,
                status=OperatorExitStatus.SWITCH_PENDING,
                failure_reason=None,
                updated_at=datetime.now(UTC),
            )
            await self.operator_exit_repository.save_operation(operation=switch_pending)
            if self.trade_mode is TradeMode.PAPER:
                await self.market_stream_owner.stop_all()
            changed = await switcher.prepare_execution_policy(
                execution_policy=target_policy,
                allow_operator_exit=True,
            )
            if changed:
                switcher.commit_execution_policy(execution_policy=target_policy)
                _LOGGER.info(
                    "Operator exit handed off durable switch: operation_id=%s "
                    "target_policy=%s",
                    operation.operation_id,
                    target_policy.value,
                )
                return
            await self.operator_exit_repository.save_operation(
                operation=replace(
                    switch_pending,
                    status=OperatorExitStatus.COMPLETE,
                    updated_at=datetime.now(UTC),
                )
            )
            self._release_runtime_gate()
        else:
            await self.operator_exit_repository.save_operation(
                operation=replace(
                    operation,
                    status=OperatorExitStatus.COMPLETE,
                    failure_reason=None,
                    updated_at=datetime.now(UTC),
                )
            )
            self._release_runtime_gate()
        _LOGGER.info(
            "Operator exit completed: operation_id=%s type=%s target_policy=%s",
            operation.operation_id,
            operation.operation_type.value,
            target_policy.value if target_policy is not None else "none",
        )

    async def _preflight_positions(self, *, positions: Sequence[Position]) -> None:
        """Reject LIVE operator mutations until the whole portfolio is managed."""
        if self.trade_mode is not TradeMode.LIVE:
            return
        self._require_live_futures()
        if not self.runtime_control.is_position_protection_ready:
            raise RuntimeError(
                "LIVE operator exit requires READY protection/recovery state"
            )
        repository = self._require(
            self.submission_attempt_repository,
            "submission attempt repository",
        )
        if await repository.get_incomplete():
            raise RuntimeError(
                "Incomplete LIVE entry recovery blocks operator exit confirmation"
            )
        if await self.operator_exit_repository.get_incomplete_attempts():
            raise RuntimeError(
                "Incomplete LIVE operator-exit recovery blocks new confirmation"
            )
        context_symbols = {
            context.symbol.upper() for context in self.runtime_control.runtime_contexts
        }
        position_symbols = {position.symbol.upper() for position in positions}
        if position_symbols != context_symbols:
            raise RuntimeError(
                "LIVE operator exit requires exact runtime ownership for all positions"
            )
        for position in positions:
            await self._require_managed_live_position(position=position)

    async def _require_managed_live_position(self, *, position: Position) -> None:
        """Require exact durable entry ownership before any operator close POST."""
        await self._get_completed_entry(position=position)
        if (
            position.stop_loss_client_algo_id is None
            or position.take_profit_client_algo_id is None
        ):
            raise RuntimeError(
                "Operator exit requires exact durable STOP and TP ownership"
            )

    async def _get_completed_entry(self, *, position: Position) -> SubmissionAttempt:
        """Return the exact completed entry attempt for one managed position."""
        entry_identity = position.entry_client_order_id
        repository = self._require(
            self.submission_attempt_repository,
            "submission attempt repository",
        )
        if entry_identity is None:
            raise RuntimeError("Operator exit requires a durable entry identity")
        attempt = await repository.get_by_client_order_id(
            client_order_id=entry_identity,
        )
        if (
            attempt is None
            or attempt.status is not SubmissionAttemptStatus.COMPLETED
            or attempt.exchange_order_id is None
            or attempt.symbol.upper() != position.symbol.upper()
        ):
            raise RuntimeError("Operator exit requires a completed exact LIVE entry")
        return attempt

    async def _prove_flat(self, *, symbol: str) -> bool:
        """Require repeated authoritative zero-exposure observations."""
        authority = self._require(
            self.live_position_service,
            "LIVE position service",
        )
        for attempt_index in range(_FLAT_PROOF_ATTEMPTS):
            if await authority.observe(symbol=symbol) is not None:
                return False
            if attempt_index + 1 < _FLAT_PROOF_ATTEMPTS:
                await asyncio.sleep(_FLAT_PROOF_DELAY_SECONDS)
        return True

    async def _handle_proven_rejection(
        self,
        *,
        operation: OperatorExitOperation,
        reason: str,
    ) -> bool:
        """Restore canonical protection before releasing a proven rejected close."""
        if self.trade_mode is TradeMode.LIVE:
            try:
                await self._reconcile_live_runtime()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self._mark_recovery_required(
                    operation=operation,
                    reason=f"{reason}; protection recovery failed: {error}",
                )
                return False
        await self._mark_failed(operation=operation, reason=reason)
        self._release_runtime_gate()
        return True

    def _set_confirmation(
        self,
        *,
        operation_type: OperatorExitType,
        symbols: tuple[str, ...],
        requested_by: str,
        symbol: str | None,
        target_execution_policy: ExecutionPolicy | None,
    ) -> OperatorExitConfirmation:
        """Create one bounded challenge while the runtime remains paused."""
        requires_typed = (
            self.trade_mode is TradeMode.LIVE
            and self.exchange_environment is ExchangeEnvironment.MAINNET
        )
        required_token = (
            f"CLOSE {symbols[0]}"
            if operation_type is OperatorExitType.CLOSE_POSITION
            else f"FLATTEN {len(symbols)}"
        )
        challenge = OperatorExitConfirmation(
            confirmation_id=uuid4().hex,
            operation_type=operation_type,
            environment=(
                "PAPER"
                if self.trade_mode is TradeMode.PAPER
                else self.exchange_environment.value.upper()
            ),
            symbols=symbols,
            required_token=required_token if requires_typed else "CONFIRM",
            requires_typed_confirmation=requires_typed,
            expires_at=datetime.now(UTC) + self.confirmation_ttl,
            target_execution_policy=target_execution_policy,
        )
        self._pending_confirmation = _PendingConfirmation(
            challenge=challenge,
            requested_by=requested_by,
            symbol=symbol,
        )
        return challenge

    def _require_pending(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
    ) -> _PendingConfirmation:
        """Return one unexpired challenge bound to the exact requester."""
        pending = self._pending_confirmation
        if pending is None:
            raise RuntimeError("Operator-exit confirmation is unavailable")
        if pending.challenge.expires_at <= datetime.now(UTC):
            self._pending_confirmation = None
            self._release_runtime_gate()
            raise RuntimeError("Operator-exit confirmation expired")
        if pending.challenge.confirmation_id != confirmation_id.strip().lower():
            raise RuntimeError("Operator-exit confirmation identity does not match")
        if pending.requested_by != self._normalize_requester(requested_by):
            raise RuntimeError("Operator-exit confirmation belongs to another chat")
        return pending

    async def _expire_confirmation(self) -> None:
        """Release an expired no-mutation confirmation reservation."""
        pending = self._pending_confirmation
        if pending is not None and pending.challenge.expires_at <= datetime.now(UTC):
            self._pending_confirmation = None
            self._release_runtime_gate()

    async def _mark_recovery_required(
        self,
        *,
        operation: OperatorExitOperation,
        reason: str,
    ) -> None:
        """Persist a fail-closed recovery reason without releasing the gate."""
        latest = await self.operator_exit_repository.get_operation(
            operation_id=operation.operation_id
        )
        base = latest if latest is not None else operation
        await self.operator_exit_repository.save_operation(
            operation=replace(
                base,
                status=OperatorExitStatus.RECOVERY_REQUIRED,
                failure_reason=reason,
                updated_at=datetime.now(UTC),
            )
        )
        self.runtime_control.pause()
        self.runtime_control.set_position_protection_ready(False)

    async def _mark_failed(
        self,
        *,
        operation: OperatorExitOperation,
        reason: str,
    ) -> None:
        """Persist a proven non-executed terminal failure."""
        latest = await self.operator_exit_repository.get_operation(
            operation_id=operation.operation_id
        )
        base = latest if latest is not None else operation
        await self.operator_exit_repository.save_operation(
            operation=replace(
                base,
                status=OperatorExitStatus.FAILED,
                failure_reason=reason,
                updated_at=datetime.now(UTC),
            )
        )

    def _start_background_recovery(self) -> None:
        """Start one owned unlimited recovery worker for an in-process failure."""
        task = self._recovery_task
        if task is not None and not task.done():
            return
        self._recovery_task = asyncio.create_task(
            self._background_recovery(),
            name="botragram-operator-exit-recovery",
        )

    async def _background_recovery(self) -> None:
        """Run unlimited recovery and keep unexpected failure visible in logs."""
        try:
            await self.recover_until_safe()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Operator-exit background recovery stopped unexpectedly")

    @staticmethod
    def _operation_targets(
        *,
        operation: OperatorExitOperation,
        positions: Sequence[Position],
    ) -> tuple[Position, ...]:
        """Return the authoritative positions covered by one confirmed operation."""
        if operation.operation_type is OperatorExitType.CLOSE_POSITION:
            return tuple(
                position
                for position in positions
                if position.symbol.upper() == operation.symbol
            )
        return tuple(positions)

    @staticmethod
    def _validate_exit_order(
        *,
        order: Order,
        attempt: OperatorExitAttempt,
    ) -> None:
        """Require exact deterministic identity and reduce-only close shape."""
        expected_side = (
            OrderSide.SELL
            if attempt.position_side is PositionSide.LONG
            else OrderSide.BUY
        )
        if (
            order.client_order_id != attempt.client_order_id
            or order.symbol.upper() != attempt.symbol
            or order.side is not expected_side
            or order.order_type is not OrderType.MARKET
            or order.quantity != attempt.quantity
        ):
            raise RuntimeError("Exchange operator close does not match durable intent")

    def _require_supported_mode(self) -> None:
        """Reject unsupported LIVE Spot exits without changing network authority."""
        if self.trade_mode is TradeMode.LIVE:
            self._require_live_futures()

    def _require_live_futures(self) -> None:
        """Limit financial LIVE exits to the audited Binance Futures workflow."""
        if self.market_type is not MarketType.FUTURES:
            raise RuntimeError("LIVE operator exits currently require Futures")

    def _release_runtime_gate(self) -> None:
        """Release only this service's operator-exit runtime reservation."""
        if self.runtime_control.operator_exit_in_progress:
            self.runtime_control.end_operator_exit()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized or not normalized.isalnum():
            raise ValueError("Operator-exit symbol must be alphanumeric")
        return normalized

    @staticmethod
    def _normalize_requester(requested_by: str) -> str:
        normalized = requested_by.strip()
        if not normalized:
            raise ValueError("Operator-exit requester must not be empty")
        return normalized

    @staticmethod
    def _require[T](dependency: T | None, label: str) -> T:
        if dependency is None:
            raise RuntimeError(f"{label} is unavailable")
        return dependency
