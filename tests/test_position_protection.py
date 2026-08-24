"""Stream-driven stepped position protection tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from botragram.config.risk_settings import RiskSettings
from botragram.engine import PnLEngine, RiskEngine, TradingEngine
from botragram.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TradeMode,
)
from botragram.exceptions import ExchangeOrderNotFoundError
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import ExchangeSymbolRules, Order, Position, Ticker
from botragram.services import PaperTradingService, PositionProtectionManager
from botragram.storage.memory import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)

_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class RecordingProtectionExchange(BinanceFuturesExchangeClient):
    """Record verified stop replacements without network access."""

    __slots__ = (
        "previous_stop_client_algo_ids",
        "stop_client_algo_ids",
        "stop_replacements",
    )

    def __init__(self) -> None:
        """Initialize an isolated exchange double."""
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.stop_replacements: list[Decimal] = []
        self.stop_client_algo_ids: list[str | None] = []
        self.previous_stop_client_algo_ids: list[str | None] = []

    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
        previous_client_algo_id: str | None = None,
    ) -> Order:
        """Record one idempotent deterministic active stop."""
        self.previous_stop_client_algo_ids.append(previous_client_algo_id)
        if client_algo_id is not None:
            try:
                return await self.get_protection_order_by_client_id(
                    symbol=symbol,
                    client_id=client_algo_id,
                )
            except ExchangeOrderNotFoundError:
                pass

        self.stop_replacements.append(stop_loss)
        self.stop_client_algo_ids.append(client_algo_id)
        return Order(
            order_id=f"stop-{len(self.stop_replacements)}",
            client_order_id=client_algo_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP_MARKET,
            status=OrderStatus.NEW,
            quantity=quantity,
            executed_quantity=Decimal("0"),
            price=None,
            stop_price=stop_loss,
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return only a previously recorded exact STOP identity."""
        for index, recorded_id in enumerate(self.stop_client_algo_ids):
            if recorded_id != client_id:
                continue
            return Order(
                order_id=f"stop-{index + 1}",
                client_order_id=recorded_id,
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.STOP_MARKET,
                status=OrderStatus.NEW,
                quantity=Decimal("1"),
                executed_quantity=Decimal("0"),
                price=None,
                stop_price=self.stop_replacements[index],
                created_at=_NOW,
                updated_at=_NOW,
            )

        raise ExchangeOrderNotFoundError("configured pending STOP was not found")

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return deterministic Futures protection price rules."""
        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=Decimal("1"),
            market_max_quantity=Decimal("1000000"),
            market_quantity_step=Decimal("1"),
            minimum_price=Decimal("0.01"),
            maximum_price=Decimal("1000000"),
            price_tick_size=Decimal("0.01"),
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return the deterministic stream-adjacent Futures MARK_PRICE."""
        assert symbol == "BTCUSDT"
        return Decimal("99.5")


class RecordingUpdateRepository(MemoryPositionRepository):
    """Record manager persistence snapshots without a database dependency."""

    __slots__ = ("updated_positions",)

    def __init__(self) -> None:
        """Initialize an empty recording repository."""
        super().__init__()
        self.updated_positions: list[Position] = []

    async def update(self, *, position: Position) -> None:
        """Record and persist the manager's immutable position snapshot."""
        self.updated_positions.append(position)
        await super().update(position=position)


