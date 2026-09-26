"""
Botragram

Description:
    Deterministic historical backtest tests.

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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.backtest_command import (
    parse_backtest_request,
    run_backtest_command,
)
from botragram.config import Settings
from botragram.config.risk_settings import RiskSettings
from botragram.engine.backtest_engine import BacktestEngine
from botragram.engine.signal_engine import SignalEngine
from botragram.enums import (
    Interval,
    MarketType,
    PositionSide,
    SignalType,
    StrategyType,
    TrailingMode,
)
from botragram.models import BacktestRequest, BacktestResult, Candle, Signal
from botragram.services.backtest_service import BacktestService
from botragram.services.setup_stalking_service import SetupStalkingService
from botragram.services.strategy_service import StrategyService
from botragram.storage import MemorySignalRepository
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)
from botragram.strategies import StrategyResolver
from botragram.strategies.base import BaseStrategy

# =============================================================================
# Constants
# =============================================================================
_START_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Test Doubles
# =============================================================================
class BuyThenHoldStrategy(BaseStrategy):
    """Open once and hold so candle protection controls the exit."""

    __slots__ = ()

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy profile used for risk levels."""
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Allow a signal from the first replay candle."""
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        """Buy on the first candle and hold on later candles."""
        self.validate_candles(candles=candles)
        candle = candles[-1]
        return Signal(
            symbol=candle.symbol,
            signal_type=(SignalType.BUY if len(candles) == 1 else SignalType.HOLD),
            price=candle.close_price,
            confidence=Decimal("1"),
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason="Deterministic backtest signal",
        )


class SellThenHoldStrategy(BaseStrategy):
    """Open short once and hold so candle protection controls the exit."""

    __slots__ = ()

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy profile used for risk levels."""
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Allow a signal from the first replay candle."""
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        """Sell on the first candle and hold on later candles."""
        self.validate_candles(candles=candles)
        candle = candles[-1]
        return Signal(
            symbol=candle.symbol,
            signal_type=(SignalType.SELL if len(candles) == 1 else SignalType.HOLD),
            price=candle.close_price,
            confidence=Decimal("1"),
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason="Deterministic backtest short signal",
        )


class AlternatingSignalStrategy(BaseStrategy):
    """Emit BUY on first candle, SELL on second candle, and HOLD afterwards."""

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy profile used for risk levels."""
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Allow an immediate signal from the first replay candle."""
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        """Generate alternating directional signals."""
        self.validate_candles(candles=candles)
        candle = candles[-1]
        if len(candles) == 1:
            sig = SignalType.BUY
        elif len(candles) == 2:
            sig = SignalType.SELL
        else:
            sig = SignalType.HOLD
        return Signal(
            symbol=candle.symbol,
            signal_type=sig,
            price=candle.close_price,
            confidence=Decimal("1"),
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason="Alternating backtest signal",
        )


@dataclass(slots=True, kw_only=True)
class HistoricalCandleStub:
    """Return deterministic pages while recording pagination cursors."""

    candles: tuple[Candle, ...]
    cursors: list[datetime]

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return the next filtered candle page."""
        del symbol, interval
        if start_time is None or end_time is None:
            raise AssertionError("Backtest pagination requires explicit boundaries")
        self.cursors.append(start_time)
        return tuple(
            candle
            for candle in self.candles
            if start_time <= candle.open_time <= end_time
        )[:limit]


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candle(
    *,
    minute: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> Candle:
    """Create one chronological one-minute candle."""
    open_time = _START_TIME + timedelta(minutes=minute)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal("1"),
    )


def _create_request() -> BacktestRequest:
    """Create a small isolated Futures backtest request."""
    return BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=2),
        initial_balance=Decimal("100"),
    )


# =============================================================================
# Engine Tests
# =============================================================================
def test_backtest_uses_stop_loss_first_when_one_candle_hits_both_exits() -> None:
    """Enforce the documented conservative SL-first OHLC policy."""
    result = asyncio.run(_run_ambiguous_candle_backtest())

    assert result.candle_count == 2
    assert result.metrics.total_trades == 1
    assert result.metrics.long_trades == 1
    assert result.metrics.losing_trades == 1
    assert result.metrics.net_pnl < 0
    assert result.trades[0].side is PositionSide.LONG
    assert result.trades[0].reason == "Paper stop-loss triggered"


