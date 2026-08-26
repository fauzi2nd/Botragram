"""Durably aggregate exact exchange fills into one closed position lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    OrderSide,
    OrderStatus,
    PositionSide,
)
from botragram.models import (
    ClosedPositionLifecycle,
    Order,
    PendingClosedPositionLifecycle,
    Position,
    SubmissionAttempt,
    Trade,
)
from botragram.repositories import ClosedPositionLifecycleRepository

__all__ = ["ClosedPositionLifecycleService"]


_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class ExactOrderTradeHistory(Protocol):
    """Fetch every fill for one exact exchange order identity."""

    async def get_trades_for_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Sequence[Trade]:
        """Return all authoritative fills for one symbol/order identity."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class ClosedPositionLifecycleService:
    """Stage closure ownership and enrich it without affecting exchange cleanup."""

    repository: ClosedPositionLifecycleRepository
    trade_history: ExactOrderTradeHistory
    pnl_asset: str = "USDT"

    def __post_init__(self) -> None:
        """Require an explicit asset for gross PnL and compatible fees."""
        if not self.pnl_asset.strip():
            raise ValueError("Closed lifecycle PnL asset must not be empty")

    async def stage(
        self,
        *,
        position: Position,
        attempt: SubmissionAttempt,
        exit_order: Order,
        close_reason: ClosedPositionReason,
        provenance: ClosedPositionProvenance,
    ) -> PendingClosedPositionLifecycle:
        """Persist exact entry/exit ownership before local position deletion."""
        entry_identity = position.entry_client_order_id
        entry_order_id = attempt.exchange_order_id
        exit_identity = exit_order.client_order_id
        if entry_identity is None or entry_identity != attempt.client_order_id:
            raise RuntimeError("Closed lifecycle requires matching entry identity")
        if entry_order_id is None:
            raise RuntimeError("Closed lifecycle requires an exchange entry order ID")
        if exit_identity is None:
            raise RuntimeError("Closed lifecycle requires an exit client identity")
        if exit_order.symbol.upper() != position.symbol.upper():
            raise RuntimeError("Closed lifecycle exit symbol does not match position")
        if attempt.symbol.upper() != position.symbol.upper():
            raise RuntimeError("Closed lifecycle entry symbol does not match position")
        expected_entry_side = (
            OrderSide.BUY if position.side is PositionSide.LONG else OrderSide.SELL
        )
        expected_exit_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        if attempt.side is not expected_entry_side:
            raise RuntimeError("Closed lifecycle entry side does not match position")
        if exit_order.side is not expected_exit_side:
            raise RuntimeError("Closed lifecycle exit side does not match position")
        if exit_order.status is not OrderStatus.FILLED:
            raise RuntimeError("Closed lifecycle requires a FILLED exit order")
        execution_order_id = exit_order.execution_order_id
        if execution_order_id is None or not execution_order_id.strip():
            execution_order_id = exit_order.order_id

        lifecycle = PendingClosedPositionLifecycle(
            entry_client_order_id=entry_identity,
            symbol=position.symbol.upper(),
            position_side=position.side,
            entry_order_id=entry_order_id,
            exit_client_order_id=exit_identity,
            exit_order_id=execution_order_id,
            close_reason=close_reason,
            provenance=provenance,
            recorded_at=exit_order.updated_at,
        )
        await self.repository.stage(lifecycle=lifecycle)
        return lifecycle

    async def has_durable_ownership(
        self,
        *,
        entry_client_order_id: str,
    ) -> bool:
        """Return whether ownership already survived a prior local commit."""
        return (
            await self.repository.get_by_entry_client_order_id(
                entry_client_order_id=entry_client_order_id,
            )
            is not None
        )

    async def complete(self, *, entry_client_order_id: str) -> None:
        """Aggregate exact entry and exit fills into one immutable closed trade."""
        record = await self.repository.get_by_entry_client_order_id(
            entry_client_order_id=entry_client_order_id,
        )
        if record is None or isinstance(record, ClosedPositionLifecycle):
            return

        entry_fills = tuple(
            await self.trade_history.get_trades_for_order(
                symbol=record.symbol,
                order_id=record.entry_order_id,
            )
        )
        exit_fills = tuple(
            await self.trade_history.get_trades_for_order(
                symbol=record.symbol,
                order_id=record.exit_order_id,
            )
        )
        self._require_exact_fills(
            fills=entry_fills,
            order_id=record.entry_order_id,
            label="entry",
        )
        self._require_exact_fills(
            fills=exit_fills,
            order_id=record.exit_order_id,
            label="exit",
        )
        if any(fill.realized_pnl is None for fill in exit_fills):
            raise RuntimeError("Closed lifecycle exit fill lacks realized PnL")

        all_fills = entry_fills + exit_fills
        fee_assets = {fill.fee_asset.upper() for fill in all_fills}
        if len(fee_assets) != 1:
            raise RuntimeError("Closed lifecycle fees use incompatible assets")
        fee_asset = next(iter(fee_assets))
        if fee_asset != self.pnl_asset.strip().upper():
            raise RuntimeError(
                "Closed lifecycle fee asset does not match the configured PnL asset"
            )
        gross_realized_pnl = sum(
            (fill.realized_pnl for fill in exit_fills if fill.realized_pnl is not None),
            start=_DECIMAL_ZERO,
        )
        fee = sum((fill.fee for fill in all_fills), start=_DECIMAL_ZERO)
        await self.repository.complete(
            lifecycle=ClosedPositionLifecycle(
                ownership=record,
                gross_realized_pnl=gross_realized_pnl,
                fee=fee,
                fee_asset=fee_asset,
                net_pnl=gross_realized_pnl - fee,
                closed_at=max(fill.executed_at for fill in exit_fills),
            )
        )

    async def complete_best_effort(self, *, entry_client_order_id: str) -> None:
        """Enrich performance without masking completed safety cleanup."""
        try:
            await self.complete(entry_client_order_id=entry_client_order_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Closed lifecycle financial enrichment remains pending: "
                "entry_client_order_id=%s",
                entry_client_order_id,
            )

    async def reconcile_pending_best_effort(self) -> None:
        """Retry every durable pending enrichment after restart/reconciliation."""
        try:
            pending = await self.repository.get_pending()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Closed lifecycle pending lookup failed")
            return
        for lifecycle in pending:
            await self.complete_best_effort(
                entry_client_order_id=lifecycle.entry_client_order_id,
            )

    @staticmethod
    def _require_exact_fills(
        *,
        fills: tuple[Trade, ...],
        order_id: str,
        label: str,
    ) -> None:
        """Require non-empty fills that all match one authoritative order."""
        if not fills:
            raise RuntimeError(f"Closed lifecycle {label} order has no fills")
        if any(fill.order_id != order_id for fill in fills):
            raise RuntimeError(
                f"Closed lifecycle {label} fills do not match the exact order"
            )
