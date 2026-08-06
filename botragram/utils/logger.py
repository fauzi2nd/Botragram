"""
Botragram

Description:
    Central application logging configuration and shutdown utilities.

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
import sys
from logging.handlers import RotatingFileHandler
from time import gmtime
from typing import Final, TextIO

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.logging_settings import LoggingSettings
from botragram.enums import LogLevel

__all__ = [
    "configure_logging",
    "setup_logger",
    "shutdown_logging",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_LOGGER_NAME: Final[str] = "botragram"
_BYTES_PER_MEBIBYTE: Final[int] = 1_048_576
_LOG_FORMAT: Final[str] = "%(asctime)sZ | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S"

_LOG_LEVELS: Final[dict[LogLevel, int]] = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.CRITICAL: logging.CRITICAL,
}
_LOG_LEVEL_ENUMS: Final[dict[int, LogLevel]] = {
    value: key for key, value in _LOG_LEVELS.items()
}


# =============================================================================
# Managed Logging Components
# =============================================================================
class _UtcFormatter(logging.Formatter):
    """Format log timestamps in UTC."""

    converter = staticmethod(gmtime)


class _ManagedStreamHandler(logging.StreamHandler[TextIO]):
    """Identify console handlers owned by Botragram logging configuration."""


class _ManagedRotatingFileHandler(RotatingFileHandler):
    """Identify rotating file handlers owned by Botragram configuration."""


class _ManagedNullHandler(logging.NullHandler):
    """Prevent fallback logging when every configured output is disabled."""


type ManagedHandler = (
    _ManagedStreamHandler | _ManagedRotatingFileHandler | _ManagedNullHandler
)


# =============================================================================
# Public Functions
# =============================================================================
def configure_logging(
    *,
    settings: LoggingSettings,
    logger_name: str = _DEFAULT_LOGGER_NAME,
) -> logging.Logger:
    """Configure console and rotating-file logging for one logger hierarchy.

    Existing handlers created by this function are replaced, making repeated
    configuration safe without duplicating log records. Handlers owned by other
    libraries are preserved.

    Args:
        settings: Validated logging settings.
        logger_name: Root name for the configured logger hierarchy.

    Returns:
        Configured logger instance.

    Raises:
        ValueError: If the logger name is empty.
        OSError: If the configured log directory or file cannot be created.
    """
    normalized_name = logger_name.strip()

    if not normalized_name:
        raise ValueError("Logger name must not be empty")

    logger = logging.getLogger(normalized_name)
    level = _LOG_LEVELS[settings.level]
    formatter = _UtcFormatter(
        fmt=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )

    _remove_managed_handlers(logger=logger)
    logger.setLevel(level)
    logger.propagate = False

    if settings.console_enabled:
        console_handler = _ManagedStreamHandler(sys.stdout)
        _configure_handler(
            handler=console_handler,
            level=level,
            formatter=formatter,
        )
        logger.addHandler(console_handler)

    if settings.file_enabled:
        file_handler = _create_file_handler(
            settings=settings,
            level=level,
            formatter=formatter,
        )
        logger.addHandler(file_handler)

    if not settings.console_enabled and not settings.file_enabled:
        logger.addHandler(_ManagedNullHandler())

    return logger


def shutdown_logging(
    *,
    logger_name: str = _DEFAULT_LOGGER_NAME,
) -> None:
    """Flush, close, and remove handlers owned by Botragram."""
    normalized_name = logger_name.strip()

    if not normalized_name:
        raise ValueError("Logger name must not be empty")

    _remove_managed_handlers(
        logger=logging.getLogger(normalized_name),
    )


def setup_logger(
    name: str = _DEFAULT_LOGGER_NAME,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure a console-only logger using the legacy helper contract.

    Args:
        name: Logger hierarchy name.
        level: Standard-library logging level.

    Returns:
        Configured logger instance.

    Raises:
        ValueError: If the logging level is unsupported.
    """
    log_level = _LOG_LEVEL_ENUMS.get(level)

    if log_level is None:
        raise ValueError(f"Unsupported logging level: {level}")

    return configure_logging(
        settings=LoggingSettings(
            level=log_level,
            console_enabled=True,
            file_enabled=False,
        ),
        logger_name=name,
    )


# =============================================================================
# Private Helpers
# =============================================================================
def _create_file_handler(
    *,
    settings: LoggingSettings,
    level: int,
    formatter: logging.Formatter,
) -> _ManagedRotatingFileHandler:
    """Create a configured rotating file handler."""
    directory = settings.directory
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    log_path = directory / settings.filename
    handler = _ManagedRotatingFileHandler(
        filename=log_path,
        maxBytes=settings.max_file_size_mb * _BYTES_PER_MEBIBYTE,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    _configure_handler(
        handler=handler,
        level=level,
        formatter=formatter,
    )

    return handler


def _configure_handler(
    *,
    handler: ManagedHandler,
    level: int,
    formatter: logging.Formatter,
) -> None:
    """Apply shared level and formatting to a managed output handler."""
    handler.setLevel(level)
    handler.setFormatter(formatter)


def _remove_managed_handlers(
    *,
    logger: logging.Logger,
) -> None:
    """Remove and close handlers installed by Botragram."""
    for handler in tuple(logger.handlers):
        if not isinstance(
            handler,
            (
                _ManagedStreamHandler,
                _ManagedRotatingFileHandler,
                _ManagedNullHandler,
            ),
        ):
            continue

        logger.removeHandler(handler)
        handler.close()
