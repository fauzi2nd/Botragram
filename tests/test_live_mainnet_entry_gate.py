"""Fresh single-symbol LIVE entry safety-gate regression tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine, TradingEngine
from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalType,
    TradeMode,
)
from botragram.models import (
    Candle,
    ExecutableQuote,
    LiveEntryRiskEvaluation,
    Order,
    Position,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
    TradingDecision,
)
from botragram.services import TradingService

__all__ = []


_NOW = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)


@dataclass(slots=True, kw_only=True)
class _MarketData:
    """Return no candles because the strategy fake owns the signal."""

    async def get_candles(
        self, *, symbol: str, interval: Interval, limit: int
    ) -> Sequence[Candle]:
        """Return a deterministic empty candle collection."""
        del symbol, interval, limit
        return ()


@dataclass(slots=True, kw_only=True)
class _Strategy:
    """Return one fixed fresh signal."""

    signal: Signal

    async def generate_and_save(
        self, *, candles: Sequence[Candle], strategy_type: object = None
    ) -> Signal:
        """Return the configured signal."""
        del candles, strategy_type
        return self.signal


@dataclass(slots=True, kw_only=True)
class _UnusedAccount:
    """Fail if legacy balance evaluation is reached."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Reject the stale LIVE risk path."""
        del asset
        raise AssertionError("Fresh LIVE entry must use authoritative risk evaluation")


@dataclass(slots=True, kw_only=True)
class _UnusedPosition:
    """Fail if legacy portfolio evaluation is reached."""

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Reject the stale LIVE portfolio path."""
        del synchronize
        raise AssertionError("Fresh LIVE entry must use authoritative risk evaluation")


@dataclass(slots=True, kw_only=True)
class _UnusedOrder:
    """Fail if generic order submission is reached."""

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Reject the unprotected order boundary."""
        del signal, risk_result, order_type, price
        raise AssertionError("Fresh LIVE entry must use protected execution")


@dataclass(slots=True, kw_only=True)
class _QuoteProvider:
    """Return one fixed executable bid/ask quote."""

    quote: ExecutableQuote

    async def get_executable_quote(self, *, symbol: str) -> ExecutableQuote:
        """Return the quote after checking its requested symbol."""
        assert symbol == self.quote.symbol
        return self.quote


@dataclass(slots=True, kw_only=True)
class _RiskEvaluator:
    """Record the executable price used by fresh risk sizing."""

    evaluation: LiveEntryRiskEvaluation
    entry_price_override: Decimal | None = None

    async def evaluate(
        self, *, signal: Signal, entry_price_override: Decimal | None = None
    ) -> LiveEntryRiskEvaluation:
        """Return one approved authoritative risk result."""
        del signal
        self.entry_price_override = entry_price_override
        return self.evaluation


@dataclass(slots=True, kw_only=True)
class _ProtectedEntry:
    """Record the sole allowed LIVE mutation boundary."""

    order: Order
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
        """Return one deterministic protected order."""
        del signal, risk_result, interval, order_type, price
        self.calls += 1
        return self.order


def _signal() -> Signal:
    """Build one BUY signal with closed-candle provenance."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name="ema_cross",
        generated_at=_NOW,
    )


def _risk_evaluation(signal: Signal) -> LiveEntryRiskEvaluation:
    """Build an approved current decision sized at the ask price."""
    risk_result = RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("1"),
            notional=Decimal("101"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("101"),
            stop_loss=Decimal("99"),
            take_profit=Decimal("105"),
            risk_amount=Decimal("2"),
            reward_amount=Decimal("4"),
            risk_reward_ratio=Decimal("2"),
        ),
    )
    return LiveEntryRiskEvaluation(
        decision=TradingDecision(
            should_execute=True,
            signal=signal,
            risk_result=risk_result,
        ),
        has_existing_position=False,
    )


def _order() -> Order:
    """Build one deterministic protected entry order."""
    return Order(
        order_id="1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("1"),
        executed_quantity=Decimal("1"),
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_single_symbol_live_entry_uses_fresh_quote_and_risk_gate() -> None:
    """Route a fresh LIVE entry through side-aware quote and fresh risk sizing."""
    asyncio.run(_run_fresh_live_entry_test())


async def _run_fresh_live_entry_test() -> None:
    signal = _signal()
    risk_evaluator = _RiskEvaluator(evaluation=_risk_evaluation(signal))
    protected_entry = _ProtectedEntry(order=_order())
    service = TradingService(
        market_service=_MarketData(),
        strategy_service=_Strategy(signal=signal),
        account_service=_UnusedAccount(),
        position_service=_UnusedPosition(),
        order_service=_UnusedOrder(),
        trading_engine=TradingEngine(risk_engine=RiskEngine(settings=RiskSettings())),
        live_futures_entry_service=protected_entry,
        live_entry_risk_evaluation_service=risk_evaluator,
        live_executable_quote_provider=_QuoteProvider(
            quote=ExecutableQuote(
                symbol="BTCUSDT",
                bid_price=Decimal("100.9"),
                ask_price=Decimal("101"),
                timestamp=_NOW + timedelta(seconds=1),
            )
        ),
        trade_mode=TradeMode.LIVE,
        utc_now=lambda: _NOW + timedelta(seconds=2),
    )

    result = await service.execute(
        symbol="BTCUSDT",
        interval=Interval.M15,
        candle_limit=100,
    )

    assert result.executed
    assert result.order == protected_entry.order
    assert risk_evaluator.entry_price_override == Decimal("101")
    assert protected_entry.calls == 1


def test_single_symbol_live_entry_rejects_wide_spread_before_risk() -> None:
    """Deny a stale market reference before any risk or mutation boundary."""
    asyncio.run(_run_wide_spread_test())


async def _run_wide_spread_test() -> None:
    signal = _signal()
    risk_evaluator = _RiskEvaluator(evaluation=_risk_evaluation(signal))
    protected_entry = _ProtectedEntry(order=_order())
    service = TradingService(
        market_service=_MarketData(),
        strategy_service=_Strategy(signal=signal),
        account_service=_UnusedAccount(),
        position_service=_UnusedPosition(),
        order_service=_UnusedOrder(),
        trading_engine=TradingEngine(risk_engine=RiskEngine(settings=RiskSettings())),
        live_futures_entry_service=protected_entry,
        live_entry_risk_evaluation_service=risk_evaluator,
        live_executable_quote_provider=_QuoteProvider(
            quote=ExecutableQuote(
                symbol="BTCUSDT",
                bid_price=Decimal("90"),
                ask_price=Decimal("110"),
                timestamp=_NOW + timedelta(seconds=1),
            )
        ),
        trade_mode=TradeMode.LIVE,
        utc_now=lambda: _NOW + timedelta(seconds=2),
    )

    result = await service.execute(
        symbol="BTCUSDT",
        interval=Interval.M15,
        candle_limit=100,
    )

    assert not result.executed
    assert result.reason == "market_reference_rejected"
    assert risk_evaluator.entry_price_override is None
    assert protected_entry.calls == 0
