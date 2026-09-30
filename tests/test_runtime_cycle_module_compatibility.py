"""
Botragram

Description:
    Public import compatibility for extracted runtime-cycle components.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.app import (
    MultiContextRunnerActivationPreconditions as AppActivationPreconditions,
)
from botragram.app import SingleSymbolTradingCycleExecutor as AppSingleExecutor
from botragram.app.multi_context_activation import (
    MultiContextRunnerActivationPreconditions,
)
from botragram.app.runtime.multi_context_activation import (
    MultiContextRunnerActivationPreconditions as RuntimeActivationPreconditions,
)
from botragram.app.runtime.single_symbol_cycle_executor import (
    SingleSymbolTradingCycleExecutor as RuntimeSingleExecutor,
)
from botragram.app.single_symbol_cycle_executor import (
    SingleSymbolTradingCycleExecutor,
)
from botragram.app.trading_runner import (
    MultiContextRunnerActivationPreconditions as RunnerActivationPreconditions,
)
from botragram.app.trading_runner import (
    SingleSymbolTradingCycleExecutor as RunnerSingleExecutor,
)

__all__: list[str] = []


def test_runtime_cycle_public_imports_preserve_class_identity() -> None:
    """App and runner imports retain the same classes after extraction."""
    assert AppActivationPreconditions is MultiContextRunnerActivationPreconditions
    assert RunnerActivationPreconditions is MultiContextRunnerActivationPreconditions
    assert AppSingleExecutor is SingleSymbolTradingCycleExecutor
    assert RunnerSingleExecutor is SingleSymbolTradingCycleExecutor
    assert RuntimeActivationPreconditions is MultiContextRunnerActivationPreconditions
    assert RuntimeSingleExecutor is SingleSymbolTradingCycleExecutor
