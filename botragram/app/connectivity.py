"""
Botragram

Description:
    Classify transient dependency failures at the application boundary.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.utils.connectivity import is_transient_connectivity_error

__all__ = ["is_transient_connectivity_error"]