async def _run_ambiguous_candle_backtest() -> BacktestResult:
    """Replay a candle whose range crosses both configured exit levels."""
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(leverage=10),
    )
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="101",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100",
            high_price="110",
            low_price="90",
            close_price="100",
        ),
    )
    return await engine.run(request=_create_request(), candles=candles)


def test_backtest_arms_stepped_stop_for_the_next_candle_only() -> None:
    """Use favorable excursion without inventing same-candle high/low ordering."""
    result = asyncio.run(_run_stepped_protection_backtest())

    assert result.candle_count == 3
    assert result.metrics.total_trades == 1
    assert result.metrics.winning_trades == 1
    assert result.trades[0].reason == "Paper stop-loss triggered"
    assert result.trades[0].exit_price > result.trades[0].entry_price
    assert any("next-candle activation" in warning for warning in result.warnings)


async def _run_stepped_protection_backtest() -> BacktestResult:
    """Cross the first step, then hit the tightened stop on the next candle."""
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(leverage=10),
    )
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.2",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100.2",
            high_price="100.7",
            low_price="99.8",
            close_price="100.4",
        ),
        _create_candle(
            minute=2,
            open_price="100.4",
            high_price="100.5",
            low_price="100.2",
            close_price="100.3",
        ),
    )
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )
    return await engine.run(request=request, candles=candles)


def test_backtest_arms_breakeven_stop_when_target_roi_reached() -> None:
    """Lock Breakeven+ when 30% ROI is reached and exit in profit on pullback."""
    result = asyncio.run(_run_breakeven_protection_backtest())

    assert result.candle_count == 3
    assert result.metrics.total_trades == 1
    assert result.trades[0].reason == "Paper stop-loss triggered"
    assert result.trades[0].exit_price >= Decimal("100.09")
    assert result.trades[0].exit_price > result.trades[0].entry_price


async def _run_breakeven_protection_backtest() -> BacktestResult:
    """Cross 30% ROI without reaching 30% TP progress, then hit Breakeven+ stop."""
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=20,
            scalping_stop_loss_pct=Decimal("0.02"),
            scalping_take_profit_pct=Decimal("0.06"),
        ),
    )
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.2",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100.1",
            high_price="101.60",
            low_price="99.95",
            close_price="101.50",
        ),
        _create_candle(
            minute=2,
            open_price="101.50",
            high_price="101.50",
            low_price="100.05",
            close_price="100.10",
        ),
    )
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )
    return await engine.run(request=request, candles=candles)


@pytest.mark.asyncio
async def test_backtest_simulates_partial_tp_with_live_parity() -> None:
    """Verify BacktestEngine triggers partial TP, reduces quantity,

    records realized PnL, adjusts protection stop to BE, and reflects in metrics.
    """
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.2",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100.1",
            high_price="103.50",  # crosses 50% TP progress (103.0)
            low_price="100.0",
            close_price="103.20",
        ),
        _create_candle(
            minute=2,
            open_price="103.0",
            high_price="103.0",
            low_price="100.10",  # drops to trigger tightened BE stop
            close_price="100.12",
        ),
    )
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )

    # 1. With partial TP ENABLED
    engine_enabled = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=10,
            scalping_stop_loss_pct=Decimal("0.02"),
            scalping_take_profit_pct=Decimal("0.06"),
            partial_tp_enabled=True,
            partial_tp_ratio=Decimal("0.50"),
            partial_tp_trigger_progress=Decimal("0.50"),
        ),
    )
    res_enabled = await engine_enabled.run(request=request, candles=candles)
    assert res_enabled.candle_count == 3
    # Two completed trades: 1 partial TP + 1 final BE stop exit
    assert res_enabled.metrics.total_trades == 2
    assert res_enabled.trades[0].reason == "Partial take-profit triggered"
    assert res_enabled.trades[0].exit_price >= Decimal("102.99")
    assert res_enabled.trades[0].realized_pnl > Decimal("0")
    assert res_enabled.trades[1].reason == "Paper stop-loss triggered"
    # Remaining quantity was half of original
    assert res_enabled.trades[0].quantity == res_enabled.trades[1].quantity
    assert res_enabled.metrics.winning_trades == 2
    assert res_enabled.metrics.net_pnl > Decimal("0")
    # Economic fees and PnL reconciliation
    assert sum(t.fees for t in res_enabled.trades) == res_enabled.metrics.total_fees
    assert (
        sum(t.realized_pnl for t in res_enabled.trades) == res_enabled.metrics.net_pnl
    )

    # 2. With partial TP DISABLED
    engine_disabled = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=10,
            scalping_stop_loss_pct=Decimal("0.02"),
            scalping_take_profit_pct=Decimal("0.06"),
            partial_tp_enabled=False,
        ),
    )
    res_disabled = await engine_disabled.run(request=request, candles=candles)
    assert res_disabled.candle_count == 3
    # Without partial TP, only 1 full trade
    assert res_disabled.metrics.total_trades == 1
    assert res_disabled.trades[0].quantity == res_enabled.trades[0].quantity * Decimal(
        "2"
    )


