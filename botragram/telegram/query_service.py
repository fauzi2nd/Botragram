"""Read-only live data provider for Telegram commands."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic
from typing import Final, Protocol

from botragram.enums import Interval, StrategyType
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    Order,
    Position,
    Ticker,
    Trade,
)
from botragram.repositories import OrderRepository, PositionRepository, TradeRepository
from botragram.services.live_market_stream_service import (
    LiveMarketStreamService,
    MarketTickListener,
)

__all__ = ["MarketTickListener", "TelegramQueryService"]


_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_SYMBOL_CACHE_SECONDS: Final[float] = 300.0
_FIRST_TICK_TIMEOUT_SECONDS: Final[float] = 5.0
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class MarketTickerProvider(Protocol):
    """Read the latest ticker for one market."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a normalized ticker."""
        ...

    async def get_trading_symbols(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[str]:
        """Return active symbols for one quote asset."""
        ...

    @property
    def is_stream_connected(self) -> bool:
        """Return whether the WebSocket transport is ready."""
        ...


class PaperBalanceProvider(Protocol):
    """Read reconstructed paper balance."""

    async def get_available_balance(self) -> Decimal:
        """Return available paper funds."""
        ...


class LiveBalanceProvider(Protocol):
    """Read normalized LIVE exchange balance."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return free exchange funds for one asset."""
        ...


class RuntimeSymbolProvider(Protocol):
    """Expose the currently selected runtime symbol."""

    @property
    def symbol(self) -> str:
        """Return the current normalized symbol."""
        ...

    @property
    def interval(self) -> Interval:
        """Return the selected market interval."""
        ...

    @property
    def strategy_type(self) -> StrategyType:
        """Return the selected trading strategy."""
        ...


class LiveRuntimeHealthProvider(Protocol):
    """Read immutable recovered LIVE runtime health for presentation."""

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return the current read-only operational health snapshot."""
        ...


class AutonomousLiveRecoveryObservabilityProvider(Protocol):
    """Read durable autonomous recovery state for presentation only."""

    async def get_snapshot(self) -> AutonomousLiveRecoverySnapshot:
        """Return a read-only durable recovery snapshot."""
        ...


@dataclass(slots=True, kw_only=True)
class TelegramQueryService:
    """Query current paper portfolio and market state without mutation."""

    symbol: str
    market_service: MarketTickerProvider
    paper_trading_service: PaperBalanceProvider
    position_repository: PositionRepository
    trade_repository: TradeRepository
    order_repository: OrderRepository
    market_stream_service: LiveMarketStreamService
    live_balance_provider: LiveBalanceProvider | None = None
    quote_asset: str = "USDT"
    interval: Interval = Interval.M15
    strategy_type: StrategyType = StrategyType.EMA_CROSS
    runtime_control: RuntimeSymbolProvider | None = None
    live_runtime_health_service: LiveRuntimeHealthProvider | None = None
    autonomous_live_recovery_observability_service: (
        AutonomousLiveRecoveryObservabilityProvider | None
    ) = None
    _trading_symbols: tuple[str, ...] = field(default=(), init=False, repr=False)
    _symbols_expire_monotonic: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Normalize the configured trading symbol."""
        normalized_symbol = self.symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Telegram query symbol must not be empty")

        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Telegram quote asset must not be empty")

        self.symbol = normalized_symbol
        self.quote_asset = normalized_quote_asset

    async def get_positions(self) -> Sequence[Position]:
        """Return all persisted active paper positions."""
        return await self.position_repository.get_open_positions()

    def get_live_runtime_health(self) -> LiveRuntimeHealthSnapshot | None:
        """Return the read-only recovered LIVE runtime health when configured."""
        service = self.live_runtime_health_service
        return service.get_snapshot() if service is not None else None

    async def get_autonomous_live_recovery(
        self,
    ) -> AutonomousLiveRecoverySnapshot | None:
        """Return durable autonomous recovery status without reconciliation."""
        service = self.autonomous_live_recovery_observability_service
        return await service.get_snapshot() if service is not None else None

    async def get_trading_symbols(self) -> Sequence[str]:
        """Return cached exchange-supported symbols for the quote asset."""
        now = monotonic()

        if self._trading_symbols and now < self._symbols_expire_monotonic:
            return self._trading_symbols

        symbols = tuple(
            await self.market_service.get_trading_symbols(
                quote_asset=self.quote_asset,
            )
        )

        if not symbols:
            raise RuntimeError(
                f"Exchange returned no active {self.quote_asset} trading symbols"
            )

        self._trading_symbols = symbols
        self._symbols_expire_monotonic = now + _SYMBOL_CACHE_SECONDS
        return symbols

    async def get_available_balance(self) -> Decimal:
        """Return the mode-appropriate available portfolio balance."""
        live_provider = self.live_balance_provider
        if live_provider is not None:
            return await live_provider.get_free_balance(asset=self.quote_asset)
        return await self.paper_trading_service.get_available_balance()

    async def get_latest_trades(self, *, limit: int) -> Sequence[Trade]:
        """Return the latest persisted paper fills."""
        if limit <= 0:
            raise ValueError("Telegram trade history limit must be greater than zero")

        count = await self.trade_repository.count()

        if count == 0:
            return ()

        return await self.trade_repository.get_latest(limit=min(limit, count))

    async def get_latest_orders(self, *, limit: int) -> Sequence[Order]:
        """Return the latest persisted paper orders."""
        if limit <= 0:
            raise ValueError("Telegram order history limit must be greater than zero")

        count = await self.order_repository.count()

        if count == 0:
            return ()

        return await self.order_repository.get_latest(limit=min(limit, count))

    async def get_last_price(self) -> Decimal:
        """Return public ticker price, falling back to a persisted position mark."""
        stream_state = self._get_singular_stream_state()
        symbol = (
            stream_state.identity.symbol
            if stream_state is not None
            else self._get_runtime_context().symbol
        )

        if stream_state is not None and stream_state.last_price is not None:
            return stream_state.last_price

        try:
            ticker = await self.market_service.get_ticker(symbol=symbol)
            return ticker.last_price
        except Exception:
            _LOGGER.exception(
                "Live ticker unavailable for Telegram status: symbol=%s",
                symbol,
            )

        position = await self.position_repository.get_by_symbol(symbol=symbol)
        return position.current_price if position is not None else _DECIMAL_ZERO

    def is_stream_transport_connected(self) -> bool:
        """Return transport readiness without claiming an active subscription."""
        return self.market_service.is_stream_connected

    async def start_market_stream(self) -> bool:
        """Delegate one selected ticker subscription to the stream owner."""
        context = self._get_runtime_context()
        identity = LiveMarketStreamIdentity.from_runtime_context(context=context)
        existing_stream = self._get_singular_stream_state()

        if existing_stream is not None:
            if existing_stream.identity != identity:
                raise RuntimeError(
                    "Cannot start a Telegram market stream while another stream "
                    "identity is owned"
                )
            return False

        await self.market_stream_service.start(context=context)
        _LOGGER.info("Telegram market stream delegated: symbol=%s", identity.symbol)
        return True

    async def wait_for_first_stream_tick(
        self,
        *,
        timeout_seconds: float = _FIRST_TICK_TIMEOUT_SECONDS,
    ) -> bool:
        """Delegate first-tick readiness to the singular stream owner."""
        stream_state = self._get_singular_stream_state()

        if stream_state is None:
            return False

        return await self.market_stream_service.wait_for_first_tick(
            identity=stream_state.identity,
            timeout_seconds=timeout_seconds,
        )

    async def stop_market_stream(self) -> bool:
        """Delegate singular stream stop to the stream lifecycle owner."""
        stream_state = self._get_singular_stream_state()

        if stream_state is None:
            return False

        return await self.market_stream_service.stop(identity=stream_state.identity)

    async def close(self) -> None:
        """Release Telegram resources without owning stream shutdown."""

    def _get_singular_stream_state(self) -> LiveMarketStreamState | None:
        """Return exactly one owner state or reject ambiguous compatibility use."""
        states = self.market_stream_service.stream_states

        if not states:
            return None

        if len(states) != 1:
            raise RuntimeError(
                "Telegram singular stream compatibility is unavailable for "
                "multiple owned streams"
            )

        return states[0]

    def _get_runtime_context(self) -> LiveRuntimePositionContext:
        """Build the selected singular runtime context for stream delegation."""
        runtime_control = self.runtime_control

        return LiveRuntimePositionContext(
            symbol=runtime_control.symbol
            if runtime_control is not None
            else self.symbol,
            interval=(
                runtime_control.interval
                if runtime_control is not None
                else self.interval
            ),
            strategy_type=(
                runtime_control.strategy_type
                if runtime_control is not None
                else self.strategy_type
            ),
        )
