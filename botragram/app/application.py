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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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

        try:
            async with self.lifecycle:
                await self.runner()
        finally:
            self._running = False
