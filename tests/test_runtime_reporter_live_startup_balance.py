"""Runtime reporter LIVE startup balance regression tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

from botragram.enums import TradeMode
from botragram.models import Account, Balance, Notification, Position
from botragram.services.health_service import HealthService
from botragram.services.runtime_reporter import RuntimeReporter


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeDatabase:
    """Provide a healthy database probe."""

    @property
    def is_connected(self) -> bool:
        return True

    async def fetch_one(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> object | None:
        del statement, parameters
        return object()


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeExchange:
    """Provide health and one authoritative account snapshot."""

    account: Account

    async def ping(self) -> bool:
        return True

    async def get_account(self) -> Account:
        return self.account


@dataclass(slots=True, kw_only=True, frozen=True)
class FakePaperBalanceProvider:
    """Remain unused by LIVE startup reporting."""

    async def get_available_balance(self) -> Decimal:
        raise AssertionError("LIVE startup must not read PAPER balance")


@dataclass(slots=True, kw_only=True, frozen=True)
class FakePositionRepository:
    """Return an empty deterministic position set."""

    async def get_open_positions(self) -> tuple[Position, ...]:
        return ()


@dataclass(slots=True, kw_only=True)
class RecordingPublisher:
    """Record notifications for assertions."""

    notifications: list[Notification] = field(default_factory=list[Notification])

    async def publish(self, *, notification: Notification) -> None:
        self.notifications.append(notification)


def test_live_startup_reports_exchange_available_balance() -> None:
    """LIVE startup must not display N/A when exchange account data is available."""
    asyncio.run(_run_live_startup_balance_test())


async def _run_live_startup_balance_test() -> None:
    publisher = RecordingPublisher()
    reporter = RuntimeReporter(
        health_service=HealthService(
            database=FakeDatabase(),
            exchange=FakeExchange(
                account=Account(
                    balances=(
                        Balance(
                            asset="USDT",
                            free=Decimal("14879.85"),
                            locked=Decimal("0"),
                        ),
                    ),
                    can_trade=True,
                )
            ),
        ),
        paper_trading_service=FakePaperBalanceProvider(),
        position_repository=FakePositionRepository(),
        notification_publisher=publisher,
        trade_mode=TradeMode.LIVE,
        symbol="BTCUSDT",
    )

    await reporter.on_started()

    assert len(publisher.notifications) == 1
    message = publisher.notifications[0].message
    assert "<b>Status:</b> HEALTHY" in message
    assert "<b>Available Balance:</b> 14,879.85 USDT" in message
    assert "<b>Available Balance:</b> N/A" not in message
