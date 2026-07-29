"""
Botragram

Description:
    Trading engine implementation.

Python:
    3.14+
"""

from __future__ import annotations

import logging

from botragram.config.app_settings import AppSettings

logger = logging.getLogger(__name__)


class TradingEngine:
    """Core trading engine orchestrating strategies and exchanges."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    async def start(self) -> None:
        """Start the trading engine."""
        logger.info("Trading engine started for %s", self._settings.app_name)
