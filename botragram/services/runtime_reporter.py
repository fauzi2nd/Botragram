"""
Botragram

Description:
    Backward-compatible import for runtime reporting service.

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
from botragram.services.runtime.runtime_reporter import RuntimeReporter

__all__ = ["RuntimeReporter"]