@pytest.mark.asyncio
async def test_backtest_partial_tp_same_candle_advances_stepped_protection() -> None:
    """Verify partial TP and stepped protection advance correctly on same candle."""
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.2",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100.1",
            high_price="103.50",  # crosses 50% TP progress and reaches Step 3 (>= 45%)
            low_price="100.0",
            close_price="103.20",
        ),
        _create_candle(
            minute=2,
            open_price="103.0",
            high_price="103.0",
            low_price="101.40",  # Drops and hits Step 3 stop
            close_price="101.42",
        ),
    )
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=10,
            scalping_stop_loss_pct=Decimal("0.02"),
            scalping_take_profit_pct=Decimal("0.06"),
            partial_tp_enabled=True,
            partial_tp_ratio=Decimal("0.50"),
            partial_tp_trigger_progress=Decimal("0.50"),
        ),
    )
    res = await engine.run(request=request, candles=candles)
    assert res.metrics.total_trades == 2
    assert res.trades[0].reason == "Partial take-profit triggered"
    assert res.trades[1].reason == "Paper stop-loss triggered"
    # Exit price reflects Step 3 stop (101.5), not initial BE stop (100.16)
    assert res.trades[1].exit_price >= Decimal("101.40")


@pytest.mark.asyncio
async def test_backtest_partial_tp_gap_candle_fill_behavior() -> None:
    """Verify conservative fill price on candles that gap past the trigger level."""
    candles_gap_long = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.1",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="104.0",  # Gaps open above trigger 103.0
            high_price="105.0",
            low_price="103.8",
            close_price="104.5",
        ),
        _create_candle(
            minute=2,
            open_price="104.5",
            high_price="104.5",
            low_price="99.0",
            close_price="99.5",
        ),
    )
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=10,
            scalping_stop_loss_pct=Decimal("0.02"),
            scalping_take_profit_pct=Decimal("0.06"),
            partial_tp_enabled=True,
            partial_tp_ratio=Decimal("0.50"),
            partial_tp_trigger_progress=Decimal("0.50"),
        ),
    )
    res_gap = await engine.run(request=request, candles=candles_gap_long)
    assert res_gap.metrics.total_trades == 2
    # Fill price for partial TP on gap open must be based on open price with slippage
    assert res_gap.trades[0].exit_price == Decimal("103.94800")

    candles_gap_short = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.1",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="96.0",  # Gaps open below trigger 97.0
            high_price="96.2",
            low_price="95.0",
            close_price="95.5",
        ),
        _create_candle(
            minute=2,
            open_price="95.5",
            high_price="103.0",
            low_price="95.5",
            close_price="102.5",
        ),
    )
    engine_short = BacktestEngine(
        strategy=SellThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=10,
            scalping_stop_loss_pct=Decimal("0.02"),
            scalping_take_profit_pct=Decimal("0.06"),
            partial_tp_enabled=True,
            partial_tp_ratio=Decimal("0.50"),
            partial_tp_trigger_progress=Decimal("0.50"),
        ),
    )
    res_gap_short = await engine_short.run(request=request, candles=candles_gap_short)
    assert res_gap_short.metrics.total_trades == 2
    # Fill price for partial TP on gap down open must be based on open
    # price with buy slippage
    assert res_gap_short.trades[0].exit_price == Decimal("96.04800")


