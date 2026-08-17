"""
Botragram

Description:
    Runtime policy for selecting a trading-cycle workflow.

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

__all__ = ["ExecutionPolicy"]


# =============================================================================
# Enums
# =============================================================================
@unique
class ExecutionPolicy(BaseEnum):
    """Select the runtime workflow after market analysis."""

    SINGLE_SYMBOL = "single_symbol"
    AUTONOMOUS_PAPER = "autonomous_paper"
    HUMAN_CONFIRMED_PAPER = "human_confirmed_paper"
