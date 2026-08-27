"""Runtime-limit-aware autonomous LIVE cycle executor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from botragram.app.trading_runner import AutonomousLiveTradingCycleExecutor
from botragram.models import LiveRuntimePortfolioContext, RuntimeRiskLimits

__all__ = ["RuntimeLimitedAutonomousLiveTradingCycleExecutor"]


class RuntimeRiskLimitProvider(Protocol):
    """Expose one immutable process-wide entry-limit snapshot."""

    def get_snapshot(self) -> RuntimeRiskLimits:
        """Return the current runtime entry limits."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class RuntimeLimitedAutonomousLiveTradingCycleExecutor(
    AutonomousLiveTradingCycleExecutor
):
    """Use one durable runtime capacity authority for global discovery."""

    runtime_risk_limit_provider: RuntimeRiskLimitProvider

    def _portfolio_is_full(self, *, portfolio: LiveRuntimePortfolioContext) -> bool:
        """Read current capacity from the same runtime limit authority."""
        limits = self.runtime_risk_limit_provider.get_snapshot()
        return len(portfolio.contexts) >= limits.max_open_positions
