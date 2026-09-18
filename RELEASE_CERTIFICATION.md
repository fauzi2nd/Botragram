# Botragram Release Certification Report

**Target Version:** `v2.7.11`<br>
**Date:** 2026-09-18<br>
**Environment:** Windows 11 (Python 3.14.6)<br>
**Status:** **RELEASE CERTIFICATION: PASS**

---

## 1. Executive Summary

This certification report provides definitive, auditable verification for Botragram's protection state machine, fallback reconciliation safety, error handling patterns, typing discipline, and accounting integrity.

Every metric, test count, and status claim in this document was directly executed on the local Windows worktree and verified against actual command outputs and exit codes.

**Final Hardening (v2.7.11):** Removed the two remaining unsafe position-delta inference paths from `_resume_pending_partial_take_profit()` and replaced them with a strict fail-closed model. The authoritative exchange order lookup is now the exclusive source for mutating position state.

---

## 2. Authoritative Windows Quality Gates Audit

Per `DEVELOPMENT_GUIDE.md` Sections 19 & 20, all release quality gates were executed locally on the Windows development worktree. Every gate executed successfully with zero failures.

| # | Quality Gate Command | Status | Exit Code | Result / Output Summary | Duration |
|---|---|:---:|:---:|---|:---:|
| 1 | `python -m compileall -q botragram tests main.py` | **PASS** | `0` | All production packages, tests, and entry point compiled cleanly. | ~1.2s |
| 2 | `python -c "import main"` | **PASS** | `0` | Bootstrap module import, composition root, and symbols load cleanly. | ~1.1s |
| 3 | `python -m ruff format --check .` | **PASS** | `0` | 501 files checked; 501 files fully compliant with project formatting rules. | ~0.6s |
| 4 | `python -m ruff check .` | **PASS** | `0` | All checks passed; 0 lint errors, 0 warnings. | ~0.7s |
| 5 | `python -m pyright` | **PASS** | `0` | 0 errors, 0 warnings, 0 informations under strict type-checking configuration. | ~14.0s |
| 6 | `python -m mypy botragram` | **PASS** | `0` | Success: no issues found in 352 source files. | ~2.5s |
| 7 | `pyrefly check` | **PASS** | `0` | 0 errors across project configuration. | ~2.0s |
| 8 | `python -m pytest` | **PASS** | `0` | **1575 passed** in 39.61s (100% pass rate across entire test suite). | 39.61s |
| 9 | `git diff --check` | **PASS** | `0` | Clean diff; no whitespace errors or merge conflict markers. | ~0.5s |

### Specialized Regression Suites

| Suite | Status | Exit Code | Result Summary | Duration |
|---|:---:|:---:|---|:---:|
| `python -m pytest tests/test_position_protection.py -q` | **PASS** | `0` | 41 passed | ~1.2s |
| `python -m pytest tests/test_partial_tp_hardening.py -q` | **PASS** | `0` | 23 passed | ~1.8s |

---

## 3. Forbidden Exception Patterns Audit

Per `DEVELOPMENT_GUIDE.md` Section 14, bare `except:`, `except Exception: pass`, and silently swallowed `asyncio.CancelledError` are prohibited in production packages.

An AST-based exhaustive scan across all production modules in `botragram/` confirms:
* **Bare `except:` count:** `0`
* **`except Exception: pass` count:** `0`
* **`pass`-only exception handlers:** `0`
* **Swallowed `asyncio.CancelledError`:** `0`

All previously discovered occurrences were remediated with specific exception types and structured logging:
1. `botragram/exchanges/bitget/futures_client.py`: Caught `(ExchangeError, ExchangeOrderNotFoundError, BitgetRestResponseError)` with `_LOGGER.debug` for order lookup and post-cancel fallback.
2. `botragram/exchanges/bybit/futures_client.py`: Caught `(ExchangeError, ExchangeOrderNotFoundError, BybitRestResponseError)` with `_LOGGER.debug` for order lookup and pre-cancel order status inspection.
3. `botragram/exchanges/binance/futures_client.py`: Caught `(ExchangeOrderNotFoundError, BinanceRestResponseError, ExchangeError)` with `_LOGGER.debug` in emergency protection cancellation during position close.
4. `botragram/services/live_market_stream_service.py`: Caught `(ExchangeError, TimeoutError, ConnectionError, ValueError, RuntimeError)` with `_LOGGER.debug` during seed ticker fetch; `asyncio.CancelledError` propagates safely.
5. `botragram/services/live_position_protection_service.py`: Re-raised `asyncio.CancelledError` and logged `_LOGGER.debug` for primary order cancel before client ID fallback.
6. `botragram/services/market_service.py`: Caught `ValueError` with `_LOGGER.debug` for resampled candle failures.
7. `botragram/app/dependency_provider.py`: Logged `_LOGGER.debug` when Telegram reconnect task is cancelled cleanly during shutdown.
8. `botragram/services/candle_retention_service.py`: Logged `_LOGGER.debug` when candle retention worker is cancelled cleanly during stop.
9. `botragram/exchanges/bitget/stream.py` & `bybit/stream.py`: Logged `_LOGGER.debug` on heartbeat cancellation.
10. `botragram/telegram/callbacks.py`: Replaced 20 `except Exception: pass` occurrences with `TelegramError` handling and structured `_LOGGER.debug` / `_LOGGER.warning`.

