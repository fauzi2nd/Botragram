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
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SubmissionAttemptStatus,
)
from botragram.enums.base import BaseEnum
from botragram.models import Order, Position, SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository

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


class LiveProtectionVerification(Protocol):
    """Verify complete exchange protection for one position."""

    async def ensure(self, *, position: Position) -> Position:
        """Return a position whose protection is exchange-verified."""
        ...

    async def probe_persisted_leg(
        self, *, position: Position, order_type: OrderType, client_id: str
    ) -> str:
        """Probe a persisted protection identity in a GET-only manner.

        Returns one of: "not_found", "active", "unexpected", "unknown".
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

            # Reconcile any persisted protection identities via GET-only probes.
            # If any leg is active/ambiguous/unreadable, block resolution.
            reconciler = self.protection_reconciler or self.protection_service
            try:
                # Stop leg
                if persisted.stop_loss_client_algo_id is not None:
                    stop_status = await reconciler.probe_persisted_leg(
                        position=persisted,
                        order_type=OrderType.STOP_MARKET,
                        client_id=persisted.stop_loss_client_algo_id,
                    )
                    if stop_status != "not_found":
                        return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

                # Take-profit leg
                if persisted.take_profit_client_algo_id is not None:
                    tp_status = await reconciler.probe_persisted_leg(
                        position=persisted,
                        order_type=OrderType.TAKE_PROFIT_MARKET,
                        client_id=persisted.take_profit_client_algo_id,
                    )
                    if tp_status != "not_found":
                        return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE
            except Exception:
                return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

            if order.status is OrderStatus.FILLED:
                resolved_attempt = replace(
                    attempt,
                    status=SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE,
                    updated_at=datetime.now(UTC),
                )

                # Perform one storage-neutral atomic transition that both
                # persists the terminal attempt state and clears any stale
                # persisted Position. Implementations guarantee caller-visible
                # atomicity and do not require service-level branching.
                await self.live_recovery_repository.resolve_no_exposure(
                    symbol=attempt.symbol, attempt=resolved_attempt
                )
                # No protection POST, deletion, or replay is issued here.
                # Set protection ready as there is no unresolved exposure.
                self.runtime_control.set_position_protection_ready(True)
                _LOGGER.info(
                    "Acknowledged LIVE entry resolved with no exposure: "
                    "symbol=%s client_order_id=%s",
                    attempt.symbol,
                    attempt.client_order_id,
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

        await self.protection_service.ensure(position=persisted_position)
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

    async def _get_visible_position(self, *, symbol: str) -> Position | None:
        """Return a bounded authoritative positive-quantity position snapshot."""
        for visibility_attempt in range(_POSITION_VISIBILITY_MAX_ATTEMPTS):
            position = await self.position_service.get(
                symbol=symbol,
                synchronize=True,
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
