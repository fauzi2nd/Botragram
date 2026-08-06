"""
Botragram

Description:
    Application shutdown entry point.

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
    "shutdown_application",
]


# =============================================================================
# Shutdown Functions
# =============================================================================
async def shutdown_application(
    *,
    lifecycle: ApplicationLifecycle,
) -> None:
    """Close application resources.

    Args:
        lifecycle: Application resource lifecycle manager.
    """
    await lifecycle.shutdown()
