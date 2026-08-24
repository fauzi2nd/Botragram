from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import aiosqlite
import pytest

from botragram.app import TradingRuntimeControl
from botragram.config.risk_settings import RiskSettings
from botragram.engine import OrderEngine, PositionEngine, RiskEngine
from botragram.enums import (
    ExchangeEnvironment,
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    StrategyType,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.exceptions import ExchangeOrderNotFoundError
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.models import (
    Account,
    AutonomousLiveEntryAuthorization,
    Candle,
    ExchangeSymbolRules,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRuntimePositionContext,
    Order,
    Position,
    SubmissionAttempt,
    Ticker,
    Trade,
)
from botragram.services import (
    LivePortfolioRecoveryService,
    LivePositionProtectionService,
    LivePostEntryRecoveryResult,
    LivePostEntryRecoveryService,
    LiveSubmissionRecoveryService,
    OrderService,
    PositionService,
    RuntimeRecoveryService,
)
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteOrderRepository,
    SQLitePositionRepository,
    SQLiteSignalRepository,
    SQLiteSubmissionAttemptRepository,
)
from botragram.storage.sqlite.live_recovery_repository import (
    SQLiteLiveRecoveryRepository,
)


class _FakeExchangeClient(BaseExchangeClient):
    def __init__(self) -> None:
        self.post_calls = 0
        self.delete_calls = 0
        self.orders: dict[str, Order] = {}
        self.positions: tuple[Position, ...] = ()

    async def connect(self) -> None:  # pragma: no cover - test stub
        return None

    async def close(self) -> None:  # pragma: no cover - test stub
        return None

    async def ping(self) -> bool:  # pragma: no cover - test stub
        return True

    async def get_account(self) -> Account:  # pragma: no cover - test stub
        raise NotImplementedError

    async def get_ticker(
        self, *, symbol: str
    ) -> Ticker:  # pragma: no cover - test stub
        raise NotImplementedError

    async def get_market_entry_rules(
        self, *, symbol: str
    ) -> ExchangeSymbolRules:  # pragma: no cover
        return ExchangeSymbolRules(
            symbol=symbol.upper(),
            market_min_quantity=Decimal("0.001"),
            market_max_quantity=Decimal("1000"),
            market_quantity_step=Decimal("0.001"),
            minimum_price=Decimal("0.01"),
            maximum_price=Decimal("1000000"),
            price_tick_size=Decimal("0.01"),
        )

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        return ()

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        return ()

    async def get_trades(self, *, symbol: str, limit: int) -> Sequence[Trade]:
        return ()

    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:  # pragma: no cover - test stub
        self.post_calls += 1
        raise NotImplementedError

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
    ) -> Sequence[Order]:  # pragma: no cover
        self.post_calls += 1
        return ()

    async def cancel_order(
        self, *, symbol: str, order_id: str
    ) -> Order:  # pragma: no cover
        self.delete_calls += 1
        raise NotImplementedError

    async def cancel_all_orders(
        self, *, symbol: str | None = None
    ) -> Sequence[Order]:  # pragma: no cover
        self.delete_calls += 1
        return ()

    async def get_order(
        self, *, symbol: str, order_id: str
    ) -> Order:  # pragma: no cover
        raise NotImplementedError

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        if client_order_id in self.orders:
            return self.orders[client_order_id]
        raise ExchangeOrderNotFoundError(f"order {client_order_id} not found")

    async def get_open_orders(
        self, *, symbol: str | None = None
    ) -> Sequence[Order]:  # pragma: no cover
        return ()

    async def get_open_protection_orders(
        self, *, symbol: str | None = None
    ) -> Sequence[Order]:  # pragma: no cover
        return ()

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        raise ExchangeOrderNotFoundError(f"protection {client_id} not found")

    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
    ) -> Order:  # pragma: no cover
        self.post_calls += 1
        raise NotImplementedError

    async def get_positions(self, *, symbol: str | None = None) -> Sequence[Position]:
        positions = tuple(
            position for position in self.positions if position.quantity > Decimal("0")
        )

        if symbol is None:
            return positions

        normalized_symbol = symbol.upper()
        return tuple(
            position
            for position in positions
            if position.symbol.upper() == normalized_symbol
        )

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
    ) -> Order:  # pragma: no cover
        del symbol, client_order_id
        self.delete_calls += 1
        raise NotImplementedError

    async def close_all_positions(self) -> Sequence[Order]:  # pragma: no cover
        self.delete_calls += 1
        return ()


