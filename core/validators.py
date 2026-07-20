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

from collections.abc import Collection
from datetime import datetime
from decimal import Decimal
from enum import Enum

from core.constants import ZERO
from core.exceptions import ValidationError

__all__ = [
    # Object
    "validate_not_none",
    "validate_instance",
    # String
    "validate_not_empty",
    "validate_no_whitespace",
    # Collection
    "validate_collection_not_empty",
    # Decimal
    "validate_decimal_positive",
    "validate_decimal_non_negative",
    "validate_decimal_greater_or_equal",
    "validate_decimal_less_or_equal",
    # Integer
    "validate_int_positive",
    "validate_int_non_negative",
    # Enum
    "validate_enum",
    # Datetime
    "validate_timezone_aware",
]


# =============================================================================
# Object
# =============================================================================


def validate_not_none(
    value: object,
    field_name: str,
) -> None:
    """Validate that a value is not None."""

    if value is None:
        raise ValidationError(
            f"{field_name} cannot be None"
        )


def validate_instance(
    value: object,
    expected_type: type,
    field_name: str,
) -> None:
    """Validate object type."""

    if not isinstance(value, expected_type):
        raise ValidationError(
            f"{field_name} must be an instance of "
            f"{expected_type.__name__}"
        )


# =============================================================================
# String
# =============================================================================


def validate_not_empty(
    value: str,
    field_name: str,
) -> None:
    """Validate that a string is not empty."""

    if not value.strip():
        raise ValidationError(
            f"{field_name} cannot be empty"
        )


def validate_no_whitespace(
    value: str,
    field_name: str,
) -> None:
    """Validate that a string contains no whitespace."""

    if any(character.isspace() for character in value):
        raise ValidationError(
            f"{field_name} must not contain whitespace"
        )


# =============================================================================
# Collection
# =============================================================================


def validate_collection_not_empty(
    value: Collection[object],
    field_name: str,
) -> None:
    """Validate that a collection is not empty."""

    if not value:
        raise ValidationError(
            f"{field_name} cannot be empty"
        )


# =============================================================================
# Decimal
# =============================================================================


def validate_decimal_positive(
    value: Decimal,
    field_name: str,
) -> None:
    """Validate decimal > 0."""

    if value <= ZERO:
        raise ValidationError(
            f"{field_name} must be > 0"
        )


def validate_decimal_non_negative(
    value: Decimal,
    field_name: str,
) -> None:
    """Validate decimal >= 0."""

    if value < ZERO:
        raise ValidationError(
            f"{field_name} must be >= 0"
        )


def validate_decimal_greater_or_equal(
    value: Decimal,
    minimum: Decimal,
    field_name: str,
) -> None:
    """Validate decimal >= minimum."""

    if value < minimum:
        raise ValidationError(
            f"{field_name} must be >= {minimum}"
        )


def validate_decimal_less_or_equal(
    value: Decimal,
    maximum: Decimal,
    field_name: str,
) -> None:
    """Validate decimal <= maximum."""

    if value > maximum:
        raise ValidationError(
            f"{field_name} must be <= {maximum}"
        )


# =============================================================================
# Integer
# =============================================================================


def validate_int_positive(
    value: int,
    field_name: str,
) -> None:
    """Validate integer > 0."""

    if value <= 0:
        raise ValidationError(
            f"{field_name} must be > 0"
        )


def validate_int_non_negative(
    value: int,
    field_name: str,
) -> None:
    """Validate integer >= 0."""

    if value < 0:
        raise ValidationError(
            f"{field_name} must be >= 0"
        )


# =============================================================================
# Enum
# =============================================================================


def validate_enum(
    value: Enum,
    enum_type: type[Enum],
    field_name: str,
) -> None:
    """Validate enum type."""

    if not isinstance(value, enum_type):
        raise ValidationError(
            f"{field_name} must be a "
            f"{enum_type.__name__}"
        )


# =============================================================================
# Datetime
# =============================================================================


def validate_timezone_aware(
    value: datetime,
    field_name: str,
) -> None:
    """Validate timezone-aware datetime."""

    if value.tzinfo is None:
        raise ValidationError(
            f"{field_name} must be timezone-aware"
        )