"""
Botragram

Description:
    TradFi market calendar engine evaluating asset sessions and trading hours.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import re
from datetime import datetime, time, timedelta, timezone
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import AssetClass, MarketSessionStatus
from botragram.models import MarketSession

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "MarketCalendarEngine",
]

# =============================================================================
# Constants
# =============================================================================
_CRYPTO_SYMBOLS: Final[frozenset[str]] = frozenset(
    (
        "BTC",
        "ETH",
        "SOL",
        "XRP",
        "DOGE",
        "ADA",
        "BNB",
        "AVAX",
        "DOT",
        "LINK",
        "NEAR",
        "SUI",
        "PEPE",
        "SHIB",
        "LTC",
        "TRX",
        "BCH",
        "ETC",
        "XLM",
        "FIL",
        "APT",
        "ARB",
        "OP",
        "TIA",
        "INJ",
        "RENDER",
        "FET",
        "ICP",
    )
)

_COMMODITY_PREFIXES: Final[frozenset[str]] = frozenset(
    (
        "XAU",
        "XAG",
        "XPT",
        "XPD",
        "USOIL",
        "UKOIL",
        "WTI",
        "BRENT",
        "COPPER",
        "NATGAS",
    )
)

_INDEX_PREFIXES: Final[frozenset[str]] = frozenset(
    (
        "US30",
        "SPX500",
        "SP500",
        "SPX",
        "NAS100",
        "US100",
        "NDX",
        "GER40",
        "DAX",
        "UK100",
        "FTSE",
        "JP225",
        "N225",
        "HK50",
        "HSI",
        "FRA40",
        "EU50",
        "STOXX50",
        "AUS200",
        "CHINA50",
    )
)

_FIAT_CURRENCIES: Final[frozenset[str]] = frozenset(
    (
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "AUD",
        "CAD",
        "CHF",
        "NZD",
        "SGD",
        "HKD",
        "CNH",
        "SEK",
        "NOK",
        "TRY",
        "ZAR",
        "MXN",
    )
)

_FOREX_OPEN_SUNDAY_HOUR: Final[int] = 21
_FOREX_CLOSE_FRIDAY_HOUR: Final[int] = 22

_COMMODITY_OPEN_SUNDAY_HOUR: Final[int] = 23
_COMMODITY_CLOSE_FRIDAY_HOUR: Final[int] = 21
_COMMODITY_BREAK_START_HOUR: Final[int] = 21
_COMMODITY_BREAK_END_HOUR: Final[int] = 22

_INDEX_OPEN_SUNDAY_HOUR: Final[int] = 22
_INDEX_CLOSE_FRIDAY_HOUR: Final[int] = 20
_INDEX_BREAK_START_HOUR: Final[int] = 20
_INDEX_BREAK_END_HOUR: Final[int] = 22


# =============================================================================
# Market Calendar Engine
# =============================================================================
class MarketCalendarEngine:
    """Deterministic trading session and market calendar engine for TradFi CFDs."""

    __slots__ = ()

    def classify_asset(self, symbol: str) -> AssetClass:
        """Classify a given symbol into its respective AssetClass."""
        clean = re.sub(
            r"(\.(s|pro|cfd|std)|(_ecn|_std|-cfd))$",
            "",
            symbol.strip(),
            flags=re.IGNORECASE,
        ).upper()

        for crypto in _CRYPTO_SYMBOLS:
            if clean.startswith(crypto) or clean == crypto:
                return AssetClass.CRYPTO

        for comm in _COMMODITY_PREFIXES:
            if clean.startswith(comm):
                return AssetClass.COMMODITY

        for idx in _INDEX_PREFIXES:
            if clean.startswith(idx):
                return AssetClass.INDEX

        if len(clean) == 6:
            base, quote = clean[:3], clean[3:]
            if base in _FIAT_CURRENCIES and quote in _FIAT_CURRENCIES:
                return AssetClass.FOREX

        if clean.endswith("USD") and len(clean) == 6:
            return AssetClass.FOREX

        return AssetClass.CRYPTO

    def get_session(
        self,
        symbol: str,
        at: datetime | None = None,
    ) -> MarketSession:
        """Return the market trading session status for a symbol at a given time."""
        current_time = (
            datetime.now(timezone.utc)
            if at is None
            else (at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc))
        )
        asset_class = self.classify_asset(symbol)

        if asset_class is AssetClass.CRYPTO:
            return MarketSession(
                symbol=symbol,
                asset_class=asset_class,
                status=MarketSessionStatus.OPEN,
                is_open=True,
                current_time=current_time,
                reason="Crypto market trades 24/7",
            )

        if asset_class is AssetClass.FOREX:
            return self._evaluate_forex(symbol, current_time)

        if asset_class is AssetClass.COMMODITY:
            return self._evaluate_commodity(symbol, current_time)

        return self._evaluate_index(symbol, current_time)

    def is_market_open(
        self,
        symbol: str,
        at: datetime | None = None,
    ) -> bool:
        """Return True if the market is open for trading the symbol."""
        return self.get_session(symbol, at).is_open

    def is_weekend_close(
        self,
        symbol: str,
        at: datetime | None = None,
    ) -> bool:
        """Return True if the market is closed specifically due to weekend."""
        return self.get_session(symbol, at).status is MarketSessionStatus.WEEKEND

    def time_to_close(
        self,
        symbol: str,
        at: datetime | None = None,
    ) -> timedelta | None:
        """Return timedelta until market close if currently open, else None."""
        session = self.get_session(symbol, at)
        if session.is_open and session.next_close is not None:
            return max(timedelta(0), session.next_close - session.current_time)
        return None

    def time_to_open(
        self,
        symbol: str,
        at: datetime | None = None,
    ) -> timedelta | None:
        """Return timedelta until market open if currently closed, else None."""
        session = self.get_session(symbol, at)
        if not session.is_open and session.next_open is not None:
            return max(timedelta(0), session.next_open - session.current_time)
        return None

    # =========================================================================
    # Internal Evaluators
    # =========================================================================

    def _evaluate_forex(self, symbol: str, current_time: datetime) -> MarketSession:
        """Evaluate Forex session (Sunday 21:00 - Friday 22:00 UTC)."""
        weekday = current_time.weekday()
        current_time_of_day = current_time.time()

        if weekday == 5:
            days_to_sunday = 1
            next_open = datetime.combine(
                current_time.date() + timedelta(days=days_to_sunday),
                time(_FOREX_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.FOREX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Forex market closed for weekend (Saturday)",
            )

        if weekday == 6 and current_time_of_day < time(_FOREX_OPEN_SUNDAY_HOUR, 0):
            next_open = datetime.combine(
                current_time.date(),
                time(_FOREX_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.FOREX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Forex market closed for weekend (Sunday pre-open)",
            )

        if weekday == 4 and current_time_of_day >= time(_FOREX_CLOSE_FRIDAY_HOUR, 0):
            next_open = datetime.combine(
                current_time.date() + timedelta(days=2),
                time(_FOREX_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.FOREX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Forex market closed for weekend (Friday post-close)",
            )

        days_to_friday = (4 - weekday) % 7
        if weekday == 6:
            days_to_friday = 5
        next_close = datetime.combine(
            current_time.date() + timedelta(days=days_to_friday),
            time(_FOREX_CLOSE_FRIDAY_HOUR, 0),
            tzinfo=timezone.utc,
        )
        return MarketSession(
            symbol=symbol,
            asset_class=AssetClass.FOREX,
            status=MarketSessionStatus.OPEN,
            is_open=True,
            current_time=current_time,
            next_close=next_close,
            reason="Forex market open",
        )

    def _evaluate_commodity(self, symbol: str, current_time: datetime) -> MarketSession:
        """Evaluate Commodity session (Sun 23:00 - Fri 21:00 UTC, break 21-22)."""
        weekday = current_time.weekday()
        current_time_of_day = current_time.time()

        if weekday == 5:
            days_to_sunday = 1
            next_open = datetime.combine(
                current_time.date() + timedelta(days=days_to_sunday),
                time(_COMMODITY_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.COMMODITY,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Commodity market closed for weekend (Saturday)",
            )

        if weekday == 6 and current_time_of_day < time(_COMMODITY_OPEN_SUNDAY_HOUR, 0):
            next_open = datetime.combine(
                current_time.date(),
                time(_COMMODITY_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.COMMODITY,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Commodity market closed for weekend (Sunday pre-open)",
            )

        if weekday == 4 and current_time_of_day >= time(
            _COMMODITY_CLOSE_FRIDAY_HOUR, 0
        ):
            next_open = datetime.combine(
                current_time.date() + timedelta(days=2),
                time(_COMMODITY_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.COMMODITY,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Commodity market closed for weekend (Friday post-close)",
            )

        if weekday in (0, 1, 2, 3) and time(
            _COMMODITY_BREAK_START_HOUR, 0
        ) <= current_time_of_day < time(_COMMODITY_BREAK_END_HOUR, 0):
            next_open = datetime.combine(
                current_time.date(),
                time(_COMMODITY_BREAK_END_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.COMMODITY,
                status=MarketSessionStatus.BREAK,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Commodity market daily maintenance break",
            )

        if weekday == 4:
            next_close = datetime.combine(
                current_time.date(),
                time(_COMMODITY_CLOSE_FRIDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
        elif weekday in (0, 1, 2, 3) and current_time_of_day < time(
            _COMMODITY_BREAK_START_HOUR, 0
        ):
            next_close = datetime.combine(
                current_time.date(),
                time(_COMMODITY_BREAK_START_HOUR, 0),
                tzinfo=timezone.utc,
            )
        else:
            days_to_friday = (4 - weekday) % 7
            if weekday == 6:
                days_to_friday = 5
            next_close = datetime.combine(
                current_time.date() + timedelta(days=days_to_friday),
                time(_COMMODITY_CLOSE_FRIDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )

        return MarketSession(
            symbol=symbol,
            asset_class=AssetClass.COMMODITY,
            status=MarketSessionStatus.OPEN,
            is_open=True,
            current_time=current_time,
            next_close=next_close,
            reason="Commodity market open",
        )

    def _evaluate_index(self, symbol: str, current_time: datetime) -> MarketSession:
        """Evaluate Equity Index session (Sun 22:00 - Fri 20:00 UTC, break 20-22)."""
        weekday = current_time.weekday()
        current_time_of_day = current_time.time()

        if weekday == 5:
            days_to_sunday = 1
            next_open = datetime.combine(
                current_time.date() + timedelta(days=days_to_sunday),
                time(_INDEX_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Index market closed for weekend (Saturday)",
            )

        if weekday == 6 and current_time_of_day < time(_INDEX_OPEN_SUNDAY_HOUR, 0):
            next_open = datetime.combine(
                current_time.date(),
                time(_INDEX_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Index market closed for weekend (Sunday pre-open)",
            )

        if weekday == 4 and current_time_of_day >= time(_INDEX_CLOSE_FRIDAY_HOUR, 0):
            next_open = datetime.combine(
                current_time.date() + timedelta(days=2),
                time(_INDEX_OPEN_SUNDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Index market closed for weekend (Friday post-close)",
            )

        if weekday in (0, 1, 2, 3) and time(
            _INDEX_BREAK_START_HOUR, 0
        ) <= current_time_of_day < time(_INDEX_BREAK_END_HOUR, 0):
            next_open = datetime.combine(
                current_time.date(),
                time(_INDEX_BREAK_END_HOUR, 0),
                tzinfo=timezone.utc,
            )
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                status=MarketSessionStatus.BREAK,
                is_open=False,
                current_time=current_time,
                next_open=next_open,
                reason="Index market daily maintenance break",
            )

        if weekday == 4:
            next_close = datetime.combine(
                current_time.date(),
                time(_INDEX_CLOSE_FRIDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )
        elif weekday in (0, 1, 2, 3) and current_time_of_day < time(
            _INDEX_BREAK_START_HOUR, 0
        ):
            next_close = datetime.combine(
                current_time.date(),
                time(_INDEX_BREAK_START_HOUR, 0),
                tzinfo=timezone.utc,
            )
        else:
            days_to_friday = (4 - weekday) % 7
            if weekday == 6:
                days_to_friday = 5
            next_close = datetime.combine(
                current_time.date() + timedelta(days=days_to_friday),
                time(_INDEX_CLOSE_FRIDAY_HOUR, 0),
                tzinfo=timezone.utc,
            )

        return MarketSession(
            symbol=symbol,
            asset_class=AssetClass.INDEX,
            status=MarketSessionStatus.OPEN,
            is_open=True,
            current_time=current_time,
            next_close=next_close,
            reason="Index market open",
        )