class FakeProtectionService:
    async def ensure(self, *, position: Position) -> Position:
        return position

    async def probe_persisted_leg(
        self, *, position: Position, order_type: OrderType, client_id: str
    ) -> str:
        return "not_found"


class FakeOrderService:
    def __init__(self, order: Order) -> None:
        self.order = order

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        return self.order


@dataclass(slots=True)
class _FakeStreamOwner:
    stream_states: tuple[LiveMarketStreamState, ...] = field(default_factory=tuple)

    async def start(
        self, *, context: LiveRuntimePositionContext
    ) -> LiveMarketStreamIdentity:
        raise NotImplementedError

    async def wait_for_first_tick(
        self, *, identity: LiveMarketStreamIdentity, timeout_seconds: float
    ) -> bool:
        return True

    async def stop(self, *, identity: LiveMarketStreamIdentity) -> bool:
        return True


@dataclass(slots=True)
class _FakeMonitorOwner:
    monitor_states: tuple[LiveProtectionMonitorState, ...] = field(
        default_factory=tuple
    )

    def register(self, *, context: LiveRuntimePositionContext) -> bool:
        return True

    def stop(self, *, symbol: str) -> bool:
        return True


class _ImmediateStreamController:
    async def start_market_stream(self) -> bool:
        return True

    async def stop_market_stream(self) -> bool:
        return True


def _now() -> datetime:
    return datetime(2026, 8, 19, tzinfo=UTC)


def _attempt() -> SubmissionAttempt:
    return SubmissionAttempt(
        client_order_id="atomic-000",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        signal_generated_at=_now(),
        interval=Interval.M15,
        strategy_type=None,
        status=SubmissionAttemptStatus.ACKNOWLEDGED,
        created_at=_now(),
        updated_at=_now(),
        exchange_order_id="entry-x",
    )


@pytest.mark.asyncio
async def test_sqlite_single_durable_transition_and_position_removal() -> None:
    db = SQLiteDatabase(database_path=":memory:")
    await db.connect()
    mgr = SQLiteMigrationManager(database=db)
    await mgr.initialize()

    pos_repo = SQLitePositionRepository(database=db)
    att_repo = SQLiteSubmissionAttemptRepository(database=db)

    # Persist prior authoritative position and attempt using same timestamp
    now = _now()
    attempt = replace(_attempt(), signal_generated_at=now)
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=now,
        updated_at=now,
        interval=Interval.M15,
        strategy_type=None,
        entry_client_order_id=attempt.client_order_id,
    )
    await pos_repo.save(position=position)

    await att_repo.save(attempt=attempt)

    filled = Order(
        order_id="entry-atomic",
        client_order_id=attempt.client_order_id,
        symbol=attempt.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_now(),
        updated_at=_now(),
    )

    service = LivePostEntryRecoveryService(
        submission_attempt_repository=att_repo,
        live_recovery_repository=SQLiteLiveRecoveryRepository(subrepo=att_repo),
        position_service=PositionService(
            position_engine=PositionEngine(exchange_client=_FakeExchangeClient()),
            position_repository=pos_repo,
        ),
        protection_service=FakeProtectionService(),
        runtime_control=TradingRuntimeControl(),
        order_service=FakeOrderService(order=filled),
    )

    # Call recovery with the ACK attempt
    result = await service.recover_acknowledged(attempt=attempt)

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE

    # Position must be removed by the atomic repository transaction
    persisted = await pos_repo.get_by_symbol(symbol=attempt.symbol)
    assert persisted is None

    stored = await att_repo.get_by_client_order_id(
        client_order_id=attempt.client_order_id
    )
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE
    await db.close()


