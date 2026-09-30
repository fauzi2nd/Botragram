"""
Botragram

Description:
    Backward-compatible import for PAPER execution authorization.

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
from botragram.services.execution.execution_authorization_service import (
    ExecutionAuthorizationService,
)

__all__ = ["ExecutionAuthorizationService"]
