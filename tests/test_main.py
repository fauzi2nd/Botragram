"""Process-boundary shutdown presentation regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

import pytest

import main as main_module

type _MainCoroutine = Coroutine[object, object, None]


def test_run_treats_keyboard_interrupt_as_intentional_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return normally when asyncio reports the operator's Ctrl+C."""

    def raise_keyboard_interrupt(coroutine: _MainCoroutine) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module.asyncio, "run", raise_keyboard_interrupt)

    main_module.run()


def test_run_does_not_swallow_ordinary_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep genuine startup and runtime tracebacks visible at the process edge."""
    failure = RuntimeError("configured process failure")

    def raise_failure(coroutine: _MainCoroutine) -> None:
        coroutine.close()
        raise failure

    monkeypatch.setattr(main_module.asyncio, "run", raise_failure)

    with pytest.raises(RuntimeError) as captured:
        main_module.run()

    assert captured.value is failure


def test_run_does_not_swallow_async_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve cancellation propagation below the KeyboardInterrupt boundary."""
    cancellation = asyncio.CancelledError()

    def raise_cancellation(coroutine: _MainCoroutine) -> None:
        coroutine.close()
        raise cancellation

    monkeypatch.setattr(main_module.asyncio, "run", raise_cancellation)

    with pytest.raises(asyncio.CancelledError) as captured:
        main_module.run()

    assert captured.value is cancellation


def test_autonomous_paper_auto_resumes_when_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-resume paper runtime when running in autonomous paper or headless mode."""
    from unittest.mock import AsyncMock, MagicMock

    from botragram.app.runtime_control import TradingRuntimeControl
    from botragram.config import Settings
    from botragram.config.app_settings import AppSettings
    from botragram.config.exchange_settings import ExchangeSettings
    from botragram.config.market_settings import MarketSettings
    from botragram.config.risk_settings import RiskSettings
    from botragram.config.strategy_settings import StrategySettings
    from botragram.config.telegram_settings import TelegramSettings
    from botragram.enums import (
        Environment,
        ExchangeType,
        ExecutionPolicy,
        Interval,
        MarketType,
        StrategyType,
        TradeMode,
    )

    settings = Settings(
        app=AppSettings(
            environment=Environment.DEVELOPMENT,
            trade_mode=TradeMode.PAPER,
            execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
            autonomous_execution_enabled=True,
        ),
        exchange=ExchangeSettings(
            exchange=ExchangeType.BYBIT,
            market_type=MarketType.FUTURES,
        ),
        market=MarketSettings(
            base_asset="BTC",
            quote_asset="USDT",
            interval=Interval.M3,
        ),
        strategy=StrategySettings(
            strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        ),
        risk=RiskSettings(),
        telegram=TelegramSettings(enabled=False),
    )

    runtime_control = TradingRuntimeControl(
        exchange_type=ExchangeType.BYBIT,
        market_type=MarketType.FUTURES,
        symbol="BTCUSDT",
        interval=Interval.M3,
        strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
    )
    assert runtime_control.is_paused

    provider = MagicMock()
    provider.settings = settings
    provider.runtime_control = runtime_control
    provider.paper_trading_service = MagicMock()
    provider.account_service = MagicMock()
    provider.position_repository.get_open_positions = AsyncMock(return_value=[])
    provider.live_futures_user_data_service = None
    provider.live_runtime_health_service = None
    provider.live_trading_performance_service = None
    provider.autonomous_live_recovery_observability_service = None
    provider.runtime_risk_limit_service = None
    provider.pnl_engine = MagicMock()
    provider.candle_sync_service.run_adaptive_background_sync = AsyncMock()
    provider.runtime_recovery_service.recover = AsyncMock(return_value=False)
    provider.telegram_bot = MagicMock()
    provider.signal_engine.get_minimum_candles.return_value = 50
    provider.trading_cycle_executor = MagicMock()
    provider.runtime_reporter = None

    restart_coordinator = MagicMock()
    restart_coordinator.has_committed_restart = False

    monkeypatch.setattr(
        main_module.TerminalMonitor,
        "run",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        main_module,
        "run_until_restart",
        AsyncMock(return_value=None),
    )

    run_trading = getattr(main_module, "_run_trading")
    asyncio.run(
        run_trading(
            dependency_provider=provider,
            settings=settings,
            restart_coordinator=restart_coordinator,
        )
    )

    assert not runtime_control.is_paused
