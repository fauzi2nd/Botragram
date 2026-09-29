"""
Botragram

Description:
    Tests for the environment file duplicate-key validator.

Python:
    3.14+
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from botragram.app.env_validator import validate_env_file
from botragram.exceptions.config import ConfigValidationError

# =============================================================================
# Helpers
# =============================================================================


def _write_env(tmp_path: Path, content: str) -> str:
    """Write content to a temp .env file and return its path as a string."""
    env_file = tmp_path / ".env"
    env_file.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(env_file)


# =============================================================================
# Tests: clean files — must not raise
# =============================================================================


class TestValidateEnvFileClean:
    def test_all_unique_keys_passes(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            FOO=1
            BAR=2
            BAZ=3
            """,
        )
        validate_env_file(path)  # must not raise

    def test_empty_file_passes(self, tmp_path: Path) -> None:
        path = _write_env(tmp_path, "")
        validate_env_file(path)

    def test_comments_only_passes(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            # This is a comment
            # Another comment
            """,
        )
        validate_env_file(path)

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            FOO=1

            BAR=2

            BAZ=3
            """,
        )
        validate_env_file(path)

    def test_export_prefix_treated_as_single_key(self, tmp_path: Path) -> None:
        """'export FOO=1' should count as key FOO and not clash with itself."""
        path = _write_env(
            tmp_path,
            """
            export FOO=1
            BAR=2
            """,
        )
        validate_env_file(path)

    def test_file_not_found_is_skipped_silently(self, tmp_path: Path) -> None:
        """Missing file must not raise — dotenv handles the absent-file case."""
        validate_env_file(str(tmp_path / "nonexistent.env"))

    def test_inline_comment_does_not_confuse_key_parsing(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            FOO=bar  # this is a comment
            BAZ=qux
            """,
        )
        validate_env_file(path)

    def test_key_with_equals_in_value_parsed_correctly(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
            SECRET_KEY=abc==base64==
            """,
        )
        validate_env_file(path)


# =============================================================================
# Tests: duplicate keys — must raise ConfigValidationError
# =============================================================================


class TestValidateEnvFileDuplicates:
    def test_simple_duplicate_raises(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            FOO=first
            BAR=1
            FOO=second
            """,
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_env_file(path)
        msg = str(exc_info.value)
        assert "FOO" in msg
        assert "lines" in msg

    def test_error_message_lists_all_conflicting_line_numbers(
        self, tmp_path: Path
    ) -> None:
        path = _write_env(
            tmp_path,
            """
            A=1
            B=2
            A=3
            C=4
            A=5
            """,
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_env_file(path)
        msg = str(exc_info.value)
        assert "A" in msg
        # The message must mention multiple line positions
        assert "lines" in msg

    def test_multiple_distinct_duplicate_keys_all_reported(
        self, tmp_path: Path
    ) -> None:
        path = _write_env(
            tmp_path,
            """
            MTF_CONFIRMATION_ENABLED=true
            LTF_CONFIRMATION_MODE=both
            MTF_CONFIRMATION_ENABLED=false
            LTF_CONFIRMATION_MODE=direction
            """,
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_env_file(path)
        msg = str(exc_info.value)
        assert "MTF_CONFIRMATION_ENABLED" in msg
        assert "LTF_CONFIRMATION_MODE" in msg

    def test_export_prefix_duplicate_detected(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            export FOO=first
            export FOO=second
            """,
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_env_file(path)
        assert "FOO" in str(exc_info.value)

    def test_error_message_mentions_file_path(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            KEY=1
            KEY=2
            """,
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_env_file(path)
        assert str(tmp_path / ".env") in str(exc_info.value) or ".env" in str(
            exc_info.value
        )

    def test_duplicate_with_comment_between_still_detected(
        self, tmp_path: Path
    ) -> None:
        path = _write_env(
            tmp_path,
            """
            PIER_REQUIRE_HTF_EXTREME_ZONE=false
            # [I] SETUP STALKING
            PIER_REQUIRE_HTF_EXTREME_ZONE=true
            """,
        )
        with pytest.raises(ConfigValidationError):
            validate_env_file(path)

    def test_real_world_env_scenario_caught(self, tmp_path: Path) -> None:
        """Reproduces the exact bug we found in production on 2026-09-29."""
        path = _write_env(
            tmp_path,
            """
            # Section 4b (early, shadowed)
            MTF_CONFIRMATION_ENABLED=true
            LTF_CONFIRMATION_ENABLED=true
            LTF_CONFIRMATION_MODE=both
            PIER_REQUIRE_HTF_EXTREME_ZONE=false

            # Section 6 (later, wins silently without validator)
            MTF_CONFIRMATION_ENABLED=true
            LTF_CONFIRMATION_ENABLED=true
            LTF_CONFIRMATION_MODE=direction
            PIER_REQUIRE_HTF_EXTREME_ZONE=true
            """,
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_env_file(path)
        msg = str(exc_info.value)
        assert "LTF_CONFIRMATION_MODE" in msg
        assert "PIER_REQUIRE_HTF_EXTREME_ZONE" in msg


# =============================================================================
# Tests: edge cases
# =============================================================================


class TestValidateEnvFileEdgeCases:
    def test_key_without_value_skipped(self, tmp_path: Path) -> None:
        """Bare keys (no '=') are valid in some dialects and should not error."""
        path = _write_env(
            tmp_path,
            """
            FOO
            BAR=1
            """,
        )
        validate_env_file(path)  # must not raise

    def test_line_with_only_equals_skipped(self, tmp_path: Path) -> None:
        """A line that is just '=' has an empty key and should be skipped."""
        path = _write_env(
            tmp_path,
            """
            =value
            FOO=1
            """,
        )
        validate_env_file(path)

    def test_unicode_values_handled(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            """
            GREETING=こんにちは
            NAME=Botragram
            """,
        )
        validate_env_file(path)

    def test_windows_crlf_line_endings(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_bytes(b"FOO=1\r\nBAR=2\r\n")
        validate_env_file(str(env_file))
