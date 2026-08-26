"""Read-only recovered LIVE runtime health aggregation tests."""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.enums import (
    Interval,
    LiveFuturesUserDataStatus,
    LiveMarketStreamLifecycleStatus,
    LiveRuntimeHealthReason,
    LiveRuntimeHealthStatus,
    StrategyType,
)
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
)
from botragram.services import LiveRuntimeHealthService


@dataclass(slots=True, frozen=True)
class _Streams:
    stream_states: tuple[LiveMarketStreamState, ...]


@dataclass(slots=True, frozen=True)
class _Monitors:
    monitor_states: tuple[LiveProtectionMonitorState, ...]


@dataclass(slots=True, frozen=True)
class _UserData:
    """Expose deterministic private-stream freshness."""

    status: LiveFuturesUserDataStatus


def _context(symbol: str) -> LiveRuntimePositionContext:
    """Build one deterministic runtime context."""
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
    )


def _stream(
    context: LiveRuntimePositionContext,
    *,
    status: LiveMarketStreamLifecycleStatus = LiveMarketStreamLifecycleStatus.RUNNING,
) -> LiveMarketStreamState:
    """Build one immutable stream summary."""
    return LiveMarketStreamState(
        identity=LiveMarketStreamIdentity.from_runtime_context(context=context),
        lifecycle_status=status,
        first_tick_received=True,
        event_count=1,
        last_price=Decimal("100"),
        last_event_monotonic=1.0,
        failure_type="RuntimeError"
        if status is LiveMarketStreamLifecycleStatus.FAILED
        else None,
    )


def _monitor(
    context: LiveRuntimePositionContext,
    *,
    failure_type: str | None = None,
) -> LiveProtectionMonitorState:
    """Build one immutable monitor summary."""
    return LiveProtectionMonitorState(
        context=context,
        is_active=True,
        failure_type=failure_type,
    )


def _service(
    contexts: tuple[LiveRuntimePositionContext, ...] = (),
    *,
    streams: tuple[LiveMarketStreamState, ...] = (),
    monitors: tuple[LiveProtectionMonitorState, ...] = (),
    authorize: bool = False,
    resume: bool = False,
) -> tuple[LiveRuntimeHealthService, TradingRuntimeControl]:
    """Build a read-only health boundary from canonical state fakes."""
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    if authorize:
        control.set_live_management_authorization(
            authorization=LiveRecoveredPositionManagementAuthorization(
                contexts=contexts,
                runtime_management_allowed=True,
            )
        )
    if resume:
        control.set_position_protection_ready(True)
        control.resume()
    return (
        LiveRuntimeHealthService(
            runtime_control=control,
            market_stream_service=_Streams(stream_states=streams),
            protection_monitoring_service=_Monitors(monitor_states=monitors),
            clock=lambda: 1.0,
        ),
        control,
    )


def test_zero_contexts_are_inactive_without_side_effects() -> None:
    """Expose no-position state without mutating the runtime controller."""
    service, control = _service()

    snapshot = service.get_snapshot()

    assert snapshot.status is LiveRuntimeHealthStatus.INACTIVE
    assert snapshot.reason is LiveRuntimeHealthReason.NO_POSITIONS
    assert control.runtime_contexts == ()
    assert control.is_paused


def test_exact_healthy_multi_portfolio_is_active_and_complete() -> None:
    """Represent every healthy context without inventing a primary position."""
    contexts = (_context("BTCUSDT"), _context("ETHUSDT"))
    service, _ = _service(
        contexts,
        streams=tuple(_stream(context) for context in contexts),
        monitors=tuple(_monitor(context) for context in contexts),
        authorize=True,
        resume=True,
    )

    snapshot = service.get_snapshot()

    assert snapshot.status is LiveRuntimeHealthStatus.ACTIVE
    assert snapshot.reason is None
    assert snapshot.contexts == contexts
    assert tuple(state.identity.symbol for state in snapshot.stream_states) == (
        "BTCUSDT",
        "ETHUSDT",
    )
    assert tuple(state.context.symbol for state in snapshot.monitor_states) == (
        "BTCUSDT",
        "ETHUSDT",
    )


