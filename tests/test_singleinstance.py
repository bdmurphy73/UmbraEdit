"""
UmbraEdit - Single Instance Tests
==================================

This file is a part of UmbraEdit.

Copyright (C) 2026 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import json
import subprocess
import sys

from pathlib import Path

import pytest

from PyQt6.QtCore import QLockFile

from umbraedit import main, singleinstance
from umbraedit.singleinstance import SingleInstanceError


@pytest.fixture(autouse=True)
def isolateInstanceLock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Keep the test lock separate from the user's application lock."""
    singleinstance.releaseSingleInstance()
    monkeypatch.setattr(singleinstance, "LOCK_FILE", tmp_path / "instance.lock")
    yield
    singleinstance.releaseSingleInstance()


@pytest.mark.base
def testSingleInstance_AcquireReleaseAndIdempotence():
    """Test that the retained lock is exclusive and process-idempotent."""
    assert singleinstance.checkSingleInstance() is True
    assert singleinstance.LOCK_FILE.exists()
    assert singleinstance._instanceLock is not None
    assert singleinstance._instanceLock.isLocked()

    assert singleinstance.checkSingleInstance() is True
    assert singleinstance._instanceLock is not None
    assert singleinstance._instanceLock.isLocked()

    singleinstance.releaseSingleInstance()
    assert singleinstance._instanceLock is None
    assert not singleinstance.LOCK_FILE.exists()

    assert singleinstance.checkSingleInstance() is True
    singleinstance.releaseSingleInstance()


@pytest.mark.base
def testSingleInstance_ExistingOwner(monkeypatch: pytest.MonkeyPatch):
    """Test that a live lock owner prevents a second instance."""
    owner = QLockFile(str(singleinstance.LOCK_FILE))
    owner.setStaleLockTime(0)
    assert owner.tryLock(0) is True

    activated = False

    def activate() -> None:
        nonlocal activated
        activated = True

    monkeypatch.setattr(singleinstance, "_activateExistingInstance", activate)
    try:
        assert singleinstance.checkSingleInstance() is False
        assert activated is True
        assert owner.isLocked()
    finally:
        owner.unlock()