The diagnostic position query in `_resume_pending_partial_take_profit()` (after the NOT_FOUND path) is wrapped in a broad `except Exception` — this is intentional and safe because:
- The query result is logged at `DEBUG` only; no mutation decision is ever made from it.
- The outer fail-closed path (retain intent + schedule retry) is reached regardless.

---

## 4. Type Suppression Audit

A full static analysis was conducted for type suppressions across the repository:

* **Production code (`botragram/`):**
  * `# type: ignore`: `0`
  * `# pyright: ignore`: `0`
  * `# mypy: ignore`: `0`
  * **Boundary `cast()` inventory:** Legitimate type assertions are restricted exclusively to deserialization of untyped vendor HTTP JSON dictionaries into `ExchangePayload` or `list[object]` within `botragram/exchanges/bitget/` and `botragram/exchanges/bybit/` transport mappers, and role extraction in `telegram/access.py`.
* **Test code (`tests/`):**
  * 6 `# type: ignore` comments in unit tests for mock object parameter types.

---

## 5. Partial TP Reconciliation Design & Invariants

In `PositionProtectionManager._resume_pending_partial_take_profit()`:

### Architecture & Safety Principle

> **`EXACT ORDER ID > POSITION DELTA INFERENCE`**
>
> The authoritative exchange order lookup (`get_order_by_client_order_id`) is the
> **only** source of truth that may trigger a position state mutation.
> Position delta is **never** used as proof of fill ownership.

### Flow

1. **Authoritative lookup first:** `get_order_by_client_order_id` is attempted up to `_PENDING_RECONCILIATION_ATTEMPTS` times.
2. **On FILLED/PARTIALLY_FILLED:** `_transition_after_partial_fill` is called exactly once.
3. **On CANCELED/REJECTED with zero fill:** pending intent is cleared; local quantity is unchanged.
4. **On `ExchangeOrderOutcomeUnknownError`:** fails closed — retains pending intent, schedules retry.
5. **On `ExchangeOrderNotFoundError` (all attempts exhausted):**
   - Logs `WARNING` that outcome is unverifiable.
   - Optionally queries positions for **diagnostic context only** (logged at `DEBUG`; no mutation made).
   - Retains pending intent unconditionally.
   - Schedules retry via `failure_retry_seconds`.

### Why position delta is unsafe as fill evidence

A position reduction matching `requested_qty` can result from:
- Liquidation by the exchange risk engine.
- Manual close by the operator.
- A concurrent order by another process.
- Exchange indexing lag (position may appear unchanged for seconds after fill).

None of these outcomes are distinguishable from the specific partial TP order without an authoritative order status.

### Regression Matrix (Cases A through K + exact-once §6)

| Case | Condition | Correct Behavior | Test |
|---|---|---|---|
| A | Exact order FILLED | Quantity deducted exactly once | `test_partial_tp_verified_fill_and_same_tick_step_advancement` |
| B | Exact order PARTIALLY_FILLED → cancel race | Fill processed at executed qty | `test_partial_tp_cancel_race_returns_filled_processed_as_full_fill` |
| C | NOT_FOUND, delta == requested | **Retain intent** (delta not authoritative) | `test_not_found_order_delta_matches_requested_retains_intent` |
| D | NOT_FOUND, position unchanged | **Retain intent** (unchanged ≠ non-fill) | `test_not_found_order_position_unchanged_retains_intent` |
| E | NOT_FOUND, delta < requested | Retain intent, fail closed | `test_fallback_reconciliation_unrelated_reduction_fails_closed` |
| F | NOT_FOUND, delta > requested | Retain intent, fail closed | `test_fallback_reconciliation_delta_exceeds_requested_fails_closed` |
| G | `ExchangeOrderOutcomeUnknownError` | Retain intent, fail closed | `test_fallback_reconciliation_order_outcome_unknown_fails_closed` |
| H | Position query fails | Retain intent, fail closed | `test_fallback_reconciliation_positions_query_failure_fails_closed` |
| I | Restart while unresolved | Durable intent persists | `test_not_found_pending_intent_survives_restart` |
| J | NOT_FOUND then FILLED | Quantity deducted exactly once on FILLED | `test_not_found_then_filled_mutates_quantity_exactly_once` |
| K | NOT_FOUND + delta match, then CANCELED | Quantity **never** deducted | `test_not_found_matching_delta_then_canceled_no_quantity_mutation` |
| §6 | Multiple ticks / restart after verified fill | Exact-once invariant preserved | `test_exact_once_invariant_verified_fill_applied_exactly_once` |

---

## 6. Protection & Accounting Invariants

* **Milestone Monotonicity:** `protection_step` monotonically advances (never regresses).
* **Stop Clamping:** `stop_loss` is monotonically tighter; same-step equal or widening stop mutations are rejected.
* **LONG & SHORT Symmetry:** Identical state machine progression and break-even preservation for both position sides.
* **PnL & Fee Accuracy:**
  * Unrealized PnL is computed on remaining post-exit quantity.
  * Realized PnL is computed strictly on executed quantity.
  * Backtest total fees match aggregated trade fees without double-counting.

---

## 7. Release Certification Verdict

```text
============================================================
RELEASE CERTIFICATION: PASS
Version: v2.7.11
Verification: All 9 local Windows quality gates passed.
Coverage: 1575 automated tests passed (0 failed, 0 skipped).
Safety: Zero forbidden exception patterns, zero bare excepts.
Typing: 0 type ignores in production, strict pyright & mypy clean.
Partial TP: Position delta removed as fill evidence (fail-closed).
Worktree: Clean and verified.
Release Ready: YES
============================================================

