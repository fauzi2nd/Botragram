from __future__ import annotations

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: fix_operator_exit_scope_layout.py TARGET")

    root = Path(sys.argv[1])
    path = root / "botragram/storage/sqlite/operator_exit_repository.py"
    text = path.read_text(encoding="utf-8")
    old = (
        "symbol, authorized_symbols, target_execution_policy, failure_reason, "
        "created_at, updated_at"
    )
    new = (
        "symbol, authorized_symbols, target_execution_policy, failure_reason, "
        "created_at,\nupdated_at"
    )
    if text.count(old) != 1:
        raise RuntimeError("expected exactly one generated operator-exit column line")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
