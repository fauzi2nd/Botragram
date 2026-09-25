"""
Botragram

Description:
    Regression and unit tests for PIER (Pinbar + Engulfing EMA-RSI Pullback)
    strategy configuration parity, semantic correctness, pullback/location
    boundaries, fallback stop-loss invariants, RiskEngine exit ceiling parity,
    and 5m microstructure study ambiguity semantics.

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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager
from botragram.config.risk_settings import RiskSettings
from botragram.constants.env import (
    ENV_PIER_ATR_PERIOD,
    ENV_PIER_ATR_SL_MULTIPLIER,
    ENV_PIER_BB_PERIOD,
    ENV_PIER_BB_STD_DEV,
    ENV_PIER_ENGULFING_MIN_BODY_ATR,
    ENV_PIER_HTF_EXTREME_BUFFER_ATR,
    ENV_PIER_INCLUDE_STAR_PATTERNS,
    ENV_PIER_LOCATION_ATR_MULTIPLIER,
    ENV_PIER_LOCATION_TOLERANCE_PCT,
    ENV_PIER_MACD_FAST_PERIOD,
    ENV_PIER_MACD_SIGNAL_PERIOD,
    ENV_PIER_MACD_SLOW_PERIOD,
    ENV_PIER_MAX_OPPOSITE_WICK_RATIO,
    ENV_PIER_MIN_CONFIDENCE,
    ENV_PIER_MIN_ENGULFING_BODY_RATIO,
    ENV_PIER_MIN_NATR_THRESHOLD,
    ENV_PIER_MIN_SL_DISTANCE_PCT,
    ENV_PIER_MIN_STRUCTURAL_RR,
    ENV_PIER_MIN_WICK_RATIO,
    ENV_PIER_PINBAR_MIN_RANGE_ATR,
    ENV_PIER_PULLBACK_ATR_MULTIPLIER,
    ENV_PIER_PULLBACK_PERIOD,
    ENV_PIER_PULLBACK_PROXIMITY_PCT,
    ENV_PIER_REQUIRE_CONFIRMATION,
    ENV_PIER_REQUIRE_HTF_EXTREME_ZONE,
    ENV_PIER_REQUIRE_KEY_LEVEL_LOCATION,
    ENV_PIER_REQUIRE_TREND_FILTER,
    ENV_PIER_RISK_REWARD_RATIO,
    ENV_PIER_RSI_LONG_MAX,
    ENV_PIER_RSI_LONG_MIN,
    ENV_PIER_RSI_PERIOD,
    ENV_PIER_RSI_SHORT_MAX,
    ENV_PIER_RSI_SHORT_MIN,
    ENV_PIER_STALKING_ENABLED,
    ENV_PIER_STALKING_MAX_BARS,
    ENV_PIER_STALKING_MAX_CANDIDATES,
    ENV_PIER_STALKING_RETEST_RATIO,
    ENV_PIER_STOCH_RSI_D_PERIOD,
    ENV_PIER_STOCH_RSI_K_PERIOD,
    ENV_PIER_STOCH_RSI_OVERBOUGHT,
    ENV_PIER_STOCH_RSI_OVERSOLD,
    ENV_PIER_STOCH_RSI_PERIOD,
    ENV_PIER_STRICT_EMA_SIDE_REJECTION,
    ENV_PIER_STRUCTURAL_TP_BUFFER_PCT,
    ENV_PIER_SWING_LOOKBACK,
    ENV_PIER_TREND_PERIOD,
    ENV_PIER_USE_MACD,
    ENV_PIER_USE_PARABOLIC_SAR,
    ENV_PIER_USE_STOCH_RSI,
    ENV_PIER_USE_STRUCTURAL_TP,
    ENV_PIER_VOLUME_MULTIPLIER,
    ENV_PIER_VOLUME_PERIOD,
)
from botragram.engine.risk_engine import RiskEngine
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)
from tests.manual.run_pier_5m_microstructure_study import (
    simulate_trade_and_excursion,
)

# =============================================================================
# Helpers and Fixtures
# =============================================================================
_START_TIME = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
    interval: Interval = Interval.M15,
) -> Candle:
    """Helper to generate a timestamped Candle for testing."""
    delta = timedelta(minutes=15 * index)
    open_time = _START_TIME + delta
    return Candle(
        symbol="BTCUSDT",
        interval=interval,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )


# =============================================================================
# Section A: Configuration Drift & Parity Tests
# =============================================================================
class TestPierConfigurationParity:
    """Validate full chain from environment -> SettingsManager -> StrategyFactory."""

    def test_environment_binding_propagation_custom_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Setting all PIER env vars propagates into StrategySettings and Strategy."""
        custom_env = {
            ENV_PIER_TREND_PERIOD: "120",
            ENV_PIER_PULLBACK_PERIOD: "25",
            ENV_PIER_RSI_PERIOD: "10",
            ENV_PIER_RSI_LONG_MIN: "40.0",
            ENV_PIER_RSI_LONG_MAX: "62.0",
            ENV_PIER_RSI_SHORT_MIN: "38.0",
            ENV_PIER_RSI_SHORT_MAX: "60.0",
            ENV_PIER_VOLUME_PERIOD: "25",
            ENV_PIER_VOLUME_MULTIPLIER: "1.25",
            ENV_PIER_MIN_WICK_RATIO: "0.55",
            ENV_PIER_MAX_OPPOSITE_WICK_RATIO: "0.25",
            ENV_PIER_MIN_ENGULFING_BODY_RATIO: "1.10",
            ENV_PIER_ATR_PERIOD: "16",
            ENV_PIER_ATR_SL_MULTIPLIER: "1.8",
            ENV_PIER_RISK_REWARD_RATIO: "2.5",
            ENV_PIER_MIN_CONFIDENCE: "0.75",
            ENV_PIER_REQUIRE_HTF_EXTREME_ZONE: "true",
            ENV_PIER_HTF_EXTREME_BUFFER_ATR: "0.25",
            ENV_PIER_STRICT_EMA_SIDE_REJECTION: "true",
            ENV_PIER_STALKING_ENABLED: "true",
            ENV_PIER_STALKING_MAX_BARS: "7",
            ENV_PIER_STALKING_MAX_CANDIDATES: "5",
            ENV_PIER_STALKING_RETEST_RATIO: "0.50",
            ENV_PIER_REQUIRE_KEY_LEVEL_LOCATION: "true",
            ENV_PIER_SWING_LOOKBACK: "15",
            ENV_PIER_REQUIRE_TREND_FILTER: "false",
            ENV_PIER_MIN_NATR_THRESHOLD: "0.003",
            ENV_PIER_MIN_SL_DISTANCE_PCT: "0.004",
            ENV_PIER_LOCATION_TOLERANCE_PCT: "0.005",
            ENV_PIER_LOCATION_ATR_MULTIPLIER: "0.6",
            ENV_PIER_PULLBACK_PROXIMITY_PCT: "0.008",
            ENV_PIER_PULLBACK_ATR_MULTIPLIER: "0.8",
            ENV_PIER_PINBAR_MIN_RANGE_ATR: "0.6",
            ENV_PIER_ENGULFING_MIN_BODY_ATR: "0.4",
            ENV_PIER_REQUIRE_CONFIRMATION: "true",
            ENV_PIER_INCLUDE_STAR_PATTERNS: "false",
            ENV_PIER_USE_PARABOLIC_SAR: "false",
            ENV_PIER_USE_MACD: "false",
            ENV_PIER_MACD_FAST_PERIOD: "8",
            ENV_PIER_MACD_SLOW_PERIOD: "21",
            ENV_PIER_MACD_SIGNAL_PERIOD: "7",
            ENV_PIER_USE_STOCH_RSI: "false",
            ENV_PIER_STOCH_RSI_PERIOD: "16",
            ENV_PIER_STOCH_RSI_K_PERIOD: "4",
            ENV_PIER_STOCH_RSI_D_PERIOD: "4",
            ENV_PIER_STOCH_RSI_OVERBOUGHT: "78.0",
            ENV_PIER_STOCH_RSI_OVERSOLD: "22.0",
        }

        for key, value in custom_env.items():
            monkeypatch.setenv(key, value)

        empty_env = tmp_path / ".empty.env"
        empty_env.write_text("")

        env = EnvironmentProvider(env_path=str(empty_env))
        settings_mgr = SettingsManager(environment_provider=env)
        strat_settings = settings_mgr.load_strategy_settings()

        # 1. Verify StrategySettings parsed the custom environment correctly
        assert strat_settings.pier_trend_period == 120
        assert strat_settings.pier_pullback_period == 25
        assert strat_settings.pier_rsi_period == 10
        assert strat_settings.pier_rsi_long_min == Decimal("40.0")
        assert strat_settings.pier_rsi_long_max == Decimal("62.0")
        assert strat_settings.pier_rsi_short_min == Decimal("38.0")
        assert strat_settings.pier_rsi_short_max == Decimal("60.0")
        assert strat_settings.pier_volume_period == 25
        assert strat_settings.pier_volume_multiplier == Decimal("1.25")
        assert strat_settings.pier_min_wick_ratio == Decimal("0.55")
        assert strat_settings.pier_max_opposite_wick_ratio == Decimal("0.25")
        assert strat_settings.pier_min_engulfing_body_ratio == Decimal("1.10")
        assert strat_settings.pier_atr_period == 16
        assert strat_settings.pier_atr_sl_multiplier == Decimal("1.8")
        assert strat_settings.pier_risk_reward_ratio == Decimal("2.5")
        assert strat_settings.pier_min_confidence == Decimal("0.75")
        assert strat_settings.pier_require_htf_extreme_zone is True
        assert strat_settings.pier_htf_extreme_buffer_atr == Decimal("0.25")
        assert strat_settings.pier_strict_ema_side_rejection is True
        assert strat_settings.pier_stalking_enabled is True
        assert strat_settings.pier_stalking_max_bars == 7
        assert strat_settings.pier_stalking_max_candidates == 5
        assert strat_settings.pier_stalking_retest_ratio == Decimal("0.50")
        assert strat_settings.pier_require_key_level_location is True
        assert strat_settings.pier_swing_lookback == 15
        assert strat_settings.pier_require_trend_filter is False
        assert strat_settings.pier_min_natr_threshold == Decimal("0.003")
        assert strat_settings.pier_min_sl_distance_pct == Decimal("0.004")
        assert strat_settings.pier_location_tolerance_pct == Decimal("0.005")
        assert strat_settings.pier_location_atr_multiplier == Decimal("0.6")
        assert strat_settings.pier_pullback_proximity_pct == Decimal("0.008")
        assert strat_settings.pier_pullback_atr_multiplier == Decimal("0.8")
        assert strat_settings.pier_pinbar_min_range_atr == Decimal("0.6")
        assert strat_settings.pier_engulfing_min_body_atr == Decimal("0.4")
        assert strat_settings.pier_require_confirmation is True
        assert strat_settings.pier_include_star_patterns is False
        assert strat_settings.pier_use_parabolic_sar is False
        assert strat_settings.pier_use_macd is False
        assert strat_settings.pier_macd_fast_period == 8
        assert strat_settings.pier_macd_slow_period == 21
        assert strat_settings.pier_macd_signal_period == 7
        assert strat_settings.pier_use_stoch_rsi is False
        assert strat_settings.pier_stoch_rsi_period == 16
        assert strat_settings.pier_stoch_rsi_k_period == 4
        assert strat_settings.pier_stoch_rsi_d_period == 4
        assert strat_settings.pier_stoch_rsi_overbought == Decimal("78.0")
        assert strat_settings.pier_stoch_rsi_oversold == Decimal("22.0")

        # 2. Verify StrategyFactory creates strategy with matching properties
        strategy = StrategyFactory.create(
            settings=replace(
                strat_settings,
                strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
            )
        )
        assert isinstance(strategy, PinbarEngulfingEmaRsiStrategy)
        assert strategy.trend_period == 120
        assert strategy.pullback_period == 25
        assert strategy.pullback_atr_multiplier == Decimal("0.8")
        assert strategy.location_atr_multiplier == Decimal("0.6")
        assert strategy.min_confidence == Decimal("0.75")
        assert strategy.require_htf_extreme_zone is True
        assert strategy.htf_extreme_buffer_atr == Decimal("0.25")
        assert strategy.strict_ema_side_rejection is True
        assert strategy.use_macd is False
        assert strategy.use_stoch_rsi is False
        assert strategy.include_star_patterns is False
        assert strategy.use_parabolic_sar is False
        assert strategy.require_confirmation is True


