"""
UmbraEdit - Project Lock File
=============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import contextlib
import json
import logging
import os

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pathlib import Path

UTC = timezone.utc

logger = logging.getLogger(__name__)

LOCK_FILE_NAME = "umbra.lock"

# Placeholder written to an empty lock file before the lock is taken.
# The Windows locking mechanism locks a byte range, so the file must not
# be empty. The placeholder is valid JSON so that a lock file left
# behind by an interrupted process is not mistaken for a live lock.
LOCK_PLACEHOLDER = '{"pid":0}'


def _lockExclusive(fd: int) -> bool:
    """Take an exclusive, non-blocking lock on a file descriptor.

    The POSIX implementation uses ``fcntl.flock()``, and the Windows
    implementation uses ``msvcrt.locking()``. The latter locks a byte
    range, so the file position is reset to the start of the file
    first.

    Returns:
        True if the lock was acquired, False otherwise.

    """
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlockFile(fd: int) -> None:
    """Release an exclusive lock on a file descriptor."""
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


def _processExists(pid: int) -> bool:
    """Check whether a process with the given PID is running.

    On Windows, ``os.kill()`` raises a generic ``OSError`` for a PID
    that does not exist, rather than a ``ProcessLookupError``, so the
    error is checked explicitly there.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class LockInfo:
    """Information about a project lock holder."""

    pid: int
    process: str
    host: str
    at: str
    kind: str  # "gui" | "cli"


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProjectLock:
    """Manages a project lock file to prevent concurrent GUI/CLI writes.

    A project can be opened by either the GUI or the CLI, but not both
    for write access. Read access is allowed from both simultaneously.

    The lock file contains JSON with the holder's PID, process name,
    host, timestamp, and kind (gui/cli).
    """

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path
        self._lock_path = project_path / LOCK_FILE_NAME
        self._fd: Optional[int] = None
        self._held = False
        self._kind = ""

    def is_locked(self) -> bool:
        """Check if the project is currently locked by another process."""
        if not self._lock_path.is_file():
            return False
        try:
            data = json.loads(self._lock_path.read_text(encoding="utf-8"))
            holder_pid = data.get("pid", 0)
            # A lock file without a valid process id cannot be held by a
            # running process, so it is a stale lock
            if not isinstance(holder_pid, int) or holder_pid <= 0:
                return False
            # Check if the process is still running
            return _processExists(holder_pid)
        except Exception:
            return True  # Can't read lock, assume locked

    def lock_info(self) -> Optional[dict[str, Any]]:
        """Return the lock information if locked, None otherwise."""
        if not self._lock_path.is_file():
            return None
        try:
            return json.loads(self._lock_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def acquire(self, kind: str = "cli", process: Optional[str] = None) -> bool:
        """Try to acquire an exclusive lock for write access.

        Args:
            kind: "gui" or "cli"
            process: Human-readable process name

        Returns:
            True if the lock was acquired, False if already locked.

        """
        if self._held:
            return True

        if self.is_locked():
            logger.warning("Project is already locked")
            return False

        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            # Open for read/write, create if needed. The file is not
            # truncated here since its content is rewritten below, and
            # the Windows locking mechanism needs a byte to lock on.
            self._fd = os.open(
                str(self._lock_path),
                os.O_RDWR | os.O_CREAT,
                0o644,
            )
            if os.fstat(self._fd).st_size == 0:
                os.write(self._fd, LOCK_PLACEHOLDER.encode("utf-8"))
            # Try non-blocking exclusive lock
            if not _lockExclusive(self._fd):
                os.close(self._fd)
                self._fd = None
                return False

            info = LockInfo(
                pid=os.getpid(),
                process=process or "umbraedit-cli",
                host=os.uname().nodename if hasattr(os, "uname") else "unknown",
                at=_utc_now_iso(),
                kind=kind,
            )
            text = (
                json.dumps(
                    {
                        "pid": info.pid,
                        "process": info.process,
                        "host": info.host,
                        "at": info.at,
                        "kind": info.kind,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, text.encode("utf-8"))
            os.ftruncate(self._fd, os.lseek(self._fd, 0, os.SEEK_CUR))
            os.fsync(self._fd)
            self._held = True
            self._kind = kind
            logger.info("Acquired project lock (%s)", kind)
            return True
        except Exception:
            logger.exception("Failed to acquire project lock")
            if self._fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self._fd)
                self._fd = None
            return False

    def release(self) -> None:
        """Release the lock if held."""
        if self._fd is not None:
            with contextlib.suppress(OSError):
                _unlockFile(self._fd)
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        if self._held:
            # Remove the lock file
            try:
                if self._lock_path.is_file():
                    self._lock_path.unlink()
            except OSError:
                pass
            self._held = False
            self._kind = ""
            logger.info("Released project lock")

    def __enter__(self) -> ProjectLock:
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit the runtime context related to this object."""
        self.release()


def check_write_access(project_path: Path) -> tuple[bool, Optional[dict[str, Any]]]:
    """Check if write access is available for a project.

    Returns:
        (available, lock_info) - available is True if no lock or we hold it,
        lock_info is the lock info if locked by another process.

    """
    lock = ProjectLock(project_path)
    if lock.is_locked():
        info = lock.lock_info()
        return False, info
    return True, None
