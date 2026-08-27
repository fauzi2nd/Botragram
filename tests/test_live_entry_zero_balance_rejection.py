"""Regression tests for deterministic LIVE balance rejection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.config.risk_settings import RiskSettings
from botragram.engine import PortfolioEngine, RiskEngine, TradingEngine
from botragram.enums import SignalType, StrategyType
from botragram.models import Position, Signal
from botragram.services import LiveEntryRiskEvaluationService


@dataclass(slots=True)
class _BalanceProvider:
    balance: Decimal

    async def get_free_balance(self, *, asset: str) -> Decimal:
        assert asset == "USDT"
        return self.balance


@dataclass(slots=True)
class _PositionProvider:
    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        assert synchronize
        return ()


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", (Decimal("0"), Decimal("-1")))
async def test_non_positive_live_balance_is_safe_risk_rejection(
    balance: Decimal,
) -> None:
    """Reject a candidate deterministically before risk sizing or submission."""
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    service = LiveEntryRiskEvaluationService(
        account_service=_BalanceProvider(balance=balance),
        position_service=_PositionProvider(),
        trading_engine=TradingEngine(
            risk_engine=RiskEngine(settings=RiskSettings()),
            portfolio_engine=PortfolioEngine(),
        ),
        balance_asset="USDT",
    )

    evaluation = await service.evaluate(signal=signal)

    assert not evaluation.has_existing_position
    assert not evaluation.decision.should_execute
    assert evaluation.decision.risk_result is None
    assert evaluation.decision.reason == "Insufficient available balance"