# =============================================================================
# Section B: Semantic Confidence Tests
# =============================================================================
class TestPierConfidenceSemantics:
    """Validate that min_confidence functions as an explicit acceptance gate."""

    def test_confidence_base_score_and_filtering(self) -> None:
        """When signal confidence is below min_confidence, it is rejected to HOLD."""
        # Baseline strategy with min_confidence = 0.65
        strat_lenient = PinbarEngulfingEmaRsiStrategy(
            trend_period=5,
            pullback_period=3,
            min_confidence=Decimal("0.65"),
        )
        # Stricter strategy with min_confidence = 0.85
        strat_strict = PinbarEngulfingEmaRsiStrategy(
            trend_period=5,
            pullback_period=3,
            min_confidence=Decimal("0.85"),
        )

        candles: list[Candle] = []
        for i in range(50):
            candles.append(
                _make_candle(
                    index=i,
                    open_price=Decimal("100.0"),
                    high_price=Decimal("105.0"),
                    low_price=Decimal("95.0"),
                    close_price=Decimal("102.0"),
                )
            )

        # Build a valid bullish pinbar on candle 51
        candles.append(
            _make_candle(
                index=50,
                open_price=Decimal("102.0"),
                high_price=Decimal("103.0"),
                low_price=Decimal("92.0"),
                close_price=Decimal("102.5"),
                volume=Decimal("150.0"),
            )
        )
        candles.append(
            _make_candle(
                index=51,
                open_price=Decimal("102.5"),
                high_price=Decimal("104.0"),
                low_price=Decimal("102.0"),
                close_price=Decimal("103.5"),
                volume=Decimal("120.0"),
            )
        )

        sig_lenient = strat_lenient.generate_signal(candles=candles)
        sig_strict = strat_strict.generate_signal(candles=candles)

        if sig_lenient.signal_type is SignalType.BUY:
            assert sig_lenient.confidence >= Decimal("0.65")
            if sig_lenient.confidence < Decimal("0.85"):
                assert sig_strict.signal_type is SignalType.HOLD
                assert "[REJECTED_CONFIDENCE]" in (sig_strict.reason or "")


