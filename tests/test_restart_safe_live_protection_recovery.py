"""Restart-safe LIVE protection and post-entry recovery regressions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine
from botragram.enums import (
    ClosedPositionReason,
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderPriceBandRejectedError,
    VenueRuleValidationError,
)
from botragram.exchanges.binance.futures_client import BinanceFuturesExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import (
    ExchangeSymbolRules,
    Order,
    PendingClosedPositionLifecycle,
    Position,
    SubmissionAttempt,
    Trade,
)
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository
from botragram.services import (
    ClosedPositionLifecycleService,
    LivePositionProtectionService,
)
from botragram.services.live_post_entry_recovery_service import (
    LivePostEntryRecoveryResult,
    LivePostEntryRecoveryService,
)
from botragram.storage.memory import (
    MemoryClosedPositionLifecycleRepository,
    MemoryPositionRepository,
    MemorySubmissionAttemptRepository,
)

_NOW = datetime(2026, 8, 24, tzinfo=UTC)
_ENTRY_ID = "btg-0123456789abcdef0123456789abcdef"
_EXIT_ID = "bex-0123456789abcdef0123456789abcdef"


def _position(
    *,
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
    stop_id: str | None = None,
    tp_id: str | None = None,
) -> Position:
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=stop_loss,
        take_profit=take_profit,
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
        stop_loss_client_algo_id=stop_id,
        take_profit_client_algo_id=tp_id,
        entry_client_order_id=_ENTRY_ID,
    )


def _attempt() -> SubmissionAttempt:
    return SubmissionAttempt(
        client_order_id=_ENTRY_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        signal_generated_at=_NOW,
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
        status=SubmissionAttemptStatus.ACKNOWLEDGED,
        created_at=_NOW,
        updated_at=_NOW,
        exchange_order_id="entry-1",
    )


def _order(
    *,
    order_id: str,
    client_id: str | None,
    side: OrderSide,
    order_type: OrderType,
    quantity: Decimal = Decimal("1"),
    trigger: Decimal | None = None,
    status: OrderStatus = OrderStatus.NEW,
) -> Order:
    return Order(
        order_id=order_id,
        client_order_id=client_id,
        symbol="BTCUSDT",
        side=side,
        order_type=order_type,
        quantity=quantity,
        executed_quantity=quantity if status is OrderStatus.FILLED else Decimal("0"),
        price=None,
        stop_price=trigger,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


class RestartProtectionExchange(BinanceFuturesExchangeClient):
    def __init__(self) -> None:
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.orders: list[Order] = [
            _order(
                order_id="tp-existing",
                client_id="btp-existing",
                side=OrderSide.SELL,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                trigger=Decimal("104"),
            )
        ]
        self.posts: list[str] = []
        self.cancelled: list[str] = []

    async def get_open_protection_orders(
        self, *, symbol: str | None = None
    ) -> tuple[Order, ...]:
        del symbol
        return tuple(self.orders)

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        del symbol
        for order in self.orders:
            if order.client_order_id == client_id:
                return order
        raise ExchangeOrderNotFoundError("not found")

    async def cancel_protection_order(self, *, symbol: str, client_id: str) -> None:
        del symbol
        self.cancelled.append(client_id)
        self.orders = [
            order for order in self.orders if order.client_order_id != client_id
        ]

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=Decimal("1"),
            market_max_quantity=Decimal("1000"),
            market_quantity_step=Decimal("1"),
            minimum_price=Decimal("1"),
            maximum_price=Decimal("1000"),
            price_tick_size=Decimal("1"),
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        del symbol
        return Decimal("100")

    async def create_protection_orders(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        stop_loss_client_algo_id: str | None = None,
        take_profit_client_algo_id: str | None = None,
    ) -> tuple[Order, ...]:
        trigger = stop_loss if stop_loss is not None else take_profit
        order_type = (
            OrderType.STOP_MARKET
            if stop_loss is not None
            else OrderType.TAKE_PROFIT_MARKET
        )
        client_id = (
            stop_loss_client_algo_id
            if stop_loss is not None
            else take_profit_client_algo_id
        )
        assert trigger is not None
        assert client_id is not None
        self.posts.append(client_id)
        order = _order(
            order_id=f"created-{len(self.orders)}",
            client_id=client_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            trigger=trigger,
        )
        self.orders.append(order)
        return (order,)


@pytest.mark.asyncio
async def test_restart_recreates_proven_missing_persisted_stop_with_same_id() -> None:
    exchange = RestartProtectionExchange()
    repository = MemoryPositionRepository()
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=repository,
        risk_engine=RiskEngine(
            settings=replace(
                RiskSettings(),
                ema_cross_stop_loss_pct=Decimal("0.02"),
                ema_cross_take_profit_pct=Decimal("0.04"),
            )
        ),
    )
    position = _position(
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        stop_id="bsl-missing",
        tp_id="btp-existing",
    )

    protected = await service.ensure(position=position)

    assert exchange.posts == ["bsl-missing"]
    assert protected.stop_loss_client_algo_id == "bsl-missing"
    assert protected.stop_loss == Decimal("98")
    assert protected.take_profit == Decimal("104")


@pytest.mark.asyncio
async def test_cleanup_skips_terminal_owned_leg_and_cancels_active_peer() -> None:
    exchange = RestartProtectionExchange()
    exchange.orders = [
        _order(
            order_id="stop-filled",
            client_id="bsl-filled",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            trigger=Decimal("98"),
            status=OrderStatus.FILLED,
        ),
        _order(
            order_id="tp-active",
            client_id="btp-active",
            side=OrderSide.SELL,
            order_type=OrderType.TAKE_PROFIT_MARKET,
            trigger=Decimal("104"),
        ),
    ]
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=MemoryPositionRepository(),
        risk_engine=RiskEngine(settings=RiskSettings()),
    )
    position = _position(
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        stop_id="bsl-filled",
        tp_id="btp-active",
    )

    await service.cancel_persisted_legs(position=position)

    assert exchange.cancelled == ["btp-active"]
    assert [order.client_order_id for order in exchange.orders] == ["bsl-filled"]


@dataclass(slots=True)
class PositionVisibility:
    current: Position | None
    persisted: Position | None

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        del symbol
        return self.current if synchronize else self.persisted

    async def save(self, *, position: Position) -> None:
        self.persisted = position

    async def delete(self, *, symbol: str) -> bool:
        del symbol
        existed = self.persisted is not None
        self.persisted = None
        return existed

    async def observe(self, *, symbol: str) -> Position | None:
        del symbol
        return self.current


class AtomicRecovery(LiveRecoveryRepository):
    def __init__(
        self,
        *,
        attempts: MemorySubmissionAttemptRepository,
        positions: PositionVisibility,
    ) -> None:
        self.attempts = attempts
        self.positions = positions

    async def resolve_no_exposure(
        self, *, symbol: str, attempt: SubmissionAttempt
    ) -> None:
        await self.positions.delete(symbol=symbol)
        await self.attempts.save(attempt=attempt)


@dataclass(slots=True)
class OrderLookup:
    orders: dict[str, Order]
    calls: list[str] = field(default_factory=list[str])

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        del symbol
        self.calls.append(client_order_id)
        try:
            return self.orders[client_order_id]
        except KeyError as error:
            raise ExchangeOrderNotFoundError("not found") from error


@dataclass(slots=True)
class ProtectionRecovery:
    statuses: dict[OrderType, str] = field(default_factory=dict[OrderType, str])
    cleanup_calls: int = 0
    fail_ensure: bool = False

    async def ensure(self, *, position: Position) -> Position:
        if self.fail_ensure:
            raise VenueRuleValidationError(
                "Protection trigger is invalid relative to current MARK_PRICE"
            )
        return position

    async def probe_persisted_leg(
        self, *, position: Position, order_type: OrderType, client_id: str
    ) -> str:
        del position, client_id
        return self.statuses.get(order_type, "not_found")

    async def cancel_persisted_legs(self, *, position: Position) -> None:
        del position
        self.cleanup_calls += 1


@dataclass(slots=True)
class EmergencyExitExchange:
    positions: PositionVisibility
    lookup: OrderLookup
    preserve_client_identity: bool = True
    price_band_rejections_remaining: int = 0
    calls: list[tuple[str, str | None]] = field(
        default_factory=list[tuple[str, str | None]]
    )

    async def close_position(
        self, *, symbol: str, client_order_id: str | None = None
    ) -> Order:
        self.calls.append((symbol, client_order_id))
        assert client_order_id is not None
        if self.price_band_rejections_remaining > 0:
            self.price_band_rejections_remaining -= 1
            raise ExchangeOrderPriceBandRejectedError(
                "configured venue price-band rejection"
            )
        returned_client_id = client_order_id if self.preserve_client_identity else None
        order = _order(
            order_id="exit-1",
            client_id=returned_client_id,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
        )
        if returned_client_id is not None:
            self.lookup.orders[returned_client_id] = order
        self.positions.current = None
        return order


@dataclass(slots=True, kw_only=True)
class ExactTradeHistory:
    """Return authoritative fills for one exact order."""

    fills_by_order_id: dict[str, tuple[Trade, ...]]

    async def get_trades_for_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> tuple[Trade, ...]:
        return tuple(
            fill for fill in self.fills_by_order_id[order_id] if fill.symbol == symbol
        )


def _trade(
    *,
    trade_id: str,
    order_id: str,
    side: OrderSide,
    realized_pnl: str,
) -> Trade:
    """Build one exact entry or recovery-exit fill."""
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        symbol="BTCUSDT",
        side=side,
        price=Decimal("100"),
        quantity=Decimal("1"),
        quote_quantity=Decimal("100"),
        fee=Decimal("0.2"),
        fee_asset="USDT",
        realized_pnl=Decimal(realized_pnl),
        executed_at=_NOW,
    )


def _lifecycle_service(
    *,
    repository: MemoryClosedPositionLifecycleRepository,
) -> ClosedPositionLifecycleService:
    """Build lifecycle enrichment for exact emergency entry and exit fills."""
    return ClosedPositionLifecycleService(
        repository=repository,
        trade_history=ExactTradeHistory(
            fills_by_order_id={
                "entry-1": (
                    _trade(
                        trade_id="entry-fill",
                        order_id="entry-1",
                        side=OrderSide.BUY,
                        realized_pnl="0",
                    ),
                ),
                "exit-1": (
                    _trade(
                        trade_id="exit-fill",
                        order_id="exit-1",
                        side=OrderSide.SELL,
                        realized_pnl="-2",
                    ),
                ),
            }
        ),
    )


@pytest.mark.asyncio
async def test_crossed_acknowledged_entry_closes_once_and_resolves() -> None:
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    positions = PositionVisibility(current=_position(), persisted=_position())
    lookup = OrderLookup(
        orders={
            _ENTRY_ID: _order(
                order_id="entry-1",
                client_id=_ENTRY_ID,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            )
        }
    )
    protection = ProtectionRecovery(fail_ensure=True)
    exit_exchange = EmergencyExitExchange(positions=positions, lookup=lookup)
    lifecycle_repository = MemoryClosedPositionLifecycleRepository()
    control = TradingRuntimeControl()
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=control,
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
        emergency_exit_exchange=exit_exchange,
        closed_lifecycle_service=_lifecycle_service(repository=lifecycle_repository),
    )

    result = await service.recover_acknowledged(attempt=attempt)

    stored = await attempts.get_by_client_order_id(client_order_id=_ENTRY_ID)
    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert exit_exchange.calls == [("BTCUSDT", _EXIT_ID)]
    assert positions.current is None
    assert positions.persisted is None
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE
    assert "position protection" not in control.get_missing_startup_requirements()
    completed = await lifecycle_repository.get_completed()
    assert len(completed) == 1
    assert completed[0].ownership.close_reason is ClosedPositionReason.EMERGENCY_CLOSE
    assert completed[0].gross_realized_pnl == Decimal("-2")
    assert completed[0].fee == Decimal("0.4")
    assert completed[0].net_pnl == Decimal("-2.4")


@pytest.mark.asyncio
async def test_emergency_stage_failure_preserves_identity_for_restart_retry() -> None:
    """Resolve once after staging recovers without submitting another close."""

    class FailOnceLifecycleRepository(MemoryClosedPositionLifecycleRepository):
        def __init__(self) -> None:
            super().__init__()
            self.fail_stage = True
            self.stage_calls = 0

        async def stage(self, *, lifecycle: PendingClosedPositionLifecycle) -> None:
            self.stage_calls += 1
            if self.fail_stage:
                raise RuntimeError("configured lifecycle stage failure")
            await super().stage(lifecycle=lifecycle)

    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    position = _position()
    positions = PositionVisibility(current=position, persisted=position)
    lookup = OrderLookup(
        orders={
            _ENTRY_ID: _order(
                order_id="entry-1",
                client_id=_ENTRY_ID,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            )
        }
    )
    protection = ProtectionRecovery(fail_ensure=True)
    exit_exchange = EmergencyExitExchange(positions=positions, lookup=lookup)
    lifecycle_repository = FailOnceLifecycleRepository()

    def build_service() -> LivePostEntryRecoveryService:
        return LivePostEntryRecoveryService(
            submission_attempt_repository=attempts,
            live_recovery_repository=AtomicRecovery(
                attempts=attempts,
                positions=positions,
            ),
            position_service=positions,
            protection_service=protection,
            runtime_control=TradingRuntimeControl(),
            order_service=lookup,
            protection_reconciler=protection,
            protection_cleanup_service=protection,
            emergency_exit_exchange=exit_exchange,
            closed_lifecycle_service=_lifecycle_service(
                repository=lifecycle_repository
            ),
        )

    with pytest.raises(RuntimeError, match="configured lifecycle stage failure"):
        await build_service().recover_acknowledged(attempt=attempt)

    stored = await attempts.get_by_client_order_id(client_order_id=_ENTRY_ID)
    assert positions.current is None
    assert positions.persisted == position
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert exit_exchange.calls == [("BTCUSDT", _EXIT_ID)]
    assert await lifecycle_repository.get_completed() == ()

    lifecycle_repository.fail_stage = False
    result = await build_service().recover_acknowledged(attempt=attempt)
    completed = await lifecycle_repository.get_completed()

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert positions.persisted is None
    assert exit_exchange.calls == [("BTCUSDT", _EXIT_ID)]
    assert lifecycle_repository.stage_calls == 2
    assert len(completed) == 1
    assert completed[0].entry_client_order_id == _ENTRY_ID


@pytest.mark.asyncio
async def test_restart_reconciles_existing_emergency_exit_into_one_lifecycle() -> None:
    """Record a previously FILLED deterministic recovery close without duplicate."""

    class RecoveryOrderLookup(OrderLookup):
        def __init__(
            self,
            *,
            orders: dict[str, Order],
            positions: PositionVisibility,
        ) -> None:
            super().__init__(orders=orders)
            self.positions = positions

        async def get_by_client_order_id(
            self,
            *,
            symbol: str,
            client_order_id: str,
        ) -> Order:
            order = await super().get_by_client_order_id(
                symbol=symbol,
                client_order_id=client_order_id,
            )
            if client_order_id == _EXIT_ID:
                self.positions.current = None
            return order

    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    positions = PositionVisibility(current=_position(), persisted=_position())
    lookup = RecoveryOrderLookup(
        positions=positions,
        orders={
            _EXIT_ID: _order(
                order_id="exit-1",
                client_id=_EXIT_ID,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            )
        },
    )
    protection = ProtectionRecovery(fail_ensure=True)
    lifecycle_repository = MemoryClosedPositionLifecycleRepository()
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
        emergency_exit_exchange=EmergencyExitExchange(
            positions=positions,
            lookup=lookup,
        ),
        closed_lifecycle_service=_lifecycle_service(repository=lifecycle_repository),
    )

    result = await service.recover_acknowledged(attempt=attempt)
    completed = await lifecycle_repository.get_completed()

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert len(completed) == 1
    assert completed[0].ownership.close_reason is ClosedPositionReason.RECOVERY_CLOSE


@pytest.mark.asyncio
async def test_crash_after_emergency_fill_recovers_lifecycle_from_zero_exposure() -> (
    None
):
    """Recover the deterministic exit when restart begins with no exposure."""
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    positions = PositionVisibility(current=None, persisted=_position())
    lookup = OrderLookup(
        orders={
            _ENTRY_ID: _order(
                order_id="entry-1",
                client_id=_ENTRY_ID,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            ),
            _EXIT_ID: _order(
                order_id="exit-1",
                client_id=_EXIT_ID,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            ),
        }
    )
    lifecycle_repository = MemoryClosedPositionLifecycleRepository()
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=ProtectionRecovery(),
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        closed_lifecycle_service=_lifecycle_service(repository=lifecycle_repository),
    )

    result = await service.recover_acknowledged(attempt=attempt)
    completed = await lifecycle_repository.get_completed()

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert positions.persisted is None
    assert len(completed) == 1
    assert completed[0].ownership.close_reason is ClosedPositionReason.RECOVERY_CLOSE


@pytest.mark.asyncio
async def test_price_band_rejected_emergency_exit_reconciles_before_retry() -> None:
    """Retry -4131 once only after proving the deterministic id is absent."""
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    positions = PositionVisibility(current=_position(), persisted=_position())
    lookup = OrderLookup(orders={})
    protection = ProtectionRecovery(fail_ensure=True)
    exit_exchange = EmergencyExitExchange(
        positions=positions,
        lookup=lookup,
        price_band_rejections_remaining=1,
    )
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
        emergency_exit_exchange=exit_exchange,
    )

    result = await service.recover_acknowledged(attempt=attempt)

    stored = await attempts.get_by_client_order_id(client_order_id=_ENTRY_ID)
    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert exit_exchange.calls == [
        ("BTCUSDT", _EXIT_ID),
        ("BTCUSDT", _EXIT_ID),
    ]
    assert lookup.calls == [_EXIT_ID, _EXIT_ID]
    assert positions.current is None
    assert positions.persisted is None
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE


@pytest.mark.asyncio
async def test_price_band_rejected_emergency_exit_retry_is_bounded() -> None:
    """Remain fail-closed after the single safe price-band retry is exhausted."""
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    positions = PositionVisibility(current=_position(), persisted=_position())
    lookup = OrderLookup(orders={})
    protection = ProtectionRecovery(fail_ensure=True)
    exit_exchange = EmergencyExitExchange(
        positions=positions,
        lookup=lookup,
        price_band_rejections_remaining=2,
    )
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
        emergency_exit_exchange=exit_exchange,
    )

    with pytest.raises(RuntimeError, match="venue price band"):
        await service.recover_acknowledged(attempt=attempt)

    stored = await attempts.get_by_client_order_id(client_order_id=_ENTRY_ID)
    assert exit_exchange.calls == [
        ("BTCUSDT", _EXIT_ID),
        ("BTCUSDT", _EXIT_ID),
    ]
    assert lookup.calls == [_EXIT_ID, _EXIT_ID, _EXIT_ID]
    assert positions.current is not None
    assert positions.persisted is not None
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.ACKNOWLEDGED


@pytest.mark.asyncio
async def test_successful_emergency_close_requires_exact_response_identity() -> None:
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    positions = PositionVisibility(current=_position(), persisted=_position())
    lookup = OrderLookup(
        orders={
            _ENTRY_ID: _order(
                order_id="entry-1",
                client_id=_ENTRY_ID,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            )
        }
    )
    protection = ProtectionRecovery(fail_ensure=True)
    exit_exchange = EmergencyExitExchange(
        positions=positions,
        lookup=lookup,
        preserve_client_identity=False,
    )
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
        emergency_exit_exchange=exit_exchange,
    )

    with pytest.raises(
        RuntimeError,
        match="Emergency exit order does not match the acknowledged entry",
    ):
        await service.recover_acknowledged(attempt=attempt)

    stored = await attempts.get_by_client_order_id(client_order_id=_ENTRY_ID)
    assert exit_exchange.calls == [("BTCUSDT", _EXIT_ID)]
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.ACKNOWLEDGED


@pytest.mark.asyncio
async def test_zero_exposure_cleans_exact_owned_orphan_before_resolution() -> None:
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    persisted = _position(
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        stop_id="bsl-owned",
        tp_id="btp-owned",
    )
    positions = PositionVisibility(current=None, persisted=persisted)
    lookup = OrderLookup(
        orders={
            _ENTRY_ID: _order(
                order_id="entry-1",
                client_id=_ENTRY_ID,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            )
        }
    )
    protection = ProtectionRecovery(
        statuses={
            OrderType.STOP_MARKET: "not_found",
            OrderType.TAKE_PROFIT_MARKET: "active",
        }
    )
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
    )

    result = await service.recover_acknowledged(attempt=attempt)

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert protection.cleanup_calls == 1
    assert positions.persisted is None


@pytest.mark.asyncio
async def test_zero_exposure_accepts_terminal_owned_leg_without_cleanup() -> None:
    attempt = _attempt()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=attempt)
    persisted = _position(
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        stop_id="bsl-owned",
        tp_id="btp-owned",
    )
    positions = PositionVisibility(current=None, persisted=persisted)
    lookup = OrderLookup(
        orders={
            _ENTRY_ID: _order(
                order_id="entry-1",
                client_id=_ENTRY_ID,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
            )
        }
    )
    protection = ProtectionRecovery(
        statuses={
            OrderType.STOP_MARKET: "terminal",
            OrderType.TAKE_PROFIT_MARKET: "not_found",
        }
    )
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempts,
        live_recovery_repository=AtomicRecovery(
            attempts=attempts,
            positions=positions,
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=lookup,
        protection_reconciler=protection,
        protection_cleanup_service=protection,
    )

    result = await service.recover_acknowledged(attempt=attempt)

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert protection.cleanup_calls == 0
    assert positions.persisted is None


@pytest.mark.asyncio
async def test_restart_promotes_active_pending_stop_and_retires_current() -> None:
    """Finish crash-interrupted stepped replacement from durable identities."""
    current_id = "bsl-11111111111111111111111111111111"
    pending_id = "bsl-22222222222222222222222222222222"
    exchange = RestartProtectionExchange()
    exchange.orders.extend(
        [
            _order(
                order_id="stop-current",
                client_id=current_id,
                side=OrderSide.SELL,
                order_type=OrderType.STOP_MARKET,
                trigger=Decimal("98"),
            ),
            _order(
                order_id="stop-pending",
                client_id=pending_id,
                side=OrderSide.SELL,
                order_type=OrderType.STOP_MARKET,
                trigger=Decimal("101"),
            ),
        ]
    )
    repository = MemoryPositionRepository()
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=repository,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )
    position = replace(
        _position(
            stop_loss=Decimal("98"),
            take_profit=Decimal("104"),
            stop_id=current_id,
            tp_id="btp-existing",
        ),
        pending_stop_loss=Decimal("101"),
        pending_stop_loss_client_algo_id=pending_id,
        pending_protection_step=1,
    )

    protected = await service.ensure(position=position)

    assert protected.stop_loss == Decimal("101")
    assert protected.stop_loss_client_algo_id == pending_id
    assert protected.protection_step == 1
    assert protected.pending_stop_loss is None
    assert protected.pending_stop_loss_client_algo_id is None
    assert current_id in exchange.cancelled
    assert pending_id not in exchange.cancelled