@pytest.mark.base
def testSingleInstance_ContentionAcrossProcesses(monkeypatch: pytest.MonkeyPatch):
    """Test that a lock owned by another process prevents startup."""
    lockPath = str(singleinstance.LOCK_FILE)
    code = (
        "import sys, time; "
        "from PyQt6.QtCore import QLockFile; "
        f"lock = QLockFile({lockPath!r}); "
        "lock.setStaleLockTime(0); "
        "assert lock.tryLock(0); "
        "print('ready', flush=True); "
        "time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"

    monkeypatch.setattr(singleinstance, "_activateExistingInstance", lambda: None)
    try:
        assert singleinstance.checkSingleInstance() is False
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.base
def testSingleInstance_UnrelatedCommandIsNotAnInstance():
    """Test that an unrelated command line cannot block startup."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "UmbraEdit.py"],
    )
    try:
        assert singleinstance.checkSingleInstance() is True
    finally:
        process.terminate()
        process.wait(timeout=5)
    singleinstance.releaseSingleInstance()


@pytest.mark.base
def testSingleInstance_LockDirectoryFailureFailsClosed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that an unusable lock directory prevents startup."""
    blockedParent = tmp_path / "blocked"
    blockedParent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(singleinstance, "LOCK_FILE", blockedParent / "instance.lock")

    activated = False

    def activate() -> None:
        nonlocal activated
        activated = True

    monkeypatch.setattr(singleinstance, "_activateExistingInstance", activate)
    with pytest.raises(SingleInstanceError):
        singleinstance.checkSingleInstance()

    assert activated is False


@pytest.mark.base
@pytest.mark.parametrize(
    "lock_error",
    [QLockFile.LockError.PermissionError, QLockFile.LockError.UnknownError],
)
def testSingleInstance_IndeterminateLockErrorFailsClosed(
    monkeypatch: pytest.MonkeyPatch,
    lock_error: QLockFile.LockError,
):
    """Test that indeterminate Qt lock errors prevent startup."""

    class FailingLock:
        def __init__(self, path: str) -> None:
            self.path = path

        def setStaleLockTime(self, staleTime: int) -> None:
            pass

        def tryLock(self, timeout: int) -> bool:
            return False

        def error(self) -> QLockFile.LockError:
            return lock_error

    monkeypatch.setattr(singleinstance, "QLockFile", FailingLock)
    with pytest.raises(SingleInstanceError):
        singleinstance.checkSingleInstance()


@pytest.mark.base
def testSingleInstance_MalformedMetadataFailsClosed(monkeypatch: pytest.MonkeyPatch):
    """Test that malformed lock metadata is preserved and blocks startup."""
    malformed = b"not a lock file\n"
    singleinstance.LOCK_FILE.write_bytes(malformed)
    activated = False

    def activate() -> None:
        nonlocal activated
        activated = True

    monkeypatch.setattr(singleinstance, "_activateExistingInstance", activate)
    with pytest.raises(SingleInstanceError):
        singleinstance.checkSingleInstance()

    assert activated is False
    assert singleinstance.LOCK_FILE.read_bytes() == malformed


@pytest.mark.base
def testSingleInstance_OwnerExitRaceRetries(monkeypatch: pytest.MonkeyPatch):
    """Test that an owner exiting during inspection is retried safely."""

    class ExitingOwnerLock:
        def __init__(self, path: str) -> None:
            self.path = path
            self.attempts = 0

        def setStaleLockTime(self, staleTime: int) -> None:
            pass

        def tryLock(self, timeout: int) -> bool:
            self.attempts += 1
            return self.attempts > 1

        def error(self) -> QLockFile.LockError:
            return QLockFile.LockError.LockFailedError

        def getLockInfo(self):
            return (False, None, None, None)

        def isLocked(self) -> bool:
            return self.attempts > 1

    monkeypatch.setattr(singleinstance, "QLockFile", ExitingOwnerLock)
    assert singleinstance.checkSingleInstance() is True
    assert singleinstance._instanceLock is not None


@pytest.mark.base
def testSingleInstance_RecoversStaleOwner():
    """Test that a lock left by a dead process can be recovered."""
    lockPath = str(singleinstance.LOCK_FILE)
    code = (
        "import os, sys; "
        "from PyQt6.QtCore import QLockFile; "
        f"lock = QLockFile({lockPath!r}); "
        "lock.setStaleLockTime(0); "
        "assert lock.tryLock(0); "
        "print('ready', flush=True); "
        "os._exit(0)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    assert process.wait(timeout=5) == 0
    assert singleinstance.LOCK_FILE.exists()

    assert singleinstance.checkSingleInstance() is True
    singleinstance.releaseSingleInstance()


@pytest.mark.base
def testSingleInstance_ReclaimsLockWithReusedPid():
    """Test that a live unrelated PID with mismatched metadata is stale."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "UmbraEdit.py"],
    )
    try:
        singleinstance.LOCK_FILE.write_text(
            f"{process.pid}\nDefinitelyNotUmbraEdit\n\n\n\n",
            encoding="utf-8",
        )
        assert singleinstance.checkSingleInstance() is True
    finally:
        process.terminate()
        process.wait(timeout=5)
    singleinstance.releaseSingleInstance()


@pytest.mark.base
def testSingleInstance_ActivationFailureStillBlocksStartup(monkeypatch: pytest.MonkeyPatch):
    """Test that activation failure cannot start a second instance."""
    owner = QLockFile(str(singleinstance.LOCK_FILE))
    owner.setStaleLockTime(0)
    assert owner.tryLock(0) is True

    def failActivation(*args: object, **kwargs: object):
        raise FileNotFoundError("The activation command is not installed")

    monkeypatch.setattr(singleinstance.subprocess, "run", failActivation)
    try:
        assert singleinstance.checkSingleInstance() is False
    finally:
        owner.unlock()


@pytest.mark.base
def testSingleInstance_MainConflictExitsSuccessfully(monkeypatch: pytest.MonkeyPatch):
    """Test that the GUI entry point exits cleanly on lock contention."""
    monkeypatch.setattr(singleinstance, "checkSingleInstance", lambda: False)

    def failCreateApp(*args: object, **kwargs: object) -> None:
        raise AssertionError("The GUI was created after lock contention")

    monkeypatch.setattr("umbraedit._createApp", failCreateApp)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0


@pytest.mark.base
def testSingleInstance_MainIndeterminateLockExitsNonzero(monkeypatch: pytest.MonkeyPatch):
    """Test that an indeterminate lock state aborts before GUI creation."""
    monkeypatch.setattr(
        singleinstance,
        "checkSingleInstance",
        lambda: (_ for _ in ()).throw(SingleInstanceError("indeterminate lock")),
    )

    def failCreateApp(*args: object, **kwargs: object) -> None:
        raise AssertionError("The GUI was created after an indeterminate lock error")

    monkeypatch.setattr("umbraedit._createApp", failCreateApp)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 1


@pytest.mark.base
def testSingleInstance_ImportDoesNotChangeApplicationPaths():
    """Test that importing the handler does not mutate global Qt metadata."""
    code = (
        "import json; "
        "from PyQt6.QtCore import QCoreApplication; "
        "import umbraedit; "
        "from umbraedit.config import Config; "
        "before_name = QCoreApplication.applicationName(); "
        "before_path = str(umbraedit.CONFIG._dataPath); "
        "import umbraedit.singleinstance; "
        "after_name = QCoreApplication.applicationName(); "
        "after_path = str(Config()._dataPath); "
        "print(json.dumps([before_name, after_name, before_path, after_path]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    beforeName, afterName, beforePath, afterPath = json.loads(result.stdout)
    assert beforeName == afterName
    assert beforePath == afterPath


@pytest.mark.base
@pytest.mark.parametrize("option", ["--help", "--version"])
def testSingleInstance_HelpAndVersionBypassLock(monkeypatch: pytest.MonkeyPatch, option: str):
    """Test that informational command-line options bypass the lock."""
    monkeypatch.setattr(
        singleinstance,
        "checkSingleInstance",
        lambda: pytest.fail("The instance lock was checked for an informational option"),
    )
    with pytest.raises(SystemExit) as exc:
        main([option])
    assert exc.value.code == 0
    assert not singleinstance.LOCK_FILE.exists()