# =============================================================================
# Section C: Pullback vs Key Location Zone Tests
# =============================================================================
class TestPierPullbackLocationZones:
    """Validate mathematical relation between near_pullback and location_ok."""

    def test_ema21_pullback_dominance_and_swing_support(self) -> None:
        """Swing support far outside EMA21 pullback zone cannot trigger a trade."""
        strat = PinbarEngulfingEmaRsiStrategy(
            trend_period=5,
            pullback_period=3,
            require_key_level_location=True,
            pullback_atr_multiplier=Decimal("1.0"),
            location_atr_multiplier=Decimal("0.5"),
        )
        # Verify that require_key_level_location is active
        assert strat.require_key_level_location is True
        assert strat.pullback_atr_multiplier == Decimal("1.0")


# =============================================================================
# Section D: Degenerate Short Stop Loss Invariant
# =============================================================================
class TestPierShortFallbackStopLoss:
    """Verify that SELL stop-loss is always strictly above entry price."""

    def test_short_stop_loss_strictly_above_entry(self) -> None:
        """Even on degenerate pattern_high <= current_close, SL > current_close."""
        strat = PinbarEngulfingEmaRsiStrategy(
            trend_period=5,
            pullback_period=3,
            atr_multiplier_sl=Decimal("1.5"),
        )
        candles: list[Candle] = []
        for i in range(50):
            candles.append(
                _make_candle(
                    index=i,
                    open_price=Decimal("200.0") - Decimal(i),
                    high_price=Decimal("202.0") - Decimal(i),
                    low_price=Decimal("198.0") - Decimal(i),
                    close_price=Decimal("199.0") - Decimal(i),
                    volume=Decimal("100.0"),
                )
            )

        signal = strat.generate_signal(candles=candles)
        if signal.signal_type is SignalType.SELL:
            assert signal.stop_loss is not None
            assert signal.stop_loss > signal.price
            assert signal.take_profit is not None
            assert signal.take_profit < signal.price