@pytest.mark.parametrize(
    ("streams", "monitors", "reason", "affected_symbol"),
    (
        (
            (
                _stream(_context("BTCUSDT")),
                _stream(
                    _context("ETHUSDT"),
                    status=LiveMarketStreamLifecycleStatus.FAILED,
                ),
            ),
            (_monitor(_context("BTCUSDT")), _monitor(_context("ETHUSDT"))),
            LiveRuntimeHealthReason.STREAM_FAILED,
            "ETHUSDT",
        ),
        (
            (_stream(_context("BTCUSDT")), _stream(_context("ETHUSDT"))),
            (
                _monitor(_context("BTCUSDT"), failure_type="RuntimeError"),
                _monitor(_context("ETHUSDT")),
            ),
            LiveRuntimeHealthReason.MONITOR_UNHEALTHY,
            "BTCUSDT",
        ),
    ),
)
def test_unhealthy_required_owner_degrades_the_whole_portfolio(
    streams: tuple[LiveMarketStreamState, ...],
    monitors: tuple[LiveProtectionMonitorState, ...],
    reason: LiveRuntimeHealthReason,
    affected_symbol: str,
) -> None:
    """Identify the failed context without reporting a healthy subset as active."""
    contexts = (_context("BTCUSDT"), _context("ETHUSDT"))
    service, _ = _service(
        contexts,
        streams=streams,
        monitors=monitors,
        authorize=True,
        resume=True,
    )

    snapshot = service.get_snapshot()

    assert snapshot.status is LiveRuntimeHealthStatus.DEGRADED
    assert snapshot.reason is reason
    assert snapshot.affected_contexts[0].symbol == affected_symbol


def test_missing_authorization_and_reconciliation_are_explicitly_blocked() -> None:
    """Keep diagnostic state separate from the authorization capability itself."""
    contexts = (_context("BTCUSDT"), _context("ETHUSDT"))
    streams = tuple(_stream(context) for context in contexts)
    monitors = tuple(_monitor(context) for context in contexts)
    service, control = _service(contexts, streams=streams, monitors=monitors)

    missing = service.get_snapshot()
    control.require_portfolio_reconciliation(context=contexts[1])
    reconciliation = service.get_snapshot()

    assert missing.status is LiveRuntimeHealthStatus.BLOCKED
    assert missing.reason is LiveRuntimeHealthReason.AUTHORIZATION_MISSING
    assert reconciliation.reason is LiveRuntimeHealthReason.RECONCILIATION_REQUIRED
    assert reconciliation.affected_contexts == (contexts[1],)


def test_snapshot_is_immutable() -> None:
    """Reject mutation of the published operational snapshot."""
    snapshot = _service()[0].get_snapshot()

    assert tuple(field.name for field in fields(snapshot)) == (
        "status",
        "reason",
        "contexts",
        "affected_contexts",
        "authorization_present",
        "authorization_exact",
        "runner_paused",
        "cycle_in_progress",
        "stream_states",
        "monitor_states",
    )
    with pytest.raises(AttributeError):
        setattr(snapshot, "status", LiveRuntimeHealthStatus.ACTIVE)


def test_stale_public_tick_degrades_runtime_health() -> None:
    """Treat a connected-but-silent public stream as non-authoritative."""
    context = _context("BTCUSDT")
    service, _ = _service(
        (context,),
        streams=(_stream(context),),
        monitors=(_monitor(context),),
        authorize=True,
        resume=True,
    )
    service = LiveRuntimeHealthService(
        runtime_control=service.runtime_control,
        market_stream_service=service.market_stream_service,
        protection_monitoring_service=service.protection_monitoring_service,
        stream_stale_after_seconds=30.0,
        clock=lambda: 31.1,
    )

    snapshot = service.get_snapshot()

    assert snapshot.status is LiveRuntimeHealthStatus.DEGRADED
    assert snapshot.reason is LiveRuntimeHealthReason.STREAM_STALE
    assert snapshot.affected_contexts == (context,)


@pytest.mark.parametrize(
    "status",
    (
        LiveFuturesUserDataStatus.STARTING,
        LiveFuturesUserDataStatus.RESYNCING,
        LiveFuturesUserDataStatus.STALE,
    ),
)
def test_private_stream_non_ready_blocks_zero_position_entry_health(
    status: LiveFuturesUserDataStatus,
) -> None:
    """Degrade autonomous entry for every non-authoritative private state."""
    service, _ = _service()
    service = LiveRuntimeHealthService(
        runtime_control=service.runtime_control,
        market_stream_service=service.market_stream_service,
        protection_monitoring_service=service.protection_monitoring_service,
        live_futures_user_data_service=_UserData(status=status),
        clock=lambda: 1.0,
    )

    snapshot = service.get_snapshot()

    assert snapshot.status is LiveRuntimeHealthStatus.DEGRADED
    assert snapshot.reason is LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY
    assert snapshot.contexts == ()
