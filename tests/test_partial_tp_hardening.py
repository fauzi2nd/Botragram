"""
Botragram

Description:
    Regression test suite for position protection partial TP hardening,
    same-tick state machine, fallback reconciliation, and invariants.

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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TradeMode,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import ExchangeSymbolRules, Order, Position, Ticker
from botragram.services import PositionProtectionManager
from botragram.storage.memory import MemoryPositionRepository

# =============================================================================
# Constants & Helpers
# =============================================================================
_NOW = datetime(2026, 8, 7, tzinfo=UTC)


def _ticker(*, price: str, seconds: int = 1) -> Ticker:
    """Return a normalized stream ticker."""
    value = Decimal(price)
    return Ticker(
        symbol="BTCUSDT",
        bid_price=value,
        ask_price=value,
        last_price=value,
        timestamp=_NOW + timedelta(seconds=seconds),
    )


class _HardeningExchange(BinanceFuturesExchangeClient):
    """Controllable exchange double for protection hardening audits."""

    def __init__(self) -> None:
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.created_orders: list[Order] = []
        self.positions: list[Position] = []
        self.fail_stop_replacement = False
        self.fail_get_order_unknown = False
        self.fail_get_positions = False
        self.ensure_stop_call_count = 0
        self.reference_price = Decimal("105.00")

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        del symbol
        return ExchangeSymbolRules(
            symbol="BTCUSDT",
            market_min_quantity=Decimal("0.001"),
            market_max_quantity=Decimal("1000000"),
            market_quantity_step=Decimal("0.001"),
            minimum_price=Decimal("0.01"),
            maximum_price=Decimal("1000000"),
            price_tick_size=Decimal("0.01"),
        )

    async def get_reference_price(self, *, symbol: str) -> Decimal:
        del symbol
        return self.reference_price

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        del symbol
        return self.reference_price

    async def create_reduce_only_market_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_order_id: str | None = None,
    ) -> Order:
        order = Order(
            order_id=f"ptp-order-{len(self.created_orders) + 1}",
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=quantity,
            executed_quantity=quantity,
            price=None,
            stop_price=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        self.created_orders.append(order)
        return order

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
        self.ensure_stop_call_count += 1
        del previous_client_algo_id
        if self.fail_stop_replacement:
            raise ExchangeOrderOutcomeUnknownError(
                "Simulated exchange failure during stop replacement"
            )
        order = Order(
            order_id=f"stop-order-{len(self.created_orders) + 1}",
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
        self.created_orders.append(order)
        return order

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        for order in self.created_orders:
            if order.client_order_id == client_id:
                return order
        raise ExchangeOrderNotFoundError(f"Stop not found: {client_id}")

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        if self.fail_get_order_unknown:
            raise ExchangeOrderOutcomeUnknownError(
                f"Simulated unknown outcome for order {client_order_id}"
            )
        for order in self.created_orders:
            if order.client_order_id == client_order_id:
                return order
        raise ExchangeOrderNotFoundError(f"Order not found: {client_order_id}")

    async def get_positions(self, *, symbol: str | None = None) -> tuple[Position, ...]:
        if self.fail_get_positions:
            raise RuntimeError("Simulated failure querying exchange positions")
        if symbol is None:
            return tuple(self.positions)
        return tuple(p for p in self.positions if p.symbol.upper() == symbol.upper())


# =============================================================================
# 1. Partial TP at Step 0 -> BE stop armed and promoted
# =============================================================================
@pytest.mark.asyncio
async def test_partial_tp_at_step_0_arms_and_promotes_be_stop() -> None:
    """Partial TP at step 0 arms BE stop and promotes cleanly."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-initial-0",
        take_profit=Decimal("110"),
        protection_step=0,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("102.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="102.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.partial_tp_order_id == "ptp-order-1"
    assert stored.pending_partial_tp_client_order_id is None
    assert stored.pending_partial_tp_quantity is None
    assert stored.protection_step == 1
    assert stored.stop_loss == Decimal("100.16")
    assert stored.pending_stop_loss is None
    assert stored.pending_stop_loss_client_algo_id is None
    assert stored.pending_protection_step == 0
    assert exchange.ensure_stop_call_count == 1


# =============================================================================
# 2. Partial TP at Step 1 when current stop == BE stop
# =============================================================================
@pytest.mark.asyncio
async def test_partial_tp_at_step_1_current_stop_equals_be_preserves_stop() -> None:
    """When current stop is already at BE, do not arm invalid identical pending stop."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("100.16"),
        stop_loss_client_algo_id="sl-active-be",
        take_profit=Decimal("110"),
        protection_step=1,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("102.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    # Should not raise ValueError about same-step tightening
    await manager.on_market_tick(ticker=_ticker(price="102.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.partial_tp_order_id == "ptp-order-1"
    assert stored.pending_partial_tp_client_order_id is None
    assert stored.pending_partial_tp_quantity is None
    assert stored.protection_step == 1
    assert stored.stop_loss == Decimal("100.16")
    assert stored.stop_loss_client_algo_id == "sl-active-be"
    assert stored.pending_stop_loss is None
    assert stored.pending_stop_loss_client_algo_id is None
    assert stored.pending_protection_step == 0
    assert exchange.ensure_stop_call_count == 0


# =============================================================================
# 3. Partial TP at Step 1 when current stop is TIGHTER than BE
# =============================================================================
@pytest.mark.asyncio
async def test_partial_tp_at_step_1_current_stop_tighter_than_be_preserves_stop() -> (
    None
):
    """When current stop is already tighter than BE, do not weaken to BE."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("100.30"),
        stop_loss_client_algo_id="sl-active-tight",
        take_profit=Decimal("110"),
        protection_step=1,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("102.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="102.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.stop_loss == Decimal("100.30")
    assert stored.stop_loss_client_algo_id == "sl-active-tight"
    assert stored.protection_step == 1
    assert stored.pending_stop_loss is None
    assert stored.pending_protection_step == 0
    assert exchange.ensure_stop_call_count == 0


# =============================================================================
# 4. Partial TP at Step 2+ -> stepped stop preserved, not weakened
# =============================================================================
@pytest.mark.asyncio
async def test_partial_tp_at_step_2_stepped_stop_preserved() -> None:
    """Stepped stop at step 2 remains canonical during partial TP."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("101.50"),
        stop_loss_client_algo_id="sl-active-step2",
        take_profit=Decimal("110"),
        protection_step=2,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("102.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="102.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.stop_loss == Decimal("101.50")
    assert stored.stop_loss_client_algo_id == "sl-active-step2"
    assert stored.protection_step == 2
    assert stored.pending_stop_loss is None
    assert stored.pending_protection_step == 0
    assert exchange.ensure_stop_call_count == 0


# =============================================================================
# 5. Partial TP when current stop is None -> BE armed and promoted
# =============================================================================
@pytest.mark.asyncio
async def test_partial_tp_when_current_stop_is_none_arms_and_promotes() -> None:
    """When stop is None, partial TP establishes durable BE protection."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=None,
        take_profit=Decimal("110"),
        protection_step=0,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("102.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="102.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.stop_loss == Decimal("100.16")
    assert stored.protection_step == 1
    assert stored.pending_stop_loss is None
    assert stored.pending_protection_step == 0
    assert exchange.ensure_stop_call_count == 1


# =============================================================================
# 6. Same-tick partial TP + subsequent step advancement
# =============================================================================
@pytest.mark.asyncio
async def test_partial_tp_verified_fill_and_same_tick_step_advancement() -> None:
    """Verified fill allows subsequent step advancement on same tick cleanly."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-initial-0",
        take_profit=Decimal("110"),
        protection_step=0,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("108.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    # Price 108.50 triggers partial TP (progress 85% >= 50%)
    # AND resolves to Step 5 (progress 85% >= 75%) on the same tick!
    await manager.on_market_tick(ticker=_ticker(price="108.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.partial_tp_order_id == "ptp-order-1"
    assert stored.protection_step == 5
    assert stored.stop_loss is not None
    assert stored.stop_loss > Decimal("100.16")
    assert stored.pending_stop_loss is None
    assert stored.pending_protection_step == 0
    # Exactly 2 stop replacement calls: 1 for BE after partial fill, 1 for Step 5
    assert exchange.ensure_stop_call_count == 2


# =============================================================================
# 7. Partial fill success + stop replacement failure -> pending preserved
# =============================================================================
@pytest.mark.asyncio
async def test_partial_fill_succeeds_stop_replacement_fails_retains_pending() -> None:
    """When stop replacement fails, pending STOP is queued and retained."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-active-0",
        take_profit=Decimal("110"),
        protection_step=0,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.fail_stop_replacement = True

    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    # Tick triggers partial TP; order fills, but stop replacement fails
    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.partial_tp_order_id == "ptp-order-1"
    # Predecessor active stop retained
    assert stored.stop_loss == Decimal("95")
    assert stored.stop_loss_client_algo_id == "sl-active-0"
    assert stored.protection_step == 0
    # Pending stop replacement safely queued
    assert stored.pending_stop_loss == Decimal("100.16")
    assert stored.pending_stop_loss_client_algo_id is not None
    assert stored.pending_protection_step == 1

    # Same-tick logic did not overwrite pending stop! Now fix exchange and recover
    exchange.fail_stop_replacement = False
    recovery_manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await recovery_manager.on_market_tick(ticker=_ticker(price="105.00", seconds=2))

    recovered = await repo.get_by_symbol(symbol="BTCUSDT")
    assert recovered is not None
    assert recovered.stop_loss == Decimal("100.16")
    assert recovered.protection_step == 1
    assert recovered.pending_stop_loss is None
    assert recovered.pending_stop_loss_client_algo_id is None
    assert recovered.pending_protection_step == 0


# =============================================================================
# 8. Restart / recovery after partial fill before stop replacement finishes
# =============================================================================
@pytest.mark.asyncio
async def test_restart_recovery_after_partial_fill_before_stop_replacement() -> None:
    """Crash after partial fill recovers pending stop replacement on restart."""
    pending_id = Position.create_stop_loss_client_algo_id()
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("5"),
        entry_price=Decimal("100"),
        current_price=Decimal("105"),
        unrealized_pnl=Decimal("25"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-active-0",
        take_profit=Decimal("110"),
        protection_step=0,
        partial_tp_executed=True,
        partial_tp_order_id="ptp-order-crash",
        pending_stop_loss=Decimal("100.16"),
        pending_stop_loss_client_algo_id=pending_id,
        pending_protection_step=1,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()

    # Fresh manager simulates restart
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("100.16")
    assert stored.protection_step == 1
    assert stored.stop_loss_client_algo_id == pending_id
    assert stored.pending_stop_loss is None
    assert stored.pending_stop_loss_client_algo_id is None
    assert stored.pending_protection_step == 0


# =============================================================================
# 9. Fallback reconciliation matrix (Cases A through G)
# =============================================================================
@pytest.mark.asyncio
async def test_not_found_order_delta_matches_requested_retains_intent() -> None:
    """Case C: exact order NOT_FOUND, delta == requested → MUST retain pending intent.

    Position delta is NOT authoritative proof of order fill ownership.
    Liquidation, manual close, or a concurrent action can produce an identical
    delta. The system must retain durable pending intent and retry.
    """
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-in-flight-exact",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    # Exchange position reduced by exactly 5 (matching requested) — but this
    # alone does NOT prove this particular order caused the delta.
    exchange.positions = [
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("5"),
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            unrealized_pnl=Decimal("25"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    ]
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    # Fail-closed: local quantity MUST NOT be mutated by position delta alone.
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-in-flight-exact"
    assert stored.pending_partial_tp_quantity == Decimal("5")


@pytest.mark.asyncio
async def test_fallback_reconciliation_unrelated_reduction_fails_closed() -> None:
    """Case B & C & E: delta != requested (e.g. delta=3 vs req=5) -> fail-closed."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-unrelated-reduction",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    # Exchange position is 7 -> delta is 3, while requested is 5!
    exchange.positions = [
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("7"),
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            unrealized_pnl=Decimal("35"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    ]
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    # No false attribution: local quantity untouched, pending intent retained
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-unrelated-reduction"
    assert stored.pending_partial_tp_quantity == Decimal("5")


@pytest.mark.asyncio
async def test_fallback_reconciliation_delta_exceeds_requested_fails_closed() -> None:
    """Case F: delta > requested (e.g. delta=7 vs req=5) -> fail-closed."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-excess-reduction",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    # Exchange position is 3 -> delta is 7 > requested 5!
    exchange.positions = [
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("3"),
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            unrealized_pnl=Decimal("15"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    ]
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-excess-reduction"


@pytest.mark.asyncio
async def test_fallback_reconciliation_delta_exceeds_local_quantity_fails_closed() -> (
    None
):
    """Case G: executed_qty > local_quantity -> fail-closed."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("5"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-exceed-local",
        pending_partial_tp_quantity=Decimal("6"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    # Negative exchange position simulates delta of 6 > local quantity of 5
    exchange.positions = [
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("-1"),
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            unrealized_pnl=Decimal("0"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    ]
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-exceed-local"
    assert stored.pending_partial_tp_quantity == Decimal("6")


@pytest.mark.asyncio
async def test_fallback_reconciliation_order_outcome_unknown_fails_closed() -> None:
    """Case F1: get_order raises ExchangeOrderOutcomeUnknownError -> fail closed."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-unknown-outcome",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.fail_get_order_unknown = True
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-unknown-outcome"
    assert stored.pending_partial_tp_quantity == Decimal("5")


@pytest.mark.asyncio
async def test_fallback_reconciliation_positions_query_failure_fails_closed() -> None:
    """Case F2: get_positions fails on venue -> fail closed, retain intent."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-pos-fail",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.fail_get_positions = True
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-pos-fail"
    assert stored.pending_partial_tp_quantity == Decimal("5")


@pytest.mark.asyncio
async def test_not_found_order_position_unchanged_retains_intent() -> None:
    """Case D: exact order NOT_FOUND, position unchanged → MUST retain pending intent.

    "Position unchanged" does not prove the order did not fill: indexing or
    propagation delay at the exchange may simply not yet be visible. The system
    must retain durable pending intent and retry on the next cycle.
    """
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-never-filled",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    # Venue position appears untouched — but this is not authoritative proof
    # that the order never filled (indexing delay may be the cause).
    exchange.positions = [
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("10"),
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            unrealized_pnl=Decimal("50"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    ]
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    # Fail-closed: intent MUST NOT be cleared without authoritative order outcome.
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-never-filled"
    assert stored.pending_partial_tp_quantity == Decimal("5")


# =============================================================================
# 10. SHORT symmetry tests
# =============================================================================
@pytest.mark.asyncio
async def test_short_partial_tp_current_stop_equals_be_preserves_stop() -> None:
    """SHORT: when current stop is at BE, do not arm invalid pending stop."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("99.84"),
        stop_loss_client_algo_id="sl-short-be",
        take_profit=Decimal("90"),
        protection_step=1,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("97.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    # Ticker at 97.50 (progress 25% for short)
    await manager.on_market_tick(ticker=_ticker(price="97.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.stop_loss == Decimal("99.84")
    assert stored.stop_loss_client_algo_id == "sl-short-be"
    assert stored.protection_step == 1
    assert stored.pending_stop_loss is None
    assert stored.pending_protection_step == 0
    assert exchange.ensure_stop_call_count == 0


@pytest.mark.asyncio
async def test_short_partial_tp_current_stop_tighter_than_be_preserves_stop() -> None:
    """SHORT: when current stop is tighter than BE (e.g. 99.70 < 99.84), preserve it."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("99.70"),
        stop_loss_client_algo_id="sl-short-tight",
        take_profit=Decimal("90"),
        protection_step=1,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("97.50")
    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.25"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    await manager.on_market_tick(ticker=_ticker(price="97.50"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("5")
    assert stored.partial_tp_executed is True
    assert stored.stop_loss == Decimal("99.70")
    assert stored.stop_loss_client_algo_id == "sl-short-tight"
    assert stored.protection_step == 1
    assert stored.pending_stop_loss is None
    assert exchange.ensure_stop_call_count == 0


# =============================================================================
# 11. Position domain invariant tests
# =============================================================================
def test_position_invariants_pending_partial_tp_quantity_validation() -> None:
    """Pending partial TP quantity must be positive and both ID/qty required."""
    base = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
    )

    with pytest.raises(ValueError, match="must be positive"):
        replace(
            base,
            pending_partial_tp_client_order_id="ptp-zero",
            pending_partial_tp_quantity=Decimal("0"),
        )

    with pytest.raises(ValueError, match="requires both"):
        replace(
            base,
            pending_partial_tp_client_order_id="ptp-missing-qty",
            pending_partial_tp_quantity=None,
        )

    with pytest.raises(ValueError, match="requires both"):
        replace(
            base,
            pending_partial_tp_client_order_id=None,
            pending_partial_tp_quantity=Decimal("5"),
        )


def test_position_invariants_pending_partial_tp_identity_clash() -> None:
    """Pending partial TP client ID must not collide with protection legs."""
    base = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-active-1",
        take_profit=Decimal("110"),
        take_profit_client_algo_id="tp-active-1",
    )

    with pytest.raises(ValueError, match="must be distinct from protection legs"):
        replace(
            base,
            pending_partial_tp_client_order_id="sl-active-1",
            pending_partial_tp_quantity=Decimal("5"),
        )

    with pytest.raises(ValueError, match="must be distinct from protection legs"):
        replace(
            base,
            pending_partial_tp_client_order_id="tp-active-1",
            pending_partial_tp_quantity=Decimal("5"),
        )


# =============================================================================
# 12. Multi-tick / restart regression tests (Cases I, J, K and exact-once §6)
# =============================================================================


class _SequencedOrderExchange(_HardeningExchange):
    """Exchange that returns pre-programmed per-call responses for order lookup.

    Each call to ``get_order_by_client_order_id`` consumes the next entry
    in ``order_responses``.  Pass ``ExchangeOrderNotFoundError()`` instances
    for not-found legs, or ``Order`` instances for found-order legs.
    """

    def __init__(self, order_responses: list[Order | Exception]) -> None:
        super().__init__()
        self._order_responses = list(order_responses)
        self._response_index = 0

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        if self._response_index >= len(self._order_responses):
            raise ExchangeOrderNotFoundError(
                f"No more programmed responses for: {client_order_id}"
            )
        response = self._order_responses[self._response_index]
        self._response_index += 1
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_not_found_pending_intent_survives_restart() -> None:
    """Case I: durable pending intent persists across manager restart.

    When the exact order lookup returns NOT_FOUND, the system retains the
    durable pending intent.  A subsequent restart (new manager instance) that
    also receives NOT_FOUND must again retain the intent — proving that the
    pending state is correctly stored and recovered from the repository.
    """
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id="ptp-in-flight-restart",
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()

    # Tick 1 — first manager instance, order not found
    manager_1 = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        failure_retry_seconds=0.00001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )
    await manager_1.on_market_tick(ticker=_ticker(price="105.00"))

    stored = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.quantity == Decimal("10")
    assert stored.partial_tp_executed is False
    assert stored.pending_partial_tp_client_order_id == "ptp-in-flight-restart"
    assert stored.pending_partial_tp_quantity == Decimal("5")

    # Simulate restart: new manager, re-reads from repository
    await asyncio.sleep(0.001)
    manager_2 = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        failure_retry_seconds=0.00001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )
    await manager_2.on_market_tick(ticker=_ticker(price="105.00", seconds=2))

    stored_2 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert stored_2 is not None
    assert stored_2.quantity == Decimal("10")
    assert stored_2.partial_tp_executed is False
    assert stored_2.pending_partial_tp_client_order_id == "ptp-in-flight-restart"
    assert stored_2.pending_partial_tp_quantity == Decimal("5")


@pytest.mark.asyncio
async def test_not_found_then_filled_mutates_quantity_exactly_once() -> None:
    """Case J: NOT_FOUND then FILLED → exactly one verified quantity mutation.

    Tick 1: order not found → intent retained, qty unchanged.
    Tick 2: order found as FILLED → qty deducted exactly once.
    Tick 3: no further mutation (idempotent).
    """
    client_id = "ptp-j-test"
    filled_order = Order(
        order_id="exch-order-j",
        client_order_id=client_id,
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("5"),
        executed_quantity=Decimal("5"),
        price=None,
        stop_price=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-j-active",
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id=client_id,
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    # _PENDING_RECONCILIATION_ATTEMPTS = 2, so two NOT_FOUND responses for tick 1
    exchange = _SequencedOrderExchange(
        order_responses=[
            ExchangeOrderNotFoundError("not found yet 1"),
            ExchangeOrderNotFoundError("not found yet 2"),
            filled_order,  # tick 2 first attempt succeeds
        ]
    )

    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.00001,
        failure_retry_seconds=0.00001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    # Tick 1 — NOT_FOUND, retain intent
    await manager.on_market_tick(ticker=_ticker(price="105.00"))
    after_tick_1 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_1 is not None
    assert after_tick_1.quantity == Decimal("10")
    assert after_tick_1.partial_tp_executed is False
    assert after_tick_1.pending_partial_tp_client_order_id == client_id

    # Tick 2 — FILLED, quantity deducted exactly once
    await asyncio.sleep(0.01)  # exceeds failure_retry_seconds=0.00001
    await manager.on_market_tick(ticker=_ticker(price="105.00", seconds=2))
    after_tick_2 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_2 is not None
    assert after_tick_2.quantity == Decimal("5")
    assert after_tick_2.partial_tp_executed is True
    assert after_tick_2.pending_partial_tp_client_order_id is None
    assert after_tick_2.pending_partial_tp_quantity is None

    # Tick 3 — no further mutation (idempotent; partial_tp_executed blocks re-trigger)
    await asyncio.sleep(0.01)
    await manager.on_market_tick(ticker=_ticker(price="105.00", seconds=3))
    after_tick_3 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_3 is not None
    assert after_tick_3.quantity == Decimal("5"), "Quantity must not be deducted twice"
    assert after_tick_3.partial_tp_executed is True


@pytest.mark.asyncio
async def test_not_found_matching_delta_then_canceled_no_quantity_mutation() -> None:
    """Case K: NOT_FOUND (delta matches request), later CANCELED → no mutation ever.

    This is the key proof that position delta was NEVER used as authoritative fill
    evidence.  If tick 1 had incorrectly inferred a fill from the delta, tick 2
    receiving CANCELED/REJECTED would detect an inconsistency.  The correct
    behavior is: tick 1 retains intent, tick 2 clears intent on CANCELED with
    zero fill — and the quantity is never deducted.
    """
    client_id = "ptp-k-test"
    canceled_order = Order(
        order_id="exch-order-k",
        client_order_id=client_id,
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        status=OrderStatus.CANCELED,
        quantity=Decimal("5"),
        executed_quantity=Decimal("0"),  # zero fill
        price=None,
        stop_price=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        pending_partial_tp_client_order_id=client_id,
        pending_partial_tp_quantity=Decimal("5"),
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    # Exchange shows position reduced by 5 (delta matches) — but order not found
    exchange = _SequencedOrderExchange(
        order_responses=[
            ExchangeOrderNotFoundError("not found 1"),
            ExchangeOrderNotFoundError("not found 2"),
            canceled_order,  # tick 2 reveals CANCELED with zero fill
        ]
    )
    # Diagnostic position shows a 5-unit reduction (matching requested_qty)
    exchange.positions = [
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("5"),  # looks like a fill, but could be unrelated
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            unrealized_pnl=Decimal("25"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    ]

    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.00001,
        failure_retry_seconds=0.00001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
    )

    # Tick 1 — NOT_FOUND + position delta matches requested → MUST retain intent
    await manager.on_market_tick(ticker=_ticker(price="105.00"))
    after_tick_1 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_1 is not None
    assert after_tick_1.quantity == Decimal("10"), (
        "Quantity must NOT have been mutated by position delta"
    )
    assert after_tick_1.partial_tp_executed is False
    assert after_tick_1.pending_partial_tp_client_order_id == client_id

    # Tick 2 — CANCELED with zero fill → clear intent, quantity STILL 10
    await asyncio.sleep(0.01)  # exceeds failure_retry_seconds=0.00001
    await manager.on_market_tick(ticker=_ticker(price="105.00", seconds=2))
    after_tick_2 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_2 is not None
    assert after_tick_2.quantity == Decimal("10"), (
        "Quantity must NEVER be deducted — order was CANCELED with zero fill"
    )
    assert after_tick_2.partial_tp_executed is False
    assert after_tick_2.pending_partial_tp_client_order_id is None
    assert after_tick_2.pending_partial_tp_quantity is None


@pytest.mark.asyncio
async def test_exact_once_invariant_verified_fill_applied_exactly_once() -> None:
    """§6 Exact-once invariant: a verified fill deducts quantity exactly once.

    Scenario:
    - initial quantity = 10, requested partial = 5
    - Tick 1: order FILLED → quantity becomes 5
    - Tick 2: repeated tick → quantity stays 5 (not deducted again)
    - Restart (new manager): quantity stays 5 (not deducted again)
    """
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95"),
        stop_loss_client_algo_id="sl-eo-active",
        take_profit=Decimal("110"),
        protection_step=0,
    )
    repo = MemoryPositionRepository()
    await repo.save(position=position)
    exchange = _HardeningExchange()
    exchange.reference_price = Decimal("105.00")

    manager = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.00001,
        failure_retry_seconds=0.00001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    # Tick 1 — partial TP fills; order is synchronously returned as FILLED
    await manager.on_market_tick(ticker=_ticker(price="105.00"))
    after_tick_1 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_1 is not None
    assert after_tick_1.quantity == Decimal("5")
    assert after_tick_1.partial_tp_executed is True
    assert after_tick_1.pending_partial_tp_client_order_id is None

    # Tick 2 — same manager, same price → quantity must remain 5
    await asyncio.sleep(
        0.01
    )  # exceeds position_refresh_seconds and failure_retry_seconds
    await manager.on_market_tick(ticker=_ticker(price="105.00", seconds=2))
    after_tick_2 = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_tick_2 is not None
    assert after_tick_2.quantity == Decimal("5"), (
        "Must not double-deduct on second tick"
    )
    assert after_tick_2.partial_tp_executed is True

    # Restart — new manager reads from repository; quantity must still be 5
    manager_2 = PositionProtectionManager(
        trade_mode=TradeMode.LIVE,
        position_repository=repo,
        exchange_client=exchange,
        position_refresh_seconds=0.001,
        failure_retry_seconds=0.00001,
        partial_tp_enabled=True,
        partial_tp_ratio=Decimal("0.50"),
        partial_tp_trigger_progress=Decimal("0.50"),
        breakeven_roi_threshold=Decimal("0.50"),
    )
    await asyncio.sleep(0.001)
    await manager_2.on_market_tick(ticker=_ticker(price="105.00", seconds=3))
    after_restart = await repo.get_by_symbol(symbol="BTCUSDT")
    assert after_restart is not None
    assert after_restart.quantity == Decimal("5"), "Must not deduct again after restart"
    assert after_restart.partial_tp_executed is True
