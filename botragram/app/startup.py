"""
Botragram

Description:
    Application startup entry point.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.lifecycle import ApplicationLifecycle

__all__ = [
    "startup_application",
]


# =============================================================================
# Startup Functions
# =============================================================================
async def startup_application(
    *,
    lifecycle: ApplicationLifecycle,
) -> None:
    """Start application resources.

    Args:
        lifecycle: Application resource lifecycle manager.
    """
    await lifecycle.startup()
