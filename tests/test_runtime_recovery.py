"""Active-position restart recovery tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.config.risk_settings import RiskSettings
from botragram.engine import PositionEngine, RiskEngine
from botragram.enums import (
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import Candle, Order, Position, Signal
from botragram.services import PositionService, RuntimeRecoveryService
from botragram.storage.memory import (
    MemoryCandleRepository,
    MemoryPositionRepository,
    MemorySignalRepository,
)

_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class RecoveryExchangeClient(BinanceFuturesExchangeClient):
    """Provide deterministic positions and protection orders for recovery."""

    __slots__ = ("create_calls", "positions", "protection_orders")

    def __init__(self, *, positions: tuple[Position, ...]) -> None:
        """Initialize the fake Futures exchange."""
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.positions = positions
        self.protection_orders: list[Order] = []
        self.create_calls = 0

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
    ) -> tuple[Order, ...]:
        """Create deterministic protection snapshots."""
        self.create_calls += 1
        created: list[Order] = []

        for order_type, trigger_price in (
            (OrderType.STOP_MARKET, stop_loss),
            (OrderType.TAKE_PROFIT_MARKET, take_profit),
        ):
            if trigger_price is None:
                continue

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
            )
            self.protection_orders.append(order)
            created.append(order)

        return tuple(created)


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
) -> tuple[RuntimeRecoveryService, TradingRuntimeControl]:
    """Build isolated recovery dependencies."""
    control = TradingRuntimeControl(
        market_type=MarketType.FUTURES,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
    )
    control.bind_strategy_selector(lambda strategy_type: None)
    service = RuntimeRecoveryService(
        trade_mode=trade_mode,
        market_type=MarketType.FUTURES,
        runtime_control=control,
        stream_controller=ImmediateTickStream(runtime_control=control),
        position_service=PositionService(
            position_engine=PositionEngine(exchange_client=exchange),
            position_repository=repository,
        ),
        position_repository=repository,
        signal_repository=signal_repository or MemorySignalRepository(),
        candle_repository=candle_repository or MemoryCandleRepository(),
        exchange_client=exchange,
        risk_engine=RiskEngine(settings=RiskSettings()),
        first_tick_timeout_seconds=0.1,
    )
    return service, control


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

    assert exchange.create_calls == 1
    assert len(exchange.protection_orders) == 2
    assert not first_control.is_paused
    assert not second_control.is_paused
    stored = await second_repository.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("64675.000")
    assert stored.take_profit == Decimal("65650.00")