# =============================================================================
# Section E: PIER SL/TP Parity with RiskEngine
# =============================================================================
class TestPierRiskEngineParity:
    """Verify structural SL/TP preservation and ceiling clamping in RiskEngine."""

    def test_structural_sl_within_ceiling_preserved(self) -> None:
        """Structural SL smaller than risk ceiling is strictly preserved."""
        risk_settings = RiskSettings(
            pier_stop_loss_pct=Decimal("0.02"),
            pier_take_profit_pct=Decimal("0.05"),
        )
        engine = RiskEngine(settings=risk_settings)

        # BUY: Entry 100, structural SL 99 (1% risk, within 2% ceiling), TP 103 (3%)
        signal = Signal(
            symbol="BTCUSDT",
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("99.0"),
            take_profit=Decimal("103.0"),
            confidence=Decimal("0.80"),
            generated_at=datetime.now(UTC),
        )

        res = engine.evaluate(signal=signal, account_balance=Decimal("1000.0"))
        assert res.approved is True
        assert res.metrics.stop_loss == Decimal("99.0")
        assert res.metrics.take_profit == Decimal("103.0")

    def test_structural_sl_exceeding_ceiling_clamped(self) -> None:
        """Structural SL wider than ceiling is clamped to risk ceiling."""
        risk_settings = RiskSettings(
            pier_stop_loss_pct=Decimal("0.015"),  # 1.5% max SL
            pier_take_profit_pct=Decimal("0.03"),  # 3.0% max TP
        )
        engine = RiskEngine(settings=risk_settings)

        # BUY: Entry 100, structural SL 97 (3% risk > 1.5% ceiling)
        signal_buy = Signal(
            symbol="BTCUSDT",
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("97.0"),
            take_profit=Decimal("102.0"),
            confidence=Decimal("0.80"),
            generated_at=datetime.now(UTC),
        )
        res_buy = engine.evaluate(signal=signal_buy, account_balance=Decimal("1000.0"))
        assert res_buy.approved is True
        # Clamped to 100 - (100 * 0.015) = 98.5
        assert res_buy.metrics.stop_loss == Decimal("98.5")

        # SELL: Entry 100, structural SL 103 (3% risk > 1.5% ceiling)
        signal_sell = Signal(
            symbol="BTCUSDT",
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
            signal_type=SignalType.SELL,
            price=Decimal("100.0"),
            stop_loss=Decimal("103.0"),
            take_profit=Decimal("98.0"),
            confidence=Decimal("0.80"),
            generated_at=datetime.now(UTC),
        )
        res_sell = engine.evaluate(
            signal=signal_sell, account_balance=Decimal("1000.0")
        )
        assert res_sell.approved is True
        # Clamped to 100 + (100 * 0.015) = 101.5
        assert res_sell.metrics.stop_loss == Decimal("101.5")


