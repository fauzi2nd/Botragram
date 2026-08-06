"""
Botragram

Description:
    Manual application runtime smoke test.

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
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import (
    Application,
    ApplicationLifecycle,
    DependencyProvider,
)
from botragram.config import Settings


# =============================================================================
# Manual Tests
# =============================================================================
async def _run_success_test() -> None:
    """Verify the application starts and stops correctly."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "application.db"

        dependency_provider = DependencyProvider(
            database_path=database_path,
        )

        lifecycle = ApplicationLifecycle(
            dependency_provider=dependency_provider,
        )

        executed = False

        async def runner() -> None:
            nonlocal executed

            executed = True

            assert lifecycle.is_started
            assert dependency_provider.is_initialized

            candle_count = await dependency_provider.candle_repository.count()

            assert candle_count == 0

        application = Application(
            settings=Settings(),
            lifecycle=lifecycle,
            runner=runner,
        )

        await application.run()

        assert executed
        assert not application.is_running
        assert not lifecycle.is_started
        assert not dependency_provider.is_initialized


async def _run_failure_test() -> None:
    """Verify resources are closed after runner failure."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "application_failure.db"

        dependency_provider = DependencyProvider(
            database_path=database_path,
        )

        lifecycle = ApplicationLifecycle(
            dependency_provider=dependency_provider,
        )

        async def runner() -> None:
            raise RuntimeError("Boom")

        application = Application(
            settings=Settings(),
            lifecycle=lifecycle,
            runner=runner,
        )

        try:
            await application.run()
        except RuntimeError as error:
            assert str(error) == "Boom"
        else:
            raise AssertionError("Expected RuntimeError")

        assert not application.is_running
        assert not lifecycle.is_started
        assert not dependency_provider.is_initialized


# =============================================================================
# Entry Point
# =============================================================================
async def _main() -> None:
    """Run all application smoke tests."""
    await _run_success_test()
    await _run_failure_test()

    print("Application smoke test passed.")


def main() -> None:
    """Run the manual test."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
