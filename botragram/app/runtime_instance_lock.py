"""
Botragram

Description:
    Process-local deployment lock for one Botragram runtime per ledger.

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
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

__all__ = [
    "RuntimeInstanceLock",
]


# =============================================================================
# Constants
# =============================================================================
_LOCK_FILE_MODE: Final[int] = 0o600
_ACTIVE_INSTANCE_ERROR_TEMPLATE: Final[str] = (
    "Another Botragram runtime is already active for this ledger: "
    "pid={process_id} lock={lock_path}"
)


# =============================================================================
# Runtime Classes
# =============================================================================
@dataclass(slots=True)
class RuntimeInstanceLock:
    """Own one atomic deployment lock for a database-scoped runtime.

    A stale lock left by an unclean machine shutdown is removed only when its
    PID is absent or malformed. The exclusive file creation remains the final
    race-safe ownership boundary.
    """

    lock_path: Path
    _owned: bool = field(default=False, init=False, repr=False)
    _process_id: int = field(default_factory=os.getpid, init=False, repr=False)

    @property
    def is_owned(self) -> bool:
        """Return whether this instance currently owns the lock file."""
        return self._owned

    def acquire(self) -> None:
        """Atomically acquire this runtime's database-scoped lock.

        Raises:
            RuntimeError: If another live process already owns the same lock.
        """
        if self._owned:
            return

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_descriptor = os.open(
                self.lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                _LOCK_FILE_MODE,
            )
        except FileExistsError:
            self._remove_stale_lock_or_raise()
            self.acquire()
            return

        try:
            os.write(file_descriptor, f"{self._process_id}\n".encode())
        finally:
            os.close(file_descriptor)
        self._owned = True

    def release(self) -> None:
        """Release this instance's lock without deleting another owner's file."""
        if not self._owned:
            return

        try:
            if self._read_process_id() == self._process_id:
                self.lock_path.unlink(missing_ok=True)
        finally:
            self._owned = False

    def _remove_stale_lock_or_raise(self) -> None:
        """Reject a live owner or remove a stale lock before retrying acquire."""
        process_id = self._read_process_id()
        if process_id is not None and self._is_process_running(process_id=process_id):
            raise RuntimeError(
                _ACTIVE_INSTANCE_ERROR_TEMPLATE.format(
                    process_id=process_id,
                    lock_path=self.lock_path,
                )
            )
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            return

    def _read_process_id(self) -> int | None:
        """Return a valid lock-owner PID, or ``None`` for a stale malformed file."""
        try:
            content = self.lock_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        try:
            process_id = int(content)
        except ValueError:
            return None
        return process_id if process_id > 0 else None

    @staticmethod
    def _is_process_running(*, process_id: int) -> bool:
        """Return whether the operating system still reports the PID as alive."""
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
