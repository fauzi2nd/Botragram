"""
Trading Bot

Module:
    core.validators

Description:
    Shared validation helpers used throughout the trading bot.

Python:
    3.14
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.constants import ZERO
from core.exceptions import ValidationError

__all__ = [
    "validate_not_empty",
    "validate_positive_decimal",
    "validate_non_negative_decimal",
    "validate_positive_int",
    "validate_non_negative_int",
    "validate_timezone_aware",
]


def validate_not_empty(value: str, field_name: str) -> None:
    """Validate that a string is not empty."""

    if not value.strip():
        raise ValidationError(f"{field_name} cannot be empty")


def validate_positive_decimal(
    value: Decimal,
    field_name: str,
) -> None:
    """Validate that a decimal value is greater than zero."""

    if value <= ZERO:
        raise ValidationError(f"{field_name} must be > 0")


def validate_non_negative_decimal(
    value: Decimal,
    field_name: str,
) -> None:
    """Validate that a decimal value is greater than or equal to zero."""

    if value < ZERO:
        raise ValidationError(f"{field_name} must be >= 0")


def validate_positive_int(
    value: int,
    field_name: str,
) -> None:
    """Validate that an integer is greater than zero."""

    if value <= 0:
        raise ValidationError(f"{field_name} must be > 0")


def validate_non_negative_int(
    value: int,
    field_name: str,
) -> None:
    """Validate that an integer is greater than or equal to zero."""

    if value < 0:
        raise ValidationError(f"{field_name} must be >= 0")


def validate_timezone_aware(
    value: datetime,
    field_name: str,
) -> None:
    """Validate that a datetime is timezone-aware."""

    if value.tzinfo is None:
        raise ValidationError(
            f"{field_name} must be timezone-aware"
        )