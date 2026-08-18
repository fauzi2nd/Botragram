"""Active-position restart recovery tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.config.risk_settings import RiskSettings
from botragram.engine import PositionEngine, RiskEngine
from botragram.enums import (
    ExchangeEnvironment,
    Interval,
    LiveMarketStreamLifecycleStatus,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.exceptions import ExchangeOrderNotFoundError
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    Candle,
    ExchangeSymbolRules,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRuntimePositionContext,
    Order,
    Position,
    Signal,
    SubmissionAttempt,
)
from botragram.services import (
    LivePortfolioRecoveryService,
    LivePositionProtectionService,
    LivePostEntryRecoveryResult,
    LiveSubmissionRecoveryResult,
    PositionService,
    RuntimeRecoveryService,
)
from botragram.storage.memory import (
    MemoryCandleRepository,
    MemoryPositionRepository,
    MemorySignalRepository,
    MemorySubmissionAttemptRepository,
)

_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class RecoveryExchangeClient(BinanceFuturesExchangeClient):
    """Provide deterministic positions and protection orders for recovery."""

    __slots__ = (
        "create_calls",
        "identity_snapshots",
        "positions",
        "position_repository",
        "protection_orders",
        "reconciled_protection_orders",
        "reconciliation_requests",
    )

    def __init__(
        self,
        *,
        positions: tuple[Position, ...],
        position_repository: MemoryPositionRepository | None = None,
    ) -> None:
        """Initialize the fake Futures exchange."""
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.positions = positions
        self.position_repository = position_repository
        self.protection_orders: list[Order] = []
        self.reconciled_protection_orders: list[Order] = []
        self.reconciliation_requests: list[str] = []
        self.create_calls = 0
        self.identity_snapshots: list[tuple[str | None, str | None]] = []

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Position, ...]:
        """Return configured active positions."""
        if symbol is None:
            return self.positions

        return tuple(
            position for position in self.positions if position.symbol == symbol.upper()
        )

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return deterministic price and quantity rules without network access."""
        return ExchangeSymbolRules(
            symbol=symbol.upper(),
            market_min_quantity=Decimal("0.001"),
            market_max_quantity=Decimal("1000"),
            market_quantity_step=Decimal("0.001"),
            minimum_price=Decimal("0.01"),
            maximum_price=Decimal("1000000"),
            price_tick_size=Decimal("0.01"),
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return a deterministic current MARK_PRICE without network access."""
        assert any(position.symbol == symbol.upper() for position in self.positions)
        return Decimal("65000")

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Order, ...]:
        """Return configured open protection orders."""
        if symbol is None:
            return tuple(self.protection_orders)

        return tuple(
            order for order in self.protection_orders if order.symbol == symbol.upper()
        )

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
        """Create deterministic protection snapshots."""
        self.create_calls += 1
        created: list[Order] = []

        for order_type, trigger_price, client_algo_id in (
            (OrderType.STOP_MARKET, stop_loss, stop_loss_client_algo_id),
            (
                OrderType.TAKE_PROFIT_MARKET,
                take_profit,
                take_profit_client_algo_id,
            ),
        ):
            if trigger_price is None:
                continue

            assert client_algo_id is not None

            repository = self.position_repository
            if repository is not None:
                persisted = await repository.get_by_symbol(symbol=symbol)
                assert persisted is not None
                self.identity_snapshots.append(
                    (
                        persisted.stop_loss_client_algo_id,
                        persisted.take_profit_client_algo_id,
                    )
                )

            order = Order(
                order_id=f"protection-{len(self.protection_orders) + 1}",
                symbol=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.NEW,
                quantity=quantity,
                executed_quantity=Decimal("0"),
                price=None,
                stop_price=trigger_price,
                created_at=_NOW,
                updated_at=_NOW,
                client_order_id=client_algo_id,
            )
            self.protection_orders.append(order)
            created.append(order)

        return tuple(created)

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return a deterministic authoritative protection lookup result."""
        self.reconciliation_requests.append(client_id)
        orders = (*self.protection_orders, *self.reconciled_protection_orders)

        for order in orders:
            if order.symbol == symbol.upper() and order.client_order_id == client_id:
                return order

        raise ExchangeOrderNotFoundError("configured protection is not found")


@dataclass(slots=True, kw_only=True)
class ImmediateTickStream:
    """Start a stream and synchronously record its first validated tick."""

    runtime_control: TradingRuntimeControl

    async def start_market_stream(self) -> bool:
        """Enable telemetry and record the first tick."""
        self.runtime_control.set_stream_enabled(True)
        self.runtime_control.record_stream_tick(price=Decimal("65000"))
        return True

    async def stop_market_stream(self) -> bool:
        """Disable stream telemetry."""
        return self.runtime_control.set_stream_enabled(False)


@dataclass(slots=True)
class FakeLiveMarketStreamOwner:
    """Record deterministic multi-stream startup without background tasks."""

    first_tick_results: dict[str, bool] = field(default_factory=dict[str, bool])
    failing_start_symbol: str | None = None
    cancelled_wait_symbol: str | None = None
    failed_before_ready_symbol: str | None = None
    events: list[str] = field(default_factory=list[str])
    stopped_identities: list[LiveMarketStreamIdentity] = field(
        default_factory=list[LiveMarketStreamIdentity],
    )
    _states: dict[LiveMarketStreamIdentity, LiveMarketStreamState] = field(
        default_factory=dict[LiveMarketStreamIdentity, LiveMarketStreamState],
    )

    @property
    def stream_states(self) -> tuple[LiveMarketStreamState, ...]:
        """Return deterministic immutable snapshots for owned fake streams."""
        return tuple(
            self._states[identity]
            for identity in sorted(
                self._states,
                key=lambda item: (item.symbol, item.interval.value),
            )
        )

    async def start(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> LiveMarketStreamIdentity:
        """Record one deterministic start or inject a configured failure."""
        identity = LiveMarketStreamIdentity.from_runtime_context(context=context)
        self.events.append(f"start:{identity.symbol}")

        if identity.symbol == self.failing_start_symbol:
            raise RuntimeError(f"configured stream start failure: {identity.symbol}")

        self._states[identity] = LiveMarketStreamState(
            identity=identity,
            lifecycle_status=LiveMarketStreamLifecycleStatus.RUNNING,
            first_tick_received=False,
            event_count=0,
            last_price=None,
            last_event_monotonic=None,
        )
        return identity

    async def wait_for_first_tick(
        self,
        *,
        identity: LiveMarketStreamIdentity,
        timeout_seconds: float,
    ) -> bool:
        """Record readiness for one stream or inject a configured result."""
        del timeout_seconds
        self.events.append(f"wait:{identity.symbol}")

        if identity.symbol == self.cancelled_wait_symbol:
            raise asyncio.CancelledError()

        stream_state = self._states[identity]
        if identity.symbol == self.failed_before_ready_symbol:
            self._states[identity] = replace(
                stream_state,
                lifecycle_status=LiveMarketStreamLifecycleStatus.FAILED,
                failure_type="RuntimeError",
            )
            return False

        if not self.first_tick_results.get(identity.symbol, True):
            return False

        self._states[identity] = replace(
            stream_state,
            first_tick_received=True,
            event_count=1,
            last_price=Decimal("65000"),
            last_event_monotonic=1.0,
        )
        return True

    async def stop(self, *, identity: LiveMarketStreamIdentity) -> bool:
        """Record one identity-specific deterministic cleanup."""
        self.events.append(f"stop:{identity.symbol}")
        self.stopped_identities.append(identity)
        return self._states.pop(identity, None) is not None


@dataclass(slots=True)
class FakeLiveProtectionMonitorOwner:
    """Record deterministic recovery-owned monitor registration and cleanup."""

    events: list[str] = field(default_factory=list[str])
    failing_register_symbol: str | None = None
    cancelled_register_symbol: str | None = None
    _contexts: dict[str, LiveRuntimePositionContext] = field(
        default_factory=dict[str, LiveRuntimePositionContext],
    )

    @property
    def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
        """Return immutable monitor snapshots in deterministic symbol order."""
        return tuple(
            LiveProtectionMonitorState(
                context=context,
                is_active=True,
                failure_type=None,
            )
            for _, context in sorted(self._contexts.items())
        )

    def register(self, *, context: LiveRuntimePositionContext) -> bool:
        """Register one fake monitor or inject the configured failure."""
        self.events.append(f"register:{context.symbol}")

        if context.symbol == self.cancelled_register_symbol:
            raise asyncio.CancelledError()
        if context.symbol == self.failing_register_symbol:
            raise RuntimeError(
                f"configured monitor registration failure: {context.symbol}"
            )
        if context.symbol in self._contexts:
            return False

        self._contexts[context.symbol] = context
        return True

    def stop(self, *, symbol: str) -> bool:
        """Release one fake runtime monitor without exchange interaction."""
        normalized_symbol = symbol.strip().upper()
        self.events.append(f"monitor_stop:{normalized_symbol}")
        return self._contexts.pop(normalized_symbol, None) is not None


@dataclass(slots=True)
class FakeSubmissionRecovery:
    """Return one configured durable submission-recovery outcome."""

    result: LiveSubmissionRecoveryResult
    error: BaseException | None = None
    events: list[str] = field(default_factory=list[str])

    async def recover_incomplete(self) -> LiveSubmissionRecoveryResult:
        """Record the pre-position startup recovery stage."""
        self.events.append("submission")
        if self.error is not None:
            raise self.error
        return self.result


@dataclass(slots=True)
class FakePostEntryRecovery:
    """Record acknowledged-entry recovery without exchange mutation."""

    result: LivePostEntryRecoveryResult
    events: list[str] = field(default_factory=list[str])
    attempts: list[SubmissionAttempt] = field(default_factory=list[SubmissionAttempt])

    async def recover_acknowledged(
        self,
        *,
        attempt: SubmissionAttempt,
    ) -> LivePostEntryRecoveryResult:
        """Record the durable acknowledged handoff."""
        self.events.append("post_entry")
        self.attempts.append(attempt)
        return self.result


def _position(
    *,
    include_metadata: bool,
) -> Position:
    """Return one deterministic long position."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("63700") if include_metadata else None,
        take_profit=Decimal("67600") if include_metadata else None,
        interval=Interval.M1 if include_metadata else None,
        strategy_type=(StrategyType.EMA_SCALPING if include_metadata else None),
    )


def _recovery_service(
    *,
    trade_mode: TradeMode,
    exchange: RecoveryExchangeClient,
    repository: MemoryPositionRepository,
    signal_repository: MemorySignalRepository | None = None,
    candle_repository: MemoryCandleRepository | None = None,
    submission_attempt_repository: MemorySubmissionAttemptRepository | None = None,
    submission_recovery: FakeSubmissionRecovery | None = None,
    post_entry_recovery: FakePostEntryRecovery | None = None,
    market_stream_service: FakeLiveMarketStreamOwner | None = None,
    protection_monitoring_service: FakeLiveProtectionMonitorOwner | None = None,
    autonomous_live_entry_authorization: AutonomousLiveEntryAuthorization | None = None,
) -> tuple[RuntimeRecoveryService, TradingRuntimeControl]:
    """Build isolated recovery dependencies."""
    control = TradingRuntimeControl(
        market_type=MarketType.FUTURES,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
    )
    control.bind_strategy_selector(lambda strategy_type: None)
    position_service = PositionService(
        position_engine=PositionEngine(exchange_client=exchange),
        position_repository=repository,
    )
    protection_service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=repository,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )
    portfolio_recovery_service = LivePortfolioRecoveryService(
        position_service=position_service,
        protection_service=protection_service,
        runtime_control=control,
        signal_repository=signal_repository or MemorySignalRepository(),
        candle_repository=candle_repository or MemoryCandleRepository(),
    )
    stream_owner = (
        market_stream_service
        if market_stream_service is not None
        else FakeLiveMarketStreamOwner()
    )
    monitor_owner = (
        protection_monitoring_service
        if protection_monitoring_service is not None
        else FakeLiveProtectionMonitorOwner()
    )
    service = RuntimeRecoveryService(
        trade_mode=trade_mode,
        market_type=MarketType.FUTURES,
        runtime_control=control,
        stream_controller=ImmediateTickStream(runtime_control=control),
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
        position_repository=repository,
        signal_repository=signal_repository or MemorySignalRepository(),
        candle_repository=candle_repository or MemoryCandleRepository(),
        live_portfolio_recovery_service=portfolio_recovery_service,
        submission_attempt_repository=submission_attempt_repository,
        live_submission_recovery_service=submission_recovery,
        live_post_entry_recovery_service=post_entry_recovery,
        autonomous_live_entry_authorization=autonomous_live_entry_authorization,
        first_tick_timeout_seconds=0.1,
    )
    return service, control


def _acknowledged_attempt() -> SubmissionAttempt:
    """Build one durable entry that requires post-entry startup recovery."""
    return SubmissionAttempt(
        client_order_id="btg-00000000000000000000000000000000",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        signal_generated_at=_NOW,
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        status=SubmissionAttemptStatus.ACKNOWLEDGED,
        created_at=_NOW,
        updated_at=_NOW,
        exchange_order_id="entry-1",
    )


@pytest.mark.asyncio
async def test_paper_position_resumes_stream_and_bot_without_setup() -> None:
    """Restore exact paper metadata and resume after the first stream tick."""
    position = _position(include_metadata=True)
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    exchange = RecoveryExchangeClient(positions=())
    service, control = _recovery_service(
        trade_mode=TradeMode.PAPER,
        exchange=exchange,
        repository=repository,
    )

    recovered = await service.recover()

    assert recovered
    assert not control.is_paused
    assert control.stream_enabled
    assert control.symbol == "BTCUSDT"
    assert control.interval is Interval.M1
    assert control.strategy_type is StrategyType.EMA_SCALPING
    assert exchange.create_calls == 0


@pytest.mark.asyncio
async def test_clean_testnet_autonomous_live_recovery_activates_global_cycle_only() -> (
    None
):
    """A clean portfolio may activate entry discovery without a fake stream."""
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=RecoveryExchangeClient(positions=()),
        repository=MemoryPositionRepository(),
        autonomous_live_entry_authorization=AutonomousLiveEntryAuthorization(
            environment=ExchangeEnvironment.TESTNET,
            explicit_opt_in=True,
        ),
    )

    recovered = await service.recover()

    assert recovered
    assert not control.is_paused
    assert control.runtime_contexts == ()
    assert not control.stream_enabled


@pytest.mark.asyncio
async def test_legacy_paper_metadata_is_reconstructed_from_entry_history() -> None:
    """Recover legacy metadata only from one exact signal and candle match."""
    position = _position(include_metadata=False)
    repository = MemoryPositionRepository()
    signal_repository = MemorySignalRepository()
    candle_repository = MemoryCandleRepository()
    await repository.save(position=position)
    await signal_repository.save(
        signal=Signal(
            symbol=position.symbol,
            signal_type=SignalType.BUY,
            price=position.entry_price,
            confidence=Decimal("0.8"),
            strategy_name=StrategyType.EMA_SCALPING.value,
            generated_at=position.opened_at,
        )
    )
    await candle_repository.save(
        candle=Candle(
            symbol=position.symbol,
            interval=Interval.M1,
            open_time=position.opened_at - timedelta(seconds=60),
            close_time=position.opened_at,
            open_price=position.entry_price,
            high_price=position.entry_price,
            low_price=position.entry_price,
            close_price=position.entry_price,
            volume=Decimal("1"),
        )
    )
    exchange = RecoveryExchangeClient(positions=())
    service, control = _recovery_service(
        trade_mode=TradeMode.PAPER,
        exchange=exchange,
        repository=repository,
        signal_repository=signal_repository,
        candle_repository=candle_repository,
    )

    assert await service.recover()
    assert control.interval is Interval.M1
    assert control.strategy_type is StrategyType.EMA_SCALPING

    stored = await repository.get_by_symbol(symbol=position.symbol)
    assert stored is not None
    assert stored.interval is Interval.M1
    assert stored.strategy_type is StrategyType.EMA_SCALPING


@pytest.mark.asyncio
async def test_live_recovery_creates_missing_protection_only_once() -> None:
    """Protect an exchange position and reuse those orders on the next restart."""
    live_position = _position(include_metadata=False)
    exchange = RecoveryExchangeClient(positions=(live_position,))

    first_repository = MemoryPositionRepository()
    await first_repository.save(position=_position(include_metadata=True))
    first_service, first_control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=first_repository,
    )
    assert await first_service.recover()

    second_repository = first_repository
    second_service, second_control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=second_repository,
    )
    assert await second_service.recover()

    assert exchange.create_calls == 2
    assert len(exchange.protection_orders) == 2
    assert not first_control.is_paused
    assert not second_control.is_paused
    stored = await second_repository.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("64675.000")
    assert stored.take_profit == Decimal("65650.00")


@pytest.mark.asyncio
async def test_live_recovery_without_autonomous_entry_permission() -> None:
    """Configuring autonomous entry off must not skip existing exposure recovery."""
    position = _position(include_metadata=True)
    exchange = RecoveryExchangeClient(positions=(position,))
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        autonomous_live_entry_authorization=None,
    )

    recovered = await service.recover()

    assert recovered
    assert not control.is_paused
    assert control.runtime_contexts[0].symbol == "BTCUSDT"
    assert exchange.create_calls == 2
    assert len(exchange.protection_orders) == 2


@pytest.mark.asyncio
async def test_live_single_position_registers_one_monitor_before_runtime_resume() -> (
    None
):
    """Retain singular activation only after BTC monitor ownership is established."""
    position = _position(include_metadata=True)
    exchange = RecoveryExchangeClient(positions=(position,))
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    monitor_owner = FakeLiveProtectionMonitorOwner()
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        protection_monitoring_service=monitor_owner,
    )

    assert await service.recover()
    assert [state.context.symbol for state in monitor_owner.monitor_states] == [
        "BTCUSDT",
    ]
    assert not control.is_paused
    assert control.stream_enabled


@pytest.mark.asyncio
async def test_live_multiple_safe_positions_activate_management_runtime() -> None:
    """Resume only after exact streams, monitors, and authorization are ready."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(eth_position, btc_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner()
    monitor_owner = FakeLiveProtectionMonitorOwner(events=stream_owner.events)
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
    )

    assert await service.recover()
    assert not control.is_paused
    assert not control.stream_enabled
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "register:BTCUSDT",
        "register:ETHUSDT",
    ]
    assert all(state.first_tick_received for state in stream_owner.stream_states)
    assert [state.context.symbol for state in monitor_owner.monitor_states] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert [context.symbol for context in control.runtime_contexts] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    with pytest.raises(RuntimeError, match="Singular runtime configuration"):
        _ = control.symbol
    authorization = control.live_management_authorization
    assert authorization is not None
    assert authorization.contexts == control.runtime_contexts
    assert not authorization.new_live_entry_allowed
    preconditions = service.get_multi_context_activation_preconditions(
        runtime_is_stopping=False,
    )
    assert preconditions is not None
    assert preconditions.is_eligible