# =============================================================================
# CLI Tests
# =============================================================================
def test_backtest_cli_parses_dates_as_an_inclusive_utc_range() -> None:
    """Normalize date-only command boundaries without local-time ambiguity."""
    request = parse_backtest_request(
        arguments=(
            "backtest",
            "--market-type",
            "spot",
            "--symbol",
            "ethusdt",
            "--interval",
            "15m",
            "--strategy",
            "ema_cross",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-02",
            "--balance",
            "1",
        )
    )

    assert request.symbol == "ETHUSDT"
    assert request.market_type is MarketType.SPOT
    assert request.start_time == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert request.end_time == datetime(
        2026,
        1,
        2,
        23,
        59,
        59,
        999999,
        tzinfo=timezone.utc,
    )
    assert request.initial_balance == Decimal("1")


def test_backtest_service_paginates_ranges_larger_than_exchange_limit() -> None:
    """Load every candle without duplication across Binance-sized pages."""
    result, provider = asyncio.run(_run_paginated_backtest())

    assert result.candle_count == 1_001
    assert len(provider.cursors) == 2
    assert provider.cursors[1] == _START_TIME + timedelta(minutes=1_000)


async def _run_paginated_backtest() -> tuple[BacktestResult, HistoricalCandleStub]:
    """Run a replay spanning two historical provider pages."""
    candles = tuple(
        _create_candle(
            minute=minute,
            open_price="100",
            high_price="100.1",
            low_price="99.9",
            close_price="100",
        )
        for minute in range(1_001)
    )
    provider = HistoricalCandleStub(candles=candles, cursors=[])
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=1_000),
        initial_balance=Decimal("100"),
    )
    service = BacktestService(
        exchange_client=provider,
        engine=BacktestEngine(
            strategy=BuyThenHoldStrategy(),
            risk_settings=RiskSettings(leverage=10),
        ),
    )
    return await service.run(request=request), provider


def test_backtest_cli_parses_data_source_and_database_path() -> None:
    """Parse explicit data source and database path arguments."""
    request = parse_backtest_request(
        arguments=(
            "backtest",
            "--market-type",
            "futures",
            "--symbol",
            "btcusdt",
            "--interval",
            "5m",
            "--strategy",
            "ema_scalping",
            "--start",
            "2026-09-01",
            "--end",
            "2026-09-02",
            "--data-source",
            "local",
            "--database-path",
            "data/custom.db",
        )
    )

    assert request.symbol == "BTCUSDT"
    assert request.data_source == "local"
    assert request.database_path == "data/custom.db"


@pytest.mark.asyncio
async def test_backtest_command_runs_with_local_resampled_data() -> None:
    """run_backtest_command detects local SQLite candles and resamples to 5m."""
    import tempfile
    import uuid

    db_file = Path(tempfile.gettempdir()) / f"local_test_{uuid.uuid4().hex}.db"
    db = SQLiteDatabase(database_path=db_file)
    await db.connect()
    try:
        await SQLiteMigrationManager(database=db).initialize()
        repo = SQLiteCandleRepository(database=db)
        candles = tuple(
            _create_candle(
                minute=i,
                open_price=f"{1000 + i}",
                high_price=f"{1005 + i}",
                low_price=f"{995 + i}",
                close_price=f"{1002 + i}",
            )
            for i in range(100)
        )
        await repo.save_many(candles=candles)
    finally:
        await db.close()

    try:
        settings = Settings()
        request = BacktestRequest(
            symbol="BTCUSDT",
            interval=Interval.M5,
            strategy_type=StrategyType.EMA_SCALPING,
            market_type=MarketType.FUTURES,
            start_time=_START_TIME,
            end_time=_START_TIME + timedelta(minutes=99),
            initial_balance=Decimal("10000"),
            data_source="local",
            database_path=str(db_file),
        )

        result = await run_backtest_command(
            settings=settings,
            request=request,
        )

        assert result.candle_count == 20
        assert "Local SQLite Resampled (1m -> 5m)" in result.data_source_description

    finally:
        db_file.unlink(missing_ok=True)


