"""
UmbraEdit - Single Instance Handler
====================================

This file is a part of UmbraEdit.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Created: Ensures only one instance of UmbraEdit runs at a time. If
another instance is running, tries to switch to it. If it appears
hung, kills the existing instance and starts a new one.

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

import logging
import os
import signal
import subprocess

from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILE = Path("/tmp/umbraedit_instance.lock")


def _getRunningPids() -> list[int]:
    """Find all running UmbraEdit process IDs (excluding this one)."""
    myPid = os.getpid()
    pids = []
    for procDir in Path("/proc").glob("[0-9]*") if Path("/proc").is_dir() else Path("/dev/null").glob("x"):
        pass
    # macOS doesn't have /proc, use ps instead
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            # Match the actual Python interpreter running UmbraEdit.py
            # Not just any process with "umbraedit" in the path (like node/esbuild)
            if "UmbraEdit.py" not in line:
                continue
            if "python" not in line and "Python" not in line:
                continue
            if "grep" in line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    pid = int(parts[1])
                    if pid != myPid:
                        pids.append(pid)
                except (ValueError, IndexError):
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return pids


def _isHung(pid: int) -> bool:
    """Check if a process with the given PID appears to be hung.

    A process is considered hung if it has been in a sleeping or
    stopped state for a long time with no CPU activity.
    """
    try:
        result = subprocess.run(
            ["ps", "-o", "state=,cputime=,etime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        parts = result.stdout.strip().split()
        if not parts:
            return False
        state = parts[0] if parts else "?"
        # States: S=sleeping, T=stopped, Z=zombie, R=running
        # Consider S (sleeping) for > 30 min or Z (zombie) as hung
        cputime = parts[1] if len(parts) > 1 else "0:00"
        etime = parts[2] if len(parts) > 2 else "0:00"
        if state == "Z":
            return True
        # Parse elapsed time, if running for > 30 min with minimal CPU, consider hung
        if ":" in etime:
            timeParts = etime.split(":")
            if len(timeParts) >= 2:
                try:
                    if "days" in etime or "-" in etime:
                        return False  # Running for days, not hung
                    totalSecs = 0
                    if len(timeParts) == 3:
                        totalSecs = int(timeParts[0]) * 3600 + int(timeParts[1]) * 60 + int(timeParts[2])
                    elif len(timeParts) == 2:
                        totalSecs = int(timeParts[0]) * 60 + int(timeParts[1])
                    if totalSecs > 1800 and cputime in ("0:00", "0:00.00"):
                        return True  # Running > 30 min with no CPU
                except (ValueError, IndexError):
                    pass
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def checkSingleInstance() -> bool:
    """Check for running UmbraEdit instances.

    Returns True if this instance should continue starting.
    Returns False if another instance took over (or is running fine).
    """
    myPid = os.getpid()
    pids = _getRunningPids()

    if not pids:
        logger.debug("No other UmbraEdit instances running")
        _writeLockFile(myPid)
        return True

    # Check each existing instance
    alivePids = []
    for pid in pids:
        try:
            os.kill(pid, 0)  # Check if process exists
            alivePids.append(pid)
        except (ProcessLookupError, PermissionError):
            pass  # Process doesn't exist anymore

    if not alivePids:
        logger.debug("All previous instances are dead")
        _writeLockFile(myPid)
        return True

    # Try to bring the first alive instance to the foreground
    import platform as plat

    if plat.system() == "Darwin":
        # On macOS, use AppleScript to activate the app
        try:
            script = 'tell application "UmbraEdit" to activate'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            logger.info("Switched to existing UmbraEdit instance")
            return False
        except Exception:
            logger.warning("Could not activate existing instance, checking if hung...")
    else:
        # On Linux, use wmctrl or xdotool if available
        try:
            subprocess.run(["wmctrl", "-a", "UmbraEdit"], capture_output=True, timeout=5)
            logger.info("Switched to existing UmbraEdit instance")
            return False
        except FileNotFoundError:
            pass

    # Check if any instances appear hung
    hungPids = [pid for pid in alivePids if _isHung(pid)]
    if hungPids:
        logger.warning("Found hung UmbraEdit instance(s): %s, killing...", hungPids)
        for pid in hungPids:
            try:
                os.kill(pid, signal.SIGKILL)
                logger.info("Killed hung process %d", pid)
            except (ProcessLookupError, PermissionError):
                pass
        # Remove hung pids from alive list
        alivePids = [pid for pid in alivePids if pid not in hungPids]
        if not alivePids:
            _writeLockFile(myPid)
            return True

    # There's a healthy instance running that we can't switch to
    logger.info("Another healthy UmbraEdit instance is already running (PID: %s)", alivePids[0])
    return False


def _writeLockFile(pid: int) -> None:
    """Write the current PID to the lock file."""
    try:
        LOCK_FILE.write_text(str(pid), encoding="utf-8")
    except OSError:
        pass
