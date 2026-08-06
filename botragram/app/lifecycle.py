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
from dataclasses import dataclass

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

        try:
            await self.dependency_provider.initialize()
        except BaseException:
            await self.dependency_provider.close()
            raise

        self._started = True

    async def shutdown(self) -> None:
        """Close application resources.

        This operation is idempotent.
        """
        if not self._started:
            return

        try:
            await self.dependency_provider.close()
        finally:
            self._started = False

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