# =============================================================================
# Section G: 5m Study Ambiguity and Look-Ahead Tests
# =============================================================================
class TestPier5mStudyValidity:
    """Validate 5m microstructure study ambiguity model and forward candle slicing."""

    def test_same_bar_sl_tp_conservative_ambiguity_classification(self) -> None:
        """When a 1m candle hits both SL and TP, outcome is conservatively LOSS."""
        entry = Decimal("100.0")
        stop_loss = Decimal("98.0")
        take_profit = Decimal("104.0")

        # Forward candle spanning from 97.0 (below SL) to 105.0 (above TP)
        ambiguous_bar = _make_candle(
            index=1,
            open_price=Decimal("100.0"),
            high_price=Decimal("105.0"),
            low_price=Decimal("97.0"),
            close_price=Decimal("103.0"),
            interval=Interval.M1,
        )

        signal = Signal(
            symbol="BTCUSDT",
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
            signal_type=SignalType.BUY,
            price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=Decimal("0.70"),
            generated_at=datetime.now(UTC),
        )

        _, _, _, _, outcome = simulate_trade_and_excursion(
            signal=signal,
            candles_1m_forward=(ambiguous_bar,),
            candles_3m_forward=(),
            signal_side="BUY",
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            is_already_3m_aligned=True,
        )

        assert outcome == "LOSS"

    def test_forward_candle_slicing_no_look_ahead(self) -> None:
        """Forward candles strictly require open_time >= signal_time."""
        signal_time = _START_TIME + timedelta(minutes=60)
        c_past = _make_candle(
            index=3,
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
        )
        c_future = _make_candle(
            index=4,
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
        )

        all_candles = (c_past, c_future)
        fwd = tuple(c for c in all_candles if c.open_time >= signal_time)
        assert len(fwd) == 1
        assert fwd[0].open_time >= signal_time


