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

from botragram.config.risk_settings import RiskSettings
from botragram.config.strategy_settings import StrategySettings
from botragram.constants.strategy import get_strategy_default_exit_rates
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
    OperatorExitConfirmation,
    OperatorExitSnapshot,
    Order,
    Position,
    RuntimeRiskLimits,
    Trade,
)
from botragram.services.live_trading_performance_service import (
    TradingPerformanceSnapshot,
)

__all__ = [
    "ALLOWED_CHAT_IDS_KEY",
    "BOT_CONTEXT_KEY",
    "MARKET_SEARCH_PENDING_KEY",
    "BotContext",
    "BotExecutionAuthorizationProvider",
    "BotMarketTypeSwitcher",
    "BotOperatorExitProvider",
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

    async def get_trading_performance(self) -> TradingPerformanceSnapshot | None:
        """Return a read-only trading performance snapshot when available."""
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

    async def prepare_exchange(self, *, exchange_type: ExchangeType) -> bool:
        """Validate and stage an exchange connector switch."""
        ...

    def commit_exchange(self, *, exchange_type: ExchangeType) -> None:
        """Commit a prepared exchange switch after its Telegram acknowledgement."""
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
    def configured_strategy_type(self) -> StrategyType:
        """Return the process-configured strategy without position context override."""
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

    @property
    def leverage(self) -> int:
        """Return the leverage selected for future cycles."""
        ...

    def select_leverage(self, leverage: int) -> bool:
        """Select leverage while paused."""
        ...

    @property
    def dynamic_leverage_enabled(self) -> bool:
        """Return whether dynamic adaptive leverage is active."""
        ...

    def select_dynamic_leverage(self, enabled: bool) -> bool:
        """Select dynamic leverage mode while paused."""
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


class BotOperatorExitProvider(Protocol):
    """Expose the bounded operator-exit application service to Telegram."""

    async def get_snapshot(self) -> OperatorExitSnapshot:
        """Return truthful durable operator-exit state."""
        ...

    async def get_positions(self) -> tuple[Position, ...]:
        """Return mode-appropriate authoritative positions."""
        ...

    async def request_close_position(
        self,
        *,
        symbol: str,
        requested_by: str,
        auto_pause: bool = False,
    ) -> OperatorExitConfirmation:
        """Create one close-position confirmation without fund mutation."""
        ...

    async def request_close_all(
        self,
        *,
        requested_by: str,
        target_execution_policy: ExecutionPolicy | None = None,
        auto_pause: bool = False,
    ) -> OperatorExitConfirmation:
        """Create one flatten or flatten-and-switch confirmation."""
        ...

    async def confirm(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
        token: str | None = None,
    ) -> OperatorExitSnapshot:
        """Confirm one exact pending operator action."""
        ...

    async def cancel_confirmation(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
    ) -> None:
        """Cancel one exact pending operator action without fund mutation."""
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
    leverage: int = 1
    leverage_ceiling: int = 50
    dynamic_leverage_enabled: bool = False
    stop_loss_pct: Decimal = Decimal("0.01")
    take_profit_pct: Decimal = Decimal("0.02")
    query_provider: BotQueryProvider | None = None

    runtime_control: BotRuntimeControl | None = None
    market_type_switcher: BotMarketTypeSwitcher | None = None
    execution_authorization_service: BotExecutionAuthorizationProvider | None = None
    runtime_risk_limit_service: BotRuntimeRiskLimitProvider | None = None
    operator_exit_service: BotOperatorExitProvider | None = None
    risk_settings: RiskSettings | None = None
    strategy_settings: StrategySettings | None = None

    @property
    def active_interval(self) -> Interval:
        """Return the active candle interval from runtime control or config."""
        control = self.runtime_control
        if control is not None:
            try:
                return control.interval
            except RuntimeError:
                return self.configured_interval
        return self.configured_interval

    def get_strategy_exit_rates(
        self,
        strategy_type: StrategyType,
    ) -> tuple[Decimal, Decimal]:
        """Resolve strategy-specific exit rates from settings or defaults."""
        settings = self.risk_settings
        if settings is None:
            return get_strategy_default_exit_rates(strategy_type)

        match strategy_type:
            case (
                StrategyType.EMA_SCALPING
                | StrategyType.RSI_BB_SCALPING
                | StrategyType.VWAP_BREAKOUT
            ):
                return (
                    settings.scalping_stop_loss_pct,
                    settings.scalping_take_profit_pct,
                )
            case StrategyType.EMA_CROSS:
                return (
                    settings.ema_cross_stop_loss_pct,
                    settings.ema_cross_take_profit_pct,
                )
            case (
                StrategyType.EMA_RSI
                | StrategyType.ICHIMOKU_CLOUD
                | StrategyType.SUPERTREND
                | StrategyType.ADX_TREND
                | StrategyType.BOLLINGER_BREAKOUT
            ):
                return (
                    settings.trend_stop_loss_pct,
                    settings.trend_take_profit_pct,
                )
            case StrategyType.MACD_SWING:
                return (
                    settings.swing_stop_loss_pct,
                    settings.swing_take_profit_pct,
                )
            case StrategyType.PINBAR_ENGULFING_EMA_RSI:
                return (
                    settings.pier_stop_loss_pct,
                    settings.pier_take_profit_pct,
                )
            case StrategyType.BOTRAGRAM_ORIGIN:
                return (
                    settings.origin_stop_loss_pct,
                    settings.origin_take_profit_pct,
                )

            case (
                StrategyType.HIGH_CONFLUENCE_EXHAUSTION
                | StrategyType.CHOCH_FVG
                | StrategyType.LIQUIDITY_SWEEP_EXHAUSTION
                | StrategyType.CHOCH_RSI_BB_HYBRID
                | StrategyType.MORPH
                | StrategyType.NY_4H_RANGE_SCALPING
                | StrategyType.QUAD_CONFLUENCE
            ):
                return get_strategy_default_exit_rates(strategy_type)
            case _:
                return settings.stop_loss_pct, settings.take_profit_pct

    def get_strategy_risk_reward_ratio(
        self,
        strategy_type: StrategyType,
    ) -> Decimal:
        """Resolve strategy-specific Target Risk-Reward Ratio."""
        if self.strategy_settings is not None:
            match strategy_type:
                case StrategyType.BOTRAGRAM_ORIGIN:
                    return self.strategy_settings.origin_risk_reward_ratio
                case StrategyType.MORPH:
                    return self.strategy_settings.morph_risk_reward_ratio
                case StrategyType.NY_4H_RANGE_SCALPING:
                    return self.strategy_settings.ny_range_risk_reward_ratio
                case StrategyType.PINBAR_ENGULFING_EMA_RSI:
                    return self.strategy_settings.pier_risk_reward_ratio
                case _:
                    pass
        sl, tp = self.get_strategy_exit_rates(strategy_type)
        if sl > Decimal("0"):
            return tp / sl
        return Decimal("2.0")

    def format_strategy_message(
        self,
        strategy_name: str,
        fast_period: int = 9,
        slow_period: int = 21,
        *,
        confirmed: bool = False,
    ) -> str:
        """Return strategy details formatted with active interval and RRR."""
        from botragram.telegram.messages import get_strategy_message

        try:
            strategy_type = StrategyType(strategy_name.casefold())
        except ValueError:
            strategy_type = None

        sl_pct, tp_pct = (
            self.get_strategy_exit_rates(strategy_type)
            if strategy_type is not None
            else (None, None)
        )
        rrr = (
            self.get_strategy_risk_reward_ratio(strategy_type)
            if strategy_type is not None
            else None
        )
        return get_strategy_message(
            strategy_name,
            fast_period,
            slow_period,
            confirmed=confirmed,
            active_interval=self.active_interval,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            risk_reward_ratio=rrr,
        )

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
