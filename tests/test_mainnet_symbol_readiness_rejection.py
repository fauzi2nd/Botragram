"""Deterministic MAINNET symbol-readiness rejection classification tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.engine import PortfolioEngine
from botragram.enums import (
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
)
from botragram.exceptions import LiveEntryPreflightError, LiveEntrySymbolReadinessError
from botragram.models import (
    Order,
    Position,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
    SubmissionAttempt,
)
from botragram.repositories import SubmissionAttemptRepository
from botragram.services import LiveFuturesEntryService

_NOW = datetime(2026, 8, 27, tzinfo=UTC)


@dataclass(slots=True)
class _AttemptRepository(SubmissionAttemptRepository):
    reserve_calls: int = 0

    async def reserve(self, *, attempt: SubmissionAttempt) -> bool:
        del attempt
        self.reserve_calls += 1
        return True

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        del attempt

    async def resolve_no_exposure(
        self,
        *,
        symbol: str,
        attempt: SubmissionAttempt,
    ) -> None:
        del symbol, attempt

    async def get_by_client_order_id(
        self,
        *,
        client_order_id: str,
    ) -> SubmissionAttempt | None:
        del client_order_id
        return None

    async def get_unresolved(self) -> Sequence[SubmissionAttempt]:
        return ()

    async def get_incomplete(self) -> Sequence[SubmissionAttempt]:
        return ()


@dataclass(slots=True)
class _OrderService:
    submit_calls: int = 0

    async def normalize_futures_market_quantity(
        self,
        *,
        symbol: str,
        quantity: Decimal,
    ) -> Decimal:
        del symbol
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
        del risk_result, order_type, price
        self.submit_calls += 1
        return Order(
            order_id="unexpected",
            symbol=signal.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("1"),
            executed_quantity=Decimal("1"),
            client_order_id=client_order_id,
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def get_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        del symbol, client_order_id
        raise AssertionError("No reconciliation expected before POST")


@dataclass(slots=True)
class _PositionService:
    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        del symbol, synchronize
        raise AssertionError("Position sync is not expected before POST")

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        del synchronize
        raise AssertionError("Portfolio sync is not expected before readiness")

    async def save(self, *, position: Position) -> None:
        del position
        raise AssertionError("Position persistence is not expected before POST")


@dataclass(slots=True)
class _Protection:
    async def validate_pre_entry_plan(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        stop_loss: Decimal,
        take_profit: Decimal,
    ) -> None:
        del symbol, position_side, stop_loss, take_profit

    async def ensure(self, *, position: Position) -> Position:
        raise AssertionError(
            f"Protection is not expected before POST: {position.symbol}"
        )


@dataclass(slots=True)
class _Readiness:
    message: str
    calls: list[str] = field(default_factory=list[str])

    async def verify_mainnet_symbol_readiness(
        self,
        *,
        symbol: str,
        maximum_leverage: int,
        entry_notional: Decimal,
    ) -> None:
        del maximum_leverage, entry_notional
        self.calls.append(symbol)
        raise RuntimeError(self.message)


def _signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name="ema_cross",
        generated_at=_NOW,
    )


def _risk_result() -> RiskResult:
    return RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("1"),
            notional=Decimal("100"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("100"),
            stop_loss=Decimal("99"),
            take_profit=Decimal("102"),
            risk_amount=Decimal("1"),
            reward_amount=Decimal("2"),
            risk_reward_ratio=Decimal("2"),
        ),
    )


def _service(
    *,
    readiness_message: str,
) -> tuple[LiveFuturesEntryService, _AttemptRepository, _OrderService]:
    attempts = _AttemptRepository()
    orders = _OrderService()
    service = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=orders,
        position_service=_PositionService(),
        protection_service=_Protection(),
        runtime_control=TradingRuntimeControl(),
        submission_attempt_repository=attempts,
        portfolio_engine=PortfolioEngine(),
        max_open_positions=1,
        venue_entry_readiness=_Readiness(message=readiness_message),
        maximum_leverage=1,
    )
    return service, attempts, orders


@pytest.mark.parametrize(
    "message",
    (
        "Binance Futures MAINNET entry requires isolated margin",
        "Binance Futures auto-add margin must be disabled",
        "Binance Futures symbol leverage exceeds the risk limit",
        "Binance Futures maximum symbol notional is below the entry",
    ),
)
@pytest.mark.asyncio
async def test_known_mainnet_readiness_rule_is_safe_pre_post_rejection(
    message: str,
) -> None:
    service, attempts, orders = _service(readiness_message=message)

    with pytest.raises(LiveEntrySymbolReadinessError, match=message):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert attempts.reserve_calls == 0
    assert orders.submit_calls == 0


@pytest.mark.asyncio
async def test_unknown_readiness_runtime_error_remains_unsafe_preflight() -> None:
    service, attempts, orders = _service(
        readiness_message="malformed leverage response"
    )

    with pytest.raises(LiveEntryPreflightError, match="preflight failed"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert attempts.reserve_calls == 0
    assert orders.submit_calls == 0
