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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import (
    Application,
    ApplicationLifecycle,
    DependencyProvider,
    SettingsManager,
)

__all__ = [
    "main",
]


# =============================================================================
# Runtime Functions
# =============================================================================
async def _run_until_cancelled() -> None:
    """Keep initialized resources active until the process is cancelled."""
    await asyncio.Event().wait()


async def main() -> None:
    """Build and run the Botragram application."""
    settings = SettingsManager().load()
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


if __name__ == "__main__":
    asyncio.run(main())
