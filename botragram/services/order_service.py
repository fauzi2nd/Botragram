"""
Botragram

Description:
    Backward-compatible import for the order service.

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
from botragram.services.execution.order_service import OrderService

__all__ = ["OrderService"]
