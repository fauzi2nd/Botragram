"""
Botragram

Description:
    Service managing multi-bar setup stalking and retest observation for
    high-confluence setups, preventing premature entries and invalidating
    weakened signals with zero capital loss.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

import logging
import threading

# =============================================================================
# Standard Library Imports
# =============================================================================
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    PositionSide,
    SignalType,
    StalkingStatus,
    StrategyType,
)
from botragram.indicators import detect_engulfing, detect_pinbar
from botragram.models import Candle, Signal
from botragram.models.stalking import StalkingFunnelReport, StalkingSetup

__all__ = [
    "SetupStalkingService",
    "StalkingSetupProvider",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_RETEST_RATIO: Final[Decimal] = Decimal("0.50")
_MAX_HISTORY_ENTRIES: Final[int] = 10


class StalkingSetupProvider(Protocol):
    """Protocol for reading active and recently stalked candidate setups."""

    @property
    def is_paused(self) -> bool:
        """Return whether setup stalking is currently paused."""
        ...

    def get_active_stalking_setups(self) -> tuple[StalkingSetup, ...]:
        """Return active or recently completed stalking setups."""
        ...

    def clear_all(self) -> None:
        """Clear all tracked setups."""
        ...

    def set_paused(self, paused: bool) -> None:
        """Pause or resume setup stalking operations."""
        ...

    def get_funnel_report(self) -> StalkingFunnelReport:
        """Return a telemetry report of the stalking funnel."""
        ...

    def invalidate_setup(
        self,
        symbol: str,
        reason: str = "Execution guard rejected",
    ) -> StalkingSetup | None:
        """Explicitly invalidate a setup."""
        ...


class SetupStalkingService:
    """Track and observe candidate setups across 1-7 subsequent bars."""

    def __init__(
        self,
        *,
        max_candidates: int = 5,
        default_max_bars: int = 7,
        retest_ratio: Decimal = _DEFAULT_RETEST_RATIO,
    ) -> None:
        if max_candidates <= 0:
            raise ValueError("Max candidates must be positive")
        if default_max_bars <= 0:
            raise ValueError("Default max bars must be positive")
        if not (Decimal("0.0") <= retest_ratio <= Decimal("1.0")):
            raise ValueError("Retest ratio must be between 0.0 and 1.0")

        self._max_candidates: Final[int] = max_candidates
        self._default_max_bars: Final[int] = default_max_bars
        self._retest_ratio: Final[Decimal] = retest_ratio
        self._lock: Final[threading.Lock] = threading.Lock()
        self._setups: dict[str, StalkingSetup] = {}
        self._paused: bool = False

        # Telemetry funnel tracking
        self._funnel_scanned: int = 0
        self._funnel_zone_candidates: int = 0
        self._funnel_registered: int = 0
        self._funnel_reversal_confirmed: int = 0
        self._funnel_retest_touched: int = 0
        self._funnel_triggered: int = 0
        self._funnel_invalidated: int = 0
        self._funnel_expired: int = 0
        self._funnel_rejections: dict[str, int] = {}
        self._completed_stalking_bars: list[int] = []

    def record_scan(self, count: int = 1) -> None:
        """Record scanned candle count for telemetry funnel."""
        if count <= 0:
            return
        with self._lock:
            self._funnel_scanned += count

    def record_zone_candidate(self, count: int = 1) -> None:
        """Record detected zone candidate count for telemetry funnel."""
        if count <= 0:
            return
        with self._lock:
            self._funnel_zone_candidates += count

    def record_rejection(self, reason: str, count: int = 1) -> None:
        """Record candidate rejection reason for telemetry funnel."""
        if count <= 0:
            return
        clean_reason = reason.strip() or "Unspecified"
        with self._lock:
            self._funnel_rejections[clean_reason] = (
                self._funnel_rejections.get(clean_reason, 0) + count
            )

    def reset_funnel_telemetry(self) -> None:
        """Reset all funnel telemetry counters."""
        with self._lock:
            self._funnel_scanned = 0
            self._funnel_zone_candidates = 0
            self._funnel_registered = 0
            self._funnel_reversal_confirmed = 0
            self._funnel_retest_touched = 0
            self._funnel_triggered = 0
            self._funnel_invalidated = 0
            self._funnel_expired = 0
            self._funnel_rejections.clear()
            self._completed_stalking_bars.clear()

    def get_funnel_report(self) -> StalkingFunnelReport:
        """Return a snapshot of the current stalking conversion funnel."""
        with self._lock:
            rejected_before = max(
                0, self._funnel_scanned - self._funnel_zone_candidates
            )
            avg_bars = (
                (
                    Decimal(sum(self._completed_stalking_bars))
                    / Decimal(len(self._completed_stalking_bars))
                ).quantize(Decimal("0.1"))
                if self._completed_stalking_bars
                else Decimal("0.0")
            )
            return StalkingFunnelReport(
                scanned_count=self._funnel_scanned,
                zone_candidates=self._funnel_zone_candidates,
                rejected_before_register=rejected_before,
                registered=self._funnel_registered,
                reversal_confirmed=self._funnel_reversal_confirmed,
                retest_touched=self._funnel_retest_touched,
                triggered=self._funnel_triggered,
                invalidated=self._funnel_invalidated,
                expired=self._funnel_expired,
                rejections_by_reason=dict(self._funnel_rejections),
                average_stalking_bars=avg_bars,
            )

    def format_funnel_summary(self) -> str:
        """Return a formatted string of the stalking funnel radar."""
        return self.get_funnel_report().format_funnel_summary()

    @property
    def max_candidates(self) -> int:
        """Return the maximum allowed concurrent stalking candidates."""
        return self._max_candidates

    @property
    def is_paused(self) -> bool:
        """Return whether setup stalking is currently paused."""
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> None:
        """Pause or resume setup stalking operations.

        When paused (e.g. position capacity reached), all active setups
        are cleared to present a clean radar, and subsequent registrations
        or candle updates are skipped.
        """
        with self._lock:
            if self._paused == paused:
                return
            self._paused = paused
            if paused:
                self._setups.clear()
                _LOGGER.info(
                    "Setup stalking paused (slots full): cleared all candidates"
                )
            else:
                _LOGGER.info("Setup stalking resumed: position slots available")

    def clear_all(self) -> None:
        """Clear all tracked setups and history."""
        with self._lock:
            if not self._setups:
                return
            self._setups.clear()
            _LOGGER.info("Cleared all setup stalking candidates")

    def register_candidate(
        self,
        *,
        signal: Signal,
        setup_candle: Candle,
        htf_zone_label: str = "HTF Extreme",
        max_bars: int | None = None,
        retest_ratio: Decimal | None = None,
        reversal_confirmed: bool | None = None,
    ) -> StalkingSetup | None:
        """Register a new candidate setup for subsequent bar stalking.

        Returns:
            The registered StalkingSetup if accepted, or None if capacity is full
            or an active stalking setup already exists for this symbol.
        """
        now = datetime.now(UTC)
        ratio = retest_ratio if retest_ratio is not None else self._retest_ratio
        bars_limit = max_bars if max_bars is not None else self._default_max_bars

        if signal.signal_type is SignalType.BUY:
            side = PositionSide.LONG
        elif signal.signal_type is SignalType.SELL:
            side = PositionSide.SHORT
        elif "[STALKING_ZONE_LONG]" in (signal.reason or "") or "LONG" in (
            signal.reason or ""
        ):
            side = PositionSide.LONG
        else:
            side = PositionSide.SHORT

        with self._lock:
            if self._paused:
                self._funnel_rejections["Paused"] = (
                    self._funnel_rejections.get("Paused", 0) + 1
                )
                _LOGGER.debug(
                    "Setup stalking paused (slots full); skipping candidate %s",
                    signal.symbol,
                )
                return None

            existing = self._setups.get(signal.symbol)
            if existing is not None and existing.status is StalkingStatus.STALKING:
                _LOGGER.debug(
                    "Stalking setup already active for %s; skipping duplicate",
                    signal.symbol,
                )
                return existing

            if (
                existing is not None
                and existing.last_processed_candle_close_time is not None
                and setup_candle.close_time <= existing.last_processed_candle_close_time
            ):
                self._funnel_rejections["Duplicate"] = (
                    self._funnel_rejections.get("Duplicate", 0) + 1
                )
                _LOGGER.debug(
                    "Setup candle close_time %s already processed for %s; "
                    "skipping duplicate registration",
                    setup_candle.close_time,
                    signal.symbol,
                )
                return None

            active_count = sum(
                1 for s in self._setups.values() if s.status is StalkingStatus.STALKING
            )
            if active_count >= self._max_candidates:
                self._funnel_rejections["Capacity full"] = (
                    self._funnel_rejections.get("Capacity full", 0) + 1
                )
                _LOGGER.info(
                    "Setup stalking capacity reached (%d/%d); skipping %s",
                    active_count,
                    self._max_candidates,
                    signal.symbol,
                )
                return None

            if "[STALKING_ZONE_LONG]" in (signal.reason or ""):
                pattern = "ZONE_LONG"
            elif "[STALKING_ZONE_SHORT]" in (signal.reason or ""):
                pattern = "ZONE_SHORT"
            elif signal.reason and "ENGULF" in signal.reason.upper():
                pattern = "ENGULFING"
            elif signal.reason and "PINBAR" in signal.reason.upper():
                pattern = "PINBAR"
            elif signal.reason and "STAR" in signal.reason.upper():
                pattern = "STAR"
            elif signal.reason and "REVERSAL" in signal.reason.upper():
                pattern = "REVERSAL"
            else:
                pattern = "ZONE"

            if reversal_confirmed is not None:
                rev_confirmed = reversal_confirmed
            elif signal.signal_type in {SignalType.BUY, SignalType.SELL}:
                rev_confirmed = True
            else:
                rev_confirmed = pattern in {
                    "ENGULFING",
                    "PINBAR",
                    "STAR",
                    "REVERSAL",
                } and not pattern.startswith("ZONE")

            body_high = max(setup_candle.open_price, setup_candle.close_price)
            body_low = min(setup_candle.open_price, setup_candle.close_price)
            body_size = body_high - body_low

            if side is PositionSide.SHORT:
                invalidation_price = setup_candle.high_price
                if rev_confirmed:
                    target_retest = (
                        body_low + (body_size * ratio)
                        if body_size > _DECIMAL_ZERO
                        else setup_candle.close_price
                    )
                else:
                    target_retest = setup_candle.close_price
            else:
                invalidation_price = setup_candle.low_price
                if rev_confirmed:
                    target_retest = (
                        body_high - (body_size * ratio)
                        if body_size > _DECIMAL_ZERO
                        else setup_candle.close_price
                    )
                else:
                    target_retest = setup_candle.close_price

            setup = StalkingSetup(
                symbol=signal.symbol,
                side=side,
                pattern_name=pattern,
                anchor_price=setup_candle.close_price,
                invalidation_price=invalidation_price,
                target_retest_price=target_retest,
                htf_zone_label=htf_zone_label,
                current_bar=0,
                max_bars=bars_limit,
                started_at=now,
                updated_at=now,
                status=StalkingStatus.STALKING,
                strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
                interval=setup_candle.interval,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                confidence=signal.confidence,
                last_processed_candle_close_time=setup_candle.close_time,
                reversal_confirmed=rev_confirmed,
            )

            self._setups[signal.symbol] = setup
            self._funnel_registered += 1
            self._prune_history_locked()

            _LOGGER.info(
                "Registered setup stalking: symbol=%s side=%s pattern=%s "
                "anchor=%s retest_target=%s invalidation=%s max_bars=%d zone=%s "
                "reversal_confirmed=%s",
                setup.symbol,
                setup.side.value,
                setup.pattern_name,
                setup.anchor_price,
                setup.target_retest_price,
                setup.invalidation_price,
                setup.max_bars,
                setup.htf_zone_label,
                setup.reversal_confirmed,
            )
            return setup

    @staticmethod
    def _detect_reversal(
        *,
        candle: Candle,
        prev_candle: Candle | None,
        side: PositionSide,
    ) -> tuple[bool, str]:
        """Detect whether candle forms a valid reversal confirmation."""
        pinbar = detect_pinbar(candle=candle, min_wick_ratio=Decimal("0.50"))
        if pinbar.matched and pinbar.side is side:
            pattern = (
                "BEARISH_PINBAR" if side is PositionSide.SHORT else "BULLISH_PINBAR"
            )
            return True, pattern

        if prev_candle is not None:
            engulf = detect_engulfing(
                prev_candle=prev_candle,
                curr_candle=candle,
                min_body_ratio=Decimal("1.0"),
            )
            if engulf.matched and engulf.side is side:
                pattern = (
                    "BEARISH_ENGULFING"
                    if side is PositionSide.SHORT
                    else "BULLISH_ENGULFING"
                )
                return True, pattern

        body = abs(candle.close_price - candle.open_price)
        if side is PositionSide.SHORT:
            upper_wick = candle.high_price - max(candle.open_price, candle.close_price)
            is_bearish = candle.close_price < candle.open_price
            has_upper_wick = candle.high_price > candle.open_price
            if is_bearish and has_upper_wick and upper_wick >= body * Decimal("0.3"):
                return True, "BEARISH_REJECTION"
        else:
            lower_wick = min(candle.open_price, candle.close_price) - candle.low_price
            is_bullish = candle.close_price > candle.open_price
            has_lower_wick = candle.low_price < candle.open_price
            if is_bullish and has_lower_wick and lower_wick >= body * Decimal("0.3"):
                return True, "BULLISH_REJECTION"

        return False, ""

    def on_candle_update(
        self,
        candle: Candle,
        prev_candle: Candle | None = None,
    ) -> StalkingSetup | None:
        """Process a newly closed bar for a stalked symbol.

        Evaluates:
        1. Invalidation: Price violates anchor extreme peak/valley.
        2. Reversal confirmation: Confirms rejection in stalked zone if pending.
        3. Retest trigger: Price tests target zone with reversal confirmation.
        4. Expiry: Bar window reaches limit without entry.

        Returns:
            The updated setup if state changed, or None.
        """
        now = datetime.now(UTC)

        with self._lock:
            if self._paused:
                return None

            setup = self._setups.get(candle.symbol)
            if setup is None or setup.status is not StalkingStatus.STALKING:
                return None

            if candle.interval is not setup.interval:
                _LOGGER.debug(
                    "Skipping candle update for %s: interval mismatch (%s != %s)",
                    candle.symbol,
                    candle.interval.value,
                    setup.interval.value,
                )
                return setup

            if (
                setup.last_processed_candle_close_time is not None
                and candle.close_time <= setup.last_processed_candle_close_time
            ):
                _LOGGER.debug(
                    "Stalking candle update skipped (duplicate/stale): "
                    "symbol=%s candle_close=%s last_processed=%s current_bar=%d",
                    candle.symbol,
                    candle.close_time,
                    setup.last_processed_candle_close_time,
                    setup.current_bar,
                )
                return setup

            next_bar = setup.current_bar + 1

            # 1. Check Invalidation: Peak/Valley breach
            if setup.side is PositionSide.SHORT:
                if candle.high_price > setup.invalidation_price:
                    self._funnel_invalidated += 1
                    self._completed_stalking_bars.append(next_bar)
                    updated = replace(
                        setup,
                        current_bar=next_bar,
                        status=StalkingStatus.INVALIDATED,
                        updated_at=now,
                        last_processed_candle_close_time=candle.close_time,
                    )
                    self._setups[candle.symbol] = updated
                    _LOGGER.info(
                        "Setup stalking INVALIDATED: symbol=%s side=SHORT "
                        "bar=%d/%d candle_high=%s breached anchor_high=%s (0 loss)",
                        candle.symbol,
                        next_bar,
                        setup.max_bars,
                        candle.high_price,
                        setup.invalidation_price,
                    )
                    return updated
            else:
                if candle.low_price < setup.invalidation_price:
                    self._funnel_invalidated += 1
                    self._completed_stalking_bars.append(next_bar)
                    updated = replace(
                        setup,
                        current_bar=next_bar,
                        status=StalkingStatus.INVALIDATED,
                        updated_at=now,
                        last_processed_candle_close_time=candle.close_time,
                    )
                    self._setups[candle.symbol] = updated
                    _LOGGER.info(
                        "Setup stalking INVALIDATED: symbol=%s side=LONG "
                        "bar=%d/%d candle_low=%s breached anchor_low=%s (0 loss)",
                        candle.symbol,
                        next_bar,
                        setup.max_bars,
                        candle.low_price,
                        setup.invalidation_price,
                    )
                    return updated

            # 2. Check Reversal Confirmation (Stage 2A) if pending
            if not setup.reversal_confirmed:
                reversal_matched, pattern_name = self._detect_reversal(
                    candle=candle,
                    prev_candle=prev_candle,
                    side=setup.side,
                )
                if reversal_matched:
                    body_high = max(candle.open_price, candle.close_price)
                    body_low = min(candle.open_price, candle.close_price)
                    body_size = body_high - body_low
                    if setup.side is PositionSide.SHORT:
                        target_retest = (
                            body_low + (body_size * self._retest_ratio)
                            if body_size > _DECIMAL_ZERO
                            else candle.close_price
                        )
                        invalidation_price = candle.high_price
                        stop_loss = (
                            max(candle.high_price, setup.stop_loss)
                            if setup.stop_loss is not None
                            else candle.high_price
                        )
                    else:
                        target_retest = (
                            body_high - (body_size * self._retest_ratio)
                            if body_size > _DECIMAL_ZERO
                            else candle.close_price
                        )
                        invalidation_price = candle.low_price
                        stop_loss = (
                            min(candle.low_price, setup.stop_loss)
                            if setup.stop_loss is not None
                            else candle.low_price
                        )

                    self._funnel_reversal_confirmed += 1
                    updated = replace(
                        setup,
                        current_bar=next_bar,
                        reversal_confirmed=True,
                        anchor_price=candle.close_price,
                        invalidation_price=invalidation_price,
                        target_retest_price=target_retest,
                        pattern_name=pattern_name,
                        stop_loss=stop_loss,
                        updated_at=now,
                        last_processed_candle_close_time=candle.close_time,
                    )
                    self._setups[candle.symbol] = updated
                    _LOGGER.info(
                        "Setup stalking REVERSAL CONFIRMED: symbol=%s side=%s "
                        "pattern=%s retest_target=%s invalidation=%s bar=%d/%d",
                        candle.symbol,
                        setup.side.value,
                        pattern_name,
                        target_retest,
                        invalidation_price,
                        next_bar,
                        setup.max_bars,
                    )
                    return updated

            # 3. Check Retest Trigger (Stage 2B) if reversal confirmed
            elif setup.reversal_confirmed:
                triggered = False
                candle_range = candle.high_price - candle.low_price
                if candle_range > _DECIMAL_ZERO:
                    if setup.side is PositionSide.SHORT:
                        # Retrace touches target AND rejects back down with upper wick
                        upper_wick = candle.high_price - max(
                            candle.open_price, candle.close_price
                        )
                        lower_wick = (
                            min(candle.open_price, candle.close_price)
                            - candle.low_price
                        )
                        rejection_ratio = upper_wick / candle_range
                        open_tol = candle_range * Decimal("0.10")
                        is_red_or_flat = candle.close_price <= candle.open_price
                        bearish_rejection = is_red_or_flat or (upper_wick >= lower_wick)
                        if (
                            candle.high_price >= setup.target_retest_price
                            and candle.close_price <= setup.target_retest_price
                            and candle.open_price
                            <= setup.target_retest_price + open_tol
                            and rejection_ratio >= Decimal("0.15")
                            and candle.close_price < candle.high_price
                            and bearish_rejection
                        ):
                            triggered = True
                    else:
                        # Pullback touches target AND bounces back up with lower wick
                        lower_wick = (
                            min(candle.open_price, candle.close_price)
                            - candle.low_price
                        )
                        upper_wick = candle.high_price - max(
                            candle.open_price, candle.close_price
                        )
                        rejection_ratio = lower_wick / candle_range
                        open_tol = candle_range * Decimal("0.10")
                        is_green_or_flat = candle.close_price >= candle.open_price
                        bullish_bounce = is_green_or_flat or (lower_wick >= upper_wick)
                        if (
                            candle.low_price <= setup.target_retest_price
                            and candle.close_price >= setup.target_retest_price
                            and candle.open_price
                            >= setup.target_retest_price - open_tol
                            and rejection_ratio >= Decimal("0.15")
                            and candle.close_price > candle.low_price
                            and bullish_bounce
                        ):
                            triggered = True

                if triggered:
                    self._funnel_retest_touched += 1
                    self._funnel_triggered += 1
                    self._completed_stalking_bars.append(next_bar)
                    updated = replace(
                        setup,
                        current_bar=next_bar,
                        status=StalkingStatus.TRIGGERED,
                        updated_at=now,
                        last_processed_candle_close_time=candle.close_time,
                    )
                    self._setups[candle.symbol] = updated
                    _LOGGER.info(
                        "Setup stalking TRIGGERED: symbol=%s side=%s bar=%d/%d "
                        "retest target reached at %s",
                        candle.symbol,
                        setup.side.value,
                        next_bar,
                        setup.max_bars,
                        setup.target_retest_price,
                    )
                    return updated

            # 4. Check Expiry
            if next_bar >= setup.max_bars:
                self._funnel_expired += 1
                self._completed_stalking_bars.append(next_bar)
                updated = replace(
                    setup,
                    current_bar=next_bar,
                    status=StalkingStatus.EXPIRED,
                    updated_at=now,
                    last_processed_candle_close_time=candle.close_time,
                )
                self._setups[candle.symbol] = updated
                _LOGGER.info(
                    "Setup stalking EXPIRED: symbol=%s bar=%d/%d (no entry)",
                    candle.symbol,
                    next_bar,
                    setup.max_bars,
                )
                return updated

            # Continue stalking
            updated = replace(
                setup,
                current_bar=next_bar,
                updated_at=now,
                last_processed_candle_close_time=candle.close_time,
            )
            self._setups[candle.symbol] = updated
            return updated

    def get_active_stalking_setups(self) -> tuple[StalkingSetup, ...]:
        """Return tracked setups, prioritizing TRIGGERED then active STALKING."""
        with self._lock:
            if self._paused:
                return ()

            triggered: list[StalkingSetup] = []
            stalking: list[StalkingSetup] = []
            completed: list[StalkingSetup] = []

            for setup in self._setups.values():
                if setup.status is StalkingStatus.TRIGGERED:
                    triggered.append(setup)
                elif setup.status is StalkingStatus.STALKING:
                    stalking.append(setup)
                else:
                    completed.append(setup)

            # Sort triggered by updated_at desc (most recent triggers first)
            triggered.sort(key=lambda s: s.updated_at, reverse=True)
            # Sort stalking by current_bar desc, then started_at desc
            stalking.sort(key=lambda s: (s.current_bar, s.started_at), reverse=True)
            # Sort completed by updated_at desc
            completed.sort(key=lambda s: s.updated_at, reverse=True)

            primary = triggered + stalking
            remaining_slots = max(0, self._max_candidates - len(primary))
            return tuple(primary + completed[:remaining_slots])

    def get_setup(self, symbol: str) -> StalkingSetup | None:
        """Return the current setup for a symbol, if any."""
        with self._lock:
            return self._setups.get(symbol)

    def set_setup_for_testing(self, setup: StalkingSetup) -> None:
        """Inject or update a setup directly for testing purposes."""
        with self._lock:
            self._setups[setup.symbol] = setup

    def invalidate_setup(
        self,
        symbol: str,
        reason: str = "Execution guard rejected",
    ) -> StalkingSetup | None:
        """Explicitly invalidate a setup (e.g. if execution guards reject entry)."""
        now = datetime.now(UTC)
        with self._lock:
            setup = self._setups.get(symbol)
            if setup is None:
                return None
            self._funnel_invalidated += 1
            updated = replace(
                setup,
                status=StalkingStatus.INVALIDATED,
                updated_at=now,
            )
            self._setups[symbol] = updated
            _LOGGER.info(
                "Setup stalking manually INVALIDATED: symbol=%s reason=%s",
                symbol,
                reason,
            )
            return updated

    def get_active_stalking_symbols(self) -> tuple[str, ...]:
        """Return symbols currently in active STALKING status."""
        with self._lock:
            if self._paused:
                return ()

            return tuple(
                s.symbol
                for s in self._setups.values()
                if s.status is StalkingStatus.STALKING
            )

    def build_triggered_signal(
        self,
        *,
        setup: StalkingSetup,
        trigger_candle: Candle,
    ) -> Signal:
        """Build an actionable entry Signal from a TRIGGERED stalking setup."""
        sig_type = (
            SignalType.BUY if setup.side is PositionSide.LONG else SignalType.SELL
        )
        entry_price = trigger_candle.close_price
        stop_loss = setup.stop_loss
        take_profit = setup.take_profit

        # Maintain valid Risk:Reward ratio relative to actual entry price
        if stop_loss is not None and take_profit is not None:
            actual_risk = abs(entry_price - stop_loss)
            orig_risk = abs(setup.anchor_price - stop_loss)
            orig_reward = abs(take_profit - setup.anchor_price)
            rr_ratio = (
                orig_reward / orig_risk if orig_risk > _DECIMAL_ZERO else Decimal("2.0")
            )

            # If setup was planned with >= 1.5R, but trigger candle close compressed
            # actual reward below 1.0R (or inverted TP), project take_profit.
            actual_reward = abs(take_profit - entry_price)
            is_inverted_tp = (
                sig_type is SignalType.BUY and take_profit <= entry_price
            ) or (sig_type is SignalType.SELL and take_profit >= entry_price)
            is_reward_exhausted = (
                rr_ratio >= Decimal("1.5")
                and actual_risk > _DECIMAL_ZERO
                and (
                    actual_reward < actual_risk * Decimal("1.0")
                    or actual_reward < orig_reward * Decimal("0.60")
                )
            )
            if is_inverted_tp or is_reward_exhausted:
                min_rr = max(Decimal("1.5"), min(rr_ratio, Decimal("2.5")))
                if sig_type is SignalType.BUY:
                    take_profit = entry_price + (actual_risk * min_rr)
                else:
                    take_profit = entry_price - (actual_risk * min_rr)

        # Boost confidence if the reversal pattern was a decisive Pinbar or Engulfing
        final_confidence = setup.confidence
        if "PINBAR" in setup.pattern_name or "ENGULFING" in setup.pattern_name:
            final_confidence = min(Decimal("0.95"), final_confidence + Decimal("0.05"))

        return Signal(
            symbol=setup.symbol,
            signal_type=sig_type,
            price=entry_price,
            confidence=final_confidence,
            strategy_name=setup.strategy_type.value,
            generated_at=trigger_candle.close_time,
            reason=(
                f"[STALKING_TRIGGERED] {setup.pattern_name} "
                f"retest@{setup.target_retest_price} confirmed on bar "
                f"{setup.current_bar}/{setup.max_bars} ({setup.htf_zone_label})"
            ),
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def remove_setup(self, symbol: str) -> None:
        """Remove a setup from tracking."""
        with self._lock:
            self._setups.pop(symbol, None)

    def _prune_history_locked(self) -> None:
        """Prune old inactive setups beyond retention limit."""
        inactive_keys = [
            k
            for k, v in self._setups.items()
            if v.status is not StalkingStatus.STALKING
        ]
        if len(inactive_keys) > _MAX_HISTORY_ENTRIES:
            # Sort by updated_at ascending and remove oldest
            inactive_items = sorted(
                [(k, self._setups[k].updated_at) for k in inactive_keys],
                key=lambda x: x[1],
            )
            for k, _ in inactive_items[: len(inactive_keys) - _MAX_HISTORY_ENTRIES]:
                self._setups.pop(k, None)
