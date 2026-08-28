"""Operator portfolio-exit request types."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["OperatorExitType"]


@unique
class OperatorExitType(BaseEnum):
    """Identify the bounded financial action authorized by an operator."""

    CLOSE_POSITION = "close_position"
    CLOSE_ALL = "close_all"
    FLATTEN_AND_SWITCH = "flatten_and_switch"
