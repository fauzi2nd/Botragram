"""
Botragram

Description:
    Main application orchestrator.

Python:
    3.14+
"""

from __future__ import annotations

import logging

from botragram.config.app_settings import AppSettings
from botragram.engine.trading_engine import TradingEngine

logger = logging.getLogger(__name__)


class Application:
    """Main orchestrator for the Botragram trading bot."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()
        self._engine = TradingEngine(settings=self._settings)

    async def run(self) -> None:
        """Run the application lifecycle."""
        logger.info("Botragram application started")
        await self._engine.start()
