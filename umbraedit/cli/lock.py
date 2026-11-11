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
import fcntl
import json
import logging
import os

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILE_NAME = "umbra.lock"


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
        self._fd: int | None = None
        self._held = False
        self._kind = ""

    def is_locked(self) -> bool:
        """Check if the project is currently locked by another process."""
        if not self._lock_path.is_file():
            return False
        try:
            data = json.loads(self._lock_path.read_text(encoding="utf-8"))
            holder_pid = data.get("pid", 0)
            # Check if the process is still running
            if holder_pid > 0:
                try:
                    os.kill(holder_pid, 0)
                    return True  # Process exists, lock is held
                except ProcessLookupError:
                    return False  # Process gone, stale lock
                except PermissionError:
                    return True  # Process exists but we can't signal it
            return True
        except Exception:
            return True  # Can't read lock, assume locked

    def lock_info(self) -> dict[str, Any] | None:
        """Return the lock information if locked, None otherwise."""
        if not self._lock_path.is_file():
            return None
        try:
            return json.loads(self._lock_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def acquire(self, kind: str = "cli", process: str | None = None) -> bool:
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
            # Open for read/write, create if needed
            self._fd = os.open(
                str(self._lock_path),
                os.O_RDWR | os.O_CREAT | os.O_TRUNC,
                0o644,
            )
            # Try non-blocking exclusive lock
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
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
            os.write(self._fd, text.encode("utf-8"))
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
                fcntl.flock(self._fd, fcntl.LOCK_UN)
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


def check_write_access(project_path: Path) -> tuple[bool, dict[str, Any] | None]:
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
