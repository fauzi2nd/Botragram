"""
Botragram

Description:
    Trading strategy factory.

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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.strategy_settings import StrategySettings
from botragram.enums import StrategyType
from botragram.strategies.base import BaseStrategy
from botragram.strategies.breakout import BollingerBreakoutStrategy
from botragram.strategies.scalping import EMAScalpingStrategy
from botragram.strategies.swing import (
    MACDSwingStrategy,
)
from botragram.strategies.trend import (
    EMACrossStrategy,
    EMARsiStrategy,
    SupertrendStrategy,
)

__all__ = [
    "StrategyFactory",
    "StrategyResolver",
]


# =============================================================================
# Strategy Resolution
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class StrategyResolver:
    """Resolve immutable strategy instances from explicit strategy types."""

    strategies: Mapping[StrategyType, BaseStrategy]

    def __post_init__(self) -> None:
        """Copy and validate the resolver registry before exposing it."""
        registry = dict(self.strategies)

        for strategy_type, strategy in registry.items():
            if strategy.strategy_type is not strategy_type:
                raise ValueError(
                    "Strategy resolver key does not match strategy instance: "
                    f"{strategy_type.value!r}"
                )

        object.__setattr__(self, "strategies", MappingProxyType(registry))

    def resolve(self, *, strategy_type: StrategyType) -> BaseStrategy:
        """Return the strategy registered for one explicit strategy type.

        Args:
            strategy_type: The context-authoritative strategy type.

        Returns:
            The matching immutable strategy instance.

        Raises:
            ValueError: If the type has no registered strategy.
        """
        strategy = self.strategies.get(strategy_type)

        if strategy is None:
            raise ValueError(f"Unsupported strategy type: {strategy_type.value!r}")

        return strategy


# =============================================================================
# Strategy Factory
# =============================================================================
class StrategyFactory:
    """Create trading strategies from strategy settings."""

    __slots__ = ()

    @staticmethod
    def create(
        *,
        settings: StrategySettings,
    ) -> BaseStrategy:
        """Create a trading strategy.

        Args:
            settings: Strategy configuration settings.

        Returns:
            Configured trading strategy.

        Raises:
            ValueError: If the configured strategy is unsupported.
        """
        match settings.strategy_type:
            case StrategyType.BOLLINGER_BREAKOUT:
                return BollingerBreakoutStrategy(
                    period=settings.bb_period,
                    standard_deviation=settings.bb_standard_deviation,
                )
            case StrategyType.EMA_CROSS:
                return EMACrossStrategy(
                    fast_period=settings.fast_period,
                    slow_period=settings.slow_period,
                )

            case StrategyType.EMA_RSI:
                return EMARsiStrategy(
                    fast_period=settings.fast_period,
                    slow_period=settings.slow_period,
                    rsi_period=settings.rsi_period,
                    rsi_overbought=settings.rsi_overbought,
                    rsi_oversold=settings.rsi_oversold,
                )

            case StrategyType.EMA_SCALPING:
                return EMAScalpingStrategy(
                    fast_period=settings.scalping_fast_period,
                    slow_period=settings.scalping_slow_period,
                    minimum_body_ratio=settings.scalping_minimum_body_ratio,
                )

            case StrategyType.MACD_SWING:
                return MACDSwingStrategy(
                    fast_period=settings.macd_fast_period,
                    slow_period=settings.macd_slow_period,
                    signal_period=settings.macd_signal_period,
                )

            case StrategyType.SUPERTREND:
                return SupertrendStrategy(
                    period=settings.supertrend_period,
                    multiplier=settings.supertrend_multiplier,
                )

            case _:
                raise ValueError(
                    f"Unsupported strategy type: {settings.strategy_type.value!r}"
                )

    @staticmethod
    def create_resolver(*, settings: StrategySettings) -> StrategyResolver:
        """Construct one reusable immutable strategy per supported type.

        Args:
            settings: Shared parameter settings used to construct each strategy.

        Returns:
            A deterministic resolver with no mutable current-strategy state.
        """
        if settings.strategy_type is StrategyType.CUSTOM:
            raise ValueError(
                f"Unsupported strategy type: {settings.strategy_type.value!r}"
            )

        return StrategyResolver(
            strategies={
                strategy_type: StrategyFactory.create(
                    settings=replace(settings, strategy_type=strategy_type),
                )
                for strategy_type in StrategyType
                if strategy_type is not StrategyType.CUSTOM
            },
        )
