"""
Botragram

Description:
    Application resource lifecycle management.

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
from dataclasses import dataclass
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.dependency_provider import DependencyProvider

__all__ = [
    "ApplicationLifecycle",
]


# =============================================================================
# Constants
# =============================================================================
_ALREADY_STARTED_ERROR = "Application lifecycle has already been started"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Lifecycle Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
)
class ApplicationLifecycle:
    """Manage application startup and shutdown resources."""

    dependency_provider: DependencyProvider

    _started: bool = False

    @property
    def is_started(self) -> bool:
        """Return whether application resources are active."""
        return self._started

    async def startup(self) -> None:
        """Initialize application resources.

        Raises:
            RuntimeError: If the lifecycle is already active.
        """
        if self._started:
            raise RuntimeError(_ALREADY_STARTED_ERROR)

        _LOGGER.info("Application resource initialization starting")

        try:
            await self.dependency_provider.initialize()
        except asyncio.CancelledError:
            await self.dependency_provider.close()
            _LOGGER.info("Application resource initialization cancelled")
            raise
        except BaseException:
            await self.dependency_provider.close()
            _LOGGER.exception("Application resource initialization failed")
            raise

        self._started = True
        _LOGGER.info("Application resources initialized")

    async def shutdown(self) -> None:
        """Close application resources.

        This operation is idempotent.
        """
        if not self._started:
            return

        _LOGGER.info("Application resource shutdown starting")

        try:
            await self.dependency_provider.close()
        finally:
            self._started = False
            _LOGGER.info("Application resources shut down")

    async def __aenter__(self) -> ApplicationLifecycle:
        """Start application resources for an async context."""
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Close application resources after an async context."""
        del exc_type, exc_value, traceback

        await self.shutdown()
