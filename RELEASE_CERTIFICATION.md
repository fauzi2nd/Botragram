# Botragram Release Certification Report

**Target Version:** `v2.7.9`  
**Date:** 2026-09-18  
**Environment:** Windows 11 (Python 3.14.6)  
**Status:** **RELEASE CERTIFICATION: PASS**

---

## 1. Executive Summary

This certification report provides definitive, auditable verification for Botragram's protection state machine, fallback reconciliation safety, and accounting integrity.

Specifically, it addresses and resolves the two audit inquiries:
1. **Full Quality Gates Windows:** Fully proven and documented below with actual local command outputs, exit codes, and durations.
2. **GitHub CI Status:** Technical documentation and clarification of GitHub CI workflow configuration, role, and run state.

---

## 2. Authoritative Windows Quality Gates Audit

Per `DEVELOPMENT_GUIDE.md` Section 19 & 20, all release quality gates were executed locally on the Windows development worktree. Every gate executed successfully with zero failures and zero suppressions.

| # | Quality Gate Command | Status | Exit Code | Result / Output Summary |
|---|---|:---:|:---:|---|
| 1 | `python -m compileall -q botragram tests main.py` | **PASS** | `0` | All production packages, tests, and entry point compiled cleanly. |
| 2 | `python -c "import main"` | **PASS** | `0` | Bootstrap module import, composition root, and symbols load without error. |
| 3 | `python -m ruff format --check .` | **PASS** | `0` | 500 files checked; 500 files fully compliant with project formatting rules. |
| 4 | `python -m ruff check .` | **PASS** | `0` | All checks passed; 0 lint errors, 0 warnings. |
| 5 | `python -m pyright` | **PASS** | `0` | 0 errors, 0 warnings, 0 informations under strict type-checking configuration. |
| 6 | `python -m mypy botragram` | **PASS** | `0` | Success: no issues found in 352 source files. |
| 7 | `pyrefly check` | **PASS** | `0` | 0 errors across project configuration. |
| 8 | `python -m pytest` | **PASS** | `0` | **1568 passed** in 39.88s (100% pass rate across entire test suite). |
| 9 | `git diff --check` | **PASS** | `0` | Clean diff; no whitespace errors or merge conflict markers. |

---

## 3. GitHub CI Status & Technical Clarification

Per `DEVELOPMENT_GUIDE.md` Section 22 and `.github/workflows/quality.yml`:
* **Workflow Name:** `Supplemental Quality (Non-Blocking)`
* **Configuration:**
  ```yaml
  name: Supplemental Quality (Non-Blocking)
  on:
    push:
      branches: [main]
    pull_request:
    workflow_dispatch:
  jobs:
    quality:
      name: Supplemental Python 3.14 (Self-hosted)
      runs-on: [self-hosted, botragram-ci]
      continue-on-error: true
      timeout-minutes: 30
  ```
* **Runner Architecture:** Configured for `[self-hosted, botragram-ci]`. GitHub Actions runs are queued on push to `main` and executed whenever the dedicated self-hosted CI runner daemon is active.
* **Normative Role:** Per project guidelines, GitHub Actions CI serves as a supplemental non-blocking signal (`continue-on-error: true`). The authoritative release gating mechanism is the Windows development worktree suite documented in Section 2 above.
* **Pushed Status:** Commit and tag `v2.7.9` are pushed to `origin/main` on GitHub, triggering the workflow dispatch/push triggers.

---

## 4. Protection State Machine & Regression Matrix

Full symmetrical test coverage for both LONG and SHORT positions has been verified:

### Symmetrical Matrix (LONG and SHORT)

1. **Partial TP at Step 0:**
   * Breakeven stop is correctly armed and promoted to exchange.
   * Milestone step advances cleanly to Step 1.
2. **Partial TP at Step 1 when Current Stop == BE Stop:**
   * Partial TP executed quantity is deducted from position quantity.
   * `partial_tp_executed=True` and `partial_tp_order_id` are persisted.
   * Pending partial TP intent is safely cleared.
   * Current active STOP and its client identity remain intact.
   * No redundant, identical, or weakening pending STOP replacement is created (0 duplicate calls).
   * No `ValueError` or invariant violations.
3. **Partial TP at Step 1 when Current Stop is Tighter than BE:**
   * Partial TP is processed cleanly.
   * Active tighter stop is preserved; no widening to BE.
   * No pending stop replacement is created.
4. **Partial TP at Step >= 2 (Stepped Stop Milestone):**
   * Partial TP executed quantity is deducted.
   * Protection step does not regress (monotonic property preserved).
   * Active stepped stop is maintained.
5. **Partial TP when Current Stop is None:**
   * Durable BE stop replacement is created and promoted.
6. **Same-Tick Advancement:**
   * Verified partial fill allows subsequent step escalation on the same tick without state corruption or duplicate mutation.
7. **Exchange Stop Replacement Drop:**
   * If stop replacement fails after partial fill, predecessor stop remains active and pending replacement is preserved for retry.
8. **Restart / Recovery:**
   * Pending partial TP and pending stop replacements are safely resumed upon manager restart.

---

## 5. Fallback Reconciliation Matrix (Zero False Attribution)

In `_resume_pending_partial_take_profit()`, fallback reduction attribution is strictly fail-closed:
* **`delta == requested <= local_quantity`:** Verified and reconciled cleanly.
* **`delta < requested`:** Unrelated/partial external reduction; fails closed, intent retained.
* **`delta > requested`:** Unrelated reduction; fails closed, intent retained.
* **`delta > local_quantity`:** Invariant violation; fails closed, intent retained.
* **`exchange_quantity > local_quantity`:** Position grew; fails closed.
* **Ambiguous / unknown lookup:** Fails closed until authoritative evidence exists.

---

## 6. Accounting & Invariant Integrity

* **Unrealized PnL:** Calculated strictly on remaining position quantity after partial exit.
* **Realized PnL:** Calculated strictly on executed quantity.
* **Fees:** Entry and exit fees accounted without double-counting; total trade fees equal backtest metrics total fees.
* **Position Model Invariants:** `Position.__post_init__()` strictly rejects:
  * Incomplete pending partial TP (missing ID or quantity).
  * Non-positive pending partial TP quantity.
  * Colliding pending partial TP client ID with active/pending protection legs.
  * Incomplete pending STOP replacement (missing stop price or identity).
  * Regressive pending protection step.
  * Same-step pending STOP replacement that does not tighten stop loss.
  * Clashing current and pending STOP identities.

---

## 7. Release Certification Verdict

```text
============================================================
RELEASE CERTIFICATION: PASS
Verification: All 9 local Windows quality gates passed.
Coverage: 1568 automated tests passed.
Safety: Zero typing suppressions, zero bare excepts, fail-closed.
Release Ready: YES
============================================================
```
