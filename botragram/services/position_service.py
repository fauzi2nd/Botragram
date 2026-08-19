"""
Botragram

Description:
    Trading position application service.

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
from dataclasses import dataclass, replace
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import PositionEngine
from botragram.models import Position
from botragram.repositories import PositionRepository

__all__ = [
    "PositionService",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_MULTIPLE_POSITIONS_ERROR_TEMPLATE = (
    "Exchange returned multiple positions for symbol {symbol!r}"
)


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionService:
    """Manage trading positions."""

    position_engine: PositionEngine
    position_repository: PositionRepository

    async def sync(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Synchronize exchange positions into the repository.

        Args:
            symbol: Optional trading symbol filter.

        Returns:
            Synchronized positions.

        Raises:
            RuntimeError: If multiple positions are returned for one symbol.
        """
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )
        stored_positions = (
            tuple(await self.position_repository.get_all())
            if normalized_symbol is None
            else tuple(
                position
                for position in (
                    await self.position_repository.get_by_symbol(
                        symbol=normalized_symbol,
                    ),
                )
                if position is not None
            )
        )
        stored_by_symbol = {
            position.symbol.upper(): position for position in stored_positions
        }

        exchange_positions = await self.position_engine.get_positions(
            symbol=normalized_symbol,
        )
        positions = tuple(
            self._merge_local_metadata(
                exchange_position=position,
                stored_position=stored_by_symbol.get(position.symbol.upper()),
            )
            for position in exchange_positions
        )

        if normalized_symbol is not None:
            matching_position = self._find_position(
                positions=positions,
                symbol=normalized_symbol,
            )

            if matching_position is None:
                await self.position_repository.delete(
                    symbol=normalized_symbol,
                )
            else:
                await self.position_repository.save(
                    position=matching_position,
                )

            return positions

        await self.position_repository.delete_all()

        if positions:
            await self.position_repository.save_many(
                positions=positions,
            )

        return positions

    @staticmethod
    def _merge_local_metadata(
        *,
        exchange_position: Position,
        stored_position: Position | None,
    ) -> Position:
        """Preserve metadata absent from an exchange position snapshot."""
        if stored_position is None:
            return exchange_position

        return replace(
            exchange_position,
            stop_loss=exchange_position.stop_loss or stored_position.stop_loss,
            take_profit=(exchange_position.take_profit or stored_position.take_profit),
            interval=exchange_position.interval or stored_position.interval,
            strategy_type=(
                exchange_position.strategy_type or stored_position.strategy_type
            ),
            protection_step=max(
                exchange_position.protection_step,
                stored_position.protection_step,
            ),
            stop_loss_client_algo_id=(
                exchange_position.stop_loss_client_algo_id
                or stored_position.stop_loss_client_algo_id
            ),
            take_profit_client_algo_id=(
                exchange_position.take_profit_client_algo_id
                or stored_position.take_profit_client_algo_id
            ),
            entry_client_order_id=(
                exchange_position.entry_client_order_id
                or stored_position.entry_client_order_id
            ),
        )

    async def get(
        self,
        *,
        symbol: str,
        synchronize: bool = False,
    ) -> Position | None:
        """Return a position for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)

        if synchronize:
            await self.sync(
                symbol=normalized_symbol,
            )

        return await self.position_repository.get_by_symbol(
            symbol=normalized_symbol,
        )

    async def get_all(
        self,
        *,
        synchronize: bool = False,
    ) -> Sequence[Position]:
        """Return all positions."""
        if synchronize:
            await self.sync()

        return await self.position_repository.get_all()

    async def save(self, *, position: Position) -> None:
        """Persist one authoritative position snapshot and its local metadata."""
        await self.position_repository.save(position=position)

    async def has_position(
        self,
        *,
        symbol: str,
        synchronize: bool = False,
    ) -> bool:
        """Return whether an active non-zero position exists."""
        position = await self.get(
            symbol=symbol,
            synchronize=synchronize,
        )

        return position is not None and position.quantity > _DECIMAL_ZERO

    async def delete(
        self,
        *,
        symbol: str,
    ) -> bool:
        """Delete a stored position."""
        return await self.position_repository.delete(
            symbol=self._normalize_symbol(symbol),
        )

    async def clear(self) -> int:
        """Delete every stored position."""
        return await self.position_repository.delete_all()

    async def count(self) -> int:
        """Return the number of stored positions."""
        return await self.position_repository.count()

    @staticmethod
    def _find_position(
        *,
        positions: Sequence[Position],
        symbol: str,
    ) -> Position | None:
        """Return one matching position and reject duplicates."""
        matching_position: Position | None = None

        for position in positions:
            if position.symbol.upper() != symbol:
                continue

            if matching_position is not None:
                raise RuntimeError(
                    _MULTIPLE_POSITIONS_ERROR_TEMPLATE.format(
                        symbol=symbol,
                    )
                )

            matching_position = position

        return matching_position

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
