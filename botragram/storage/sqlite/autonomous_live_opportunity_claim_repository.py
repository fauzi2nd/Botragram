"""SQLite durable autonomous LIVE closed-candle replay denial."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from botragram.enums import Interval, SignalType
from botragram.models import Signal
from botragram.repositories import AutonomousLiveOpportunityClaimRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteAutonomousLiveOpportunityClaimRepository"]


_ACTIONABLE_SIGNAL_TYPES: Final[frozenset[SignalType]] = frozenset(
    {SignalType.BUY, SignalType.SELL}
)
_INSERT_CLAIM_SQL: Final[str] = """
INSERT INTO autonomous_live_opportunity_claims (
    symbol,
    interval,
    strategy_name,
    signal_generated_at
)
VALUES (?, ?, ?, ?)
ON CONFLICT (
    symbol,
    interval,
    strategy_name,
    signal_generated_at
)
DO NOTHING;
"""


class SQLiteAutonomousLiveOpportunityClaimRepository(
    AutonomousLiveOpportunityClaimRepository
):
    """Use one atomic INSERT-or-ignore as the replay-denial boundary."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        self._database = database

    async def claim(self, *, signal: Signal, interval: Interval) -> bool:
        """Persist the first exact actionable closed-candle identity."""
        if signal.signal_type not in _ACTIONABLE_SIGNAL_TYPES:
            raise ValueError(
                "Autonomous LIVE opportunity claims require BUY or SELL signals"
            )

        affected_rows = await self._database.execute(
            statement=_INSERT_CLAIM_SQL,
            parameters=(
                self._normalize_symbol(signal.symbol),
                interval.value,
                self._normalize_strategy_name(signal.strategy_name),
                self._datetime_to_utc_text(signal.generated_at),
            ),
        )
        if affected_rows not in {0, 1}:
            raise RuntimeError(
                "Autonomous LIVE opportunity claim affected an invalid row count"
            )
        return affected_rows == 1

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("Autonomous LIVE opportunity symbol must not be empty")
        return normalized

    @staticmethod
    def _normalize_strategy_name(strategy_name: str) -> str:
        normalized = strategy_name.strip()
        if not normalized:
            raise ValueError(
                "Autonomous LIVE opportunity strategy name must not be empty"
            )
        return normalized

    @staticmethod
    def _datetime_to_utc_text(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Autonomous LIVE opportunity generated time must be timezone-aware"
            )
        return value.astimezone(UTC).isoformat()
