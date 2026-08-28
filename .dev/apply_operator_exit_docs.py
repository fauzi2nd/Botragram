from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_operator_exit_docs.py <target-root>")

    root = Path(sys.argv[1]).resolve()
    path = root / "README.md"
    text = path.read_text(encoding="utf-8")
    anchor = "### MAINNET-candidate release gate\n"
    if text.count(anchor) != 1:
        raise SystemExit("README MAINNET release-gate anchor was not found exactly once")

    section = '''### Operator-controlled exits

Telegram allow-list users can inspect and request explicit portfolio exits through
the operator-exit control plane. The public commands are:

- `/exitstatus` — show the authoritative operator-exit/recovery snapshot;
- `/closeposition <symbol>` — request one position close while already PAUSED;
- `/closeall` — request a whole-portfolio flatten while already PAUSED;
- `/closeandswitch <execution_policy>` — request an explicit flatten-and-switch
  transition inside the immutable boot capability envelope;
- `/confirmexit <confirmation_id> <confirmation_token>` — consume one exact,
  chat-bound confirmation challenge; and
- `/cancelexit <confirmation_id>` — cancel an unexecuted pending confirmation.

`/positions` also exposes explicit per-position **Close** buttons and a **Close All
Positions** action. A normal close request does not auto-pause the runtime: the
operator must pause first. The combined **Close All & Switch** transition is the
only operator-exit request allowed to auto-pause because the pause is part of the
explicit mode-transition workflow. The target execution policy is committed only
after authoritative zero exposure and canonical recovery/reconciliation have
converged; the replacement session starts PAUSED.

PAPER and TESTNET confirmations may use the inline **Confirm Exit** action or the
exact `/confirmexit ... CONFIRM` command. MAINNET never receives an inline
financial-confirm button. Its challenge requires the exact typed token rendered
by Botragram, such as `CLOSE BTCUSDT` or `FLATTEN 1`, and remains bound to the
requesting Telegram chat and confirmation expiry.

LIVE operator exits currently require Futures and exact managed runtime ownership.
Before a confirmation is issued, Botragram requires READY protection/recovery,
no incomplete LIVE entry or operator-exit attempt, a completed durable entry
identity, and exact durable STOP/TP ownership for every affected position. A
confirmed LIVE close persists its deterministic client order identity before the
single reduce-only MARKET POST. Deterministic rejection is reconciled back to
canonical protection; timeout, transport ambiguity, cancellation, malformed
responses, or other uncertain submission outcomes remain fail-closed and enter
durable recovery. Recovery reconciles by the existing identity and does not
blindly submit a second close order.

'''
    path.write_text(
        text.replace(anchor, section + anchor, 1),
        encoding="utf-8",
        newline="\n",
    )
    print("Operator-exit README documentation applied")


if __name__ == "__main__":
    main()