@pytest.mark.asyncio
async def test_sqlite_transaction_rollback_preserves_state() -> None:
    db = SQLiteDatabase(database_path=":memory:")
    await db.connect()
    mgr = SQLiteMigrationManager(database=db)
    await mgr.initialize()

    pos_repo = SQLitePositionRepository(database=db)
    att_repo = SQLiteSubmissionAttemptRepository(database=db)

    now = _now()
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=now,
        updated_at=now,
        interval=Interval.M15,
        strategy_type=None,
    )
    await pos_repo.save(position=position)
    attempt = replace(_attempt(), signal_generated_at=now)
    await att_repo.save(attempt=attempt)

    filled = Order(
        order_id="entry-atomic",
        client_order_id=attempt.client_order_id,
        symbol=attempt.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_now(),
        updated_at=_now(),
    )

    # Create a failing DB wrapper that raises during the upsert inside the
    # transactional repository method so we can assert rollback semantics.
    from contextlib import asynccontextmanager

    class FailingSQLiteDB(SQLiteDatabase):
        @asynccontextmanager
        async def transaction(self) -> AsyncGenerator[aiosqlite.Connection, None]:
            connection = self._require_connection()

            class ProxyConn:
                def __init__(self, conn: aiosqlite.Connection) -> None:
                    self._conn = conn

                async def execute(
                    self, statement: str, parameters: tuple[object, ...] = ()
                ) -> aiosqlite.Cursor:
                    if "submission_attempts" in statement:
                        raise RuntimeError("simulate upsert failure")
                    return await self._conn.execute(statement, parameters)

                async def executemany(
                    self, statement: str, parameter_rows: tuple[tuple[object, ...], ...]
                ) -> aiosqlite.Cursor:
                    return await self._conn.executemany(statement, parameter_rows)

                async def executescript(self, script: str) -> aiosqlite.Cursor:
                    return await self._conn.executescript(script)

            try:
                await connection.execute("BEGIN")
                # Cast the proxy to the connection type for the transaction
                yield cast(aiosqlite.Connection, ProxyConn(connection))
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    # Recreate DB with the failing transaction wrapper
    await db.close()
    db = FailingSQLiteDB(database_path=":memory:")
    await db.connect()
    mgr = SQLiteMigrationManager(database=db)
    await mgr.initialize()

    pos_repo = SQLitePositionRepository(database=db)
    att_repo = SQLiteSubmissionAttemptRepository(database=db)

    now = _now()
    attempt = replace(_attempt(), signal_generated_at=now)
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=now,
        updated_at=now,
        interval=Interval.M15,
        strategy_type=None,
        entry_client_order_id=attempt.client_order_id,
    )
    await pos_repo.save(position=position)
    await att_repo.save(attempt=attempt)

    service = LivePostEntryRecoveryService(
        submission_attempt_repository=att_repo,
        live_recovery_repository=SQLiteLiveRecoveryRepository(subrepo=att_repo),
        position_service=PositionService(
            position_engine=PositionEngine(exchange_client=_FakeExchangeClient()),
            position_repository=pos_repo,
        ),
        protection_service=FakeProtectionService(),
        runtime_control=TradingRuntimeControl(),
        order_service=FakeOrderService(order=filled),
    )

    with pytest.raises(RuntimeError):
        await service.recover_acknowledged(attempt=attempt)

    # After rollback, position still exists and attempt remains ACKNOWLEDGED
    persisted = await pos_repo.get_by_symbol(symbol=attempt.symbol)
    assert persisted is not None
    stored = await att_repo.get_by_client_order_id(
        client_order_id=attempt.client_order_id
    )
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.ACKNOWLEDGED
    await db.close()


