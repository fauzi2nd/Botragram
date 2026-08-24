"""Direct regression tests for canonical LIVE runtime portfolio reconciliation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    Interval,
    LiveMarketStreamLifecycleStatus,
    LivePortfolioRecoveryStatus,
    LivePortfolioRecoveryUnsafeReason,
    PositionSide,
    StrategyType,
)
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LivePortfolioRecoveryResult,
    LiveProtectionMonitorState,
    LiveRuntimePositionContext,
    Position,
)
from botragram.services.live_runtime_portfolio_reconciliation_service import (
    LiveRuntimePortfolioReconciliationService,
)
from tests.test_runtime_recovery import (
    FakeLiveMarketStreamOwner,
    FakeLiveProtectionMonitorOwner,
)


@dataclass(slots=True)
class _Streams(FakeLiveMarketStreamOwner):
    async def stop_all(self) -> None:
        self._states.clear()

    def seed_state(self, state: LiveMarketStreamState) -> None:
        self._states[state.identity] = state


class _Monitors(FakeLiveProtectionMonitorOwner):
    def stop_all(self) -> None:
        self._contexts.clear()


@dataclass(slots=True)
class _PortfolioRecovery:
    results: list[LivePortfolioRecoveryResult]

    async def recover(self) -> LivePortfolioRecoveryResult:
        return self.results[0] if len(self.results) == 1 else self.results.pop(0)


def _position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"),
        leverage=1,
        opened_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _service(
    results: list[LivePortfolioRecoveryResult],
) -> tuple[
    LiveRuntimePortfolioReconciliationService,
    TradingRuntimeControl,
    _Streams,
    _Monitors,
]:
    control = TradingRuntimeControl()
    streams = _Streams()
    monitors = _Monitors()
    return (
        LiveRuntimePortfolioReconciliationService(
            runtime_control=control,
            live_portfolio_recovery_service=_PortfolioRecovery(results=results),
            market_stream_service=streams,
            protection_monitoring_service=monitors,
            first_tick_timeout_seconds=1.0,
        ),
        control,
        streams,
        monitors,
    )


def test_zero_portfolio_clears_contexts_and_opens_protection_gate() -> None:
    service, control, streams, monitors = _service(
        [
            LivePortfolioRecoveryResult(
                status=LivePortfolioRecoveryStatus.NO_POSITIONS,
                recovered_positions=(),
            )
        ]
    )

    context = asyncio.run(service.reconcile_context())
    assert context is not None
    assert context.contexts == ()
    assert control.runtime_contexts == ()
    assert control.live_management_authorization is None
    assert control.is_position_protection_ready
    assert streams.stream_states == ()
    assert monitors.monitor_states == ()


@pytest.mark.parametrize(
    "symbols", [("BTCUSDT",), ("ETHUSDT", "BTCUSDT"), ("SOLUSDT", "ETHUSDT", "BTCUSDT")]
)
def test_reconciliation_adopts_canonical_exact_portfolio(
    symbols: tuple[str, ...],
) -> None:
    positions = tuple(_position(symbol) for symbol in symbols)
    status = (
        LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
        if len(positions) == 1
        else LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
    )
    service, control, streams, monitors = _service(
        [LivePortfolioRecoveryResult(status=status, recovered_positions=positions)]
    )

    context = asyncio.run(service.reconcile_context())
    assert context is not None
    assert tuple(item.symbol for item in context.contexts) == tuple(sorted(symbols))
    assert tuple(context.symbol for context in control.runtime_contexts) == tuple(
        sorted(symbols)
    )
    assert tuple(state.identity.symbol for state in streams.stream_states) == tuple(
        sorted(symbols)
    )
    assert tuple(state.context.symbol for state in monitors.monitor_states) == tuple(
        sorted(symbols)
    )
    assert control.live_management_authorization is not None
    assert control.live_management_authorization.contexts == control.runtime_contexts
    assert control.is_position_protection_ready


def test_reconciliation_is_idempotent_for_healthy_portfolio() -> None:
    result = LivePortfolioRecoveryResult(
        status=LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE,
        recovered_positions=(_position("BTCUSDT"),),
    )
    service, control, streams, monitors = _service([result])

    assert asyncio.run(service.reconcile())
    assert asyncio.run(service.reconcile())
    assert streams.events.count("start:BTCUSDT") == 1
    assert monitors.events.count("register:BTCUSDT") == 1
    assert len(control.runtime_contexts) == 1


@dataclass(slots=True)
class _NaturalExit:
    calls: int = 0

    async def reconcile(self) -> None:
        self.calls += 1


@dataclass(slots=True)
class _CancelledNaturalExit:
    async def reconcile(self) -> None:
        raise asyncio.CancelledError()


@dataclass(slots=True)
class _CancelledRecovery:
    async def recover(self) -> LivePortfolioRecoveryResult:
        raise asyncio.CancelledError()


class _UnhealthyMonitors(_Monitors):
    def __init__(self, *, context: LiveRuntimePositionContext) -> None:
        super().__init__()
        self._contexts[context.symbol] = context

    @property
    def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
        return tuple(
            LiveProtectionMonitorState(
                context=context,
                is_active=True,
                failure_type="RuntimeError",
            )
            for context in self._contexts.values()
        )


@dataclass(slots=True)
class _CancelledCleanupStreams(_Streams):
    async def stop_all(self) -> None:
        raise asyncio.CancelledError()


def _safe(*positions: Position) -> LivePortfolioRecoveryResult:
    return LivePortfolioRecoveryResult(
        status=(
            LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
            if len(positions) == 1
            else LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
        ),
        recovered_positions=positions,
    )


def _closed(control: TradingRuntimeControl) -> None:
    assert control.is_position_protection_ready is False
    assert control.is_paused is True
    assert control.live_management_authorization is None


def test_partial_exit_de_adopts_and_then_clears_survivor() -> None:
    natural_exit = _NaturalExit()
    service, control, streams, monitors = _service(
        [
            _safe(_position("BTCUSDT"), _position("ETHUSDT")),
            _safe(_position("ETHUSDT")),
            LivePortfolioRecoveryResult(
                status=LivePortfolioRecoveryStatus.NO_POSITIONS,
                recovered_positions=(),
            ),
        ]
    )
    service = replace(service, live_natural_exit_recovery_service=natural_exit)

    assert asyncio.run(service.reconcile()) is True
    assert asyncio.run(service.reconcile()) is True
    assert streams.events.count("stop:BTCUSDT") == 1
    assert streams.events.count("stop:ETHUSDT") == 0
    assert monitors.events.count("monitor_stop:BTCUSDT") == 1
    assert streams.events.count("start:ETHUSDT") == 1
    assert monitors.events.count("register:ETHUSDT") == 1
    assert tuple(context.symbol for context in control.runtime_contexts) == ("ETHUSDT",)
    assert control.live_management_authorization is not None
    assert control.live_management_authorization.contexts == control.runtime_contexts
    assert control.is_position_protection_ready is True

    assert asyncio.run(service.reconcile()) is True
    assert streams.events.count("stop:ETHUSDT") == 1
    assert monitors.events.count("monitor_stop:ETHUSDT") == 1
    assert control.runtime_contexts == ()
    assert control.live_management_authorization is None
    assert control.is_position_protection_ready is True
    assert natural_exit.calls == 3


def test_first_tick_failure_cleans_every_readiness_claim() -> None:
    service, control, streams, monitors = _service([_safe(_position("BTCUSDT"))])
    streams.first_tick_results["BTCUSDT"] = False

    assert asyncio.run(service.reconcile()) is False
    _closed(control)
    assert streams.stream_states == ()
    assert monitors.monitor_states == ()


@pytest.mark.parametrize("failed", [True, False])
def test_existing_unhealthy_target_stream_fails_closed(failed: bool) -> None:
    service, control, streams, monitors = _service([_safe(_position("BTCUSDT"))])
    identity = LiveMarketStreamIdentity(symbol="BTCUSDT", interval=Interval.M1)
    streams.seed_state(
        LiveMarketStreamState(
            identity=identity,
            lifecycle_status=(
                LiveMarketStreamLifecycleStatus.FAILED
                if failed
                else LiveMarketStreamLifecycleStatus.RUNNING
            ),
            first_tick_received=failed,
            event_count=0,
            last_price=None,
            last_event_monotonic=None,
            failure_type="RuntimeError" if failed else None,
        )
    )
    if not failed:
        streams.first_tick_results["BTCUSDT"] = False

    assert asyncio.run(service.reconcile()) is False
    _closed(control)
    assert streams.stream_states == ()
    assert monitors.monitor_states == ()


def test_unhealthy_monitor_is_replaced_after_protection_recovery() -> None:
    """Replace sticky local monitor failure after portfolio protection is safe."""

    class RecoverableUnhealthyMonitors(_Monitors):
        def __init__(self, *, context: LiveRuntimePositionContext) -> None:
            super().__init__()
            self._contexts[context.symbol] = context
            self.unhealthy_symbols = {context.symbol}

        @property
        def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
            return tuple(
                LiveProtectionMonitorState(
                    context=context,
                    is_active=True,
                    failure_type=(
                        "RuntimeError"
                        if context.symbol in self.unhealthy_symbols
                        else None
                    ),
                )
                for context in self._contexts.values()
            )

        def stop(self, *, symbol: str) -> bool:
            stopped = super().stop(symbol=symbol)
            self.unhealthy_symbols.discard(symbol.strip().upper())
            return stopped

    service, control, streams, _ = _service([_safe(_position("BTCUSDT"))])
    context = LiveRuntimePositionContext(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    monitors = RecoverableUnhealthyMonitors(context=context)
    service = replace(service, protection_monitoring_service=monitors)

    assert asyncio.run(service.reconcile()) is True
    assert monitors.events == ["monitor_stop:BTCUSDT", "register:BTCUSDT"]
    assert monitors.monitor_states[0].failure_type is None
    assert control.is_position_protection_ready
    assert streams.stream_states[0].identity.symbol == "BTCUSDT"


def test_unhealthy_monitor_fails_closed() -> None:
    service, control, streams, _ = _service([_safe(_position("BTCUSDT"))])
    context = LiveRuntimePositionContext(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    monitors = _UnhealthyMonitors(context=context)
    service = replace(service, protection_monitoring_service=monitors)

    assert asyncio.run(service.reconcile()) is False
    _closed(control)
    assert streams.stream_states == ()
    assert monitors.monitor_states == ()


def test_unsafe_recovery_does_not_adopt_anything() -> None:
    service, control, streams, monitors = _service(
        [
            LivePortfolioRecoveryResult(
                status=LivePortfolioRecoveryStatus.UNSAFE,
                recovered_positions=(),
                unsafe_reason=LivePortfolioRecoveryUnsafeReason.PORTFOLIO_SYNC_FAILED,
            )
        ]
    )

    assert asyncio.run(service.reconcile_context()) is None
    _closed(control)
    assert streams.events == []
    assert monitors.events == []


@pytest.mark.parametrize("field", ["interval", "strategy_type"])
def test_missing_position_metadata_fails_closed(field: str) -> None:
    position = _position("BTCUSDT")
    if field == "interval":
        position = replace(position, interval=None)
    else:
        position = replace(position, strategy_type=None)
    service, control, streams, monitors = _service([_safe(position)])

    assert asyncio.run(service.reconcile()) is False
    _closed(control)
    assert streams.stream_states == ()
    assert monitors.monitor_states == ()


@pytest.mark.parametrize("source", ["natural_exit", "recovery", "wait"])
def test_cancellation_propagates_without_ready_state(source: str) -> None:
    service, control, streams, monitors = _service([_safe(_position("BTCUSDT"))])
    if source == "natural_exit":
        service = replace(
            service,
            live_natural_exit_recovery_service=_CancelledNaturalExit(),
        )
    elif source == "recovery":
        service = replace(service, live_portfolio_recovery_service=_CancelledRecovery())
    else:
        streams.cancelled_wait_symbol = "BTCUSDT"

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.reconcile())
    _closed(control)
    assert streams.stream_states == ()
    assert monitors.monitor_states == ()


def test_cleanup_cancellation_propagates_after_fail_closed_state() -> None:
    service, control, _, monitors = _service([_safe(_position("BTCUSDT"))])
    streams = _CancelledCleanupStreams()
    service = replace(
        service,
        market_stream_service=streams,
        protection_monitoring_service=monitors,
        live_portfolio_recovery_service=_CancelledRecovery(),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.reconcile())
    _closed(control)
