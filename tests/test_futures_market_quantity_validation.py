"""Futures MARKET quantity normalization regression tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Never

import pytest

from botragram.engine import OrderEngine
from botragram.enums import OrderSide, OrderType
from botragram.exceptions import VenueRuleValidationError
from botragram.models import ExchangeSymbolRules, Ticker


@dataclass(slots=True)
class _Exchange:
    """Provide typed read-only venue data to the order engine."""

    rules: ExchangeSymbolRules
    price: Decimal = Decimal("1")
    raise_rules: BaseException | None = None

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return configured rules or propagate the configured failure."""
        assert symbol == self.rules.symbol
        if self.raise_rules is not None:
            raise self.raise_rules
        return self.rules

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a typed current reference price."""
        assert symbol == self.rules.symbol
        return Ticker(
            symbol=symbol,
            bid_price=self.price,
            ask_price=self.price,
            last_price=self.price,
            timestamp=datetime.now(UTC),
        )

    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Never:
        """Reject mutations in a read-only normalization test."""
        del symbol, side, order_type, quantity, price, client_order_id
        raise AssertionError("Unexpected order mutation")

    async def cancel_order(self, *, symbol: str, order_id: str) -> Never:
        """Reject cancellations in a read-only normalization test."""
        del symbol, order_id
        raise AssertionError("Unexpected order mutation")

    async def get_order(self, *, symbol: str, order_id: str) -> Never:
        """Reject unrelated order reads in a normalization test."""
        del symbol, order_id
        raise AssertionError("Unexpected order read")

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Never:
        """Reject unrelated order reads in a normalization test."""
        del symbol, client_order_id
        raise AssertionError("Unexpected order read")


def _rules(
    *,
    step: str,
    minimum: str = "1",
    maximum: str = "10000000",
    minimum_notional: str | None = None,
) -> ExchangeSymbolRules:
    """Build deterministic typed Futures MARKET rules."""
    return ExchangeSymbolRules(
        symbol="TESTUSDT",
        market_min_quantity=Decimal(minimum),
        market_max_quantity=Decimal(maximum),
        market_quantity_step=Decimal(step),
        minimum_notional=(Decimal(minimum_notional) if minimum_notional else None),
        minimum_price=Decimal("0.0001"),
        maximum_price=Decimal("1000000"),
        price_tick_size=Decimal("0.0001"),
    )


@pytest.mark.parametrize(
    ("quantity", "step", "expected"),
    [
        ("1596.424010217113665389527458", "1", "1596"),
        ("983284.1691248770894788593904", "1", "983284"),
        ("12.37", "0.25", "12.25"),
        ("12.37", "5", "10"),
    ],
)
def test_normalizes_quantity_down_on_arbitrary_step_grid(
    quantity: str, step: str, expected: str
) -> None:
    """Step size, not decimal precision, drives conservative normalization."""
    engine = OrderEngine(exchange_client=_Exchange(rules=_rules(step=step)))

    normalized = asyncio.run(
        engine.normalize_futures_market_quantity(
            symbol="TESTUSDT", quantity=Decimal(quantity)
        )
    )

    assert normalized == Decimal(expected)
    assert normalized <= Decimal(quantity)


@pytest.mark.parametrize(
    ("quantity", "rules", "price"),
    [
        ("0.9", _rules(step="1"), Decimal("10")),
        ("5", _rules(step="1", minimum_notional="10"), Decimal("1")),
        ("11", _rules(step="1", maximum="10"), Decimal("1")),
    ],
)
def test_rejects_invalid_quantity_before_order_submission(
    quantity: str, rules: ExchangeSymbolRules, price: Decimal
) -> None:
    """Invalid min/max/notional rules fail closed at the venue boundary."""
    engine = OrderEngine(exchange_client=_Exchange(rules=rules, price=price))

    with pytest.raises(VenueRuleValidationError):
        asyncio.run(
            engine.normalize_futures_market_quantity(
                symbol="TESTUSDT", quantity=Decimal(quantity)
            )
        )


def test_cancellation_during_rule_lookup_propagates() -> None:
    """Cancellation must not create a substitute venue decision."""
    engine = OrderEngine(
        exchange_client=_Exchange(
            rules=_rules(step="1"), raise_rules=asyncio.CancelledError()
        )
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            engine.normalize_futures_market_quantity(
                symbol="TESTUSDT", quantity=Decimal("10")
            )
        )
