"""
Botragram

Description:
    MAINNET readiness regression tests for ambiguous POST timeouts, crash boundaries,
    and fail-closed reconciliation invariants.

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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import TradingRuntimeControl
from botragram.config.risk_settings import RiskSettings
from botragram.engine import PortfolioEngine, RiskEngine
from botragram.enums import (
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.exchanges.binance.futures_client import BinanceFuturesExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import (
    ExchangeSymbolRules,
    Order,
    Position,
    RiskMetrics,
    RiskResult,
    Signal,
    SubmissionAttempt,
)
from botragram.models.risk import PositionSize
from botragram.services import (
    LiveFuturesEntryService,
    LivePositionProtectionService,
    LiveSubmissionRecoveryResult,
    LiveSubmissionRecoveryService,
)
from botragram.storage.memory import (
    MemoryPositionRepository,
    MemorySubmissionAttemptRepository,
)

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 8, 24, tzinfo=UTC)
_CLIENT_ORDER_ID = "btg-0123456789abcdef0123456789abcdef"


# =============================================================================
# Fixtures and Doubles
# =============================================================================
def _sample_signal(*, symbol: str = "BTCUSDT") -> Signal:
    """Return an approved BUY signal."""
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        price=Decimal("65000"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_SCALPING.value,
        generated_at=_NOW,
    )


def _sample_risk_result() -> RiskResult:
    """Return an approved Futures risk result."""
    return RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("0.01"),
            notional=Decimal("650"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("65000"),
            stop_loss=Decimal("64000"),
            take_profit=Decimal("66000"),
            risk_amount=Decimal("10"),
            reward_amount=Decimal("10"),
            risk_reward_ratio=Decimal("1"),
        ),
    )


def _order(
    *,
    order_id: str,
    client_id: str | None,
    side: OrderSide,
    order_type: OrderType,
    quantity: Decimal = Decimal("0.01"),
    trigger: Decimal | None = None,
    status: OrderStatus = OrderStatus.NEW,
) -> Order:
    """Create a fully-populated typed Order fixture."""
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


@dataclass(slots=True)
class MockPositionService:
    """In-memory position service satisfying LivePositionSynchronization."""

    persisted: Position | None = None
    on_post_position: Position | None = None
    saved_positions: list[Position] = field(default_factory=list[Position])

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        del symbol, synchronize
        return self.on_post_position or self.persisted

    async def get_all(self, *, synchronize: bool) -> Sequence[Position]:
        del synchronize
        return () if self.persisted is None else (self.persisted,)

    async def save(self, *, position: Position) -> None:
        self.persisted = position
        self.saved_positions.append(position)


@dataclass(slots=True)
class MockOrderService:
    """Order service capturing submission calls with configurable error injection."""

    submit_calls: int = 0
    normalize_calls: int = 0
    get_calls: int = 0
    submit_error: BaseException | None = None
    reconcile_order: Order | None = None
    reconcile_error: BaseException | None = None

    async def normalize_futures_market_quantity(
        self, *, symbol: str, quantity: Decimal
    ) -> Decimal:
        """Return the normalized quantity."""
        del symbol
        self.normalize_calls += 1
        return quantity

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit one market entry order or raise configured error."""
        del signal, risk_result, order_type, price
        self.submit_calls += 1
        if self.submit_error is not None:
            raise self.submit_error
        return _order(
            order_id="exchange-order-1",
            client_id=client_order_id,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.01"),
            status=OrderStatus.FILLED,
        )

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Fetch order by client id for reconciliation."""
        del symbol
        self.get_calls += 1
        if self.reconcile_error is not None:
            raise self.reconcile_error
        if self.reconcile_order is not None:
            return self.reconcile_order
        return _order(
            order_id="exchange-order-1",
            client_id=client_order_id,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.01"),
            status=OrderStatus.FILLED,
        )


class MockProtectionExchangeClient(BinanceFuturesExchangeClient):
    """Mock exchange client capturing protection order creations with timeout."""

    def __init__(self, *, post_error: BaseException | None = None) -> None:
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.posts: list[
            tuple[Decimal | None, Decimal | None, str | None, str | None]
        ] = []
        self.get_calls: int = 0
        self.orders: list[Order] = []
        self.post_error: BaseException | None = post_error

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return symbol rules for preflight normalization."""
        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=Decimal("0.001"),
            market_max_quantity=Decimal("1000"),
            market_quantity_step=Decimal("0.001"),
            minimum_price=Decimal("1"),
            maximum_price=Decimal("100000"),
            price_tick_size=Decimal("1"),
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return current mark price."""
        del symbol
        return Decimal("65000")

    async def get_open_protection_orders(
        self, *, symbol: str | None = None
    ) -> tuple[Order, ...]:
        """Return open protection orders."""
        del symbol
        return tuple(self.orders)

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        """Return protection order by client identity."""
        del symbol
        self.get_calls += 1
        for order in self.orders:
            if order.client_order_id == client_id:
                return order
        raise ExchangeOrderNotFoundError("Protection order not found")

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
        """Record protection POST or raise configured error."""
        self.posts.append(
            (
                stop_loss,
                take_profit,
                stop_loss_client_algo_id,
                take_profit_client_algo_id,
            )
        )
        if self.post_error is not None:
            raise self.post_error

        created: list[Order] = []
        if stop_loss is not None and stop_loss_client_algo_id is not None:
            order = _order(
                order_id=f"stop-{len(self.orders) + 1}",
                client_id=stop_loss_client_algo_id,
                side=side,
                order_type=OrderType.STOP_MARKET,
                quantity=quantity,
                trigger=stop_loss,
                status=OrderStatus.NEW,
            )
            self.orders.append(order)
            created.append(order)
        if take_profit is not None and take_profit_client_algo_id is not None:
            order = _order(
                order_id=f"tp-{len(self.orders) + 1}",
                client_id=take_profit_client_algo_id,
                side=side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                quantity=quantity,
                trigger=take_profit,
                status=OrderStatus.NEW,
            )
            self.orders.append(order)
            created.append(order)
        return tuple(created)


# =============================================================================
# Phase 3 & 4 Regression Tests: Crash and Ambiguous Timeout Boundaries
# =============================================================================
@pytest.mark.asyncio
async def test_crash_before_prepared_leaves_clean_state_without_leakage() -> None:
    """Verify that failure during preflight leaves no durable attempt or exposure."""
    attempt_repo = MemorySubmissionAttemptRepository()
    position_service = MockPositionService()
    control = TradingRuntimeControl()
    orders = MockOrderService()

    class FailingProtectionService:
        async def validate_pre_entry_plan(
            self,
            *,
            symbol: str,
            position_side: PositionSide,
            stop_loss: Decimal,
            take_profit: Decimal,
        ) -> None:
            del symbol, position_side, stop_loss, take_profit
            raise RuntimeError("preflight connection error")

        async def ensure(self, *, position: Position) -> Position:
            return position

    service = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=orders,
        position_service=position_service,
        protection_service=FailingProtectionService(),
        runtime_control=control,
        submission_attempt_repository=attempt_repo,
        portfolio_engine=PortfolioEngine(),
        max_open_positions=3,
    )

    with pytest.raises(Exception, match="preflight"):
        await service.execute(
            signal=_sample_signal(),
            risk_result=_sample_risk_result(),
            interval=Interval.M5,
            order_type=OrderType.MARKET,
            price=Decimal("65000"),
        )

    # Invariants: 0 POST sent, 0 attempts persisted, runtime protection remains ready
    assert orders.submit_calls == 0
    assert await attempt_repo.get_incomplete() == ()
    assert position_service.persisted is None


@pytest.mark.asyncio
async def test_crash_after_prepared_before_post_blocks_entry_and_reconciles() -> None:
    """Verify PREPARED state without POST is reconciled as non-executed on restart."""
    attempt_repo = MemorySubmissionAttemptRepository()
    orders = MockOrderService(reconcile_error=ExchangeOrderNotFoundError("not found"))

    # Simulate crash right after attempt was PREPARED in repository before POST
    prepared_attempt = SubmissionAttempt(
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        signal_generated_at=_NOW,
        interval=Interval.M5,
        strategy_type=StrategyType.EMA_SCALPING,
        status=SubmissionAttemptStatus.PREPARED,
        created_at=_NOW,
        updated_at=_NOW,
    )
    await attempt_repo.save(attempt=prepared_attempt)

    recovery_service = LiveSubmissionRecoveryService(
        submission_attempt_repository=attempt_repo,
        order_service=orders,
    )

    # Startup recovery checks incomplete attempt
    result = await recovery_service.recover_incomplete()

    # Invariant: NEVER duplicate POST. Attempt transitions to STILL_INCOMPLETE
    assert orders.submit_calls == 0
    assert result is LiveSubmissionRecoveryResult.STILL_INCOMPLETE


@pytest.mark.asyncio
async def test_entry_post_timeout_reconciles_by_client_id_without_second_post() -> None:
    """Verify entry POST timeout triggers GET reconciliation without re-submitting."""
    attempt_repo = MemorySubmissionAttemptRepository()
    position_service = MockPositionService(
        on_post_position=Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.01"),
            entry_price=Decimal("65000"),
            current_price=Decimal("65000"),
            unrealized_pnl=Decimal("0"),
            leverage=1,
            opened_at=_NOW,
            updated_at=_NOW,
            stop_loss=Decimal("64000"),
            take_profit=Decimal("66000"),
            interval=Interval.M5,
            strategy_type=StrategyType.EMA_SCALPING,
        )
    )
    position_repo = MemoryPositionRepository()
    control = TradingRuntimeControl()
    orders = MockOrderService(
        submit_error=ExchangeOrderOutcomeUnknownError("HTTP gateway timeout")
    )
    exchange_client = MockProtectionExchangeClient()
    protection_service = LivePositionProtectionService(
        exchange_client=exchange_client,
        position_repository=position_repo,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )

    service = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=orders,
        position_service=position_service,
        protection_service=protection_service,
        runtime_control=control,
        submission_attempt_repository=attempt_repo,
        portfolio_engine=PortfolioEngine(),
        max_open_positions=3,
    )

    order = await service.execute(
        signal=_sample_signal(),
        risk_result=_sample_risk_result(),
        interval=Interval.M5,
        order_type=OrderType.MARKET,
        price=Decimal("65000"),
    )

    # Invariant: EXACTLY ONE POST call made, then reconciled via GET
    assert orders.submit_calls == 1
    assert orders.get_calls == 1
    assert order.status is OrderStatus.FILLED
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_protection_post_timeout_reconciles_via_get_without_blind_retry() -> None:
    """Verify STOP/TP timeout reconciles existing algo orders without blind retry."""
    position_repo = MemoryPositionRepository()
    exchange_client = MockProtectionExchangeClient(
        post_error=ExchangeOrderOutcomeUnknownError("Read timeout on protection POST")
    )
    # The exchange did receive and register the stop order despite local timeout
    existing_stop = _order(
        order_id="stop-1",
        client_id="bsl-sample0123456789abcdef012345",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=Decimal("0.01"),
        trigger=Decimal("64000"),
        status=OrderStatus.NEW,
    )
    existing_tp = _order(
        order_id="tp-1",
        client_id="btp-sample0123456789abcdef012345",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity=Decimal("0.01"),
        trigger=Decimal("66000"),
        status=OrderStatus.NEW,
    )
    exchange_client.orders.extend([existing_stop, existing_tp])

    protection_service = LivePositionProtectionService(
        exchange_client=exchange_client,
        position_repository=position_repo,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )

    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("64000"),
        take_profit=Decimal("66000"),
        stop_loss_client_algo_id="bsl-sample0123456789abcdef012345",
        take_profit_client_algo_id="btp-sample0123456789abcdef012345",
        interval=Interval.M5,
        strategy_type=StrategyType.EMA_SCALPING,
    )
    await position_repo.save(position=pos)

    # Calling ensure must verify via GET and NOT send duplicate POSTs
    protected = await protection_service.ensure(position=pos)

    # Invariant: 0 POSTs made because persisted legs were found via GET
    assert exchange_client.posts == []
    assert exchange_client.get_calls >= 2
    assert protected.stop_loss == Decimal("64000")
    assert protected.take_profit == Decimal("66000")