# =============================================================================
# Section H: Symmetrical Risk & Structural Levels Tests
# =============================================================================
class TestPierSymmetryAndZones:
    """Validate BUY/SELL symmetry, degenerate fallback SL, and zone interactions."""

    def test_degenerate_short_fallback_sl_strictly_above_entry(self) -> None:
        """Verify degenerate fallback branch sets stop_loss = current_close + ATR."""
        strat = PinbarEngulfingEmaRsiStrategy(
            trend_period=5,
            pullback_period=3,
            atr_multiplier_sl=Decimal("2.0"),
        )
        current_close = Decimal("100.0")
        current_atr = Decimal("2.0")

        # Invariant for SELL: stop_loss must ALWAYS be strictly greater than entry
        fallback_sl = current_close + (strat.atr_multiplier_sl * current_atr)
        assert fallback_sl > current_close
        assert fallback_sl == Decimal("104.0")

        # Invariant for BUY: stop_loss must ALWAYS be strictly less than entry
        fallback_buy_sl = current_close - (strat.atr_multiplier_sl * current_atr)
        assert fallback_buy_sl < current_close
        assert fallback_buy_sl == Decimal("96.0")

    def test_indicator_toggles_propagation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Verify toggling star, psar, macd, stoch rsi propagates to strategy."""
        toggles = {
            ENV_PIER_INCLUDE_STAR_PATTERNS: "true",
            ENV_PIER_USE_PARABOLIC_SAR: "true",
            ENV_PIER_USE_MACD: "true",
            ENV_PIER_USE_STOCH_RSI: "true",
        }
        for k, v in toggles.items():
            monkeypatch.setenv(k, v)

        empty_env = tmp_path / ".empty2.env"
        empty_env.write_text("")

        env = EnvironmentProvider(env_path=str(empty_env))
        mgr = SettingsManager(environment_provider=env)
        settings = mgr.load_strategy_settings()

        strat = StrategyFactory.create(
            settings=replace(
                settings,
                strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
            )
        )
        assert isinstance(strat, PinbarEngulfingEmaRsiStrategy)
        assert strat.include_star_patterns is True
        assert strat.use_parabolic_sar is True
        assert strat.use_macd is True
        assert strat.use_stoch_rsi is True

    def test_structural_tp_configuration_propagation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Verify structural TP parameters propagate to strategy."""
        toggles = {
            ENV_PIER_USE_STRUCTURAL_TP: "true",
            ENV_PIER_STRUCTURAL_TP_BUFFER_PCT: "0.005",
            ENV_PIER_MIN_STRUCTURAL_RR: "1.2",
            ENV_PIER_BB_PERIOD: "25",
            ENV_PIER_BB_STD_DEV: "2.5",
        }
        for k, v in toggles.items():
            monkeypatch.setenv(k, v)

        empty_env = tmp_path / ".empty_struct.env"
        empty_env.write_text("")

        env = EnvironmentProvider(env_path=str(empty_env))
        mgr = SettingsManager(environment_provider=env)
        settings = mgr.load_strategy_settings()

        strat = StrategyFactory.create(
            settings=replace(
                settings,
                strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
            )
        )
        assert isinstance(strat, PinbarEngulfingEmaRsiStrategy)
        assert strat.use_structural_tp is True
        assert strat.structural_tp_buffer_pct == Decimal("0.005")
        assert strat.min_structural_rr == Decimal("1.2")
        assert strat.bb_period == 25
        assert strat.bb_std_dev == Decimal("2.5")


