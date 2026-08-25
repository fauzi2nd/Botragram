"""Process-level deployment lock regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from botragram.app.runtime_instance_lock import RuntimeInstanceLock


def test_runtime_lock_excludes_a_second_instance(tmp_path: Path) -> None:
    """Reject a concurrent runtime for one database-scoped deployment."""
    lock_path = tmp_path / "botragram.lock"
    first = RuntimeInstanceLock(lock_path=lock_path)
    second = RuntimeInstanceLock(lock_path=lock_path)

    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already active"):
            second.acquire()
    finally:
        first.release()

    assert not lock_path.exists()


def test_runtime_lock_replaces_a_malformed_stale_file(tmp_path: Path) -> None:
    """Recover cleanly after an interrupted process leaves an invalid lock."""
    lock_path = tmp_path / "botragram.lock"
    lock_path.write_text("interrupted-shutdown\n", encoding="utf-8")
    lock = RuntimeInstanceLock(lock_path=lock_path)

    lock.acquire()

    assert lock.is_owned
    assert lock_path.read_text(encoding="utf-8").strip().isdigit()
    lock.release()
    assert not lock_path.exists()