@pytest.mark.asyncio
async def test_sqlite_restart_idempotency_normal_runtime_recovery_twice() -> None:
    """Dedicated restart-idempotency regression using the NORMAL
    RuntimeRecoveryService/startup recovery path TWICE.
    """
    db = SQLiteDatabase(database_path=":memory:")
    await db.connect()
    mgr = SQLiteMigrationManager(database=db)
    await mgr.initialize()

    class CountingSQLitePositionRepository(SQLitePositionRepository):
        def __init__(self, *, database: SQLiteDatabase) -> None:
            super().__init__(database=database)
            self.mutation_count = 0

        async def save(self, *, position: Position) -> None:
            self.mutation_count += 1
            await super().save(position=position)

        async def delete(self, *, symbol: str) -> bool:
            self.mutation_count += 1
            return await super().delete(symbol=symbol)

    class CountingSQLiteSubmissionAttemptRepository(SQLiteSubmissionAttemptRepository):
        def __init__(self, *, database: SQLiteDatabase) -> None:
            super().__init__(database=database)
            self.resolve_calls = 0
            self.save_count = 0

        async def resolve_no_exposure(
            self, *, symbol: str, attempt: SubmissionAttempt
        ) -> None:
            self.resolve_calls += 1
            await super().resolve_no_exposure(symbol=symbol, attempt=attempt)

        async def save(self, *, attempt: SubmissionAttempt) -> None:
            self.save_count += 1
            await super().save(attempt=attempt)

    pos_repo = CountingSQLitePositionRepository(database=db)
    att_repo = CountingSQLiteSubmissionAttemptRepository(database=db)
    sig_repo = SQLiteSignalRepository(database=db)
    candle_repo = SQLiteCandleRepository(database=db)
    ord_repo = SQLiteOrderRepository(database=db)

    now = _now()
    attempt = replace(
        _attempt(),
        signal_generated_at=now,
        strategy_type=StrategyType.EMA_SCALPING,
        status=SubmissionAttemptStatus.ACKNOWLEDGED,
    )
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=now,
        updated_at=now,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_SCALPING,
        stop_loss_client_algo_id="stop-1",
        take_profit_client_algo_id="tp-1",
        entry_client_order_id=attempt.client_order_id,
    )
    # Seed: prior persisted Position exists
    await pos_repo.save(position=position)
    # Seed: attempt = ACKNOWLEDGED
    await att_repo.save(attempt=attempt)

    filled = Order(
        order_id="entry-atomic",
        client_order_id=attempt.client_order_id,
        symbol=attempt.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_now(),
        updated_at=_now(),
    )

    exchange = _FakeExchangeClient()
    exchange.orders[attempt.client_order_id] = filled
    exchange.positions = ()  # authoritative exchange position is zero

    pos_engine = PositionEngine(exchange_client=exchange)
    ord_engine = OrderEngine(exchange_client=exchange)
    position_service = PositionService(
        position_engine=pos_engine,
        position_repository=pos_repo,
    )
    order_service = OrderService(
        order_engine=ord_engine,
        order_repository=ord_repo,
    )
    risk_engine = RiskEngine(settings=RiskSettings())
    protection_service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=pos_repo,
        risk_engine=risk_engine,
    )
    runtime_control = TradingRuntimeControl(
        market_type=MarketType.FUTURES,
        symbol="BTCUSDT",
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_SCALPING,
    )
    live_recovery_repo = SQLiteLiveRecoveryRepository(subrepo=att_repo)
    post_entry_recovery = LivePostEntryRecoveryService(
        submission_attempt_repository=att_repo,
        live_recovery_repository=live_recovery_repo,
        position_service=position_service,
        protection_service=protection_service,
        runtime_control=runtime_control,
        order_service=order_service,
        protection_reconciler=protection_service,
    )
    submission_recovery = LiveSubmissionRecoveryService(
        submission_attempt_repository=att_repo,
        order_service=order_service,
    )
    portfolio_recovery = LivePortfolioRecoveryService(
        position_service=position_service,
        protection_service=protection_service,
        runtime_control=runtime_control,
        signal_repository=sig_repo,
        candle_repository=candle_repo,
    )
    stream_owner = _FakeStreamOwner()
    monitor_owner = _FakeMonitorOwner()
    stream_controller = _ImmediateStreamController()
    auth = AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.TESTNET,
        explicit_opt_in=True,
    )

    runtime_recovery_service = RuntimeRecoveryService(
        trade_mode=TradeMode.LIVE,
        market_type=MarketType.FUTURES,
        runtime_control=runtime_control,
        stream_controller=stream_controller,
        market_stream_service=stream_owner,
        protection_monitoring_service=monitor_owner,
        position_repository=pos_repo,
        signal_repository=sig_repo,
        candle_repository=candle_repo,
        live_portfolio_recovery_service=portfolio_recovery,
        submission_attempt_repository=att_repo,
        live_submission_recovery_service=submission_recovery,
        live_post_entry_recovery_service=post_entry_recovery,
        autonomous_live_entry_authorization=auth,
        first_tick_timeout_seconds=0.1,
    )

    # ==================== PASS #1 ====================
    pass1_result = await runtime_recovery_service.recover()
    assert pass1_result is True

    # PASS #1 assertions:
    # 1. RESOLVED_NO_EXPOSURE
    stored_attempt_1 = await att_repo.get_by_client_order_id(
        client_order_id=attempt.client_order_id
    )
    assert stored_attempt_1 is not None
    assert stored_attempt_1.status is SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE
    # 2. Position absent
    persisted_pos_1 = await pos_repo.get_by_symbol(symbol=attempt.symbol)
    assert persisted_pos_1 is None
    # 3. resolve_no_exposure total calls = 1
    assert att_repo.resolve_calls == 1
    # 4. incomplete attempts = 0
    incompletes_1 = await att_repo.get_incomplete()
    assert len(incompletes_1) == 0
    # 5. exchange POST = 0
    assert exchange.post_calls == 0
    # 6. exchange DELETE = 0
    assert exchange.delete_calls == 0
    # 7. protection mutation = 0 (no protection orders created)
    # 8. runtime position contexts = 0
    assert len(runtime_control.runtime_contexts) == 0
    # 9. authoritative portfolio = zero
    exchange_positions_1 = await exchange.get_positions()
    assert len(exchange_positions_1) == 0

    # Snapshot mutation counts after pass 1
    pos_mutations_after_pass1 = pos_repo.mutation_count
    att_saves_after_pass1 = att_repo.save_count

    # ==================== PASS #2 ====================
    # Invoke THE SAME startup/runtime recovery path again
    pass2_result = await runtime_recovery_service.recover()
    assert pass2_result is True

    # PASS #2 assertions:
    # 1. normal success (pass2_result is True)
    # 2. resolve_no_exposure total calls remains 1
    assert att_repo.resolve_calls == 1
    # 3. no attempt rewrite
    assert att_repo.save_count == att_saves_after_pass1
    stored_attempt_2 = await att_repo.get_by_client_order_id(
        client_order_id=attempt.client_order_id
    )
    assert stored_attempt_2 == stored_attempt_1
    # 4. no Position mutation
    assert pos_repo.mutation_count == pos_mutations_after_pass1
    persisted_pos_2 = await pos_repo.get_by_symbol(symbol=attempt.symbol)
    assert persisted_pos_2 is None
    # 5. incomplete attempts remain 0
    incompletes_2 = await att_repo.get_incomplete()
    assert len(incompletes_2) == 0
    # 6. exchange POST = 0
    assert exchange.post_calls == 0
    # 7. exchange DELETE = 0
    assert exchange.delete_calls == 0
    # 8. protection mutation = 0
    # 9. runtime contexts remain 0
    assert len(runtime_control.runtime_contexts) == 0
    # 10. portfolio remains zero
    exchange_positions_2 = await exchange.get_positions()
    assert len(exchange_positions_2) == 0
    await db.close()


