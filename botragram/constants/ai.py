"""
Botragram

Description:
    AI related constants.

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
from botragram.enums import AiModelType, AiProvider

__all__ = [
    "DEFAULT_AI_PROVIDER",
    "DEFAULT_AI_MODEL",
    "DEFAULT_AI_TEMPERATURE",
    "DEFAULT_AI_MAX_TOKENS",
    "DEFAULT_AI_TIMEOUT",
]

# =============================================================================
# AI
# =============================================================================
DEFAULT_AI_PROVIDER: AiProvider = AiProvider.OPENAI

DEFAULT_AI_MODEL: AiModelType = AiModelType.GPT_5_5

DEFAULT_AI_TEMPERATURE: float = 0.2

DEFAULT_AI_MAX_TOKENS: int = 2_048

DEFAULT_AI_TIMEOUT: int = 30
