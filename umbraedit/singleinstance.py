"""
UmbraEdit - Single Instance Handler
====================================

This file is a part of UmbraEdit.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Created: Ensures only one instance of UmbraEdit runs at a time. If
another instance is running, tries to switch to it. Indeterminate lock
states fail closed and require explicit recovery.

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

import atexit
import logging
import subprocess
import sys

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QLockFile, QStandardPaths

logger = logging.getLogger(__name__)

_dataRoot = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
LOCK_FILE = Path(_dataRoot) / "umbraedit" / "instance.lock"

_instanceLock: Optional[QLockFile] = None
_LOCK_FAILED_ERROR = QLockFile.LockError.LockFailedError


class SingleInstanceError(RuntimeError):
    """Raised when the single-instance lock cannot be used safely."""


def _activateExistingInstance() -> None:
    """Try to bring an existing UmbraEdit window to the foreground."""
    if sys.platform == "darwin":
        command = ["osascript", "-e", 'tell application "UmbraEdit" to activate']
    elif sys.platform.startswith("linux"):
        command = ["wmctrl", "-a", "UmbraEdit"]
    else:
        # There is no portable Windows activation command in this module.
        return

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not activate existing UmbraEdit instance: %s", exc)
        return

    if result.returncode == 0:
        logger.info("Switched to existing UmbraEdit instance")
    else:
        logger.warning("Could not activate existing UmbraEdit instance")


def checkSingleInstance() -> bool:
    """Check whether this process may continue starting.

    The lock is retained for the lifetime of the process. A second call
    from the same process is idempotent. If another process owns the
    lock, the existing window is activated and ``False`` is returned.

    An indeterminate lock state raises :class:`SingleInstanceError`.
    Failing closed is required because allowing a second instance to
    start without proven exclusivity could corrupt shared application
    data.
    """
    global _instanceLock

    if _instanceLock is not None and _instanceLock.isLocked():
        return True

    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SingleInstanceError(
            f"Could not create the UmbraEdit instance lock directory '{LOCK_FILE.parent}'."
        ) from exc

    lock = QLockFile(str(LOCK_FILE))
    lock.setStaleLockTime(0)

    if lock.tryLock(0):
        _instanceLock = lock
        logger.debug("No other UmbraEdit instances running")
        return True

    if lock.error() != _LOCK_FAILED_ERROR:
        raise SingleInstanceError(f"Could not acquire the UmbraEdit instance lock '{LOCK_FILE}': {lock.error()}.")

    lockInfo = lock.getLockInfo()
    if not lockInfo[0]:
        # The owner may have exited between the failed acquisition and the
        # metadata read, or it may still be writing the lock metadata. A
        # bounded retry distinguishes an exited owner from malformed data.
        if lock.tryLock(100):
            _instanceLock = lock
            logger.debug("No other UmbraEdit instances running")
            return True

        if lock.error() != _LOCK_FAILED_ERROR:
            raise SingleInstanceError(f"Could not acquire the UmbraEdit instance lock '{LOCK_FILE}': {lock.error()}.")
        lockInfo = lock.getLockInfo()

    if not lockInfo[0]:
        raise SingleInstanceError(
            f"The UmbraEdit instance lock '{LOCK_FILE}' has malformed metadata. "
            "UmbraEdit cannot verify that another instance is not running. "
            "Close any running UmbraEdit instance and remove the lock file manually to recover."
        )

    logger.info("Another UmbraEdit instance is already running (PID: %s)", lockInfo[1])

    # Failure to activate the existing window must never allow a second
    # instance to start and mutate the same application data.
    _activateExistingInstance()
    return False


def releaseSingleInstance() -> None:
    """Release the retained application instance lock."""
    global _instanceLock

    lock = _instanceLock
    _instanceLock = None
    if lock is not None:
        try:
            lock.unlock()
        except Exception as exc:
            logger.warning("Could not release the UmbraEdit instance lock: %s", exc)


atexit.register(releaseSingleInstance)
