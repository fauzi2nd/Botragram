"""
Botragram

Description:
    Base storage infrastructure package initialization.

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
from botragram.storage.base.memory_repository import BaseMemoryRepository

__all__ = [
    "BaseMemoryRepository",
]