def test_backtest_cli_parses_close_on_opposite_signal() -> None:
    """Verify CLI parses --close-on-opposite-signal into BacktestRequest."""
    base_args = (
        "backtest",
        "--market-type",
        "futures",
        "--symbol",
        "btcusdt",
        "--interval",
        "1m",
        "--strategy",
        "ema_scalping",
        "--start",
        "2026-09-01",
        "--end",
        "2026-09-02",
    )
    req_default = parse_backtest_request(arguments=base_args)
    assert req_default.close_on_opposite_signal is False

    req_flag = parse_backtest_request(
        arguments=(*base_args, "--close-on-opposite-signal"),
    )
    assert req_flag.close_on_opposite_signal is True


@pytest.mark.asyncio
async def test_backtest_engine_respects_close_on_opposite_signal_flag() -> None:
    """Verify BacktestEngine ignores opposite signals by default for live parity."""
    engine = BacktestEngine(
        strategy=AlternatingSignalStrategy(),
        risk_settings=RiskSettings(leverage=10),
    )
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.1",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100",
            high_price="100.1",
            low_price="99.9",
            close_price="100.05",
        ),
        _create_candle(
            minute=2,
            open_price="100.05",
            high_price="100.1",
            low_price="99.9",
            close_price="100.02",
        ),
    )

    # 1. Default (close_on_opposite_signal=False):
    # Long position stays open across candle 1 and closes only at end of range
    res_default = await engine.run(
        request=replace(_create_request(), close_on_opposite_signal=False),
        candles=candles,
    )
    assert res_default.metrics.total_trades == 1
    assert res_default.trades[0].reason == "End of backtest range"

    # 2. Enabled (close_on_opposite_signal=True):
    # Long position closes on candle 1 due to SELL signal
    res_opposite = await engine.run(
        request=replace(_create_request(), close_on_opposite_signal=True),
        candles=candles,
    )
    assert res_opposite.metrics.total_trades == 1
    assert res_opposite.trades[0].reason == "Paper long position closed by signal"


