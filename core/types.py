"""
Trading Bot

Module:
    core.types

Description:
    Shared type aliases used throughout the trading bot.

Python:
    3.14
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeAlias

__all__ = [
    "JsonValue",
    "JsonObject",
    "JsonArray",
    "PathLike",
    "DecimalLike",
]

# =============================================================================
# JSON
# =============================================================================

JsonValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | JsonObject
    | JsonArray
)

JsonObject: TypeAlias = Mapping[str, JsonValue]

JsonArray: TypeAlias = list[JsonValue]

# =============================================================================
# Filesystem
# =============================================================================

PathLike: TypeAlias = str | Path

# =============================================================================
# Numeric
# =============================================================================

DecimalLike: TypeAlias = Decimal | int | str