class SteppedPriceFilterExchange(RecordingProtectionExchange):
    """Record stepped replacement requests after canonical venue normalization."""

    __slots__ = ("mark_price", "mark_price_error", "rules_error")

    def __init__(
        self,
        *,
        mark_price: Decimal,
        rules_error: BaseException | None = None,
        mark_price_error: BaseException | None = None,
    ) -> None:
        """Initialize configurable read-only Futures inputs for one test."""
        super().__init__()
        self.mark_price = mark_price
        self.rules_error = rules_error
        self.mark_price_error = mark_price_error

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return the deterministic 1000BONK-style PRICE_FILTER rules."""
        if self.rules_error is not None:
            raise self.rules_error
        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=Decimal("1"),
            market_max_quantity=Decimal("100000"),
            market_quantity_step=Decimal("1"),
            minimum_price=Decimal("0.0000010"),
            maximum_price=Decimal("200"),
            price_tick_size=Decimal("0.0000010"),
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return configured MARK_PRICE or propagate cancellation/failure."""
        del symbol
        if self.mark_price_error is not None:
            raise self.mark_price_error
        return self.mark_price


def _short_position() -> Position:
    """Return a short with a one-percent target distance."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("100.5"),
        take_profit=Decimal("99"),
    )


def _ticker(*, price: str, seconds: int) -> Ticker:
    """Return one normalized stream ticker."""
    value = Decimal(price)
    return Ticker(
        symbol="BTCUSDT",
        bid_price=value,
        ask_price=value,
        last_price=value,
        timestamp=_NOW + timedelta(seconds=seconds),
    )


def _stepped_position(
    *,
    side: PositionSide,
    current_stop: str,
    entry_price: str,
    take_profit: str,
) -> Position:
    """Return a step-one position whose raw replacement is off the price grid."""
    return Position(
        symbol="BTCUSDT",
        side=side,
        quantity=Decimal("1"),
        entry_price=Decimal(entry_price),
        current_price=Decimal(entry_price),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal(current_stop),
        take_profit=Decimal(take_profit),
    )


@pytest.mark.asyncio
async def test_paper_protection_advances_steps_and_never_moves_backward() -> None:
    """Lock 30% at half TP progress and 40% at sixty percent progress."""
    repository = MemoryPositionRepository()
    await repository.save(position=_short_position())
    exchange = RecordingProtectionExchange()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=repository,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
    )

    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))
    await manager.on_market_tick(ticker=_ticker(price="99.4", seconds=2))
    await manager.on_market_tick(ticker=_ticker(price="99.45", seconds=3))

    position = await repository.get_by_symbol(symbol="BTCUSDT")
    assert position is not None
    assert position.stop_loss == Decimal("99.60")
    assert position.protection_step == 2
    assert exchange.stop_replacements == []


@pytest.mark.asyncio
async def test_live_protection_verifies_exchange_before_persisting_step() -> None:
    """Move the persisted stop only after the live adapter confirms it."""
    repository = MemoryPositionRepository()
    await repository.save(position=_short_position())
    exchange = RecordingProtectionExchange()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
    )

    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))

    position = await repository.get_by_symbol(symbol="BTCUSDT")
    assert position is not None
    assert exchange.stop_replacements == [Decimal("99.70")]
    assert exchange.stop_client_algo_ids[0] is not None
    assert position.stop_loss == Decimal("99.70")
    assert position.stop_loss_client_algo_id == exchange.stop_client_algo_ids[0]
    assert position.protection_step == 1


@pytest.mark.asyncio
async def test_live_protection_assigns_a_fresh_identity_to_each_stop_replacement() -> (
    None
):
    """Persist a new durable identity before every distinct LIVE stop mutation."""
    repository = MemoryPositionRepository()
    await repository.save(position=_short_position())
    exchange = RecordingProtectionExchange()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
    )

    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))
    await manager.on_market_tick(ticker=_ticker(price="99.4", seconds=2))

    assert len(exchange.stop_client_algo_ids) == 2
    assert exchange.stop_client_algo_ids[0] is not None
    assert exchange.stop_client_algo_ids[1] is not None
    assert exchange.stop_client_algo_ids[0] != exchange.stop_client_algo_ids[1]


@pytest.mark.asyncio
async def test_live_stepped_long_stop_uses_canonical_price_filter_normalization() -> (
    None
):
    """Persist and submit the final upward-normalized LONG replacement trigger."""
    position = _stepped_position(
        side=PositionSide.LONG,
        current_stop="0.0022490",
        entry_price="0.00225712",
        take_profit="0.00226712",
    )
    repository = RecordingUpdateRepository()
    await repository.save(position=position)
    exchange = SteppedPriceFilterExchange(mark_price=Decimal("0.00226212"))
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
    )

    await manager.on_market_tick(ticker=_ticker(price="0.00226212", seconds=1))

    stored = await repository.get_by_symbol(symbol=position.symbol)
    assert stored is not None
    assert exchange.stop_replacements == [Decimal("0.0022610")]
    pending = repository.updated_positions[0]
    assert pending.stop_loss == Decimal("0.0022490")
    assert pending.pending_stop_loss == Decimal("0.0022610")
    assert pending.pending_stop_loss_client_algo_id is not None
    assert stored.stop_loss == Decimal("0.0022610")
    assert stored.stop_loss_client_algo_id == pending.pending_stop_loss_client_algo_id
    assert stored.pending_stop_loss is None
    assert stored.pending_stop_loss_client_algo_id is None


@pytest.mark.asyncio
async def test_live_stepped_short_stop_uses_inverse_price_filter_normalization() -> (
    None
):
    """Persist and submit the final downward-normalized SHORT replacement trigger."""
    position = _stepped_position(
        side=PositionSide.SHORT,
        current_stop="0.0022710",
        entry_price="0.00226312",
        take_profit="0.00225312",
    )
    repository = RecordingUpdateRepository()
    await repository.save(position=position)
    exchange = SteppedPriceFilterExchange(mark_price=Decimal("0.00225812"))
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
    )

    await manager.on_market_tick(ticker=_ticker(price="0.00225812", seconds=1))

    stored = await repository.get_by_symbol(symbol=position.symbol)
    assert stored is not None
    assert exchange.stop_replacements == [Decimal("0.0022600")]
    assert stored.stop_loss == Decimal("0.0022600")


@pytest.mark.asyncio
async def test_live_stepped_same_tick_normalization_does_not_create_mutation() -> None:
    """Avoid protection churn when an improved raw price shares the current tick."""
    position = _stepped_position(
        side=PositionSide.LONG,
        current_stop="0.0022610",
        entry_price="0.00225712",
        take_profit="0.00226712",
    )
    repository = RecordingUpdateRepository()
    await repository.save(position=position)
    exchange = SteppedPriceFilterExchange(mark_price=Decimal("0.00226212"))
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
    )

    await manager.on_market_tick(ticker=_ticker(price="0.00226212", seconds=1))

    assert repository.updated_positions == []
    assert exchange.stop_replacements == []
    assert exchange.stop_client_algo_ids == []


@pytest.mark.asyncio
async def test_invalid_live_stepped_stop_defers_without_losing_protection() -> None:
    """Keep verified protection healthy when a stepped stop misses its MARK window."""
    position = _stepped_position(
        side=PositionSide.LONG,
        current_stop="0.0022490",
        entry_price="0.00225712",
        take_profit="0.00226712",
    )
    repository = RecordingUpdateRepository()
    await repository.save(position=position)
    exchange = SteppedPriceFilterExchange(mark_price=Decimal("0.0022600"))
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
        failure_retry_seconds=0.001,
    )

    await manager.on_market_tick(ticker=_ticker(price="0.00226212", seconds=1))

    stored = await repository.get_by_symbol(symbol=position.symbol)
    assert stored == position
    assert repository.updated_positions == []
    assert exchange.stop_replacements == []
    assert exchange.stop_client_algo_ids == []

    await asyncio.sleep(0.002)
    exchange.mark_price = Decimal("0.00226212")
    await manager.on_market_tick(ticker=_ticker(price="0.00226212", seconds=2))

    stored = await repository.get_by_symbol(symbol=position.symbol)
    assert stored is not None
    assert exchange.stop_replacements == [Decimal("0.0022610")]
    assert stored.stop_loss == Decimal("0.0022610")
    assert stored.protection_step == 1


@pytest.mark.asyncio
async def test_live_stepped_rule_or_mark_read_failure_has_no_mutation() -> None:
    """Reject failed authoritative inputs before durable replacement state exists."""
    for rules_error, mark_price_error in (
        (RuntimeError("rules unavailable"), None),
        (None, RuntimeError("mark unavailable")),
    ):
        position = _stepped_position(
            side=PositionSide.LONG,
            current_stop="0.0022490",
            entry_price="0.00225712",
            take_profit="0.00226712",
        )
        repository = RecordingUpdateRepository()
        await repository.save(position=position)
        exchange = SteppedPriceFilterExchange(
            mark_price=Decimal("0.00226212"),
            rules_error=rules_error,
            mark_price_error=mark_price_error,
        )
        manager = PositionProtectionManager(
            trade_mode=TradeMode.LIVE,
            position_repository=repository,
            exchange_client=exchange,
        )

        with pytest.raises(RuntimeError):
            await manager.on_market_tick(ticker=_ticker(price="0.00226212", seconds=1))

        assert repository.updated_positions == []
        assert exchange.stop_replacements == []


def test_live_stepped_cancellation_before_identity_propagates() -> None:
    """Never convert cancellation into a replacement or stale-stop cancellation."""

    async def run() -> None:
        position = _stepped_position(
            side=PositionSide.LONG,
            current_stop="0.0022490",
            entry_price="0.00225712",
            take_profit="0.00226712",
        )
        repository = RecordingUpdateRepository()
        await repository.save(position=position)
        exchange = SteppedPriceFilterExchange(
            mark_price=Decimal("0.00226212"),
            mark_price_error=asyncio.CancelledError(),
        )
        manager = PositionProtectionManager(
            trade_mode=TradeMode.LIVE,
            position_repository=repository,
            exchange_client=exchange,
        )

        await manager.on_market_tick(ticker=_ticker(price="0.00226212", seconds=1))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())


@pytest.mark.asyncio
async def test_paper_stream_closes_position_when_stepped_stop_is_hit() -> None:
    """Close on the stream instead of waiting for the next candle cycle."""
    position_repository = MemoryPositionRepository()
    await position_repository.save(position=_short_position())
    service = PaperTradingService(
        order_repository=MemoryOrderRepository(),
        trade_repository=MemoryTradeRepository(),
        position_repository=position_repository,
        trading_engine=TradingEngine(risk_engine=RiskEngine(settings=RiskSettings())),
        pnl_engine=PnLEngine(),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=position_repository,
        exchange_client=RecordingProtectionExchange(),
    )

    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))
    await service.on_market_tick(ticker=_ticker(price="99.7", seconds=2))

    assert await position_repository.get_by_symbol(symbol="BTCUSDT") is None


@pytest.mark.asyncio
async def test_live_failed_step_keeps_current_stop_and_pending_intent() -> None:
    """Never overwrite current STOP ownership before replacement is proven."""

    class FailOnceExchange(RecordingProtectionExchange):
        __slots__ = ("fail_once",)

        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        async def ensure_stop_loss_order(
            self,
            *,
            symbol: str,
            side: OrderSide,
            quantity: Decimal,
            stop_loss: Decimal,
            client_algo_id: str | None = None,
            previous_client_algo_id: str | None = None,
        ) -> Order:
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("configured replacement failure")
            return await super().ensure_stop_loss_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_loss=stop_loss,
                client_algo_id=client_algo_id,
                previous_client_algo_id=previous_client_algo_id,
            )

    current_id = "bsl-11111111111111111111111111111111"
    position = replace(
        _short_position(),
        stop_loss_client_algo_id=current_id,
    )
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    exchange = FailOnceExchange()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        failure_retry_seconds=0.001,
    )

    with pytest.raises(RuntimeError, match="configured replacement failure"):
        await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))

    pending = await repository.get_by_symbol(symbol=position.symbol)
    assert pending is not None
    assert pending.stop_loss == Decimal("100.5")
    assert pending.stop_loss_client_algo_id == current_id
    assert pending.protection_step == 0
    assert pending.pending_stop_loss == Decimal("99.70")
    assert pending.pending_stop_loss_client_algo_id is not None
    assert pending.pending_protection_step == 1

    await asyncio.sleep(0.002)
    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=2))

    promoted = await repository.get_by_symbol(symbol=position.symbol)
    assert promoted is not None
    assert promoted.stop_loss == Decimal("99.70")
    assert promoted.stop_loss_client_algo_id == pending.pending_stop_loss_client_algo_id
    assert promoted.protection_step == 1
    assert promoted.pending_stop_loss is None
    assert promoted.pending_stop_loss_client_algo_id is None
    assert promoted.pending_protection_step == 0
    assert exchange.previous_stop_client_algo_ids == [current_id]


@pytest.mark.asyncio
async def test_live_absent_invalid_pending_stop_is_retired_without_churn() -> None:
    """Release a stale absent pending intent once its trigger is venue-invalid."""
    current_id = "bsl-11111111111111111111111111111111"
    stale_pending_id = "bsl-22222222222222222222222222222222"
    position = replace(
        _short_position(),
        stop_loss_client_algo_id=current_id,
        pending_stop_loss=Decimal("99.70"),
        pending_stop_loss_client_algo_id=stale_pending_id,
        pending_protection_step=1,
    )
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    exchange = SteppedPriceFilterExchange(mark_price=Decimal("100"))
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
    )

    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))

    cleared = await repository.get_by_symbol(symbol=position.symbol)
    assert cleared is not None
    assert cleared.stop_loss == Decimal("100.5")
    assert cleared.stop_loss_client_algo_id == current_id
    assert cleared.protection_step == 0
    assert cleared.pending_stop_loss is None
    assert cleared.pending_stop_loss_client_algo_id is None
    assert cleared.pending_protection_step == 0
    assert exchange.stop_replacements == []

    exchange.mark_price = Decimal("99.5")
    await asyncio.sleep(0.002)
    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=2))

    advanced = await repository.get_by_symbol(symbol=position.symbol)
    assert advanced is not None
    assert advanced.stop_loss == Decimal("99.700000")
    assert advanced.stop_loss_client_algo_id is not None
    assert advanced.stop_loss_client_algo_id != stale_pending_id
    assert advanced.protection_step == 1


@pytest.mark.asyncio
async def test_live_active_pending_stop_promotes_despite_moved_mark_price() -> None:
    """Do not discard an already-active pending STOP because MARK_PRICE moved."""
    current_id = "bsl-33333333333333333333333333333333"
    pending_id = "bsl-44444444444444444444444444444444"
    position = replace(
        _short_position(),
        stop_loss_client_algo_id=current_id,
        pending_stop_loss=Decimal("99.70"),
        pending_stop_loss_client_algo_id=pending_id,
        pending_protection_step=1,
    )
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    exchange = SteppedPriceFilterExchange(mark_price=Decimal("100"))
    exchange.stop_replacements.append(Decimal("99.70"))
    exchange.stop_client_algo_ids.append(pending_id)
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repository,
        exchange_client=exchange,
    )

    await manager.on_market_tick(ticker=_ticker(price="99.5", seconds=1))

    promoted = await repository.get_by_symbol(symbol=position.symbol)
    assert promoted is not None
    assert promoted.stop_loss == Decimal("99.70")
    assert promoted.stop_loss_client_algo_id == pending_id
    assert promoted.protection_step == 1
    assert promoted.pending_stop_loss is None
    assert promoted.pending_stop_loss_client_algo_id is None
    assert exchange.previous_stop_client_algo_ids == [current_id]
