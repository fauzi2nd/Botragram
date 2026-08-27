"""Cooperative trading runtime pause and resume control."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic

from botragram.enums import ExchangeType, Interval, MarketType, StrategyType
from botragram.models import (
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePortfolioContext,
    LiveRuntimePositionContext,
)

__all__ = [
    "MarketStreamTelemetry",
    "TradingRuntimeControl",
]


@dataclass(slots=True, kw_only=True, frozen=True)
class MarketStreamTelemetry:
    """Immutable snapshot of local market-stream activity."""

    enabled: bool
    event_count: int
    last_price: Decimal | None
    last_event_monotonic: float | None


@dataclass(slots=True, kw_only=True)
class TradingRuntimeControl:
    """Coordinate pause/resume state without cancelling application resources."""

    exchange_type: ExchangeType = ExchangeType.BINANCE
    market_type: MarketType = MarketType.SPOT
    symbol: str = "BTCUSDT"
    interval: Interval = Interval.M15
    strategy_type: StrategyType = StrategyType.EMA_CROSS
    stream_enabled: bool = False
    _exchange_confirmed: bool = field(default=False, init=False, repr=False)
    _market_type_confirmed: bool = field(default=False, init=False, repr=False)
    _symbol_confirmed: bool = field(default=False, init=False, repr=False)
    _interval_confirmed: bool = field(default=False, init=False, repr=False)
    _strategy_confirmed: bool = field(default=False, init=False, repr=False)
    _position_protection_ready: bool = field(default=True, init=False, repr=False)
    _cycle_in_progress: bool = field(default=False, init=False, repr=False)
    _risk_limit_change_in_progress: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _stream_event_count: int = field(default=0, init=False, repr=False)
    _stream_last_price: Decimal | None = field(default=None, init=False, repr=False)
    _stream_last_event_monotonic: float | None = field(
        default=None,
        init=False,
        repr=False,
    )

    _active_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )
    _strategy_selector: Callable[[StrategyType], None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _runtime_contexts: tuple[LiveRuntimePositionContext, ...] = field(
        default=(),
        init=False,
        repr=False,
    )
    _live_management_authorization: (
        LiveRecoveredPositionManagementAuthorization | None
    ) = field(default=None, init=False, repr=False)
    _reconciliation_required_context: LiveRuntimePositionContext | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize settings and remain paused for Telegram configuration."""
        self.symbol = self._normalize_symbol(self.symbol)

    def __getattribute__(self, name: str) -> object:
        """Reject ambiguous legacy runtime access when multiple contexts exist."""
        if name in {"symbol", "interval", "strategy_type"}:
            contexts = object.__getattribute__(self, "_runtime_contexts")
            if len(contexts) > 1:
                raise RuntimeError(
                    "Singular runtime configuration is unavailable for multiple "
                    "runtime contexts"
                )
            if len(contexts) == 1:
                return getattr(contexts[0], name)
        return object.__getattribute__(self, name)

    @property
    def runtime_contexts(self) -> tuple[LiveRuntimePositionContext, ...]:
        """Return the immutable canonical recovered runtime portfolio context."""
        return self._runtime_contexts

    @property
    def live_management_authorization(
        self,
    ) -> LiveRecoveredPositionManagementAuthorization | None:
        """Return the exact process-local recovered LIVE capability, if installed."""
        return self._live_management_authorization

    @property
    def reconciliation_required_context(self) -> LiveRuntimePositionContext | None:
        """Return the exact recovered context requiring portfolio reconciliation."""
        return self._reconciliation_required_context

    def set_runtime_contexts(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Atomically replace the complete recovered runtime portfolio context."""
        candidate = LiveRuntimePortfolioContext(contexts=tuple(contexts))
        self._runtime_contexts = candidate.contexts
        self._reconciliation_required_context = None

        authorization = self._live_management_authorization
        if authorization is not None and authorization.contexts != candidate.contexts:
            self._live_management_authorization = None

        if len(candidate.contexts) != 1:
            self._reset_singular_runtime_state()

    def clear_runtime_contexts(self) -> None:
        """Clear recovered runtime contexts and reset singular compatibility state."""
        self.set_runtime_contexts(contexts=())

    def set_live_management_authorization(
        self,
        *,
        authorization: LiveRecoveredPositionManagementAuthorization,
    ) -> None:
        """Install an authorization only for the exact current context tuple."""
        if authorization.contexts != self._runtime_contexts:
            raise ValueError(
                "Recovered LIVE management authorization does not match runtime "
                "contexts"
            )

        self._live_management_authorization = authorization

    def clear_live_management_authorization(self) -> None:
        """Clear any process-local recovered LIVE management authorization."""
        self._live_management_authorization = None

    def require_portfolio_reconciliation(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> None:
        """Record one stale recovered context for read-only operational diagnosis."""
        if context not in self._runtime_contexts:
            raise ValueError("Reconciliation context is not part of runtime state")

        self._reconciliation_required_context = context

    @property
    def is_paused(self) -> bool:
        """Return whether new trading cycles are paused."""
        return not self._active_event.is_set()

    @property
    def is_position_protection_ready(self) -> bool:
        """Return the read-only LIVE protection gate state."""
        return self._position_protection_ready

    @property
    def risk_limit_change_in_progress(self) -> bool:
        """Return whether a durable runtime limit update owns configuration."""
        return self._risk_limit_change_in_progress

    def pause(self) -> bool:
        """Pause future cycles and return whether state changed."""
        if self.is_paused:
            return False

        self._active_event.clear()
        return True

    def resume(self) -> bool:
        """Resume future cycles and return whether state changed."""
        self._require_no_risk_limit_change()
        if not self.is_paused:
            return False

        authorization = self._live_management_authorization
        if self._runtime_contexts and authorization is not None:
            if not authorization.authorizes_contexts(
                contexts=self._runtime_contexts,
            ):
                raise RuntimeError(
                    "Managed LIVE runtime requires exact recovered LIVE "
                    "management authorization"
                )

            if not self._position_protection_ready:
                raise RuntimeError(
                    "Managed LIVE runtime requires verified position protection"
                )

            self._active_event.set()
            return True

        missing = self.get_missing_startup_requirements()

        if missing:
            raise RuntimeError(
                "Startup configuration incomplete: " + ", ".join(missing)
            )

        self._active_event.set()
        return True

    def resume_global_cycle(self) -> bool:
        """Resume an already-authorized global workflow without stream state.

        Composition is responsible for authorizing this narrow activation. The
        method intentionally does not select a runtime context or alter
        recovered-position management authorization.
        """
        self._require_no_risk_limit_change()
        if not self.is_paused:
            return False

        if not self._position_protection_ready:
            raise RuntimeError("Global runtime requires verified position protection")

        self._active_event.set()
        return True

    def begin_risk_limit_change(self) -> None:
        """Reserve one paused runtime-limit update against resume and cycles."""
        if not self.is_paused:
            raise RuntimeError("Pause trading before changing runtime risk limits")
        if self._cycle_in_progress:
            raise RuntimeError("Wait for the active trading cycle to finish")
        if self._risk_limit_change_in_progress:
            raise RuntimeError("A runtime risk-limit change is already in progress")
        self._risk_limit_change_in_progress = True

    def end_risk_limit_change(self) -> None:
        """Release the runtime-limit update reservation."""
        if not self._risk_limit_change_in_progress:
            raise RuntimeError("No runtime risk-limit change is in progress")
        self._risk_limit_change_in_progress = False

    def confirm_exchange(self, exchange_type: ExchangeType) -> bool:
        """Confirm the exchange connector already loaded for this process."""
        self._require_paused_configuration()

        if exchange_type is not self.exchange_type:
            raise RuntimeError(
                "Changing exchange requires selecting another environment profile "
                "and restarting Botragram"
            )

        changed = not self._exchange_confirmed
        self._exchange_confirmed = True
        return changed

    def require_configuration_change_allowed(self) -> None:
        """Raise when runtime state cannot safely change connector settings."""
        self._require_paused_configuration()

    def confirm_market_type(self, market_type: MarketType) -> bool:
        """Confirm the product family loaded by the active connector."""
        if market_type is not self.market_type:
            raise RuntimeError(
                "Requested market type does not match the active connector"
            )

        if self._market_type_confirmed:
            return False

        self._require_paused_configuration()
        self._market_type_confirmed = True
        return True

    def select_symbol(self, symbol: str) -> bool:
        """Select the symbol used by future cycles while paused."""
        self._require_paused_configuration()
        normalized = self._normalize_symbol(symbol)
        self._symbol_confirmed = True

        if normalized == self.symbol:
            return False

        self.symbol = normalized
        return True

    def select_interval(self, interval: Interval) -> bool:
        """Select the candle interval used by future cycles while paused."""
        self._require_paused_configuration()
        self._interval_confirmed = True

        if interval is self.interval:
            return False

        self.interval = interval
        return True

    def select_strategy(self, strategy_type: StrategyType) -> bool:
        """Select and apply the strategy used by future cycles while paused."""
        self._require_paused_configuration()
        self._strategy_confirmed = True

        if strategy_type is self.strategy_type:
            return False

        selector = self._strategy_selector

        if selector is None:
            raise RuntimeError("Runtime strategy selector is not configured")

        selector(strategy_type)
        self.strategy_type = strategy_type
        return True

    def get_missing_startup_requirements(self) -> tuple[str, ...]:
        """Return setup items that still prevent Telegram from starting trading."""
        missing = list(self.get_missing_configuration_requirements())

        if not self.stream_enabled:
            missing.append("stream subscription")
        elif self._stream_event_count == 0:
            missing.append("first stream tick")

        if not self._position_protection_ready:
            missing.append("position protection")

        return tuple(missing)

    def restore_configuration(
        self,
        *,
        symbol: str,
        interval: Interval,
        strategy_type: StrategyType,
    ) -> None:
        """Restore a persisted position configuration while startup is paused."""
        self.confirm_exchange(self.exchange_type)
        self.confirm_market_type(self.market_type)
        self.select_symbol(symbol)
        self.select_interval(interval)
        self.select_strategy(strategy_type)
        self.set_runtime_contexts(
            contexts=(
                LiveRuntimePositionContext(
                    symbol=symbol,
                    interval=interval,
                    strategy_type=strategy_type,
                ),
            ),
        )

    def set_position_protection_ready(self, ready: bool) -> bool:
        """Set the live-position protection gate and return whether it changed."""
        if self._position_protection_ready is ready:
            return False

        self._position_protection_ready = ready
        return True

    def get_missing_configuration_requirements(self) -> tuple[str, ...]:
        """Return manual selections required before starting the market stream."""
        missing: list[str] = []

        if not self._exchange_confirmed:
            missing.append("exchange")

        if not self._market_type_confirmed:
            missing.append("market type")

        if not self._symbol_confirmed:
            missing.append("symbol")

        if not self._interval_confirmed:
            missing.append("interval")

        if not self._strategy_confirmed:
            missing.append("strategy")

        return tuple(missing)

    def bind_strategy_selector(
        self,
        selector: Callable[[StrategyType], None],
    ) -> None:
        """Bind the application callback that atomically replaces a strategy."""
        self._strategy_selector = selector

    def set_stream_enabled(self, enabled: bool) -> bool:
        """Record whether a real market subscription is active."""
        if self.stream_enabled is enabled:
            return False

        self.stream_enabled = enabled

        if enabled:
            self._stream_event_count = 0
            self._stream_last_price = None
            self._stream_last_event_monotonic = None

        return True

    def _reset_singular_runtime_state(self) -> None:
        """Clear stream telemetry and stale legacy values without selecting context."""
        self.symbol = "BTCUSDT"
        self.interval = Interval.M15
        self.strategy_type = StrategyType.EMA_CROSS
        self._symbol_confirmed = False
        self._interval_confirmed = False
        self._strategy_confirmed = False
        self.stream_enabled = False
        self._stream_event_count = 0
        self._stream_last_price = None
        self._stream_last_event_monotonic = None

    def record_stream_tick(self, *, price: Decimal) -> None:
        """Record one validated stream event using the local monotonic clock."""
        if price <= 0:
            raise ValueError("Stream ticker price must be greater than zero")

        self._stream_event_count += 1
        self._stream_last_price = price
        self._stream_last_event_monotonic = monotonic()

    def get_stream_telemetry(self) -> MarketStreamTelemetry:
        """Return an immutable snapshot of current stream activity."""
        return MarketStreamTelemetry(
            enabled=self.stream_enabled,
            event_count=self._stream_event_count,
            last_price=self._stream_last_price,
            last_event_monotonic=self._stream_last_event_monotonic,
        )

    @property
    def cycle_in_progress(self) -> bool:
        """Return whether a trading cycle currently owns runtime settings."""
        return self._cycle_in_progress

    def begin_cycle(self) -> None:
        """Lock runtime configuration for one trading cycle."""
        if self._cycle_in_progress:
            raise RuntimeError("A trading cycle is already in progress")
        self._require_no_risk_limit_change()
        self._cycle_in_progress = True

    def end_cycle(self) -> None:
        """Release the runtime-configuration cycle lock."""
        self._cycle_in_progress = False

    async def wait_until_active(self, *, stop_event: asyncio.Event) -> bool:
        """Wait until resumed or stopped; return false when stop wins."""
        if stop_event.is_set():
            return False

        if not self.is_paused:
            return True

        active_task = asyncio.create_task(self._active_event.wait())
        stop_task = asyncio.create_task(stop_event.wait())
        tasks = (active_task, stop_task)

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        return not stop_event.is_set()

    def _require_paused_configuration(self) -> None:
        """Reject runtime configuration changes during active trading."""
        if not self.is_paused:
            raise RuntimeError("Pause trading before changing runtime settings")

        if self._cycle_in_progress:
            raise RuntimeError("Wait for the active trading cycle to finish")

        self._require_no_risk_limit_change()

        if self.stream_enabled:
            raise RuntimeError(
                "Stop the market stream before changing runtime settings"
            )

    def _require_no_risk_limit_change(self) -> None:
        """Reject activation or other configuration while a limit write is pending."""
        if self._risk_limit_change_in_progress:
            raise RuntimeError("Runtime risk-limit change is still in progress")

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize and validate a runtime trading symbol."""
        normalized = symbol.strip().upper()

        if not normalized:
            raise ValueError("Runtime trading symbol must not be empty")

        if not normalized.isalnum():
            raise ValueError("Runtime trading symbol must be alphanumeric")

        return normalized