@pytest.mark.asyncio
async def test_live_recovery_replaces_prior_multi_position_runtime_ownership() -> None:
    """Rebuild a fresh exact portfolio without retaining prior local resources."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(
        positions=(
            replace(btc_position, stop_loss=None, take_profit=None),
            replace(eth_position, stop_loss=None, take_profit=None),
        )
    )
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner()
    monitor_owner = FakeLiveProtectionMonitorOwner(events=stream_owner.events)
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
    )

    assert await service.recover()
    first_authorization = control.live_management_authorization
    assert first_authorization is not None

    assert await service.recover()
    second_authorization = control.live_management_authorization
    assert second_authorization is not None
    assert second_authorization is not first_authorization
    assert second_authorization.contexts == control.runtime_contexts
    assert [context.symbol for context in control.runtime_contexts] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert [state.context.symbol for state in monitor_owner.monitor_states] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert [state.identity.symbol for state in stream_owner.stream_states] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "register:BTCUSDT",
        "register:ETHUSDT",
        "monitor_stop:ETHUSDT",
        "monitor_stop:BTCUSDT",
        "stop:ETHUSDT",
        "stop:BTCUSDT",
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "register:BTCUSDT",
        "register:ETHUSDT",
    ]


@pytest.mark.asyncio
async def test_live_multiple_safe_positions_start_three_streams_in_context_order() -> (
    None
):
    """Start and verify every recovered stream sequentially before resuming."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT", interval=Interval.H1)
    sol_position = replace(btc_position, symbol="SOLUSDT", interval=Interval.M5)
    exchange = RecoveryExchangeClient(
        positions=(sol_position, eth_position, btc_position),
    )
    repository = MemoryPositionRepository()
    for position in (btc_position, eth_position, sol_position):
        await repository.save(position=position)
    stream_owner = FakeLiveMarketStreamOwner()
    monitor_owner = FakeLiveProtectionMonitorOwner(events=stream_owner.events)
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
    )

    assert await service.recover()
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "start:SOLUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "wait:SOLUSDT",
        "register:BTCUSDT",
        "register:ETHUSDT",
        "register:SOLUSDT",
    ]
    assert [state.identity.symbol for state in stream_owner.stream_states] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert all(state.first_tick_received for state in stream_owner.stream_states)
    assert [state.context.symbol for state in monitor_owner.monitor_states] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert not control.is_paused


