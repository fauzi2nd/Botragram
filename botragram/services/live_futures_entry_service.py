"""Protected LIVE Futures MARKET-entry workflow."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import Interval, MarketType, OrderType, StrategyType
from botragram.models import Order, Position, RiskResult, Signal

__all__ = ["LiveFuturesEntryService"]


_DECIMAL_ZERO = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class LiveOrderSubmission(Protocol):
    """Submit one already-approved exchange entry order."""

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Submit and persist one exchange order."""
        ...


class LivePositionSynchronization(Protocol):
    """Synchronize and persist an exchange position snapshot."""

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return one optionally synchronized position."""
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
        self.runtime_control.set_position_protection_ready(False)
        _LOGGER.info(
            "Live Futures entry submission started: symbol=%s signal=%s",
            signal.symbol,
            signal.signal_type.value,
        )

        try:
            order = await self.order_service.submit(
                signal=signal,
                risk_result=risk_result,
                order_type=order_type,
                price=price,
            )
            _LOGGER.info(
                "Live Futures entry acknowledged: symbol=%s order_id=%s",
                signal.symbol,
                order.order_id,
            )
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
        except Exception:
            _LOGGER.exception(
                "Live Futures entry is unsafe; protection gate remains closed: "
                "symbol=%s",
                signal.symbol,
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

    @staticmethod
    def _resolve_strategy_type(strategy_name: str) -> StrategyType | None:
        """Retain known strategy metadata without rejecting custom strategies."""
        try:
            return StrategyType(strategy_name)
        except ValueError:
            return None
