"""Regression tests for DependencyProvider wiring of recovery services."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from botragram.app import DependencyProvider

_TMP_DIRS: list[object] = []


async def _build_provider() -> DependencyProvider:
    # Use a non-autoremoved temp directory to avoid platform-specific
    # permission issues when DependencyProvider holds open file handles.
    tmp = TemporaryDirectory()
    _TMP_DIRS.append(tmp)
    db = Path(tmp.name) / "wiring.db"
    provider = DependencyProvider(database_path=db)
    await provider.initialize()
    return provider


def test_live_post_entry_recovery_service_has_order_service() -> None:
    """Ensure DependencyProvider wires order GET into recovery service."""
    provider = asyncio.run(_build_provider())

    try:
        service = provider.live_post_entry_recovery_service
        assert service is not None
        # The production provider must supply the order_service dependency.
        assert getattr(service, "order_service", None) is provider.order_service
        # The reconciler for persisted protections should be the live protection service
        assert (
            getattr(service, "protection_reconciler", None)
            is provider.live_position_protection_service
        )
        operator_exit = provider.operator_exit_service
        assert (
            operator_exit.operator_exit_repository is provider.operator_exit_repository
        )
        assert (
            provider.runtime_recovery_service.operator_exit_recovery_service
            is operator_exit
        )
        assert (
            provider.live_natural_exit_recovery_service.operator_exit_repository
            is provider.operator_exit_repository
        )
    finally:
        asyncio.run(provider.close())
