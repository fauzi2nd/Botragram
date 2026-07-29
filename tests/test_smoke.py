"""
Botragram

Description:
    Basic smoke tests for the scaffolded project.

Python:
    3.14+
"""

from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import asyncio

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.application import Application
from botragram.config.app_settings import AppSettings
from botragram.engine.trading_engine import TradingEngine


# =============================================================================
# Test Doubles
# =============================================================================
class StubEngine:
    """Record market-data refresh requests for application-loop tests."""

    def __init__(self, events: list[str]) -> None:
        """Initialize the event log.

        Args:
            events: Ordered events recorded by the test.
        """
        self._events = events

    async def process_tick(self) -> None:
        """Record a market-data refresh."""
        self._events.append("tick")


class StubTelegramBot:
    """Record Telegram synchronization requests for application-loop tests."""

    def __init__(self, events: list[str]) -> None:
        """Initialize the event log.

        Args:
            events: Ordered events recorded by the test.
        """
        self._events = events

    async def sync_engine_state(self) -> None:
        """Record a Telegram state synchronization."""
        self._events.append("sync")


def test_application_can_be_created() -> None:
    """Ensure the application can be instantiated."""
    application = Application(settings=AppSettings())
    assert application is not None


def test_engine_can_be_created() -> None:
    """Ensure the trading engine can be instantiated."""
    engine = TradingEngine(settings=AppSettings())
    assert engine is not None


def test_application_iteration_refreshes_market_before_telegram() -> None:
    """Test each application iteration refreshes prices before Telegram sync."""
    events: list[str] = []
    application = Application.__new__(Application)
    application._engine = StubEngine(events)
    application._telegram_bot = StubTelegramBot(events)

    asyncio.run(application._run_iteration())

    assert events == ["tick", "sync"]
