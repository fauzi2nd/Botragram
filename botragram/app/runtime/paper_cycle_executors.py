"""
Botragram

Description:
    PAPER discovery adapters for sequential trading runtime cycles.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderType, StrategyType
from botragram.models import (
    DiscoveryScanReport,
    ExecutionAuthorization,
    LiveRecoveredPositionManagementAuthorization,
    TradingDecision,
    TradingResult,
)

__all__ = [
    "AutonomousPaperTradingCycleExecutor",
    "HumanConfirmedPaperTradingCycleExecutor",
]


_PENDING_HUMAN_PAPER_APPROVAL_REASON: Final[str] = "Pending human PAPER approval"


class AutonomousPaperExecutionProvider(Protocol):
    """Execute a bounded autonomous PAPER opportunity cycle."""

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> Sequence[TradingResult]:
        """Discover and execute ranked PAPER candidates."""
        ...


class HumanConfirmedPaperExecutionProvider(Protocol):
    """Prepare bounded PAPER opportunities for explicit human approval."""

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[ExecutionAuthorization]:
        """Return newly prepared non-executed authorizations."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousPaperTradingCycleExecutor:
    """Adapt autonomous discovery to a runtime cycle with PAPER-only safety."""

    autonomous_execution_service: AutonomousPaperExecutionProvider
    quote_asset: str
    max_symbols: int
    top_n: int

    def __post_init__(self) -> None:
        """Normalize and validate static autonomous-discovery inputs."""
        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Autonomous execution quote asset must not be empty")

        if self.max_symbols <= 0:
            raise ValueError("Autonomous execution maximum symbols must be positive")

        if self.top_n <= 0:
            raise ValueError("Autonomous execution top N must be positive")

        object.__setattr__(self, "quote_asset", normalized_quote_asset)

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        strategy_type: StrategyType | None = None,
        live_management_authorization: (
            LiveRecoveredPositionManagementAuthorization | None
        ) = None,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Execute one bounded PAPER discovery cycle without order submission."""
        _ = (
            symbol,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            synchronize_position,
        )

        if submit_order:
            raise RuntimeError("Autonomous execution is restricted to paper mode")

        return await self.autonomous_execution_service.execute(
            quote_asset=self.quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
            initial_balance=account_balance_override,
        )

    @property
    def last_scan_report(self) -> DiscoveryScanReport | None:
        """Return the most recent discovery scan report if available."""
        discovery = getattr(
            self.autonomous_execution_service, "discovery_service", None
        )
        report = getattr(discovery, "last_scan_report", None)
        return report if isinstance(report, DiscoveryScanReport) else None


@dataclass(slots=True, kw_only=True, frozen=True)
class HumanConfirmedPaperTradingCycleExecutor:
    """Adapt confirmation discovery to a PAPER runtime cycle without execution."""

    human_confirmation_service: HumanConfirmedPaperExecutionProvider
    quote_asset: str
    max_symbols: int
    top_n: int

    def __post_init__(self) -> None:
        """Normalize and validate static confirmation-discovery inputs."""
        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Human confirmation quote asset must not be empty")

        if self.max_symbols <= 0:
            raise ValueError("Human confirmation maximum symbols must be positive")

        if self.top_n <= 0:
            raise ValueError("Human confirmation top N must be positive")

        object.__setattr__(self, "quote_asset", normalized_quote_asset)

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        strategy_type: StrategyType | None = None,
        live_management_authorization: (
            LiveRecoveredPositionManagementAuthorization | None
        ) = None,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Prepare human approvals while structurally rejecting order submission."""
        _ = (
            symbol,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
        )

        if submit_order:
            raise RuntimeError("Human-confirmed execution is restricted to paper mode")

        authorizations = await self.human_confirmation_service.execute(
            quote_asset=self.quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
        )
        return tuple(
            TradingResult(
                executed=False,
                decision=TradingDecision(
                    should_execute=False,
                    signal=authorization.signal,
                    risk_result=None,
                    reason=_PENDING_HUMAN_PAPER_APPROVAL_REASON,
                ),
                order=None,
                reason=_PENDING_HUMAN_PAPER_APPROVAL_REASON,
            )
            for authorization in authorizations
        )

    @property
    def last_scan_report(self) -> DiscoveryScanReport | None:
        """Return the most recent discovery scan report if available."""
        discovery = getattr(self.human_confirmation_service, "discovery_service", None)
        report = getattr(discovery, "last_scan_report", None)
        return report if isinstance(report, DiscoveryScanReport) else None
