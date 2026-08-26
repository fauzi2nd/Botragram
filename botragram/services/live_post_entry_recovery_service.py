"""
Botragram

Description:
    Restore one acknowledged LIVE entry through authoritative position state.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import unique
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SubmissionAttemptStatus,
)
from botragram.enums.base import BaseEnum
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderPriceBandRejectedError,
    VenueRuleValidationError,
)
from botragram.models import Order, Position, SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository
from botragram.services.closed_position_lifecycle_service import (
    ClosedPositionLifecycleService,
)

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "LivePostEntryRecoveryResult",
    "LivePostEntryRecoveryService",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_POSITION_VISIBILITY_MAX_ATTEMPTS: Final[int] = 2
_POSITION_VISIBILITY_DELAY_SECONDS: Final[float] = 0.05
_EMERGENCY_EXIT_PRICE_BAND_MAX_SUBMISSIONS: Final[int] = 2
_EMERGENCY_EXIT_PRICE_BAND_RETRY_DELAY_SECONDS: Final[float] = 0.25
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Protocols
# =============================================================================
class LivePositionVisibility(Protocol):
    """Read and persist an authoritative exchange position snapshot."""

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return one optionally synchronized position."""
        ...

    async def save(self, *, position: Position) -> None:
        """Persist one position with its runtime metadata."""
        ...

    async def delete(self, *, symbol: str) -> bool:
        """Delete a stored position by symbol."""
        ...

    async def observe(self, *, symbol: str) -> Position | None:
        """Read authoritative position state without mutating persistence."""
        ...


class LiveProtectionVerification(Protocol):
    """Verify complete exchange protection for one position."""

    async def ensure(self, *, position: Position) -> Position:
        """Return a position whose protection is exchange-verified."""
        ...

    async def probe_persisted_leg(
        self, *, position: Position, order_type: OrderType, client_id: str
    ) -> str:
        """Probe a persisted protection identity in a GET-only manner.

        Returns one of: "not_found", "active", "terminal", "unexpected", "unknown".
        """
        ...


class LiveAcknowledgedEntryRecovery(Protocol):
    """Complete one acknowledged entry without exposing entry mutation."""

    async def recover_acknowledged(
        self,
        *,
        attempt: SubmissionAttempt,
    ) -> LivePostEntryRecoveryResult:
        """Return the recovery result for the durable acknowledged attempt."""
        ...


