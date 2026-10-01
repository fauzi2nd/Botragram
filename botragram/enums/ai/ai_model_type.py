"""
Botragram

Description:
    AI model type enumeration.

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
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = ["AiModelType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class AiModelType(BaseEnum):
    """Supported AI models."""

    GPT_5_5 = "gpt-5.5"
    GPT_5 = "gpt-5"

    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"

    CLAUDE_SONNET_4 = "claude-sonnet-4"

    LLAMA_3_1 = "llama3.1"
