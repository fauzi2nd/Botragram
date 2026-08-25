"""
Botragram

Description:
    Operating-system deployment lock for one Botragram runtime per ledger.

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
import errno
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import fcntl
    import msvcrt
elif sys.platform == "win32":
    import msvcrt
else:
    import fcntl

__all__ = [
    "RuntimeInstanceLock",
]


# =============================================================================
# Constants
# =============================================================================
_LOCK_FILE_MODE: Final[int] = 0o600
_LOCK_BYTE_COUNT: Final[int] = 1
_LOCK_METADATA_MAX_BYTES: Final[int] = 64
_UNKNOWN_PROCESS_ID: Final[str] = "unknown"
_WINDOWS_LOCK_CONTENTION_ERRORS: Final[frozenset[int]] = frozenset(
    {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
)
_ACTIVE_INSTANCE_ERROR_TEMPLATE: Final[str] = (
    "Another Botragram runtime is already active for this ledger: "
    "pid={process_id} lock={lock_path}"
)


# =============================================================================
# Runtime Classes
# =============================================================================
@dataclass(slots=True)
class RuntimeInstanceLock:
    """Own one OS-backed lock for a database-scoped runtime.

    The operating system releases the lock when the owning file descriptor is
    closed or its process exits. PID metadata is diagnostic only and is never
    used to probe or signal another process.
    """

    lock_path: Path
    _owned: bool = field(default=False, init=False, repr=False)
    _process_id: int = field(default_factory=os.getpid, init=False, repr=False)
    _file_descriptor: int | None = field(default=None, init=False, repr=False)

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
        file_descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT,
            _LOCK_FILE_MODE,
        )
        acquired = False
        try:
            if not self._try_acquire_file_lock(file_descriptor=file_descriptor):
                process_id = self._read_process_id(
                    file_descriptor=file_descriptor,
                )
                raise RuntimeError(
                    _ACTIVE_INSTANCE_ERROR_TEMPLATE.format(
                        process_id=process_id or _UNKNOWN_PROCESS_ID,
                        lock_path=self.lock_path,
                    )
                )
            self._write_process_id(file_descriptor=file_descriptor)
            self._file_descriptor = file_descriptor
            self._owned = True
            acquired = True
        finally:
            if not acquired:
                os.close(file_descriptor)

    def release(self) -> None:
        """Release this instance's lock without deleting another owner's file."""
        if not self._owned:
            return

        file_descriptor = self._file_descriptor
        if file_descriptor is None:
            self._owned = False
            return

        try:
            self._release_file_lock(file_descriptor=file_descriptor)
        finally:
            try:
                os.close(file_descriptor)
            finally:
                self._file_descriptor = None
                self._owned = False

    @staticmethod
    def _try_acquire_file_lock(*, file_descriptor: int) -> bool:
        """Try to acquire the platform lock without blocking."""
        if sys.platform == "win32":
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(
                    file_descriptor,
                    msvcrt.LK_NBLCK,
                    _LOCK_BYTE_COUNT,
                )
            except OSError as error:
                if error.errno in _WINDOWS_LOCK_CONTENTION_ERRORS:
                    return False
                raise
            return True

        try:
            fcntl.flock(
                file_descriptor,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            return False
        return True

    @staticmethod
    def _release_file_lock(*, file_descriptor: int) -> None:
        """Release the platform lock held by the file descriptor."""
        if sys.platform == "win32":
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            msvcrt.locking(
                file_descriptor,
                msvcrt.LK_UNLCK,
                _LOCK_BYTE_COUNT,
            )
            return
        fcntl.flock(file_descriptor, fcntl.LOCK_UN)

    def _write_process_id(self, *, file_descriptor: int) -> None:
        """Replace diagnostic lock metadata with this process identifier."""
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        os.ftruncate(file_descriptor, 0)
        os.write(file_descriptor, f"{self._process_id}\n".encode(encoding="ascii"))

    @staticmethod
    def _read_process_id(*, file_descriptor: int) -> int | None:
        """Return diagnostic owner metadata when it is readable and valid."""
        try:
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            content = os.read(file_descriptor, _LOCK_METADATA_MAX_BYTES).decode(
                encoding="ascii"
            )
        except OSError, UnicodeDecodeError:
            return None
        try:
            process_id = int(content.strip())
        except ValueError:
            return None
        return process_id if process_id > 0 else None
