"""
Botragram

Description:
    Main application runtime.

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
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.lifecycle import ApplicationLifecycle
from botragram.config import Settings

__all__ = [
    "Application",
]


# =============================================================================
# Type Aliases
# =============================================================================
type ApplicationRunner = Callable[[], Awaitable[None]]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Application Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
)
class Application:
    """Manage the Botragram application runtime."""

    settings: Settings
    lifecycle: ApplicationLifecycle
    runner: ApplicationRunner

    _running: bool = False

    @property
    def is_running(self) -> bool:
        """Return whether the application runner is active."""
        return self._running

    async def run(self) -> None:
        """Start resources and execute the application runner.

        Raises:
            RuntimeError: If the application is already running.
        """
        if self._running:
            raise RuntimeError("Application is already running")

        self._running = True
        _LOGGER.info(
            "Application starting",
            extra={
                "app_name": self.settings.app.app_name,
                "app_version": self.settings.app.app_version,
                "trade_mode": self.settings.app.trade_mode.value,
            },
        )

        try:
            async with self.lifecycle:
                _LOGGER.info("Application resources started")
                await self.runner()
        except asyncio.CancelledError:
            _LOGGER.info("Application cancellation requested")
            raise
        except Exception:
            _LOGGER.exception("Application runner failed")
            raise
        finally:
            self._running = False
            _LOGGER.info("Application stopped")