@pytest.mark.asyncio
async def test_sqlite_failed_correlation_preserves_stale_position() -> None:
    """A failed no-exposure proof must preserve all durable recovery evidence."""
    db = SQLiteDatabase(database_path=":memory:")
    await db.connect()
    manager = SQLiteMigrationManager(database=db)
    await manager.initialize()

    position_repository = SQLitePositionRepository(database=db)
    attempt_repository = SQLiteSubmissionAttemptRepository(database=db)
    exchange = _FakeExchangeClient()

    now = _now()
    attempt = _attempt()
    stale_position = Position(
        symbol=attempt.symbol,
        side=PositionSide.LONG,
        quantity=attempt.quantity,
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=now,
        updated_at=now,
        interval=attempt.interval,
        strategy_type=attempt.strategy_type,
        entry_client_order_id="different-entry-identity",
    )

    await position_repository.save(position=stale_position)
    await attempt_repository.save(attempt=attempt)

    service = LivePostEntryRecoveryService(
        submission_attempt_repository=attempt_repository,
        live_recovery_repository=SQLiteLiveRecoveryRepository(
            subrepo=attempt_repository,
        ),
        position_service=PositionService(
            position_engine=PositionEngine(exchange_client=exchange),
            position_repository=position_repository,
        ),
        protection_service=FakeProtectionService(),
        runtime_control=TradingRuntimeControl(),
    )

    result = await service.recover_acknowledged(attempt=attempt)

    assert result is LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE

    stored_attempt = await attempt_repository.get_by_client_order_id(
        client_order_id=attempt.client_order_id,
    )
    assert stored_attempt is not None
    assert stored_attempt.status is SubmissionAttemptStatus.ACKNOWLEDGED

    persisted_position = await position_repository.get_by_symbol(
        symbol=attempt.symbol,
    )
    assert persisted_position is not None
    assert persisted_position.entry_client_order_id == "different-entry-identity"

    assert exchange.post_calls == 0
    assert exchange.delete_calls == 0

    await db.close()
