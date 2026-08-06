"""
Botragram

Description:
    Manual application dependency provider smoke test.

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
from botragram.app import DependencyProvider
from botragram.repositories import (
    CandleRepository,
    OrderRepository,
    PositionRepository,
    SignalRepository,
    TradeRepository,
)

# =============================================================================
# Constants
# =============================================================================
_NOT_INITIALIZED_ERROR = "Dependency provider has not been initialized"


# =============================================================================
# Test Helpers
# =============================================================================
def _assert_uninitialized_access(
    provider: DependencyProvider,
) -> None:
    """Assert repository access fails before initialization."""
    repository_getters = (
        lambda: provider.candle_repository,
        lambda: provider.signal_repository,
        lambda: provider.order_repository,
        lambda: provider.trade_repository,
        lambda: provider.position_repository,
    )

    for repository_getter in repository_getters:
        try:
            repository_getter()
        except RuntimeError as error:
            assert str(error) == _NOT_INITIALIZED_ERROR
        else:
            raise AssertionError("Expected repository access to raise RuntimeError")


# =============================================================================
# Manual Test
# =============================================================================
async def _run_test() -> None:
    """Run the dependency provider smoke test."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_provider_test.db"

        provider = DependencyProvider(
            database_path=database_path,
        )

        assert provider.is_initialized is False

        _assert_uninitialized_access(provider)

        await provider.initialize()

        assert provider.is_initialized is True
        assert database_path.exists()

        candle_repository = provider.candle_repository
        signal_repository = provider.signal_repository
        order_repository = provider.order_repository
        trade_repository = provider.trade_repository
        position_repository = provider.position_repository

        assert isinstance(
            candle_repository,
            CandleRepository,
        )
        assert isinstance(
            signal_repository,
            SignalRepository,
        )
        assert isinstance(
            order_repository,
            OrderRepository,
        )
        assert isinstance(
            trade_repository,
            TradeRepository,
        )
        assert isinstance(
            position_repository,
            PositionRepository,
        )

        assert await candle_repository.count() == 0
        assert await signal_repository.count() == 0
        assert await order_repository.count() == 0
        assert await trade_repository.count() == 0
        assert await position_repository.count() == 0

        # Repeated initialization must be idempotent.
        await provider.initialize()

        assert provider.is_initialized is True
        assert provider.candle_repository is candle_repository
        assert provider.signal_repository is signal_repository
        assert provider.order_repository is order_repository
        assert provider.trade_repository is trade_repository
        assert provider.position_repository is position_repository

        await provider.close()

        assert provider.is_initialized is False

        _assert_uninitialized_access(provider)

        # Repeated close must be safe.
        await provider.close()

        assert provider.is_initialized is False

        print(
            "Dependency provider smoke test passed:",
            {
                "database_created": database_path.exists(),
                "repositories_initialized": 5,
                "closed": True,
            },
        )


async def _run_context_manager_test() -> None:
    """Test provider asynchronous context management."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_provider_context_test.db"

        async with DependencyProvider(
            database_path=database_path,
        ) as provider:
            assert provider.is_initialized is True

            assert await provider.candle_repository.count() == 0

        assert provider.is_initialized is False


# =============================================================================
# Entry Point
# =============================================================================
async def _main() -> None:
    """Run all provider smoke tests."""
    await _run_test()
    await _run_context_manager_test()


def main() -> None:
    """Run the manual test."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