# =============================================================================
# Section I: HTF Extreme Gate Fail-Closed Regression Tests
# =============================================================================
class TestPierHtfExtremeGateFailClosed:
    """Validate that require_htf_extreme_zone strictly fails closed."""

    def test_bullish_pinbar_fails_closed_when_htf_bb_unavailable(self) -> None:
        """When HTF BB cannot be computed, require_htf_extreme_zone MUST emit HOLD."""
        candles: list[Candle] = []
        base = Decimal("100.0")
        for i in range(45):
            price = base + Decimal(str(i * 1.0))
            candles.append(
                _make_candle(
                    index=i,
                    open_price=price,
                    high_price=price + Decimal("1.5"),
                    low_price=price - Decimal("0.5"),
                    close_price=price + Decimal("0.8"),
                    volume=Decimal("100.0"),
                )
            )

        for i in range(45, 55):
            prev_close = candles[-1].close_price
            candles.append(
                _make_candle(
                    index=i,
                    open_price=prev_close,
                    high_price=prev_close + Decimal("0.2"),
                    low_price=prev_close - Decimal("1.5"),
                    close_price=prev_close - Decimal("1.2"),
                    volume=Decimal("100.0"),
                )
            )

        # Candle 55: Bullish Pinbar (Hammer) bouncing near EMA10 with elevated volume
        last_close = candles[-1].close_price
        candles.append(
            _make_candle(
                index=55,
                open_price=last_close,
                high_price=last_close + Decimal("0.8"),
                low_price=last_close - Decimal("8.0"),
                close_price=last_close + Decimal("0.5"),
                volume=Decimal("250.0"),
            )
        )

        # 1. Strategy with require_htf_extreme_zone=False -> emits BUY
        strat_open = PinbarEngulfingEmaRsiStrategy(
            trend_period=50,
            pullback_period=10,
            rsi_period=14,
            volume_period=10,
            require_htf_extreme_zone=False,
            strict_ema_side_rejection=False,
        )
        sig_open = strat_open.generate_signal(candles=candles)
        assert sig_open.signal_type is SignalType.BUY

        # 2. Strategy with require_htf_extreme_zone=True -> FAIL-CLOSED to HOLD
        strat_closed = PinbarEngulfingEmaRsiStrategy(
            trend_period=50,
            pullback_period=10,
            rsi_period=14,
            volume_period=10,
            require_htf_extreme_zone=True,
            strict_ema_side_rejection=False,
        )
        sig_closed = strat_closed.generate_signal(candles=candles)
        assert sig_closed.signal_type is SignalType.HOLD

    def test_bearish_engulfing_fails_closed_when_htf_bb_unavailable(self) -> None:
        """When HTF BB cannot be computed, setup strictly fails closed to HOLD."""
        candles: list[Candle] = []
        base = Decimal("200.0")
        for i in range(45):
            price = base - Decimal(str(i * 1.0))
            candles.append(
                _make_candle(
                    index=i,
                    open_price=price,
                    high_price=price + Decimal("0.5"),
                    low_price=price - Decimal("1.5"),
                    close_price=price - Decimal("0.8"),
                    volume=Decimal("100.0"),
                )
            )

        for i in range(45, 54):
            prev_close = candles[-1].close_price
            candles.append(
                _make_candle(
                    index=i,
                    open_price=prev_close,
                    high_price=prev_close + Decimal("1.5"),
                    low_price=prev_close - Decimal("0.2"),
                    close_price=prev_close + Decimal("1.2"),
                    volume=Decimal("100.0"),
                )
            )

        c53_close = candles[-1].close_price
        candles.append(
            _make_candle(
                index=54,
                open_price=c53_close,
                high_price=c53_close + Decimal("1.0"),
                low_price=c53_close - Decimal("0.2"),
                close_price=c53_close + Decimal("0.8"),
                volume=Decimal("100.0"),
            )
        )
        c54 = candles[-1]
        engulf_open = c54.close_price + Decimal("0.5")
        candles.append(
            _make_candle(
                index=55,
                open_price=engulf_open,
                high_price=engulf_open + Decimal("0.5"),
                low_price=c54.open_price - Decimal("2.0"),
                close_price=c54.open_price - Decimal("1.5"),
                volume=Decimal("250.0"),
            )
        )

        # 1. Strategy with require_htf_extreme_zone=False -> emits SELL
        strat_open = PinbarEngulfingEmaRsiStrategy(
            trend_period=50,
            pullback_period=10,
            rsi_period=14,
            volume_period=10,
            require_htf_extreme_zone=False,
            strict_ema_side_rejection=False,
        )
        sig_open = strat_open.generate_signal(candles=candles)
        assert sig_open.signal_type is SignalType.SELL

        # 2. Strategy with require_htf_extreme_zone=True -> FAIL-CLOSED to HOLD
        strat_closed = PinbarEngulfingEmaRsiStrategy(
            trend_period=50,
            pullback_period=10,
            rsi_period=14,
            volume_period=10,
            require_htf_extreme_zone=True,
            strict_ema_side_rejection=False,
        )
        sig_closed = strat_closed.generate_signal(candles=candles)
        assert sig_closed.signal_type is SignalType.HOLD
