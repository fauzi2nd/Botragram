"""
Botragram

Description:
    Shared state exposed to Telegram handlers.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    Interval,
    MarketType,
    StrategyType,
)
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    Order,
    Position,
    RuntimeRiskLimits,
    Trade,
)

__all__ = [
    "ALLOWED_CHAT_IDS_KEY",
    "BOT_CONTEXT_KEY",
    "MARKET_SEARCH_PENDING_KEY",
    "BotContext",
    "BotExecutionAuthorizationProvider",
    "BotMarketTypeSwitcher",
    "BotQueryProvider",
    "BotRuntimeControl",
    "BotRuntimeRiskLimitProvider",
]

BOT_CONTEXT_KEY: Final[str] = "bot_context"
ALLOWED_CHAT_IDS_KEY: Final[str] = "allowed_chat_ids"
MARKET_SEARCH_PENDING_KEY: Final[str] = "market_search_pending"


class BotQueryProvider(Protocol):
    """Read current application data for Telegram views."""

    async def get_positions(self) -> Sequence[Position]:
        """Return active positions."""
        ...

    async def get_trading_symbols(self) -> Sequence[str]:
        """Return exchange-supported active market symbols."""
        ...

    async def get_available_balance(self) -> Decimal:
        """Return the mode-appropriate available portfolio balance."""
        ...

    async def get_latest_trades(self, *, limit: int) -> Sequence[Trade]:
        """Return recent persisted fills."""
        ...

    async def get_latest_orders(self, *, limit: int) -> Sequence[Order]:
        """Return recent persisted orders."""
        ...

    async def get_last_price(self) -> Decimal:
        """Return the latest available market price."""
        ...

    def get_live_runtime_health(self) -> LiveRuntimeHealthSnapshot | None:
        """Return a read-only runtime health snapshot when available."""
        ...

    async def get_autonomous_live_recovery(
        self,
    ) -> AutonomousLiveRecoverySnapshot | None:
        """Return durable autonomous recovery state when available."""
        ...

    def is_stream_transport_connected(self) -> bool:
        """Return whether the exchange WebSocket transport is ready."""
        ...

    async def start_market_stream(self) -> bool:
        """Start ticker subscription for the selected symbol."""
        ...

    async def wait_for_first_stream_tick(
        self,
        *,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Wait briefly for the active subscription's first tick."""
        ...

    async def stop_market_stream(self) -> bool:
        """Stop the active ticker subscription."""
        ...


class BotMarketTypeSwitcher(Protocol):
    """Stage and commit safe exchange product restarts."""

    async def prepare(self, *, market_type: MarketType) -> bool:
        """Validate and stage a Spot or Futures switch."""
        ...

    def commit(self, *, market_type: MarketType) -> None:
        """Commit a prepared switch after its Telegram acknowledgement."""
        ...

    @property
    def current_execution_policy(self) -> ExecutionPolicy:
        """Return the execution workflow owned by this runtime session."""
        ...

    def available_execution_policies(self) -> tuple[ExecutionPolicy, ...]:
        """Return workflows allowed by the immutable boot capability envelope."""
        ...

    async def prepare_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> bool:
        """Validate and stage a safe execution-policy session replacement."""
        ...

    def commit_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> None:
        """Commit a prepared execution-policy replacement."""
        ...


