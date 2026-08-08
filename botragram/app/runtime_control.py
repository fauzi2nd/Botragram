"""Cooperative trading runtime pause and resume control."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic

from botragram.enums import ExchangeType, Interval, MarketType, StrategyType

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

    def __post_init__(self) -> None:
        """Normalize settings and remain paused for Telegram configuration."""
        self.symbol = self._normalize_symbol(self.symbol)

    @property
    def is_paused(self) -> bool:
        """Return whether new trading cycles are paused."""
        return not self._active_event.is_set()

    def pause(self) -> bool:
        """Pause future cycles and return whether state changed."""
        if self.is_paused:
            return False

        self._active_event.clear()
        return True

    def resume(self) -> bool:
        """Resume future cycles and return whether state changed."""
        if not self.is_paused:
            return False

        missing = self.get_missing_startup_requirements()

        if missing:
            raise RuntimeError(
                "Startup configuration incomplete: " + ", ".join(missing)
            )

        self._active_event.set()
        return True

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

        if self.stream_enabled:
            raise RuntimeError(
                "Stop the market stream before changing runtime settings"
            )

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize and validate a runtime trading symbol."""
        normalized = symbol.strip().upper()

        if not normalized:
            raise ValueError("Runtime trading symbol must not be empty")

        if not normalized.isalnum():
            raise ValueError("Runtime trading symbol must be alphanumeric")

        return normalized
