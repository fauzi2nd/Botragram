"""Protected LIVE entry MAINNET preflight regression tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.engine import PortfolioEngine
from botragram.enums import (
    Interval,
    MarketType,
    OrderType,
    PositionSide,
    SignalType,
)
from botragram.exceptions import LiveEntryPreflightError
from botragram.models import (
    Order,
    Position,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
)
from botragram.services import LiveFuturesEntryService
from botragram.storage.memory import MemorySubmissionAttemptRepository

__all__ = []


_NOW = datetime(2026, 8, 25, tzinfo=UTC)


@dataclass(slots=True, kw_only=True)
class _OrderService:
    """Normalize quantity but reject any mutation after failed preflight."""

    submit_calls: int = 0

    async def normalize_futures_market_quantity(
        self, *, symbol: str, quantity: Decimal
    ) -> Decimal:
        """Return the requested deterministic quantity."""
        assert symbol == "BTCUSDT"
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
        """Reject any POST after an unsafe symbol configuration."""
        del signal, risk_result, order_type, price, client_order_id
        self.submit_calls += 1
        raise AssertionError("Unsafe MAINNET symbol configuration must block POST")

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Reject reconciliation because no POST may occur."""
        del symbol, client_order_id
        raise AssertionError("No MAINNET submission should require reconciliation")


@dataclass(slots=True, kw_only=True)
class _PositionService:
    """Provide the unused position synchronization contract."""

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Reject synchronization before a blocked entry."""
        del symbol, synchronize
        raise AssertionError("Preflight must fail before position synchronization")

    async def get_all(self, *, synchronize: bool) -> Sequence[Position]:
        """Reject portfolio loading before a blocked entry."""
        del synchronize
        raise AssertionError("Preflight must fail before portfolio synchronization")

    async def save(self, *, position: Position) -> None:
        """Reject persistence before a blocked entry."""
        del position
        raise AssertionError("Preflight must fail before position persistence")


@dataclass(slots=True, kw_only=True)
class _ProtectionService:
    """Record whether protection validation was reached."""

    validation_calls: int = 0

    async def validate_pre_entry_plan(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        stop_loss: Decimal,
        take_profit: Decimal,
    ) -> None:
        """Reject an unexpected call after venue preflight failure."""
        del symbol, position_side, stop_loss, take_profit
        self.validation_calls += 1

    async def ensure(self, *, position: Position) -> Position:
        """Return a position only to satisfy the protected-entry contract."""
        return position


@dataclass(slots=True, kw_only=True)
class _UnsafeVenueReadiness:
    """Reject one MAINNET symbol while recording normalized notional."""

    entry_notional: Decimal | None = None

    async def verify_mainnet_symbol_readiness(
        self,
        *,
        symbol: str,
        maximum_leverage: int,
        entry_notional: Decimal,
    ) -> None:
        """Fail closed on an unsafe venue leverage setting."""
        assert symbol == "BTCUSDT"
        assert maximum_leverage == 2
        self.entry_notional = entry_notional
        raise RuntimeError("venue leverage is unsafe")


def _signal() -> Signal:
    """Build one valid BUY entry signal."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name="ema_cross",
        generated_at=_NOW,
    )


def _risk_result() -> RiskResult:
    """Build one approved entry whose normalized notional is deterministic."""
    return RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("0.5"),
            notional=Decimal("50"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("100"),
            stop_loss=Decimal("98"),
            take_profit=Decimal("104"),
            risk_amount=Decimal("1"),
            reward_amount=Decimal("2"),
            risk_reward_ratio=Decimal("2"),
        ),
    )


def test_mainnet_symbol_preflight_fails_before_prepared_or_post() -> None:
    """Keep unsafe symbol state outside durable and exchange mutation boundaries."""
    asyncio.run(_run_mainnet_symbol_preflight_test())


async def _run_mainnet_symbol_preflight_test() -> None:
    repository = MemorySubmissionAttemptRepository()
    order_service = _OrderService()
    protection_service = _ProtectionService()
    readiness = _UnsafeVenueReadiness()
    service = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=order_service,
        position_service=_PositionService(),
        protection_service=protection_service,
        runtime_control=TradingRuntimeControl(market_type=MarketType.FUTURES),
        submission_attempt_repository=repository,
        portfolio_engine=PortfolioEngine(),
        max_open_positions=1,
        venue_entry_readiness=readiness,
        maximum_leverage=2,
    )

    with pytest.raises(LiveEntryPreflightError):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert readiness.entry_notional == Decimal("50.0")
    assert await repository.get_incomplete() == ()
    assert order_service.submit_calls == 0
    assert protection_service.validation_calls == 0
