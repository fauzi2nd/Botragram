"""
Botragram

Description:
    Central logging configuration tests.

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
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest
from pytest import CaptureFixture

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.logging_settings import LoggingSettings
from botragram.enums import LogLevel
from botragram.utils.logger import (
    configure_logging,
    setup_logger,
    shutdown_logging,
)

# =============================================================================
# Constants
# =============================================================================
_LOGGER_NAME = "botragram.tests.logging"
_LOG_LINE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
    r" \| INFO \| botragram\.tests\.logging \| configured$"
)


# =============================================================================
# Test Types
# =============================================================================
class LoggingSettingsOverrides(TypedDict, total=False):
    """Supported keyword overrides for invalid settings cases."""

    filename: str
    max_file_size_mb: int
    backup_count: int


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture(autouse=True)
def clean_test_logger() -> Iterator[None]:
    """Remove managed handlers before and after every logging test."""
    shutdown_logging(logger_name=_LOGGER_NAME)
    yield
    shutdown_logging(logger_name=_LOGGER_NAME)


# =============================================================================
# Settings Tests
# =============================================================================
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"filename": "   "}, "filename"),
        ({"filename": "nested/botragram.log"}, "directory path"),
        ({"max_file_size_mb": 0}, "greater than zero"),
        ({"backup_count": -1}, "must not be negative"),
    ],
)
def test_logging_settings_reject_invalid_rotation_configuration(
    overrides: LoggingSettingsOverrides,
    message: str,
) -> None:
    """Reject unsafe filenames and invalid rotation limits."""
    with pytest.raises(ValueError, match=message):
        LoggingSettings(**overrides)


# =============================================================================
# Logger Configuration Tests
# =============================================================================
def test_configure_logging_writes_filtered_utc_console_output(
    capsys: CaptureFixture[str],
) -> None:
    """Write eligible messages to stdout using the UTC format."""
    logger = configure_logging(
        settings=LoggingSettings(
            level=LogLevel.INFO,
            console_enabled=True,
            file_enabled=False,
        ),
        logger_name=_LOGGER_NAME,
    )

    logger.debug("filtered")
    logger.info("configured")

    output = capsys.readouterr().out.strip()
    assert _LOG_LINE_PATTERN.fullmatch(output)
    assert "filtered" not in output


def test_configure_logging_writes_to_rotating_file(tmp_path: Path) -> None:
    """Create the configured directory and persist UTF-8 log records."""
    log_directory = tmp_path / "nested" / "logs"
    logger = configure_logging(
        settings=LoggingSettings(
            level=LogLevel.DEBUG,
            console_enabled=False,
            file_enabled=True,
            directory=log_directory,
            filename="application.log",
            max_file_size_mb=1,
            backup_count=2,
        ),
        logger_name=_LOGGER_NAME,
    )

    logger.debug("file configured")
    shutdown_logging(logger_name=_LOGGER_NAME)

    contents = (log_directory / "application.log").read_text(encoding="utf-8")
    assert "DEBUG | botragram.tests.logging | file configured" in contents


def test_reconfiguration_replaces_only_managed_handlers(
    capsys: CaptureFixture[str],
) -> None:
    """Prevent duplicate records while preserving caller-owned handlers."""
    logger = logging.getLogger(_LOGGER_NAME)
    external_handler = logging.NullHandler()
    logger.addHandler(external_handler)
    preserved_handlers = tuple(logger.handlers)

    try:
        settings = LoggingSettings(
            console_enabled=True,
            file_enabled=False,
        )
        configure_logging(settings=settings, logger_name=_LOGGER_NAME)
        configure_logging(settings=settings, logger_name=_LOGGER_NAME)

        logger.info("one record")

        output = capsys.readouterr().out
        assert output.count("one record") == 1
        assert external_handler in logger.handlers
        assert all(handler in logger.handlers for handler in preserved_handlers)
        assert len(logger.handlers) == len(preserved_handlers) + 1
    finally:
        logger.removeHandler(external_handler)


def test_disabled_outputs_install_a_null_handler(
    capsys: CaptureFixture[str],
) -> None:
    """Suppress last-resort output when every destination is disabled."""
    existing_handler_count = len(logging.getLogger(_LOGGER_NAME).handlers)
    logger = configure_logging(
        settings=LoggingSettings(
            console_enabled=False,
            file_enabled=False,
        ),
        logger_name=_LOGGER_NAME,
    )

    logger.error("suppressed")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert len(logger.handlers) == existing_handler_count + 1
    assert isinstance(logger.handlers[-1], logging.NullHandler)


def test_shutdown_logging_removes_managed_handlers() -> None:
    """Close and remove every output owned by the central configuration."""
    existing_handlers = tuple(logging.getLogger(_LOGGER_NAME).handlers)
    logger = configure_logging(
        settings=LoggingSettings(file_enabled=False),
        logger_name=_LOGGER_NAME,
    )

    shutdown_logging(logger_name=_LOGGER_NAME)

    assert tuple(logger.handlers) == existing_handlers


def test_legacy_setup_logger_maps_standard_level() -> None:
    """Keep the legacy console helper compatible with standard levels."""
    logger = setup_logger(name=_LOGGER_NAME, level=logging.WARNING)

    assert logger.level == logging.WARNING


def test_legacy_setup_logger_rejects_custom_level() -> None:
    """Reject levels that cannot be represented by LoggingSettings."""
    with pytest.raises(ValueError, match="Unsupported logging level"):
        setup_logger(name=_LOGGER_NAME, level=15)


def test_logger_name_must_not_be_empty() -> None:
    """Reject configuration and shutdown without a logger hierarchy."""
    settings = LoggingSettings(file_enabled=False)

    with pytest.raises(ValueError, match="Logger name"):
        configure_logging(settings=settings, logger_name="   ")

    with pytest.raises(ValueError, match="Logger name"):
        shutdown_logging(logger_name="   ")
