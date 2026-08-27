"""Authoritative portfolio and balance risk evaluation for one LIVE signal."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Protocol

from botragram.engine import TradingEngine
from botragram.models import LiveEntryRiskEvaluation, Position, RuntimeRiskLimits, Signal
from botragram.services.live_account_drawdown_service import (
    LiveAccountDrawdownService,
)

__all__ = ["LiveEntryRiskEvaluationService"]

_DECIMAL_ZERO = Decimal("0")


class _LiveAccountBalanceProvider(Protocol):
    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return free balance for one quote asset."""
        ...


class _LiveAccountEquityProvider(Protocol):
    async def get_equity(self, *, asset: str) -> Decimal:
        """Return current account equity including unrealized PnL."""
        ...


class _LivePositionPortfolioProvider(Protocol):
    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return current positions with optional exchange synchronization."""
        ...


class _LiveNaturalExitRecovery(Protocol):
    async def reconcile(self) -> None:
        """Remove proven orphan protection or fail closed."""
        ...


class _RuntimeRiskLimitProvider(Protocol):
    def get_snapshot(self) -> RuntimeRiskLimits:
        """Return the current immutable runtime entry limits."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveEntryRiskEvaluationService:
    """Evaluate one signal against a fresh authoritative LIVE portfolio."""

    account_service: _LiveAccountBalanceProvider
    position_service: _LivePositionPortfolioProvider
    trading_engine: TradingEngine
    balance_asset: str
    equity_provider: _LiveAccountEquityProvider | None = None
    drawdown_service: LiveAccountDrawdownService | None = None
    natural_exit_recovery_service: _LiveNaturalExitRecovery | None = None
    runtime_risk_limit_provider: _RuntimeRiskLimitProvider | None = None

    def __post_init__(self) -> None:
        """Normalize and validate the balance asset boundary."""
        normalized_asset = self.balance_asset.strip().upper()
        if not normalized_asset:
            raise ValueError("LIVE entry balance asset must not be empty")
        object.__setattr__(self, "balance_asset", normalized_asset)
        if (self.equity_provider is None) is not (self.drawdown_service is None):
            raise ValueError(
                "LIVE drawdown evaluation requires both an equity provider and service"
            )

    async def evaluate(
        self,
        *,
        signal: Signal,
        entry_price_override: Decimal | None = None,
    ) -> LiveEntryRiskEvaluation:
        """Return a fresh portfolio-aware decision for the exact signal."""
        evaluation_signal = self._get_evaluation_signal(
            signal=signal,
            entry_price_override=entry_price_override,
        )
        runtime_limits = (
            self.runtime_risk_limit_provider.get_snapshot()
            if self.runtime_risk_limit_provider is not None
            else None
        )
        if self.natural_exit_recovery_service is not None:
            await self.natural_exit_recovery_service.reconcile()

        positions = await self.position_service.get_all(synchronize=True)
        has_existing_position = any(
            position.symbol.upper() == signal.symbol.upper()
            and position.quantity > _DECIMAL_ZERO
            for position in positions
        )
        balance = await self.account_service.get_free_balance(asset=self.balance_asset)
        current_drawdown_pct = _DECIMAL_ZERO
        equity_provider = self.equity_provider
        drawdown_service = self.drawdown_service
        if equity_provider is not None and drawdown_service is not None:
            current_drawdown_pct = await drawdown_service.get_current_drawdown_pct(
                equity=await equity_provider.get_equity(asset=self.balance_asset)
            )
        decision = self.trading_engine.evaluate(
            signal=evaluation_signal,
            account_balance=balance,
            current_drawdown_pct=current_drawdown_pct,
            has_open_position=has_existing_position,
            open_positions=positions,
            max_open_positions=(
                runtime_limits.max_open_positions
                if runtime_limits is not None
                else None
            ),
            max_position_size_usdt=(
                runtime_limits.max_position_size_usdt
                if runtime_limits is not None
                else None
            ),
        )
        if entry_price_override is not None:
            decision = replace(decision, signal=signal)

        return LiveEntryRiskEvaluation(
            decision=decision,
            has_existing_position=has_existing_position,
        )

    @staticmethod
    def _get_evaluation_signal(
        *,
        signal: Signal,
        entry_price_override: Decimal | None,
    ) -> Signal:
        if entry_price_override is None:
            return signal
        if (
            not entry_price_override.is_finite()
            or entry_price_override <= _DECIMAL_ZERO
        ):
            raise ValueError("LIVE entry price override must be finite and positive")
        return replace(signal, price=entry_price_override)
