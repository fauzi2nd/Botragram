"""Stream-driven stepped position protection tests."""

from __future__ import annotations

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
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import Order, Position, Ticker
from botragram.services import PaperTradingService, PositionProtectionManager
from botragram.storage.memory import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)

_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class RecordingProtectionExchange(BinanceFuturesExchangeClient):
    """Record verified stop replacements without network access."""

    __slots__ = ("stop_client_algo_ids", "stop_replacements")

    def __init__(self) -> None:
        """Initialize an isolated exchange double."""
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.stop_replacements: list[Decimal] = []
        self.stop_client_algo_ids: list[str | None] = []

    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
    ) -> Order:
        """Record and return one deterministic active stop."""
        self.stop_replacements.append(stop_loss)
        self.stop_client_algo_ids.append(client_algo_id)
        return Order(
            order_id=f"stop-{len(self.stop_replacements)}",
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
