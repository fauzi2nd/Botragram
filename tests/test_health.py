"""Runtime dependency health and reporting tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from botragram.enums import NotificationType, SignalType, TradeMode
from botragram.models import Notification, Signal, TradingDecision, TradingResult
from botragram.services import HealthService, RuntimeReporter
from botragram.storage.memory import MemoryPositionRepository

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True, kw_only=True)
class FakeDatabaseHealth:
    """Return deterministic SQLite probe state."""

    is_connected: bool = True
    fail: bool = False

    async def fetch_one(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> object | None:
        """Return one probe row or simulate an operational failure."""
        del statement, parameters

        if self.fail:
            raise RuntimeError("database unavailable")

        return object()


@dataclass(slots=True, kw_only=True)
class FakeExchangeHealth:
    """Return deterministic exchange probe state."""

    healthy: bool = True
    fail: bool = False

    async def ping(self) -> bool:
        """Return reachability or simulate a network failure."""
        if self.fail:
            raise RuntimeError("exchange unavailable")

        return self.healthy


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeBalanceProvider:
    """Return deterministic paper balance."""

    balance: Decimal
    fail: bool = False

    async def get_available_balance(self) -> Decimal:
        """Return available paper funds."""
        if self.fail:
            raise RuntimeError("paper balance must not be read")

        return self.balance


@dataclass(slots=True, kw_only=True)
class RecordingNotificationPublisher:
    """Capture runtime notifications."""

    notifications: list[Notification] = field(default_factory=list[Notification])

    async def publish(self, *, notification: Notification) -> None:
        """Capture one notification."""
        self.notifications.append(notification)


def _create_result() -> TradingResult:
    """Create one completed non-executed cycle result."""
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.HOLD,
        price=Decimal("100"),
        confidence=Decimal("0.5"),
        strategy_name="health_test",
        generated_at=_NOW,
    )
    decision = TradingDecision(
        should_execute=False,
        signal=signal,
        risk_result=None,
        reason="Hold",
    )
    return TradingResult(
        executed=False,
        decision=decision,
        order=None,
        reason=decision.reason,
    )


def test_health_service_reports_healthy_and_degraded_dependencies() -> None:
    """Detect both healthy dependencies and isolated failures."""
    asyncio.run(_run_health_service_test())


async def _run_health_service_test() -> None:
    """Probe healthy and failing dependency combinations."""
    healthy_report = await HealthService(
        database=FakeDatabaseHealth(),
        exchange=FakeExchangeHealth(),
    ).check()
    degraded_report = await HealthService(
        database=FakeDatabaseHealth(fail=True),
        exchange=FakeExchangeHealth(fail=True),
    ).check()

    assert healthy_report.healthy
    assert not degraded_report.healthy
    assert not degraded_report.database_healthy
    assert not degraded_report.exchange_healthy


def test_runtime_reporter_sanitizes_failures_and_reports_portfolio() -> None:
    """Publish startup, periodic, failure, and shutdown observations safely."""
    asyncio.run(_run_runtime_reporter_test())


async def _run_runtime_reporter_test() -> None:
    """Exercise the complete runtime observer lifecycle."""
    publisher = RecordingNotificationPublisher()
    reporter = RuntimeReporter(
        health_service=HealthService(
            database=FakeDatabaseHealth(),
            exchange=FakeExchangeHealth(),
        ),
        paper_trading_service=FakeBalanceProvider(balance=Decimal("10000")),
        position_repository=MemoryPositionRepository(),
        notification_publisher=publisher,
        trade_mode=TradeMode.PAPER,
        symbol="BTCUSDT",
        report_every_cycles=2,
    )
    result = _create_result()

    await reporter.on_started()
    await reporter.on_cycle_completed(result=result)
    await reporter.on_cycle_completed(result=result)
    assert len(publisher.notifications) == 2

    # Intermediate transient failure should be suppressed (no spam)
    await reporter.on_cycle_failed(
        error=RuntimeError("API_SECRET=must-not-leak"),
        consecutive_failures=1,
        maximum_failures=3,
    )
    assert len(publisher.notifications) == 2

    # Terminal failure at maximum threshold (3/3) must be published
    await reporter.on_cycle_failed(
        error=RuntimeError("API_SECRET=must-not-leak"),
        consecutive_failures=3,
        maximum_failures=3,
    )
    await reporter.on_stopped()

    messages = "\n".join(item.message for item in publisher.notifications)

    assert len(publisher.notifications) == 4
    assert "HEALTHY" in messages
    assert "Completed Cycles:</b> 2" in messages
    assert "RuntimeError" in messages
    assert "Consecutive Cycle Failures:</b> 3/3" in messages
    assert "must-not-leak" not in messages
    assert publisher.notifications[2].level is NotificationType.ERROR


def test_runtime_reporter_does_not_report_paper_balance_in_live_mode() -> None:
    """Avoid presenting simulated funds as a live exchange balance."""
    asyncio.run(_run_live_reporter_test())


async def _run_live_reporter_test() -> None:
    """Start live reporting without reading the paper portfolio balance."""
    publisher = RecordingNotificationPublisher()
    reporter = RuntimeReporter(
        health_service=HealthService(
            database=FakeDatabaseHealth(),
            exchange=FakeExchangeHealth(),
        ),
        paper_trading_service=FakeBalanceProvider(
            balance=Decimal("0"),
            fail=True,
        ),
        position_repository=MemoryPositionRepository(),
        notification_publisher=publisher,
        trade_mode=TradeMode.LIVE,
        symbol="BTCUSDT",
        report_every_cycles=1,
    )

    await reporter.on_started()
    await reporter.on_cycle_completed(result=_create_result())

    assert len(publisher.notifications) == 1
    assert "Available Balance:</b> N/A" in publisher.notifications[0].message


def test_startup_report_survives_an_unavailable_paper_balance() -> None:
    """Still publish degraded startup context when portfolio reads fail."""
    asyncio.run(_run_unavailable_balance_report_test())


async def _run_unavailable_balance_report_test() -> None:
    """Simulate a failed balance query during startup reporting."""
    publisher = RecordingNotificationPublisher()
    reporter = RuntimeReporter(
        health_service=HealthService(
            database=FakeDatabaseHealth(fail=True),
            exchange=FakeExchangeHealth(),
        ),
        paper_trading_service=FakeBalanceProvider(
            balance=Decimal("0"),
            fail=True,
        ),
        position_repository=MemoryPositionRepository(),
        notification_publisher=publisher,
        trade_mode=TradeMode.PAPER,
        symbol="BTCUSDT",
    )

    await reporter.on_started()

    assert len(publisher.notifications) == 1
    assert "DEGRADED" in publisher.notifications[0].message
    assert "Available Balance:</b> N/A" in publisher.notifications[0].message
