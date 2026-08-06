"""
Botragram

Description:
    Process entry point and top-level application composition.

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
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import (
    Application,
    ApplicationLifecycle,
    DependencyProvider,
    SettingsManager,
)
from botragram.utils.logger import configure_logging, shutdown_logging

__all__ = [
    "main",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger("botragram.main")


# =============================================================================
# Runtime Functions
# =============================================================================
async def _run_until_cancelled() -> None:
    """Keep initialized resources active until the process is cancelled."""
    await asyncio.Event().wait()


async def main() -> None:
    """Build and run the Botragram application."""
    settings = SettingsManager().load()
    configure_logging(settings=settings.logging)

    try:
        _LOGGER.info(
            "Application configuration loaded",
            extra={
                "environment": settings.app.environment.value,
                "exchange": settings.exchange.exchange.value,
                "testnet": settings.exchange.testnet,
                "trade_mode": settings.app.trade_mode.value,
            },
        )
        dependency_provider = DependencyProvider(
            database_path=settings.app.database_path,
            settings=settings,
        )
        lifecycle = ApplicationLifecycle(
            dependency_provider=dependency_provider,
        )
        application = Application(
            settings=settings,
            lifecycle=lifecycle,
            runner=_run_until_cancelled,
        )
        await application.run()
    finally:
        shutdown_logging()


if __name__ == "__main__":
    asyncio.run(main())
