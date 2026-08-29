"""Binance Futures client with authoritative position configuration enrichment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Final

from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient as BaseBinanceFuturesExchangeClient,
)
from botragram.models import Position

__all__ = ["BinanceFuturesExchangeClient"]

_POSITIONS_ENDPOINT: Final[str] = "/fapi/v3/positionRisk"
_SYMBOL_CONFIG_ENDPOINT: Final[str] = "/fapi/v1/symbolConfig"
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


class BinanceFuturesExchangeClient(BaseBinanceFuturesExchangeClient):
    """Compose V3 position state with authoritative per-symbol configuration."""

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return non-zero Futures positions with authoritative venue leverage."""
        params: dict[str, str] | None = None
        if symbol is not None:
            params = {"symbol": self._normalize_symbol(symbol)}

        payload = await self._rest.get(
            _POSITIONS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        raw_positions = tuple(
            self._require_mapping(item) for item in self._require_sequence(payload)
        )
        active_positions = tuple(
            self._mapper.map_position(position)
            for position in raw_positions
            if Decimal(str(position.get("positionAmt", "0"))) != _DECIMAL_ZERO
        )
        if not active_positions:
            return ()

        symbols = frozenset(position.symbol.upper() for position in active_positions)
        leverage_by_symbol = await self._get_position_leverages(
            symbols=symbols,
            requested_symbol=(
                self._normalize_symbol(symbol) if symbol is not None else None
            ),
        )
        return tuple(
            replace(
                position,
                leverage=leverage_by_symbol[position.symbol.upper()],
            )
            for position in active_positions
        )

    async def _get_position_leverages(
        self,
        *,
        symbols: frozenset[str],
        requested_symbol: str | None,
    ) -> dict[str, int]:
        """Read current initial leverage from Binance's configuration endpoint."""
        params = (
            {"symbol": requested_symbol}
            if requested_symbol is not None
            else None
        )
        payload = await self._rest.get(
            _SYMBOL_CONFIG_ENDPOINT,
            params=params,
            authenticated=True,
        )
        leverage_by_symbol: dict[str, int] = {}
        for item in self._require_sequence(payload):
            configuration = self._require_mapping(item)
            raw_symbol = configuration.get("symbol")
            if not isinstance(raw_symbol, str):
                raise RuntimeError("Binance Futures symbol configuration is invalid")
            normalized_symbol = self._normalize_symbol(raw_symbol)
            if normalized_symbol not in symbols:
                continue

            leverage = configuration.get("leverage")
            if (
                isinstance(leverage, bool)
                or not isinstance(leverage, int)
                or leverage <= 0
            ):
                raise RuntimeError("Binance Futures symbol leverage is invalid")
            if normalized_symbol in leverage_by_symbol:
                raise RuntimeError(
                    "Binance Futures symbol configuration is ambiguous"
                )
            leverage_by_symbol[normalized_symbol] = leverage

        missing_symbols = symbols - leverage_by_symbol.keys()
        if missing_symbols:
            rendered = ", ".join(sorted(missing_symbols))
            raise RuntimeError(
                "Binance Futures symbol configuration is missing for active "
                f"positions: {rendered}"
            )
        return leverage_by_symbol
