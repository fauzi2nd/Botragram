"""
Botragram

Description:
    LIVE recovered-position management authorization boundary tests.

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine, TradingEngine
from botragram.enums import (
    Interval,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    Candle,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
    Order,
    Position,
    RiskResult,
    Signal,
)
from botragram.services import TradingService

__all__ = []


# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_RECOVERED_POSITION_NOT_OPEN_REASON = (
    "Recovered LIVE position is no longer open; portfolio reconciliation is required"
)


# =============================================================================
# Test Fakes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class _MarketService:
    """Return a fixed candle sequence without exchange I/O."""

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> Sequence[Candle]:
        """Return no candles because the strategy fake supplies the signal."""
        del symbol, interval, limit
        return ()


@dataclass(slots=True, kw_only=True)
class _StrategyService:
    """Generate one otherwise-entry-eligible signal."""

    signal: Signal
    calls: int = 0

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Return the signal after recording the evaluation boundary."""
        del candles, strategy_type
        self.calls += 1
        return self.signal


@dataclass(slots=True, kw_only=True)
class _AccountService:
    """Provide a deterministic account balance."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return a positive balance for a hypothetical entry decision."""
        del asset
        return Decimal("1000")


@dataclass(slots=True, kw_only=True)
class _PositionService:
    """Return an authoritative empty portfolio after recovered BTC disappears."""

    calls: int = 0

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return no open positions while recording authoritative synchronization."""
        assert synchronize
        self.calls += 1
        return ()


@dataclass(slots=True, kw_only=True)
class _OrderService:
    """Fail if a generic order boundary is reached."""

    calls: int = 0

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Reject any unexpected order submission."""
        del signal, risk_result, order_type, price
        self.calls += 1
        raise AssertionError("Recovered management must not submit an order")


@dataclass(slots=True, kw_only=True)
class _LiveEntryService:
    """Fail if protected Futures entry is reached."""

    calls: int = 0

    async def execute(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        interval: Interval,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Reject any unexpected protected LIVE entry."""
        del signal, risk_result, interval, order_type, price
        self.calls += 1
        raise AssertionError("Recovered management must not create LIVE exposure")


# =============================================================================
# Test Helpers
# =============================================================================
def _context() -> LiveRuntimePositionContext:
    """Build the exact recovered BTC management context."""
    return LiveRuntimePositionContext(
        symbol="BTCUSDT",
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _signal() -> Signal:
    """Build a BUY signal that normal risk evaluation would approve."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=_NOW,
    )


def _service(
    *,
    strategy_service: _StrategyService,
    position_service: _PositionService,
    order_service: _OrderService,
    live_entry_service: _LiveEntryService,
) -> TradingService:
    """Build the real trading-service entry boundary with local fakes."""
    return TradingService(
        market_service=_MarketService(),
        strategy_service=strategy_service,
        account_service=_AccountService(),
        position_service=position_service,
        order_service=order_service,
        trading_engine=TradingEngine(risk_engine=RiskEngine(settings=RiskSettings())),
        live_futures_entry_service=live_entry_service,
        trade_mode=TradeMode.LIVE,
    )


# =============================================================================
# Tests
# =============================================================================
def test_recovered_management_cannot_recreate_a_disappeared_live_position() -> None:
    """Deny entry after authoritative sync proves the recovered BTC is gone."""
    asyncio.run(_run_disappeared_position_test())


async def _run_disappeared_position_test() -> None:
    """Exercise the real TradingService boundary after a recovered position closes."""
    strategy_service = _StrategyService(signal=_signal())
    position_service = _PositionService()
    order_service = _OrderService()
    live_entry_service = _LiveEntryService()
    service = _service(
        strategy_service=strategy_service,
        position_service=position_service,
        order_service=order_service,
        live_entry_service=live_entry_service,
    )
    authorization = LiveRecoveredPositionManagementAuthorization(
        contexts=(_context(),),
        runtime_management_allowed=True,
    )

    result = await service.execute(
        symbol="BTCUSDT",
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        candle_limit=100,
        order_type=OrderType.MARKET,
        live_management_authorization=authorization,
    )

    assert strategy_service.calls == 1
    assert position_service.calls == 1
    assert not result.executed
    assert result.reason == _RECOVERED_POSITION_NOT_OPEN_REASON
    assert not order_service.calls
    assert not live_entry_service.calls


def test_recovered_management_authorization_rejects_new_live_entry_capability() -> None:
    """Keep autonomous or other new LIVE exposure structurally unavailable."""
    with pytest.raises(ValueError, match="New LIVE entry authorization"):
        LiveRecoveredPositionManagementAuthorization(
            contexts=(_context(),),
            runtime_management_allowed=True,
            new_live_entry_allowed=True,
        )
