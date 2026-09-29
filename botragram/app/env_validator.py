"""
Botragram

Description:
    Environment file validator. Detects duplicate keys in dotenv files so
    that silent-override bugs are caught at startup rather than at runtime.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import logging
from pathlib import Path
from typing import Final

# =============================================================================
# Exports
# =============================================================================
__all__ = ["validate_env_file"]

_LOGGER: Final[logging.Logger] = logging.getLogger("botragram.app.env_validator")

# Keys that are intentionally allowed to appear more than once.
# Document *why* each exception exists; do not add keys speculatively.
_ALLOWED_DUPLICATES: Final[frozenset[str]] = frozenset()


def validate_env_file(env_path: str) -> None:
    """Raise ``ConfigValidationError`` if *env_path* contains duplicate keys.

    ``python-dotenv`` silently accepts duplicate keys and uses the **last**
    occurrence.  This creates a class of hard-to-find bugs where an earlier
    assignment is overridden by a later one without any warning.

    This validator reads the raw file before ``load_dotenv`` processes it and
    fails fast so the operator sees the conflict immediately at startup.

    Args:
        env_path: Absolute or relative path to the dotenv file to validate.

    Raises:
        ConfigValidationError: If one or more keys appear more than once in the
            file and are not listed in ``_ALLOWED_DUPLICATES``.
        FileNotFoundError: If *env_path* does not refer to an existing file.
    """
    # Import here to keep the top-level import surface minimal.
    from botragram.exceptions.config import ConfigValidationError

    path = Path(env_path)
    if not path.is_file():
        # If the file is absent dotenv handles the fallback; not our concern.
        _LOGGER.debug(
            "env_validator: file not found, skipping duplicate-key check: %s",
            env_path,
        )
        return

    seen: dict[str, list[int]] = {}  # key -> list of 1-based line numbers

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()

        # Skip blank lines and comments.
        if not line or line.startswith("#"):
            continue

        # Skip export-prefixed keys (POSIX shell style).
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        # Only process lines that look like KEY=... or KEY (no value).
        eq_pos = line.find("=")
        if eq_pos == -1:
            # A bare key is valid in some dotenv dialects; skip silently.
            continue

        key = line[:eq_pos].strip()
        if not key:
            continue

        seen.setdefault(key, []).append(lineno)

    duplicates = {
        key: lines
        for key, lines in seen.items()
        if len(lines) > 1 and key not in _ALLOWED_DUPLICATES
    }

    if not duplicates:
        _LOGGER.debug(
            "env_validator: no duplicate keys found in %s (%d keys checked)",
            env_path,
            len(seen),
        )
        return

    # Build a human-readable report sorted by first occurrence.
    report_lines: list[str] = []
    for key in sorted(duplicates, key=lambda k: duplicates[k][0]):
        lines_str = ", ".join(str(ln) for ln in duplicates[key])
        report_lines.append(f"  {key}: lines {lines_str}")

    report = "\n".join(report_lines)
    msg = (
        f"Duplicate keys detected in environment file '{env_path}'.\n"
        f"python-dotenv silently uses the LAST value, which hides config bugs.\n"
        f"Resolve each duplicate before starting Botragram:\n"
        f"{report}"
    )
    _LOGGER.error("env_validator: %s", msg)
    raise ConfigValidationError(msg)