class LiveOrderFetch(Protocol):
    """Fetch an authoritative exchange order by client-assigned id."""

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Return the authoritative order snapshot for the client id."""
        ...


class LiveProtectionCleanup(Protocol):
    """Cancel only exact durable protection identities."""

    async def cancel_persisted_legs(self, *, position: Position) -> None:
        """Cancel persisted STOP/TP identities and prove them absent."""
        ...


class LiveEmergencyExitExchange(Protocol):
    """Submit one deterministic reduce-only emergency position close."""

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
    ) -> Order:
        """Close one active Futures position."""
        ...


# =============================================================================
# Enums
# =============================================================================
@unique
class LivePostEntryRecoveryResult(BaseEnum):
    """Outcome of recovery after an entry is durably acknowledged."""

    COMPLETED = "completed"
    RESOLVED_NO_EXPOSURE = "resolved_no_exposure"
    POSITION_NOT_VISIBLE = "position_not_visible"


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LivePostEntryRecoveryService:
    """Complete one acknowledged LIVE entry without querying or creating it."""

    submission_attempt_repository: SubmissionAttemptRepository
    live_recovery_repository: LiveRecoveryRepository
    position_service: LivePositionVisibility
    protection_service: LiveProtectionVerification
    runtime_control: TradingRuntimeControl
    order_service: LiveOrderFetch | None = None
    # Optional protection reconciler to probe persisted protection identities
    protection_reconciler: LiveProtectionVerification | None = None
    protection_cleanup_service: LiveProtectionCleanup | None = None
    emergency_exit_exchange: LiveEmergencyExitExchange | None = None
    closed_lifecycle_service: ClosedPositionLifecycleService | None = None

    async def recover_acknowledged(
        self,
        *,
        attempt: SubmissionAttempt,
    ) -> LivePostEntryRecoveryResult:
        """Restore position metadata, protection, and durable completion.

        The acknowledged attempt remains incomplete whenever exchange position
        visibility is absent or any later safety operation raises.

        Args:
            attempt: The sole entry attempt already acknowledged by the exchange.

        Returns:
            The completed or still-not-visible recovery outcome.

        Raises:
            RuntimeError: If the attempt is not acknowledged or protection fails.
            asyncio.CancelledError: If recovery is cancelled.
        """
        if attempt.status is not SubmissionAttemptStatus.ACKNOWLEDGED:
            raise RuntimeError("Post-entry recovery requires an acknowledged attempt")

        self.runtime_control.set_position_protection_ready(False)
        position = await self._get_visible_position(symbol=attempt.symbol)

        if position is None:
            _LOGGER.warning(
                "Acknowledged LIVE entry position is not yet visible: "
                "symbol=%s client_order_id=%s",
                attempt.symbol,
                attempt.client_order_id,
            )
            # Require a persisted authoritative position from a prior sync to
            # prove the entry was previously visible.
            persisted = await self.position_service.get(
                symbol=attempt.symbol,
                synchronize=False,
            )
            if persisted is None:
                return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

            # Position/attempt correlation gate. Fetch one authoritative order
            # after identity mismatch is ruled out so ``order`` is always bound.
            if (
                persisted.entry_client_order_id is not None
                and persisted.entry_client_order_id != attempt.client_order_id
            ):
                _LOGGER.warning(
                    "Position entry identity mismatch: persisted=%s attempt=%s",
                    persisted.entry_client_order_id,
                    attempt.client_order_id,
                )
                return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

            if self.order_service is None:
                return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

            try:
                order = await self.order_service.get_by_client_order_id(
                    symbol=attempt.symbol,
                    client_order_id=attempt.client_order_id,
                )
            except Exception:
                return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

            if persisted.entry_client_order_id is None:
                if not self._legacy_correlation_proof(
                    attempt=attempt,
                    persisted=persisted,
                    order=order,
                ):
                    return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

            if order.status is OrderStatus.FILLED:
                if not await self._reconcile_zero_exposure_protection(
                    position=persisted,
                ):
                    return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE
                lifecycle_id = await self._stage_existing_recovery_lifecycle(
                    attempt=attempt,
                    position=persisted,
                )
                await self._resolve_no_exposure(attempt=attempt)
                await self._complete_recovery_lifecycle_best_effort(
                    entry_client_order_id=lifecycle_id,
                )
                return LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE

            return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

        persisted_position = replace(
            position,
            interval=attempt.interval,
            strategy_type=attempt.strategy_type,
            entry_client_order_id=attempt.client_order_id,
        )
        await self.position_service.save(position=persisted_position)
        _LOGGER.info(
            "Acknowledged LIVE entry position synchronized: symbol=%s quantity=%s "
            "entry_price=%s",
            persisted_position.symbol,
            persisted_position.quantity,
            persisted_position.entry_price,
        )

        try:
            await self.protection_service.ensure(position=persisted_position)
        except VenueRuleValidationError as error:
            _LOGGER.warning(
                "Acknowledged LIVE entry protection plan is no longer venue-valid; "
                "starting deterministic reduce-only recovery exit: symbol=%s",
                persisted_position.symbol,
            )
            await self._recover_unprotectable_position(
                attempt=attempt,
                position=persisted_position,
                cause=error,
            )
            return LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE

        await self.submission_attempt_repository.save(
            attempt=replace(
                attempt,
                status=SubmissionAttemptStatus.COMPLETED,
                updated_at=datetime.now(UTC),
            )
        )
        self.runtime_control.set_position_protection_ready(True)
        _LOGGER.info(
            "Acknowledged LIVE entry recovery completed: symbol=%s client_order_id=%s",
            attempt.symbol,
            attempt.client_order_id,
        )
        return LivePostEntryRecoveryResult.COMPLETED

    async def _reconcile_zero_exposure_protection(
        self,
        *,
        position: Position,
    ) -> bool:
        """Clean exact owned orphan legs after an already bounded absence proof.

        ``recover_acknowledged`` reaches this helper only after
        ``_get_visible_position`` has already produced two consecutive
        authoritative zero-exposure observations. Do not spend another read
        unless an owned protection mutation is actually required.
        """
        reconciler = self.protection_reconciler or self.protection_service
        has_active_leg = False

        try:
            for order_type, client_id in (
                (OrderType.STOP_MARKET, position.stop_loss_client_algo_id),
                (OrderType.TAKE_PROFIT_MARKET, position.take_profit_client_algo_id),
            ):
                if client_id is None:
                    continue
                status = await reconciler.probe_persisted_leg(
                    position=position,
                    order_type=order_type,
                    client_id=client_id,
                )
                if status == "active":
                    has_active_leg = True
                    continue
                if status in {"not_found", "terminal"}:
                    continue
                return False
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "LIVE zero-exposure protection probe failed: symbol=%s",
                position.symbol,
            )
            return False

        if not has_active_leg:
            return True

        cleanup = self.protection_cleanup_service
        if cleanup is None:
            return False

        if await self._get_visible_position(symbol=position.symbol) is not None:
            return False

        try:
            await cleanup.cancel_persisted_legs(position=position)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "LIVE zero-exposure protection cleanup failed: symbol=%s",
                position.symbol,
            )
            return False

        return await self._get_visible_position(symbol=position.symbol) is None

    async def _recover_unprotectable_position(
        self,
        *,
        attempt: SubmissionAttempt,
        position: Position,
        cause: VenueRuleValidationError,
    ) -> None:
        """Close an unprotectable acknowledged entry exactly once per durable id."""
        order_service = self.order_service
        exchange = self.emergency_exit_exchange
        if order_service is None or exchange is None:
            raise RuntimeError(
                "Restart-safe emergency exit dependencies are unavailable"
            ) from cause

        current = await self._get_visible_position(symbol=position.symbol)
        if current is None:
            if not await self._reconcile_zero_exposure_protection(position=position):
                raise RuntimeError(
                    "Zero exposure could not be proven safe after protection failure"
                ) from cause
            lifecycle_id = await self._stage_existing_recovery_lifecycle(
                attempt=attempt,
                position=position,
            )
            await self._resolve_no_exposure(attempt=attempt)
            await self._complete_recovery_lifecycle_best_effort(
                entry_client_order_id=lifecycle_id,
            )
            return

        exit_client_id = self._emergency_exit_client_order_id(
            entry_client_order_id=attempt.client_order_id,
        )
        existing_exit: Order | None = None
        try:
            existing_exit = await order_service.get_by_client_order_id(
                symbol=attempt.symbol,
                client_order_id=exit_client_id,
            )
        except ExchangeOrderNotFoundError:
            existing_exit = None
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Emergency exit identity could not be reconciled"
            ) from error

        exit_order: Order | None = existing_exit
        if existing_exit is not None:
            self._validate_emergency_exit_order(
                order=existing_exit,
                attempt=attempt,
                position=current,
                client_order_id=exit_client_id,
            )
            if existing_exit.status is not OrderStatus.FILLED:
                raise RuntimeError(
                    "Existing emergency exit is not in a proven FILLED state"
                )
        else:
            exit_order = await self._submit_emergency_exit(
                attempt=attempt,
                position=position,
                exit_client_id=exit_client_id,
                order_service=order_service,
                exchange=exchange,
            )

        if await self._get_visible_position(symbol=position.symbol) is not None:
            raise RuntimeError(
                "Emergency exit did not prove zero authoritative exposure"
            )

        if not await self._reconcile_zero_exposure_protection(position=position):
            raise RuntimeError("Emergency exit left protection cleanup unresolved")

        lifecycle_id = await self._stage_recovery_lifecycle(
            attempt=attempt,
            position=position,
            exit_order=exit_order,
            close_reason=(
                ClosedPositionReason.RECOVERY_CLOSE
                if existing_exit is not None
                else ClosedPositionReason.EMERGENCY_CLOSE
            ),
        )
        await self._resolve_no_exposure(attempt=attempt)
        await self._complete_recovery_lifecycle_best_effort(
            entry_client_order_id=lifecycle_id,
        )

    async def _submit_emergency_exit(
        self,
        *,
        attempt: SubmissionAttempt,
        position: Position,
        exit_client_id: str,
        order_service: LiveOrderFetch,
        exchange: LiveEmergencyExitExchange,
    ) -> Order | None:
        """Submit a deterministic emergency exit with one price-band retry."""
        for submission_index in range(_EMERGENCY_EXIT_PRICE_BAND_MAX_SUBMISSIONS):
            current = await self._get_visible_position(symbol=position.symbol)
            if current is None:
                return None

            try:
                close_order = await exchange.close_position(
                    symbol=attempt.symbol,
                    client_order_id=exit_client_id,
                )
            except ExchangeOrderPriceBandRejectedError as error:
                try:
                    existing_exit = await order_service.get_by_client_order_id(
                        symbol=attempt.symbol,
                        client_order_id=exit_client_id,
                    )
                except ExchangeOrderNotFoundError:
                    existing_exit = None
                except ExchangeOrderOutcomeUnknownError as lookup_error:
                    raise RuntimeError(
                        "Emergency exit identity could not be reconciled "
                        "after price-band rejection"
                    ) from lookup_error

                if existing_exit is not None:
                    self._validate_emergency_exit_order(
                        order=existing_exit,
                        attempt=attempt,
                        position=current,
                        client_order_id=exit_client_id,
                    )
                    if existing_exit.status is OrderStatus.FILLED:
                        return existing_exit
                    raise RuntimeError(
                        "Price-band rejected emergency exit identity exists "
                        "without a proven FILLED state"
                    )

                if await self._get_visible_position(symbol=position.symbol) is None:
                    return None

                if submission_index + 1 >= _EMERGENCY_EXIT_PRICE_BAND_MAX_SUBMISSIONS:
                    raise RuntimeError(
                        "Emergency exit remained blocked by the venue price band"
                    ) from error

                _LOGGER.warning(
                    "Emergency exit rejected by venue price band; retrying once "
                    "after exact identity reconciliation: symbol=%s "
                    "client_order_id=%s",
                    attempt.symbol,
                    exit_client_id,
                )
                await asyncio.sleep(_EMERGENCY_EXIT_PRICE_BAND_RETRY_DELAY_SECONDS)
                continue
            except ExchangeOrderOutcomeUnknownError:
                if await self._get_visible_position(symbol=position.symbol) is not None:
                    raise RuntimeError(
                        "Emergency exit outcome is unknown while exposure remains"
                    )
                return None

            self._validate_emergency_exit_order(
                order=close_order,
                attempt=attempt,
                position=current,
                client_order_id=exit_client_id,
            )
            return close_order

        raise RuntimeError("Emergency exit submission budget was exhausted")

    async def _stage_recovery_lifecycle(
        self,
        *,
        attempt: SubmissionAttempt,
        position: Position,
        exit_order: Order | None,
        close_reason: ClosedPositionReason,
    ) -> str | None:
        """Require durable recovery ownership before terminalizing local identity."""
        service = self.closed_lifecycle_service
        if service is None:
            return None
        if await service.has_durable_ownership(
            entry_client_order_id=attempt.client_order_id,
        ):
            return attempt.client_order_id
        if exit_order is None:
            raise RuntimeError(
                "Recovery cannot terminalize without durable exit ownership"
            )
        await service.stage(
            position=position,
            attempt=attempt,
            exit_order=exit_order,
            close_reason=close_reason,
            provenance=ClosedPositionProvenance.RECOVERY_EMERGENCY_ORDER,
        )
        return attempt.client_order_id

    async def _stage_existing_recovery_lifecycle(
        self,
        *,
        attempt: SubmissionAttempt,
        position: Position,
    ) -> str | None:
        """Require existing or recovered ownership before local terminalization."""
        service = self.closed_lifecycle_service
        order_service = self.order_service
        if service is None:
            return None
        if await service.has_durable_ownership(
            entry_client_order_id=attempt.client_order_id,
        ):
            return attempt.client_order_id
        if order_service is None:
            raise RuntimeError(
                "Recovery cannot prove durable exit ownership without order lookup"
            )
        exit_client_id = self._emergency_exit_client_order_id(
            entry_client_order_id=attempt.client_order_id,
        )
        try:
            exit_order = await order_service.get_by_client_order_id(
                symbol=attempt.symbol,
                client_order_id=exit_client_id,
            )
            self._validate_emergency_exit_order(
                order=exit_order,
                attempt=attempt,
                position=position,
                client_order_id=exit_client_id,
            )
            if exit_order.status is not OrderStatus.FILLED:
                raise RuntimeError(
                    "Recovered emergency exit is not in a proven FILLED state"
                )
        except ExchangeOrderNotFoundError as error:
            raise RuntimeError(
                "Recovery cannot prove a durable emergency exit identity"
            ) from error
        except asyncio.CancelledError:
            raise
        return await self._stage_recovery_lifecycle(
            attempt=attempt,
            position=position,
            exit_order=exit_order,
            close_reason=ClosedPositionReason.RECOVERY_CLOSE,
        )

    async def _complete_recovery_lifecycle_best_effort(
        self,
        *,
        entry_client_order_id: str | None,
    ) -> None:
        """Complete staged performance only after safety state is terminal."""
        service = self.closed_lifecycle_service
        if entry_client_order_id is not None and service is not None:
            await service.complete_best_effort(
                entry_client_order_id=entry_client_order_id,
            )

    async def _resolve_no_exposure(self, *, attempt: SubmissionAttempt) -> None:
        """Atomically terminalize one acknowledged entry after zero exposure proof."""
        resolved_attempt = replace(
            attempt,
            status=SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE,
            updated_at=datetime.now(UTC),
        )
        await self.live_recovery_repository.resolve_no_exposure(
            symbol=attempt.symbol,
            attempt=resolved_attempt,
        )
        self.runtime_control.set_position_protection_ready(True)
        _LOGGER.info(
            "Acknowledged LIVE entry resolved with no exposure: "
            "symbol=%s client_order_id=%s",
            attempt.symbol,
            attempt.client_order_id,
        )

    @staticmethod
    def _emergency_exit_client_order_id(*, entry_client_order_id: str) -> str:
        """Derive one deterministic 36-character exit identity from btg-* entry id."""
        if not entry_client_order_id.startswith("btg-"):
            raise RuntimeError("Emergency exit requires a canonical btg-* entry id")
        suffix = entry_client_order_id.removeprefix("btg-")
        if len(suffix) != 32:
            raise RuntimeError("Emergency exit requires a 32-character entry suffix")
        return f"bex-{suffix}"

    @staticmethod
    def _validate_emergency_exit_order(
        *,
        order: Order,
        attempt: SubmissionAttempt,
        position: Position,
        client_order_id: str,
    ) -> None:
        """Require exact deterministic identity before trusting an emergency close."""
        closing_side = (
            OrderSide.SELL if attempt.side is OrderSide.BUY else OrderSide.BUY
        )
        if (
            order.client_order_id != client_order_id
            or order.symbol.upper() != attempt.symbol.upper()
            or order.side is not closing_side
            or order.order_type is not OrderType.MARKET
            or order.quantity < position.quantity
        ):
            raise RuntimeError(
                "Emergency exit order does not match the acknowledged entry"
            )

    async def _get_visible_position(self, *, symbol: str) -> Position | None:
        """Return a bounded authoritative positive-quantity position snapshot."""
        for visibility_attempt in range(_POSITION_VISIBILITY_MAX_ATTEMPTS):
            position = await self.position_service.observe(
                symbol=symbol,
            )
            if position is not None and position.quantity > _DECIMAL_ZERO:
                return position

            if visibility_attempt + 1 < _POSITION_VISIBILITY_MAX_ATTEMPTS:
                await asyncio.sleep(_POSITION_VISIBILITY_DELAY_SECONDS)

        return None

    @staticmethod
    def _legacy_correlation_proof(
        *,
        attempt: SubmissionAttempt,
        persisted: Position,
        order: Order,
    ) -> bool:
        """Return True only when NULL-identity evidence fully correlates.

        Timestamps are omitted: local scratch does not contain authoritative
        Run #2 order created_at/updated_at values, so a causal clock rule is
        not asserted. Signal time is never used.

        Quantity: Order.quantity is origQty and Order.executed_quantity is
        executedQty. FILLED proof requires executedQty to equal the persisted
        and attempted size. origQty may exceed executedQty; executedQty may
        not exceed origQty.
        """
        if order.client_order_id is None:
            _LOGGER.warning("Legacy correlation: order client_order_id is missing")
            return False

        if order.client_order_id != attempt.client_order_id:
            _LOGGER.warning(
                "Legacy correlation: client_order_id mismatch order=%s attempt=%s",
                order.client_order_id,
                attempt.client_order_id,
            )
            return False

        if attempt.exchange_order_id is None:
            _LOGGER.warning("Legacy correlation: attempt exchange_order_id is missing")
            return False

        if order.order_id != attempt.exchange_order_id:
            _LOGGER.warning(
                "Legacy correlation: exchange order id mismatch order=%s attempt=%s",
                order.order_id,
                attempt.exchange_order_id,
            )
            return False

        if order.status is not OrderStatus.FILLED:
            _LOGGER.warning(
                "Legacy correlation: order not FILLED status=%s",
                order.status,
            )
            return False

        if (
            order.symbol.upper() != attempt.symbol.upper()
            or order.symbol.upper() != persisted.symbol.upper()
        ):
            _LOGGER.warning(
                "Legacy correlation: symbol mismatch order=%s attempt=%s persisted=%s",
                order.symbol,
                attempt.symbol,
                persisted.symbol,
            )
            return False

        if order.side is not attempt.side:
            _LOGGER.warning(
                "Legacy correlation: side mismatch order=%s attempt=%s",
                order.side,
                attempt.side,
            )
            return False

        expected_position_side = (
            PositionSide.LONG if attempt.side is OrderSide.BUY else PositionSide.SHORT
        )
        if persisted.side is not expected_position_side:
            _LOGGER.warning(
                "Legacy correlation: position side incompatible "
                "attempt_side=%s persisted_position_side=%s",
                attempt.side,
                persisted.side,
            )
            return False

        if order.order_type is not attempt.order_type:
            _LOGGER.warning(
                "Legacy correlation: order_type mismatch order=%s attempt=%s",
                order.order_type,
                attempt.order_type,
            )
            return False

        if order.executed_quantity != persisted.quantity:
            _LOGGER.warning(
                "Legacy correlation: executed quantity mismatch executed=%s "
                "persisted=%s",
                order.executed_quantity,
                persisted.quantity,
            )
            return False

        if persisted.quantity != attempt.quantity:
            _LOGGER.warning(
                "Legacy correlation: persisted quantity mismatch persisted=%s "
                "attempt=%s",
                persisted.quantity,
                attempt.quantity,
            )
            return False

        if order.executed_quantity > order.quantity:
            _LOGGER.warning(
                "Legacy correlation: executedQty exceeds origQty executed=%s orig=%s",
                order.executed_quantity,
                order.quantity,
            )
            return False

        if persisted.interval is None or persisted.interval is not attempt.interval:
            _LOGGER.warning(
                "Legacy correlation: interval missing or mismatch persisted=%s "
                "attempt=%s",
                persisted.interval,
                attempt.interval,
            )
            return False

        if (
            persisted.strategy_type is None
            or persisted.strategy_type is not attempt.strategy_type
        ):
            _LOGGER.warning(
                "Legacy correlation: strategy_type missing or mismatch "
                "persisted=%s attempt=%s",
                persisted.strategy_type,
                attempt.strategy_type,
            )
            return False

        if persisted.stop_loss_client_algo_id is None:
            _LOGGER.warning("Legacy correlation: stop-loss identity is missing")
            return False

        if persisted.take_profit_client_algo_id is None:
            _LOGGER.warning("Legacy correlation: take-profit identity is missing")
            return False

        return True