@pytest.mark.asyncio
async def test_backtest_engine_with_stalking_strategy_service() -> None:
    """BacktestEngine executes full zone -> stalk -> retest -> entry lifecycle."""
    # Fake strategy that yields a zone candidate on bar 0
    anchor_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.HOLD,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=_START_TIME,
        reason="[STALKING_ZONE_SHORT] Price in 15m Upper BB",
        stop_loss=Decimal("112"),
        take_profit=Decimal("80"),
    )

    class _FakeZoneStrategy(BaseStrategy):
        @property
        def strategy_type(self) -> StrategyType:
            return StrategyType.PINBAR_ENGULFING_EMA_RSI

        @property
        def minimum_candles(self) -> int:
            return 1

        def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
            return Signal(
                symbol="BTCUSDT",
                signal_type=SignalType.HOLD,
                price=candles[-1].close_price,
                confidence=Decimal("0.85"),
                strategy_name=self.strategy_type.value,
                generated_at=candles[-1].close_time,
                reason="Default hold",
            )

        def detect_zone_candidate(
            self,
            *,
            candles: Sequence[Candle],
        ) -> Signal | None:
            if len(candles) == 1:
                return anchor_signal
            return None

    fake_strat = _FakeZoneStrategy()
    signal_engine = SignalEngine(
        strategy_resolver=StrategyResolver(
            strategies={StrategyType.PINBAR_ENGULFING_EMA_RSI: fake_strat}
        ),
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_service = SetupStalkingService(max_candidates=5)
    strategy_service = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_service,
        stalking_enabled=True,
    )

    engine = BacktestEngine(
        strategy=fake_strat,
        risk_settings=RiskSettings(leverage=10),
        strategy_service=strategy_service,
    )

    # Bar 0: Stalking zone candidate registered (awaiting reversal)
    candle0 = _create_candle(
        minute=0,
        open_price="100",
        high_price="105",
        low_price="98",
        close_price="99",
    )
    # Bar 1: Reversal confirmed via Bearish Pinbar
    # (high 102, open 98.5, close 98, low 97.5, wick ratio = 77% > 50%)
    candle1 = _create_candle(
        minute=1,
        open_price="98.5",
        high_price="102",
        low_price="97.5",
        close_price="98",
    )
    # Target retest = body_low + (body_size * 0.5) = 98 + (0.5 * 0.5) = 98.25
    # Bar 2: Retest touches 98.25 (high 98.5) and rejects down to close at 97 <= 98.25
    candle2 = _create_candle(
        minute=2,
        open_price="97.5",
        high_price="98.5",
        low_price="96.5",
        close_price="97",
    )
    # Bar 3: Price drops to 75, hitting TP at 80
    candle3 = _create_candle(
        minute=3,
        open_price="97",
        high_price="97.5",
        low_price="75",
        close_price="76",
    )

    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=4),
        initial_balance=Decimal("1000"),
    )

    result = await engine.run(
        request=request,
        candles=(candle0, candle1, candle2, candle3),
    )

    # Trade was entered on bar 2 (TRIGGERED) and closed at TP on bar 3
    assert result.metrics.total_trades == 1
    assert result.trades[0].side is PositionSide.SHORT
    assert result.trades[0].entry_price == Decimal("97") * (
        Decimal("1") - Decimal("0.0005")
    )
    assert "take-profit" in (result.trades[0].reason or "").lower()


@pytest.mark.asyncio
async def test_backtest_engine_swing_pivot_trailing_stop_with_be_floor() -> None:
    """BacktestEngine advances trailing stop with SWING_PIVOT and BE floor."""
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(
            leverage=10,
            scalping_stop_loss_pct=Decimal("0.05"),  # SL at ~95.0
            scalping_take_profit_pct=Decimal("0.20"),  # TP at ~120.0
            stepped_stop_enabled=True,
            trailing_mode=TrailingMode.SWING_PIVOT,
            trailing_swing_window=3,
            trailing_buffer_pct=Decimal("0.0015"),
            breakeven_progress_threshold=Decimal("0.35"),
            breakeven_fee_buffer=Decimal("0.0016"),
        ),
    )

    # Bar 0: Long entered at close 100.0, SL=95.0, TP=120.0
    c0 = _create_candle(
        minute=0, open_price="99", high_price="101", low_price="99", close_price="100"
    )
    # Bar 1: Price fluctuates, low 98.0
    c1 = _create_candle(
        minute=1, open_price="100", high_price="102", low_price="98", close_price="101"
    )
    # Bar 2: Price reaches high 108.0 (TP distance 20, 8/20 = 40% >= 35% BE progress)
    # Swing low of window 3 is 98.0 -> buffered is 97.853 < BE floor 100.16
    # Protection advances stop loss to BE floor 100.16
    c2 = _create_candle(
        minute=2,
        open_price="101",
        high_price="108",
        low_price="100.5",
        close_price="107",
    )
    # Bar 3: Price drops to 100.0 <= 100.16. Stop loss triggered!
    c3 = _create_candle(
        minute=3,
        open_price="107",
        high_price="107.5",
        low_price="99.5",
        close_price="100",
    )

    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=4),
        initial_balance=Decimal("1000"),
    )

    res = await engine.run(request=request, candles=(c0, c1, c2, c3))
    assert res.metrics.total_trades == 1
    trade = res.trades[0]
    assert trade.side is PositionSide.LONG
    # Exit price should be at or near BE floor (100.16), not at initial SL 95.0!
    assert trade.exit_price is not None
    assert trade.exit_price >= Decimal("100.0")
    assert "stop-loss" in (trade.reason or "").lower()