class BotRuntimeControl(Protocol):
    """Pause and resume future trading cycles."""

    @property
    def is_paused(self) -> bool:
        """Return whether trading cycles are paused."""
        ...

    def pause(self) -> bool:
        """Pause and return whether state changed."""
        ...

    def resume(self) -> bool:
        """Resume and return whether state changed."""
        ...

    def resume_global_cycle(self) -> bool:
        """Resume an already-authorized autonomous global workflow."""
        ...

    @property
    def runtime_contexts(self) -> tuple[LiveRuntimePositionContext, ...]:
        """Return the canonical managed LIVE runtime contexts."""
        ...

    @property
    def is_position_protection_ready(self) -> bool:
        """Return whether the LIVE position-protection gate is ready."""
        ...

    @property
    def symbol(self) -> str:
        """Return the symbol selected for future cycles."""
        ...

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy selected for future cycles."""
        ...

    @property
    def stream_enabled(self) -> bool:
        """Return whether a market subscription is active."""
        ...

    @property
    def interval(self) -> Interval:
        """Return the interval selected for future cycles."""
        ...

    @property
    def market_type(self) -> MarketType:
        """Return the configured exchange product family."""
        ...

    def confirm_exchange(self, exchange_type: ExchangeType) -> bool:
        """Confirm the exchange connector loaded for this process."""
        ...

    def select_symbol(self, symbol: str) -> bool:
        """Select a trading symbol while paused."""
        ...

    def select_strategy(self, strategy_type: StrategyType) -> bool:
        """Select a strategy while paused."""
        ...

    def select_interval(self, interval: Interval) -> bool:
        """Select a candle interval while paused."""
        ...

    def get_missing_startup_requirements(self) -> tuple[str, ...]:
        """Return selections or stream state still blocking startup."""
        ...

    def get_missing_configuration_requirements(self) -> tuple[str, ...]:
        """Return manual selections required before stream startup."""
        ...


class BotRuntimeRiskLimitProvider(Protocol):
    """Read and durably update autonomous LIVE runtime entry limits."""

    @property
    def max_open_positions_ceiling(self) -> int:
        """Return the immutable environment capacity ceiling."""
        ...

    @property
    def max_position_size_usdt_ceiling(self) -> Decimal:
        """Return the immutable environment notional ceiling."""
        ...

    def get_snapshot(self) -> RuntimeRiskLimits:
        """Return the current immutable runtime limits."""
        ...

    async def update(
        self,
        *,
        max_open_positions: int,
        max_position_size_usdt: Decimal,
        updated_by: str,
    ) -> RuntimeRiskLimits:
        """Durably replace runtime entry limits."""
        ...


class BotExecutionAuthorizationProvider(Protocol):
    """Consume prepared PAPER authorizations for Telegram callbacks."""

    async def get(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorization | None:
        """Return one prepared authorization by opaque identifier."""
        ...

    async def approve(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorizationOutcome:
        """Approve and revalidate one prepared authorization."""
        ...

    async def reject(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorizationOutcome:
        """Reject one prepared authorization without execution."""
        ...


@dataclass(slots=True, kw_only=True)
class BotContext:
    """Store the application state displayed by Telegram handlers."""

    is_running: bool = False
    trade_mode: str = "PAPER"
    execution_policy: ExecutionPolicy = ExecutionPolicy.SINGLE_SYMBOL
    symbol: str = "BTCUSDT"
    strategy_name: str = "EMA_CROSS"
    configured_interval: Interval = Interval.M15
    exchange_type: str = "BINANCE"
    last_price: Decimal = Decimal("0")
    positions: tuple[Position, ...] = ()
    query_provider: BotQueryProvider | None = None
    runtime_control: BotRuntimeControl | None = None
    market_type_switcher: BotMarketTypeSwitcher | None = None
    execution_authorization_service: BotExecutionAuthorizationProvider | None = None
    runtime_risk_limit_service: BotRuntimeRiskLimitProvider | None = None

    @property
    def is_discovery_workflow(self) -> bool:
        """Return whether symbol selection is owned by a discovery workflow."""
        return (
            self.execution_policy is not ExecutionPolicy.SINGLE_SYMBOL
            or self.is_autonomous_live
        )

    @property
    def is_autonomous_live(self) -> bool:
        """Return whether the active workflow is autonomous LIVE discovery."""
        if self.execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE:
            return True
        # Compatibility for older adapter tests/contexts created before the
        # execution-policy field existed. Production composition sets it explicitly.
        return (
            self.execution_policy is ExecutionPolicy.SINGLE_SYMBOL
            and self.trade_mode.strip().upper() == "LIVE"
            and self.runtime_risk_limit_service is not None
        )

    @property
    def market_type(self) -> MarketType:
        """Return the runtime market type or the safe Spot default."""
        control = self.runtime_control
        return control.market_type if control is not None else MarketType.SPOT