@pytest.mark.asyncio
async def test_live_monitor_registration_failure_cleans_attempt_owned_resources() -> (
    None
):
    """Release BTC monitoring and streams when ETH registration fails."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(btc_position, eth_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner()
    monitor_owner = FakeLiveProtectionMonitorOwner(
        events=stream_owner.events,
        failing_register_symbol="ETHUSDT",
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
    )

    assert not await service.recover()
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "register:BTCUSDT",
        "register:ETHUSDT",
        "monitor_stop:BTCUSDT",
        "stop:ETHUSDT",
        "stop:BTCUSDT",
    ]
    assert monitor_owner.monitor_states == ()
    assert stream_owner.stream_states == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_monitor_registration_cancellation_cleans_resources() -> None:
    """Propagate cancellation after releasing attempt-owned monitors and streams."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(btc_position, eth_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner()
    monitor_owner = FakeLiveProtectionMonitorOwner(
        events=stream_owner.events,
        cancelled_register_symbol="ETHUSDT",
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover()

    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "register:BTCUSDT",
        "register:ETHUSDT",
        "monitor_stop:BTCUSDT",
        "stop:ETHUSDT",
        "stop:BTCUSDT",
    ]
    assert monitor_owner.monitor_states == ()
    assert stream_owner.stream_states == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_multi_stream_start_failure_cleans_only_started_streams() -> None:
    """Fail closed and clean BTC when ETH stream start cannot begin."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(btc_position, eth_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner(failing_start_symbol="ETHUSDT")
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
    )

    assert not await service.recover()
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "stop:BTCUSDT",
    ]
    assert stream_owner.stream_states == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_multi_stream_first_tick_timeout_cleans_all_started_streams() -> (
    None
):
    """Reject partial readiness instead of retaining a BTC-only stream portfolio."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(btc_position, eth_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner(
        first_tick_results={"ETHUSDT": False},
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
    )

    assert not await service.recover()
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "stop:ETHUSDT",
        "stop:BTCUSDT",
    ]
    assert stream_owner.stream_states == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_multi_stream_failure_before_readiness_cleans_all_streams() -> None:
    """Treat identity-specific stream failure as portfolio startup failure."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(btc_position, eth_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner(
        failed_before_ready_symbol="BTCUSDT",
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
    )

    assert not await service.recover()
    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "stop:ETHUSDT",
        "stop:BTCUSDT",
    ]
    assert stream_owner.stream_states == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_multi_stream_wait_cancellation_cleans_started_streams() -> None:
    """Propagate cancellation only after deterministic recovery-owned cleanup."""
    btc_position = _position(include_metadata=True)
    eth_position = replace(btc_position, symbol="ETHUSDT")
    exchange = RecoveryExchangeClient(positions=(btc_position, eth_position))
    repository = MemoryPositionRepository()
    await repository.save(position=btc_position)
    await repository.save(position=eth_position)
    stream_owner = FakeLiveMarketStreamOwner(cancelled_wait_symbol="ETHUSDT")
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        market_stream_service=stream_owner,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover()

    assert stream_owner.events == [
        "start:BTCUSDT",
        "start:ETHUSDT",
        "wait:BTCUSDT",
        "wait:ETHUSDT",
        "stop:ETHUSDT",
        "stop:BTCUSDT",
    ]
    assert stream_owner.stream_states == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_no_positions_clears_stale_runtime_context() -> None:
    """Do not retain a prior singular context when exchange portfolio is empty."""
    exchange = RecoveryExchangeClient(positions=())
    repository = MemoryPositionRepository()
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )
    control.set_runtime_contexts(
        contexts=(
            LiveRuntimePositionContext(
                symbol="SOLUSDT",
                interval=Interval.M1,
                strategy_type=StrategyType.EMA_SCALPING,
            ),
        ),
    )

    assert not await service.recover()
    assert control.runtime_contexts == ()
    assert not control.stream_enabled


@pytest.mark.asyncio
async def test_live_recovery_clears_preexisting_monitor_state_before_recovery() -> None:
    """Release stale monitor ownership instead of merging it into recovery."""
    exchange = RecoveryExchangeClient(positions=())
    repository = MemoryPositionRepository()
    monitor_owner = FakeLiveProtectionMonitorOwner()
    assert monitor_owner.register(
        context=LiveRuntimePositionContext(
            symbol="BTCUSDT",
            interval=Interval.M1,
            strategy_type=StrategyType.EMA_SCALPING,
        )
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
        protection_monitoring_service=monitor_owner,
    )

    assert not await service.recover()
    assert monitor_owner.monitor_states == ()
    assert control.runtime_contexts == ()
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_unsafe_portfolio_clears_stale_runtime_context() -> None:
    """Partial portfolio diagnostics must never preserve prior active context."""
    exchange = RecoveryExchangeClient(positions=(_position(include_metadata=False),))
    repository = MemoryPositionRepository()
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )
    control.set_runtime_contexts(
        contexts=(
            LiveRuntimePositionContext(
                symbol="SOLUSDT",
                interval=Interval.M1,
                strategy_type=StrategyType.EMA_SCALPING,
            ),
        ),
    )

    assert not await service.recover()
    assert control.runtime_contexts == ()
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_live_protection_identities_are_durable_before_new_leg_posts() -> None:
    """Persist distinct logical-leg identities before the first protection POST."""
    position = _position(include_metadata=True)
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    exchange = RecoveryExchangeClient(
        positions=(position,),
        position_repository=repository,
    )
    service, _ = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )

    assert await service.recover()
    stored = await repository.get_by_symbol(symbol=position.symbol)
    assert stored is not None
    assert stored.stop_loss_client_algo_id is not None
    assert stored.take_profit_client_algo_id is not None
    assert stored.stop_loss_client_algo_id != stored.take_profit_client_algo_id
    assert exchange.identity_snapshots == [
        (
            stored.stop_loss_client_algo_id,
            None,
        ),
        (
            stored.stop_loss_client_algo_id,
            stored.take_profit_client_algo_id,
        ),
    ]


@pytest.mark.asyncio
async def test_live_recovery_reconciles_only_missing_protection_leg() -> None:
    """Reuse shared reconciliation when only take-profit coverage is absent."""
    position = _position(include_metadata=True)
    exchange = RecoveryExchangeClient(positions=(position,))
    exchange.protection_orders.append(
        Order(
            order_id="existing-stop",
            symbol=position.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            status=OrderStatus.NEW,
            quantity=position.quantity,
            executed_quantity=Decimal("0"),
            price=None,
            stop_price=position.stop_loss,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    service, _ = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )

    assert await service.recover()
    assert exchange.create_calls == 1
    assert len(exchange.protection_orders) == 2
    assert exchange.protection_orders[0].order_type is OrderType.STOP_MARKET
    assert exchange.protection_orders[1].order_type is OrderType.TAKE_PROFIT_MARKET


@pytest.mark.asyncio
async def test_live_restart_fails_closed_when_persisted_missing_leg_is_not_found() -> (
    None
):
    """Never POST after a restart cannot prove a durable protection mutation."""
    persisted = replace(
        _position(include_metadata=True),
        stop_loss=Decimal("64675"),
        take_profit=Decimal("65650"),
        stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
        take_profit_client_algo_id="btp-00000000000000000000000000000000",
    )
    repository = MemoryPositionRepository()
    await repository.save(position=persisted)
    exchange = RecoveryExchangeClient(positions=(persisted,))
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )

    assert not await service.recover()
    assert exchange.create_calls == 0
    assert exchange.reconciliation_requests == [persisted.stop_loss_client_algo_id]
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_restart_does_not_let_an_old_stop_mask_missing_replacement() -> None:
    """Keep startup paused when an old stop cannot prove the new durable leg."""
    persisted = replace(
        _position(include_metadata=True),
        stop_loss_client_algo_id="bsl-00000000000000000000000000000001",
        take_profit_client_algo_id="btp-00000000000000000000000000000000",
    )
    exchange = RecoveryExchangeClient(positions=(persisted,))
    exchange.protection_orders.extend(
        (
            Order(
                order_id="old-stop",
                symbol=persisted.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.STOP_MARKET,
                status=OrderStatus.NEW,
                quantity=persisted.quantity,
                executed_quantity=Decimal("0"),
                price=None,
                stop_price=Decimal("64000"),
                created_at=_NOW,
                updated_at=_NOW,
                client_order_id="bsl-00000000000000000000000000000000",
            ),
            Order(
                order_id="take-profit",
                symbol=persisted.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                status=OrderStatus.NEW,
                quantity=persisted.quantity,
                executed_quantity=Decimal("0"),
                price=None,
                stop_price=Decimal("65650"),
                created_at=_NOW,
                updated_at=_NOW,
                client_order_id=persisted.take_profit_client_algo_id,
            ),
        )
    )
    repository = MemoryPositionRepository()
    await repository.save(position=persisted)
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )

    assert not await service.recover()
    assert exchange.create_calls == 0
    assert exchange.reconciliation_requests == [persisted.stop_loss_client_algo_id]
    assert control.is_paused


@pytest.mark.asyncio
async def test_live_restart_adopts_proven_persisted_protection_without_post() -> None:
    """Reuse authoritative client-identity matches even before open-order visibility."""
    persisted = replace(
        _position(include_metadata=True),
        stop_loss=Decimal("64675"),
        take_profit=Decimal("65650"),
        stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
        take_profit_client_algo_id="btp-00000000000000000000000000000000",
    )
    exchange = RecoveryExchangeClient(positions=(persisted,))
    exchange.reconciled_protection_orders.extend(
        (
            Order(
                order_id="reconciled-stop",
                symbol=persisted.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.STOP_MARKET,
                status=OrderStatus.NEW,
                quantity=persisted.quantity,
                executed_quantity=Decimal("0"),
                price=None,
                stop_price=Decimal("64675"),
                created_at=_NOW,
                updated_at=_NOW,
                client_order_id=persisted.stop_loss_client_algo_id,
            ),
            Order(
                order_id="reconciled-take-profit",
                symbol=persisted.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                status=OrderStatus.NEW,
                quantity=persisted.quantity,
                executed_quantity=Decimal("0"),
                price=None,
                stop_price=Decimal("65650"),
                created_at=_NOW,
                updated_at=_NOW,
                client_order_id=persisted.take_profit_client_algo_id,
            ),
        )
    )
    repository = MemoryPositionRepository()
    await repository.save(position=persisted)
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=repository,
    )

    assert await service.recover()
    assert exchange.create_calls == 0
    assert exchange.reconciliation_requests == [
        persisted.stop_loss_client_algo_id,
        persisted.take_profit_client_algo_id,
    ]
    assert not control.is_paused


@pytest.mark.asyncio
async def test_live_startup_recovers_acknowledged_entry_before_runtime_readiness() -> (
    None
):
    """Run post-entry recovery before the existing one-position resume workflow."""
    position = _position(include_metadata=True)
    exchange = RecoveryExchangeClient(positions=(position,))
    position_repository = MemoryPositionRepository()
    await position_repository.save(position=position)
    attempt_repository = MemorySubmissionAttemptRepository()
    attempt = _acknowledged_attempt()
    await attempt_repository.save(attempt=attempt)
    events: list[str] = []
    submission_recovery = FakeSubmissionRecovery(
        result=LiveSubmissionRecoveryResult.ORDER_ACKNOWLEDGED,
        events=events,
    )
    post_entry_recovery = FakePostEntryRecovery(
        result=LivePostEntryRecoveryResult.COMPLETED,
        events=events,
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=position_repository,
        submission_attempt_repository=attempt_repository,
        submission_recovery=submission_recovery,
        post_entry_recovery=post_entry_recovery,
    )

    assert await service.recover()
    assert events == ["submission", "post_entry"]
    assert post_entry_recovery.attempts == [attempt]
    assert not control.is_paused


@pytest.mark.asyncio
async def test_live_startup_stays_paused_for_incomplete_submission_recovery() -> None:
    """Do not synchronize positions or create protection after an unsafe handoff."""
    exchange = RecoveryExchangeClient(positions=(_position(include_metadata=True),))
    position_repository = MemoryPositionRepository()
    attempt_repository = MemorySubmissionAttemptRepository()
    await attempt_repository.save(attempt=_acknowledged_attempt())
    submission_recovery = FakeSubmissionRecovery(
        result=LiveSubmissionRecoveryResult.STILL_INCOMPLETE,
    )
    post_entry_recovery = FakePostEntryRecovery(
        result=LivePostEntryRecoveryResult.COMPLETED,
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=position_repository,
        submission_attempt_repository=attempt_repository,
        submission_recovery=submission_recovery,
        post_entry_recovery=post_entry_recovery,
    )

    assert not await service.recover()
    assert submission_recovery.events == ["submission"]
    assert post_entry_recovery.attempts == []
    assert exchange.create_calls == 0
    assert control.is_paused
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_live_startup_stays_paused_when_post_entry_position_is_not_visible() -> (
    None
):
    """Do not fall through to normal recovery after an incomplete post-entry stage."""
    exchange = RecoveryExchangeClient(positions=(_position(include_metadata=True),))
    position_repository = MemoryPositionRepository()
    attempt_repository = MemorySubmissionAttemptRepository()
    await attempt_repository.save(attempt=_acknowledged_attempt())
    events: list[str] = []
    submission_recovery = FakeSubmissionRecovery(
        result=LiveSubmissionRecoveryResult.ORDER_ACKNOWLEDGED,
        events=events,
    )
    post_entry_recovery = FakePostEntryRecovery(
        result=LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE,
        events=events,
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=position_repository,
        submission_attempt_repository=attempt_repository,
        submission_recovery=submission_recovery,
        post_entry_recovery=post_entry_recovery,
    )

    assert not await service.recover()
    assert events == ["submission", "post_entry"]
    assert exchange.create_calls == 0
    assert control.is_paused
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_live_startup_propagates_submission_recovery_cancellation() -> None:
    """Do not convert cancellation into a recoverable startup result."""
    exchange = RecoveryExchangeClient(positions=())
    position_repository = MemoryPositionRepository()
    attempt_repository = MemorySubmissionAttemptRepository()
    submission_recovery = FakeSubmissionRecovery(
        result=LiveSubmissionRecoveryResult.NOTHING_TO_RECOVER,
        error=asyncio.CancelledError(),
    )
    post_entry_recovery = FakePostEntryRecovery(
        result=LivePostEntryRecoveryResult.COMPLETED,
    )
    service, control = _recovery_service(
        trade_mode=TradeMode.LIVE,
        exchange=exchange,
        repository=position_repository,
        submission_attempt_repository=attempt_repository,
        submission_recovery=submission_recovery,
        post_entry_recovery=post_entry_recovery,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover()

    assert post_entry_recovery.attempts == []
    assert control.is_paused
