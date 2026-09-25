"""
Botragram

Description:
    Base strategies package initialization.

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
from botragram.strategies.base.asset_thresholds import (
    resolve_asset_class,
    resolve_effective_distance_pct,
    resolve_effective_natr_bounds,
    resolve_timeframe_scale_factor,
)
from botragram.strategies.base.strategy import BaseStrategy

__all__ = [
    "BaseStrategy",
    "resolve_asset_class",
    "resolve_effective_distance_pct",
    "resolve_effective_natr_bounds",
    "resolve_timeframe_scale_factor",
]
