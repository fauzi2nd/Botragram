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
from botragram.enums import SubmissionAttemptStatus
from botragram.enums.base import BaseEnum
from botragram.models import Position, SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository

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


class LiveProtectionVerification(Protocol):
    """Verify complete exchange protection for one position."""

    async def ensure(self, *, position: Position) -> Position:
        """Return a position whose protection is exchange-verified."""
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


# =============================================================================
# Enums
# =============================================================================
@unique
class LivePostEntryRecoveryResult(BaseEnum):
    """Outcome of recovery after an entry is durably acknowledged."""

    COMPLETED = "completed"
    POSITION_NOT_VISIBLE = "position_not_visible"


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LivePostEntryRecoveryService:
    """Complete one acknowledged LIVE entry without querying or creating it."""

    submission_attempt_repository: SubmissionAttemptRepository
    position_service: LivePositionVisibility
    protection_service: LiveProtectionVerification
    runtime_control: TradingRuntimeControl

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
            return LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

        persisted_position = replace(
            position,
            interval=attempt.interval,
            strategy_type=attempt.strategy_type,
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
