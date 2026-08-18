"""Authoritative portfolio and balance risk evaluation for one LIVE signal."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from botragram.engine import TradingEngine
from botragram.models import LiveEntryRiskEvaluation, Position, Signal

__all__ = ["LiveEntryRiskEvaluationService"]


_DECIMAL_ZERO = Decimal("0")


class _LiveAccountBalanceProvider(Protocol):
    """Provide the current LIVE balance for risk evaluation."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return free balance for one quote asset."""
        ...


class _LivePositionPortfolioProvider(Protocol):
    """Provide the current authoritative LIVE position portfolio."""

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return current positions with optional exchange synchronization."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveEntryRiskEvaluationService:
    """Evaluate one signal against a fresh authoritative LIVE portfolio."""

    account_service: _LiveAccountBalanceProvider
    position_service: _LivePositionPortfolioProvider
    trading_engine: TradingEngine
    balance_asset: str

    def __post_init__(self) -> None:
        """Normalize and validate the balance asset boundary."""
        normalized_asset = self.balance_asset.strip().upper()

        if not normalized_asset:
            raise ValueError("LIVE entry balance asset must not be empty")

        object.__setattr__(self, "balance_asset", normalized_asset)

    async def evaluate(self, *, signal: Signal) -> LiveEntryRiskEvaluation:
        """Return a fresh portfolio-aware decision for the exact signal."""
        positions = await self.position_service.get_all(synchronize=True)
        has_existing_position = any(
            position.symbol.upper() == signal.symbol.upper()
            and position.quantity > _DECIMAL_ZERO
            for position in positions
        )
        balance = await self.account_service.get_free_balance(asset=self.balance_asset)
        decision = self.trading_engine.evaluate(
            signal=signal,
            account_balance=balance,
            has_open_position=has_existing_position,
            open_positions=positions,
        )

        return LiveEntryRiskEvaluation(
            decision=decision,
            has_existing_position=has_existing_position,
        )
