"""
Botragram

Description:
    Basic smoke tests for the scaffolded project.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.app.application import Application
from botragram.config.app_settings import AppSettings
from botragram.engine.trading_engine import TradingEngine


def test_application_can_be_created() -> None:
    """Ensure the application can be instantiated."""
    application = Application(settings=AppSettings())
    assert application is not None


def test_engine_can_be_created() -> None:
    """Ensure the trading engine can be instantiated."""
    engine = TradingEngine(settings=AppSettings())
    assert engine is not None
