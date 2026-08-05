"""
Botragram

Description:
    AI model configuration settings.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from dataclasses import dataclass

__all__ = [
    "AISettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class AISettings:
    """AI model configuration settings."""

    enabled: bool = False

    provider: str = "openai"
    model: str = "gpt-5"

    api_key: str = ""

    temperature: float = 0.2
    max_tokens: int = 1000
