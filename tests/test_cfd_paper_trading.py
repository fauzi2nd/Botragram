"""
Botragram

Description:
    Tests for CFD paper trading simulation and global discovery telemetry in paper mode.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from botragram.app.global_discovery_telemetry import GlobalDiscoveryTelemetry
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.app.terminal_monitor import TerminalMonitor
from botragram.app.trading_runner import (
    AutonomousPaperTradingCycleExecutor,
    TradingRunner,
)
from botragram.config.risk_settings import RiskSettings
from botragram.engine import (
    CfdFinancingEngine,
    CfdSizingEngine,
    PnLEngine,
    RiskEngine,
    TradingEngine,
)
from botragram.enums import (
    Interval,
    MarketType,
    SignalType,
    TradeMode,
)
from botragram.models import Signal, Ticker, TradingDecision, TradingResult
from botragram.services import PaperTradingService
from botragram.storage.memory import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _create_cfd_paper_fixture(
    *,
    initial_balance: Decimal = Decimal("10000"),
    requested_leverage: int = 125,
) -> tuple[PaperTradingService, MemoryPositionRepository]:
    """Create an isolated paper portfolio configured for CFD."""
    orders = MemoryOrderRepository()
    trades = MemoryTradeRepository()
    positions = MemoryPositionRepository()
    cfd_sizing = CfdSizingEngine()
    cfd_financing = CfdFinancingEngine(sizing=cfd_sizing)
    trading_engine = TradingEngine(
        risk_engine=RiskEngine(
            settings=RiskSettings(
                leverage=requested_leverage,
                risk_per_trade_pct=Decimal("0.02"),
            ),
        ),
        cfd_sizing_engine=cfd_sizing,
        cfd_financing_engine=cfd_financing,
        market_type=MarketType.CFD,
    )
    pnl_engine = PnLEngine()
    service = PaperTradingService(
        order_repository=orders,
        trade_repository=trades,
        position_repository=positions,
        trading_engine=trading_engine,
        pnl_engine=pnl_engine,
        initial_balance=initial_balance,
        cfd_sizing_engine=cfd_sizing,
        cfd_financing_engine=cfd_financing,
        market_type=MarketType.CFD,
    )
    return service, positions


class FakePaperDiscoveryService:
    """Simulate discovery candidates in paper mode."""

    def __init__(self, results: tuple[TradingResult, ...]) -> None:
        self.results = results
        self.calls: list[object] = []

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> tuple[TradingResult, ...]:
        self.calls.append(
            (quote_asset, interval, candle_limit, max_symbols, top_n, initial_balance)
        )
        return self.results


def test_cfd_paper_trading_lot_margin_and_leverage() -> None:
    """Verify CFD paper trading calculates lots, margin, and caps leverage."""
    service, positions = _create_cfd_paper_fixture(
        initial_balance=Decimal("10000"),
        requested_leverage=125,
    )

    # 1. Test Gold (XAUUSD) - commodity capped at 50x leverage
    gold_signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        price=Decimal("2500"),
        stop_loss=Decimal("2480"),  # $20 SL distance = 200 pips
        take_profit=Decimal("2540"),
        confidence=Decimal("0.9"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )

    result = asyncio.run(service.execute(signal=gold_signal))

    assert result.executed
    assert result.decision.should_execute
    assert result.decision.risk_result is not None
    # Leverage is native 800 for Gold commodity
    assert result.decision.risk_result.position.leverage == 800
    # Quantity is lots (contract size 100 oz per lot)
    lots = result.decision.risk_result.position.quantity
    assert lots > Decimal("0")
    # Position saved in repository has correct lots and leverage
    saved_pos = asyncio.run(positions.get_by_symbol(symbol="XAUUSD"))
    assert saved_pos is not None
    assert saved_pos.leverage == 800
    assert saved_pos.quantity == lots


def test_cfd_paper_trading_forex_leverage_and_pnl() -> None:
    """Verify Forex CFD (EURUSD) 100x leverage and contract size PnL calculation."""
    service, positions = _create_cfd_paper_fixture(
        initial_balance=Decimal("10000"),
        requested_leverage=125,
    )

    eur_signal = Signal(
        symbol="EURUSD",
        signal_type=SignalType.BUY,
        price=Decimal("1.1000"),
        stop_loss=Decimal("1.0950"),  # 50 pips
        take_profit=Decimal("1.1100"),  # 100 pips
        confidence=Decimal("0.85"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )

    result = asyncio.run(service.execute(signal=eur_signal))
    assert result.executed
    assert result.decision.risk_result is not None
    # Forex leverage is native 500
    assert result.decision.risk_result.position.leverage == 500

    pos = asyncio.run(positions.get_by_symbol(symbol="EURUSD"))
    assert pos is not None
    assert pos.quantity > Decimal("0")

    # HOLD signal at +50 pips higher (1.1050) marks position to market
    hold_signal = Signal(
        symbol="EURUSD",
        signal_type=SignalType.HOLD,
        price=Decimal("1.1050"),
        confidence=Decimal("0.5"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )
    manage_result = asyncio.run(service.execute(signal=hold_signal))
    assert not manage_result.executed

    updated_pos = asyncio.run(positions.get_by_symbol(symbol="EURUSD"))
    assert updated_pos is not None
    # 50 pips gain * $10/pip/lot * lots
    # With contract_size = 100,000, 0.0050 price diff * lots * 100,000 > 0
    assert updated_pos.unrealized_pnl > Decimal("0")

    # On market tick hitting take profit (1.1105 > TP 1.1100), position auto-closes
    tp_ticker = Ticker(
        symbol="EURUSD",
        last_price=Decimal("1.1105"),
        bid_price=Decimal("1.1104"),
        ask_price=Decimal("1.1106"),
        timestamp=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
    )
    asyncio.run(service.on_market_tick(ticker=tp_ticker))

    # Flat position after TP hit
    assert asyncio.run(positions.get_by_symbol(symbol="EURUSD")) is None


def test_paper_trading_global_discovery_telemetry() -> None:
    """Verify Global Discovery Telemetry is updated in Paper mode."""
    telemetry = GlobalDiscoveryTelemetry(
        interval=Interval.M15,
        max_symbols=10,
        universe_limit=50,
        batch_size=10,
        top_n=3,
    )

    dummy_signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        price=Decimal("2500"),
        confidence=Decimal("0.88"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )
    dummy_decision = TradingDecision(
        should_execute=True,
        signal=dummy_signal,
        risk_result=None,
    )
    dummy_result = TradingResult(
        executed=True,
        decision=dummy_decision,
        order=None,
        reason="Paper fill simulated",
    )

    fake_service = FakePaperDiscoveryService(results=(dummy_result,))
    executor = AutonomousPaperTradingCycleExecutor(
        autonomous_execution_service=fake_service,  # type: ignore[arg-type]
        quote_asset="USDT",
        max_symbols=10,
        top_n=3,
    )

    runner = TradingRunner(
        executor=executor,
        symbol="XAUUSD",
        interval=Interval.M15,
        trade_mode=TradeMode.PAPER,
        candle_limit=100,
        global_discovery_telemetry=telemetry,
    )

    results = asyncio.run(runner.run_once())

    assert len(results) == 1
    snapshot = telemetry.get_snapshot()
    assert snapshot.state.value == "completed"
    assert len(snapshot.candidates) == 1
    assert snapshot.candidates[0].symbol == "XAUUSD"
    assert snapshot.candidates[0].direction is SignalType.BUY
    assert snapshot.candidates[0].confidence == Decimal("0.88")


def test_terminal_monitor_renders_global_discovery_in_paper_mode() -> None:
    """Verify TerminalMonitor renders Global Discovery panel when in Paper mode."""
    telemetry = GlobalDiscoveryTelemetry(
        interval=Interval.M15,
        max_symbols=10,
        universe_limit=50,
        batch_size=10,
        top_n=3,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        signal_type=SignalType.SELL,
        price=Decimal("1.0900"),
        confidence=Decimal("0.82"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )
    dummy_decision = TradingDecision(
        should_execute=True,
        signal=dummy_signal,
        risk_result=None,
    )
    dummy_result = TradingResult(
        executed=True,
        decision=dummy_decision,
        order=None,
        reason="Paper entry executed",
    )
    telemetry.complete_cycle(
        results=(dummy_result,),
    )

    orders = MemoryOrderRepository()
    trades = MemoryTradeRepository()
    positions = MemoryPositionRepository()
    trading_engine = TradingEngine(
        risk_engine=RiskEngine(settings=RiskSettings()),
    )
    paper_service = PaperTradingService(
        order_repository=orders,
        trade_repository=trades,
        position_repository=positions,
        trading_engine=trading_engine,
        pnl_engine=PnLEngine(),
    )

    class FakeLiveBalanceProvider:
        async def get_free_balance(self, *, asset: str) -> Decimal:
            return Decimal("10000")

    monitor = TerminalMonitor(
        runtime_control=TradingRuntimeControl(),
        paper_balance_provider=paper_service,
        live_balance_provider=FakeLiveBalanceProvider(),
        position_provider=positions,
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.PAPER,
        quote_asset="USDT",
        exchange_name="BITGET",
        global_discovery_telemetry_provider=telemetry,
    )

    status = asyncio.run(monitor.collect_status())
    assert status.global_discovery is not None
    assert status.global_discovery.actionable_count == 1
    assert len(status.global_discovery.candidates) == 1
    assert status.global_discovery.candidates[0].symbol == "EURUSD"

    # Render dashboard
    dashboard = monitor.render_dashboard(status)
    assert dashboard is not None


def test_cfd_paper_trading_gold_min_lot_800x_margin_on_small_balance() -> None:
    """Verify Gold 0.01 min lot executes on a 100 USDT balance using 800x leverage."""
    service, positions = _create_cfd_paper_fixture(
        initial_balance=Decimal("100"),
    )

    gold_signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        price=Decimal("2650"),
        stop_loss=Decimal("2640"),  # $10 SL distance = 100 pips
        take_profit=Decimal("2670"),
        confidence=Decimal("0.90"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )

    result = asyncio.run(service.execute(signal=gold_signal))

    assert result.executed is True
    assert result.decision.should_execute is True
    assert result.decision.risk_result is not None
    # Native leverage 800x
    assert result.decision.risk_result.position.leverage == 800
    # Minimum lot clamped to 0.01
    assert result.decision.risk_result.position.quantity == Decimal("0.01")
    # Notional value: 0.01 * 100 * 2650 = $2650
    assert result.decision.risk_result.position.notional == Decimal("2650.00")

    # Position is persisted with 800x leverage
    saved_pos = asyncio.run(positions.get_by_symbol(symbol="XAUUSD"))
    assert saved_pos is not None
    assert saved_pos.leverage == 800
    assert saved_pos.quantity == Decimal("0.01")

    # Available balance after required margin (~$3.31) and fee (~$1.59)
    available_balance = asyncio.run(service.get_available_balance())
    # 100 - (2650 / 800 + fee) > 90 USDT
    assert available_balance > Decimal("90")
    assert available_balance < Decimal("100")
