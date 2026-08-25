"""Process-level deployment lock regression tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from botragram.app.runtime_instance_lock import RuntimeInstanceLock

_CHILD_READY_MESSAGE: Final[str] = "lock-acquired"
_CHILD_EXIT_TIMEOUT_SECONDS: Final[float] = 10.0
_CRASHING_LOCK_OWNER_SCRIPT: Final[str] = f"""
import os
import sys
from pathlib import Path

from botragram.app.runtime_instance_lock import RuntimeInstanceLock

runtime_lock = RuntimeInstanceLock(lock_path=Path(sys.argv[1]))
runtime_lock.acquire()
print({_CHILD_READY_MESSAGE!r}, flush=True)
sys.stdin.readline()
os._exit(0)
"""


def test_runtime_lock_excludes_a_second_instance(tmp_path: Path) -> None:
    """Reject a concurrent runtime for one database-scoped deployment."""
    lock_path = tmp_path / "botragram.lock"
    first = RuntimeInstanceLock(lock_path=lock_path)
    second = RuntimeInstanceLock(lock_path=lock_path)

    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already active"):
            second.acquire()
        assert not second.is_owned
    finally:
        first.release()

    second.acquire()
    second.release()


def test_runtime_lock_ignores_stale_pid_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acquire an unlocked stale file without probing the recorded PID."""
    lock_path = tmp_path / "botragram.lock"
    lock_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    lock = RuntimeInstanceLock(lock_path=lock_path)

    def fail_if_process_is_signaled(process_id: int, signal_number: int) -> None:
        pytest.fail(
            "Runtime lock attempted a PID signal probe: "
            f"pid={process_id} signal={signal_number}"
        )

    monkeypatch.setattr(os, "kill", fail_if_process_is_signaled)
    lock.acquire()
    try:
        assert lock.is_owned
    finally:
        lock.release()


def test_runtime_lock_recovers_after_owner_process_exits(tmp_path: Path) -> None:
    """Recover the OS lock after an owner exits without calling release."""
    lock_path = tmp_path / "botragram.lock"
    owner = subprocess.Popen(
        [sys.executable, "-c", _CRASHING_LOCK_OWNER_SCRIPT, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert owner.stdin is not None
    assert owner.stdout is not None

    try:
        assert owner.stdout.readline().strip() == _CHILD_READY_MESSAGE
        with pytest.raises(RuntimeError, match="already active"):
            RuntimeInstanceLock(lock_path=lock_path).acquire()

        owner.stdin.write("exit-without-release\n")
        owner.stdin.flush()
        assert owner.wait(timeout=_CHILD_EXIT_TIMEOUT_SECONDS) == 0

        recovered = RuntimeInstanceLock(lock_path=lock_path)
        recovered.acquire()
        try:
            assert recovered.is_owned
        finally:
            recovered.release()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=_CHILD_EXIT_TIMEOUT_SECONDS)
        owner.stdin.close()
        owner.stdout.close()
