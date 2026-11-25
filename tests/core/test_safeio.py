"""
UmbraEdit - Safe File Operations Tests
======================================

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

import contextlib
import ctypes
import errno
import os
import sys

from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, BinaryIO, Optional, cast

import pytest

from umbraedit.core import safeio


class _FakeSyscall:
    """A callable that records a raw Linux syscall invocation."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        oldPath = args[2]
        newPath = args[4]
        assert isinstance(oldPath, bytes)
        assert isinstance(newPath, bytes)
        os.rename(oldPath, newPath)
        return 0


class _FakeLibc:
    """A minimal libc replacement without the renameat2 wrapper."""

    def __init__(self) -> None:
        self.syscall = _FakeSyscall()


class _FakeExistingSyscall:
    """A raw syscall that reports an existing target."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        ctypes.set_errno(errno.EEXIST)
        return -1


class _FakeDarwinRenameatx:
    """A Darwin renameatx_np() replacement that records its arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        return 0


@pytest.mark.core
def testSafeIO_RenameNoReplace(tmp_path: Path):
    """Test that an atomic rename never replaces an existing target."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")

    assert safeio.renameNoReplace(source, target) is True
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "source"

    second = tmp_path / "second"
    second.write_text("second", encoding="utf-8")
    assert safeio.renameNoReplace(second, target) is False
    assert second.exists()
    assert target.read_text(encoding="utf-8") == "source"


@pytest.mark.core
def testSafeIO_DarwinRenameBetweenUsesFullPathsAndCorrectFdcwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that Darwin descriptor-less rename sides use full paths."""
    fakeRename = _FakeDarwinRenameatx()
    fakeLibc = SimpleNamespace(renameatx_np=fakeRename)
    source = tmp_path / "source"
    target = tmp_path / "target"

    with monkeypatch.context() as mp:
        mp.setattr(safeio.ctypes, "CDLL", lambda *args, **kwargs: fakeLibc)
        mp.setattr(safeio, "sys", SimpleNamespace(platform="darwin"))

        safeio.renameNoReplaceBetween(source, target, sourceDirFd=101)
        safeio.renameNoReplaceBetween(source, target, targetDirFd=202)
        safeio.renameNoReplaceBetween(source, target, sourceDirFd=101, targetDirFd=202)

    assert fakeRename.calls[0][0] == 101
    assert fakeRename.calls[0][1] == b"source"
    assert fakeRename.calls[0][2] == safeio._DARWIN_AT_FDCWD
    assert fakeRename.calls[0][3] == os.fsencode(target)

    assert fakeRename.calls[1][0] == safeio._DARWIN_AT_FDCWD
    assert fakeRename.calls[1][1] == os.fsencode(source)
    assert fakeRename.calls[1][2] == 202
    assert fakeRename.calls[1][3] == b"target"

    assert fakeRename.calls[2][0] == 101
    assert fakeRename.calls[2][1] == b"source"
    assert fakeRename.calls[2][2] == 202
    assert fakeRename.calls[2][3] == b"target"


@pytest.mark.core
@pytest.mark.skipif(
    not (safeio.sys.platform == "darwin" or safeio.sys.platform.startswith("linux")),
    reason="Requires descriptor-relative no-replace rename support",
)
def testSafeIO_RenameNoReplaceBetweenDescriptorForms(tmp_path: Path):
    """Test source-only, target-only, and two-descriptor rename forms."""
    sourceDir = tmp_path / "source"
    targetDir = tmp_path / "target"
    sourceDir.mkdir()
    targetDir.mkdir()

    (sourceDir / "source-only").write_text("source-only", encoding="utf-8")
    sourceFd = safeio.openDirectory(sourceDir)
    try:
        assert safeio.renameNoReplaceBetween(
            Path("source-only"),
            targetDir / "source-only",
            sourceDirFd=sourceFd,
        )
    finally:
        os.close(sourceFd)
    assert (targetDir / "source-only").read_text(encoding="utf-8") == "source-only"

    (sourceDir / "target-only").write_text("target-only", encoding="utf-8")
    targetFd = safeio.openDirectory(targetDir)
    try:
        assert safeio.renameNoReplaceBetween(
            sourceDir / "target-only",
            Path("target-only"),
            targetDirFd=targetFd,
        )
    finally:
        os.close(targetFd)
    assert (targetDir / "target-only").read_text(encoding="utf-8") == "target-only"

    (sourceDir / "both").write_text("both", encoding="utf-8")
    sourceFd = safeio.openDirectory(sourceDir)
    targetFd = safeio.openDirectory(targetDir)
    try:
        assert safeio.renameNoReplaceBetween(
            Path("both"),
            Path("both"),
            sourceDirFd=sourceFd,
            targetDirFd=targetFd,
        )
    finally:
        os.close(sourceFd)
        os.close(targetFd)
    assert (targetDir / "both").read_text(encoding="utf-8") == "both"


@pytest.mark.core
def testSafeIO_RenameNoReplaceIfSameFile(tmp_path: Path):
    """Test that the identity-checked helper moves the expected file."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)

    assert safeio.renameNoReplaceIfSameFile(source, target, expectedIdentity) is True
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "source"


@pytest.mark.core
def testSafeIO_RenameNoReplaceIfSameFileKeepsSourceWhenTargetExists(tmp_path: Path):
    """Test that an existing target leaves the expected source in place."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)

    assert safeio.renameNoReplaceIfSameFile(source, target, expectedIdentity) is False
    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "target"


@pytest.mark.core
def testSafeIO_RenameNoReplaceIfSameFileRestoresRacedSource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a raced source replacement is restored, not deleted."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)
    realRename = safeio.renameNoReplaceBetween
    injected = False

    def injectRace(
        renameSource: Path,
        renameTarget: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        nonlocal injected
        if not injected and renameSource.name == source.name and renameTarget.name.startswith(".umbraedit-rename-"):
            injected = True
            source.unlink()
            source.write_text("replacement", encoding="utf-8")
        return realRename(
            renameSource,
            renameTarget,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", injectRace)
        with pytest.raises(OSError):
            safeio.renameNoReplaceIfSameFile(source, target, expectedIdentity)

    assert injected is True
    assert source.read_text(encoding="utf-8") == "replacement"
    assert not target.exists()
    assert list(tmp_path.glob(".umbraedit-rename-*")) == []


@pytest.mark.core
def testSafeIO_RenameNoReplaceIfSameFilePreservesConcurrentTarget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a concurrent target replacement is never removed."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)
    realRename = safeio.renameNoReplaceBetween
    injected = False

    def injectRace(
        renameSource: Path,
        renameTarget: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        nonlocal injected
        result = realRename(
            renameSource,
            renameTarget,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )
        if not injected and renameTarget.name == target.name:
            injected = True
            target.unlink()
            target.write_text("concurrent", encoding="utf-8")
        return result

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", injectRace)
        with pytest.raises(OSError):
            safeio.renameNoReplaceIfSameFile(source, target, expectedIdentity)

    assert injected is True
    assert not target.exists()
    conflicts = list(tmp_path.glob(".umbraedit-conflict-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == "concurrent"


@pytest.mark.core
def testSafeIO_RenameNoReplaceIfSameFilePreservesConcurrentSymlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a concurrent symbolic-link target is never followed."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    outside = tmp_path / "outside"
    source.write_text("source", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)
    realRename = safeio.renameNoReplaceBetween
    injected = False

    def injectRace(
        renameSource: Path,
        renameTarget: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        nonlocal injected
        result = realRename(
            renameSource,
            renameTarget,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )
        if not injected and renameTarget.name == target.name:
            injected = True
            target.unlink()
            os.symlink(outside, target)
        return result

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", injectRace)
        with pytest.raises(OSError):
            safeio.renameNoReplaceIfSameFile(source, target, expectedIdentity)

    assert injected is True
    assert not target.exists()
    conflicts = list(tmp_path.glob(".umbraedit-conflict-*"))
    assert len(conflicts) == 1
    assert conflicts[0].is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative rename test")
def testSafeIO_RenameNoReplaceIfSameFileUsesBothParentDescriptors(tmp_path: Path):
    """Test that publication remains bound to both opened parent directories."""
    sourceDir = tmp_path / "source"
    targetDir = tmp_path / "target"
    movedSourceDir = tmp_path / "moved-source"
    movedTargetDir = tmp_path / "moved-target"
    sourceDir.mkdir()
    targetDir.mkdir()
    source = sourceDir / "source"
    source.write_text("source", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)

    sourceFd = safeio.openDirectory(sourceDir)
    targetFd = safeio.openDirectory(targetDir)
    try:
        sourceDir.rename(movedSourceDir)
        targetDir.rename(movedTargetDir)
        assert safeio.renameNoReplaceIfSameFile(
            source,
            targetDir / "target",
            expectedIdentity,
            sourceDirFd=sourceFd,
            targetDirFd=targetFd,
        )
    finally:
        os.close(sourceFd)
        os.close(targetFd)

    assert (movedTargetDir / "target").read_text(encoding="utf-8") == "source"
    assert not (movedSourceDir / "source").exists()


@pytest.mark.core
def testSafeIO_WindowsPathDescendantValidation():
    """Test that Windows descendant checks are component and case aware."""
    root = Path("C:\\project\\root")
    child = Path("C:\\project\\root\\child")
    sibling = Path("C:\\project\\root-elsewhere\\child")

    assert safeio._windowsPathIsDirectChild(root, child)
    assert safeio._windowsPathIsDirectChild(Path("C:\\PROJECT\\ROOT"), Path("c:\\project\\root\\child"))
    assert not safeio._windowsPathIsDirectChild(root, sibling)
    assert not safeio._windowsPathIsDirectChild(root, root)
    assert not safeio._windowsPathIsDirectChild(Path("D:\\project"), child)


@pytest.mark.core
def testSafeIO_WindowsStatMatchesNativeHandle():
    """Test that Windows stat snapshots are bound to native handle identities."""
    legacyIdentity = safeio.FileIdentity(44, 7, 123456, safeio._GENERATION_WINDOWS_LEGACY)
    legacyInformation = safeio._WindowsHandleInformation(
        identity=legacyIdentity,
        attributes=0,
        legacyIdentity=legacyIdentity,
    )
    legacyStat = SimpleNamespace(
        # Windows st_dev is a drive number, not the native volume serial.
        st_dev=99,
        st_ino=7,
        st_ctime_ns=123456,
        st_mode=0o100000,
        st_file_attributes=0,
    )
    assert safeio._windowsStatMatchesHandle(cast(os.stat_result, legacyStat), legacyInformation) is True

    fileId = (1 << 64) + 7
    fileIdIdentity = safeio.FileIdentity(
        44,
        fileId,
        123456,
        safeio._GENERATION_WINDOWS_FILE_ID,
    )
    fileIdInformation = safeio._WindowsHandleInformation(
        identity=fileIdIdentity,
        attributes=0,
        legacyIdentity=legacyIdentity,
    )
    fileIdStat = SimpleNamespace(
        st_dev=44,
        st_ino=fileId,
        st_birthtime_ns=123456,
        st_mode=0o100000,
        st_file_attributes=0,
    )
    assert safeio._windowsStatMatchesHandle(cast(os.stat_result, fileIdStat), fileIdInformation) is True

    replacementStat = SimpleNamespace(
        st_dev=44,
        st_ino=8,
        st_ctime_ns=123456,
        st_mode=0o100000,
        st_file_attributes=0,
    )
    assert safeio._windowsStatMatchesHandle(cast(os.stat_result, replacementStat), legacyInformation) is False

    # Python 3.9 cannot expose a 128-bit ReFS file ID through stat. If the
    # legacy index is also unavailable, the snapshot cannot be bound safely
    # to the native handle and cleanup must fail closed.
    refsZeroLegacy = safeio.FileIdentity(
        44,
        0,
        123456,
        safeio._GENERATION_WINDOWS_LEGACY,
    )
    refsInformation = safeio._WindowsHandleInformation(
        identity=fileIdIdentity,
        attributes=0,
        legacyIdentity=refsZeroLegacy,
    )
    refsStat = SimpleNamespace(
        st_dev=44,
        st_ino=0,
        st_ctime_ns=123456,
        st_mode=0o100000,
        st_file_attributes=0,
    )
    assert safeio._windowsStatMatchesHandle(cast(os.stat_result, refsStat), refsInformation) is False


@pytest.mark.core
def testSafeIO_WindowsTreeRejectsChildOutsideValidatedRoot(monkeypatch: pytest.MonkeyPatch):
    """Test that Windows tree cleanup rejects a child outside its root."""
    rootPath = Path("C:\\project\\root")
    childPath = Path("C:\\project\\root\\child")
    rootIdentity = safeio.FileIdentity(0, 1, 2, safeio._GENERATION_BIRTH)
    childIdentity = safeio.FileIdentity(0, 2, 3, safeio._GENERATION_BIRTH)
    rootStat = SimpleNamespace(st_mode=0o040000, st_file_attributes=0)
    childStat = SimpleNamespace(st_mode=0o100000, st_file_attributes=0)
    entry = SimpleNamespace(
        path=os.fspath(childPath),
        stat=lambda follow_symlinks=False: childStat,
    )
    scannedPaths: list[str] = []

    class FakeScandir:
        def __init__(self, path: Path):
            scannedPaths.append(os.fspath(path))

        def __enter__(self):
            return iter((entry,))

        def __exit__(self, *args: object):
            return False

    fakeOS = SimpleNamespace(**vars(os))
    fakeOS.lstat = lambda path: rootStat if path == rootPath else childStat
    fakeOS.scandir = FakeScandir
    deletedHandles: list[int] = []

    def openHandle(path: Path, *, directory: bool) -> int:
        return 1 if path == rootPath else 2

    def handleInfo(handle: int):
        identity = rootIdentity if handle == 1 else childIdentity
        attributes = safeio._FILE_ATTRIBUTE_DIRECTORY if handle == 1 else 0
        return safeio._WindowsHandleInformation(identity=identity, attributes=attributes)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "os", fakeOS)
        mp.setattr(safeio, "identityMatches", lambda *args, **kwargs: True)
        mp.setattr(safeio, "fileIdentity", lambda path, *args, **kwargs: childIdentity)
        mp.setattr(safeio, "_openWindowsDeleteHandle", openHandle)
        mp.setattr(safeio, "_windowsHandleInformation", handleInfo)
        mp.setattr(safeio, "_windowsStatMatchesHandle", lambda *args: True)
        mp.setattr(
            safeio,
            "_windowsHandleFinalPath",
            lambda handle: rootPath if handle == 1 else Path("C:\\outside\\child"),
        )
        mp.setattr(safeio, "_setWindowsDeleteDisposition", lambda handle, path: deletedHandles.append(handle))
        mp.setattr(safeio, "_closeWindowsHandle", lambda handle: None)

        with pytest.raises(OSError):
            safeio._removeWindowsTreeByHandle(rootPath, rootIdentity)

    assert scannedPaths == [os.fspath(rootPath)]
    assert deletedHandles == []


@pytest.mark.core
def testSafeIO_WindowsTreePreservesEntryReplacedAfterScan(monkeypatch: pytest.MonkeyPatch):
    """Test that a child replaced after enumeration is never deleted."""
    rootPath = Path("C:\\project\\root")
    childPath = Path("C:\\project\\root\\child")
    rootIdentity = safeio.FileIdentity(44, 1, 100, safeio._GENERATION_WINDOWS_LEGACY)
    originalChildIdentity = safeio.FileIdentity(44, 2, 200, safeio._GENERATION_WINDOWS_LEGACY)
    replacementChildIdentity = safeio.FileIdentity(44, 3, 300, safeio._GENERATION_WINDOWS_LEGACY)
    rootStat = SimpleNamespace(
        st_mode=0o040000,
        st_file_attributes=safeio._FILE_ATTRIBUTE_DIRECTORY,
        st_dev=44,
        st_ino=1,
        st_ctime_ns=100,
    )
    childStat = SimpleNamespace(
        st_mode=0o100000,
        st_file_attributes=0,
        st_dev=44,
        st_ino=2,
        st_ctime_ns=200,
    )
    entry = SimpleNamespace(
        path=os.fspath(childPath),
        stat=lambda follow_symlinks=False: childStat,
    )

    class FakeScandir:
        def __init__(self, path: Path):
            pass

        def __enter__(self):
            return iter((entry,))

        def __exit__(self, *args: object):
            return False

    fakeOS = SimpleNamespace(**vars(os))
    fakeOS.lstat = lambda path: rootStat if path == rootPath else childStat
    fakeOS.scandir = FakeScandir
    deletedHandles: list[int] = []

    def openHandle(path: Path, *, directory: bool) -> int:
        return 1 if path == rootPath else 2

    def handleInfo(handle: int, **kwargs: object):
        identity = rootIdentity if handle == 1 else replacementChildIdentity
        attributes = safeio._FILE_ATTRIBUTE_DIRECTORY if handle == 1 else 0
        return safeio._WindowsHandleInformation(
            identity=identity,
            attributes=attributes,
            legacyIdentity=identity,
        )

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "os", fakeOS)
        mp.setattr(safeio, "identityMatches", lambda *args, **kwargs: True)
        mp.setattr(safeio, "_openWindowsDeleteHandle", openHandle)
        mp.setattr(safeio, "_windowsHandleInformation", handleInfo)
        mp.setattr(
            safeio,
            "_windowsHandleFinalPath",
            lambda handle: rootPath if handle == 1 else childPath,
        )
        mp.setattr(safeio, "_setWindowsDeleteDisposition", lambda handle, path: deletedHandles.append(handle))
        mp.setattr(safeio, "_closeWindowsHandle", lambda handle: None)

        with pytest.raises(OSError, match="cleanup entry changed"):
            safeio._removeWindowsTreeByHandle(rootPath, rootIdentity)

    assert deletedHandles == []
    assert originalChildIdentity != replacementChildIdentity


@pytest.mark.core
def testSafeIO_WindowsTreeDoesNotTraverseReparsePoint(monkeypatch: pytest.MonkeyPatch):
    """Test that Windows tree cleanup deletes a reparse point as a leaf."""
    rootPath = Path("C:\\project\\root")
    childPath = Path("C:\\project\\root\\child")
    rootIdentity = safeio.FileIdentity(0, 1, 2, safeio._GENERATION_BIRTH)
    childIdentity = safeio.FileIdentity(0, 2, 3, safeio._GENERATION_BIRTH)
    rootStat = SimpleNamespace(st_mode=0o040000, st_file_attributes=0)
    childStat = SimpleNamespace(st_mode=0o040000, st_file_attributes=safeio._FILE_ATTRIBUTE_REPARSE_POINT)

    def failCachedStat(*args: object, **kwargs: object) -> None:
        raise AssertionError("Cached DirEntry metadata cannot identify the object")

    entry = SimpleNamespace(
        path=os.fspath(childPath),
        stat=failCachedStat,
    )
    scannedPaths: list[str] = []

    class FakeScandir:
        def __init__(self, path: Path):
            scannedPaths.append(os.fspath(path))

        def __enter__(self):
            return iter((entry,))

        def __exit__(self, *args: object):
            return False

    fakeOS = SimpleNamespace(**vars(os))
    fakeOS.lstat = lambda path: rootStat if path == rootPath else childStat
    fakeOS.scandir = FakeScandir
    deletedHandles: list[int] = []

    def openHandle(path: Path, *, directory: bool) -> int:
        return 1 if path == rootPath else 2

    def handleInfo(handle: int):
        identity = rootIdentity if handle == 1 else childIdentity
        attributes = safeio._FILE_ATTRIBUTE_DIRECTORY
        if handle == 2:
            attributes |= safeio._FILE_ATTRIBUTE_REPARSE_POINT
        return safeio._WindowsHandleInformation(identity=identity, attributes=attributes)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "os", fakeOS)
        mp.setattr(safeio, "identityMatches", lambda *args, **kwargs: True)
        mp.setattr(safeio, "fileIdentity", lambda path, *args, **kwargs: childIdentity)
        mp.setattr(safeio, "_openWindowsDeleteHandle", openHandle)
        mp.setattr(safeio, "_windowsHandleInformation", handleInfo)
        mp.setattr(safeio, "_windowsStatMatchesHandle", lambda *args: True)
        mp.setattr(
            safeio,
            "_windowsHandleFinalPath",
            lambda handle: rootPath if handle == 1 else childPath,
        )
        mp.setattr(safeio, "_setWindowsDeleteDisposition", lambda handle, path: deletedHandles.append(handle))
        mp.setattr(safeio, "_closeWindowsHandle", lambda handle: None)

        safeio._removeWindowsTreeByHandle(rootPath, rootIdentity)

    assert scannedPaths == [os.fspath(rootPath)]
    assert deletedHandles == [2, 1]


@pytest.mark.core
def testSafeIO_WindowsTreeRejectsDirectoryMovedBeforeRecursiveScan(monkeypatch: pytest.MonkeyPatch):
    """Test that a directory moved outside the root is not scanned or deleted."""
    rootPath = Path("C:\\project\\root")
    movedPath = Path("C:\\outside\\root")
    rootIdentity = safeio.FileIdentity(0, 1, 2, safeio._GENERATION_BIRTH)
    scannedPaths: list[str] = []

    def failScan(path: Path):
        scannedPaths.append(os.fspath(path))
        raise AssertionError("The moved directory was scanned")

    with monkeypatch.context() as mp:
        mp.setattr(safeio.os, "scandir", failScan)
        mp.setattr(
            safeio,
            "_windowsHandleInformation",
            lambda handle: safeio._WindowsHandleInformation(identity=rootIdentity, attributes=0),
        )
        mp.setattr(safeio, "_windowsHandleFinalPath", lambda handle: movedPath)

        with pytest.raises(OSError, match="moved outside"):
            safeio._removeWindowsDirectoryContents(
                1,
                rootPath,
                rootIdentity,
                rootPath,
            )

    assert scannedPaths == []


@pytest.mark.core
def testSafeIO_WindowsFileIdentityIncludesVolumeAnd128BitId(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that Windows file IDs are volume-scoped and retain 128 bits."""
    volumes = {1: 11, 2: 22}
    fileIds = {1: (1 << 127) + 1, 2: (1 << 127) + 1}

    def legacyInformation(handle: int) -> safeio._WindowsHandleInformation:
        identity = safeio.FileIdentity(
            volumes[handle],
            7,
            123456,
            safeio._GENERATION_WINDOWS_LEGACY,
        )
        return safeio._WindowsHandleInformation(identity=identity, attributes=0)

    def fileId(handle: int) -> tuple[int, int]:
        return volumes[handle], fileIds[handle]

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsLegacyHandleInformation", legacyInformation)
        mp.setattr(safeio, "_windowsFileId", fileId)

        first = safeio._windowsHandleInformation(1)
        second = safeio._windowsHandleInformation(2)

    assert first.identity.device == 11
    assert first.identity.inode == (1 << 127) + 1
    assert first.identity.generationSource == safeio._GENERATION_WINDOWS_FILE_ID
    assert first.identity != second.identity


@pytest.mark.core
def testSafeIO_WindowsFileIdWorksWithZeroLegacyIndex(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that a valid 128-bit ID is accepted if the legacy index is zero."""
    legacy = safeio._WindowsHandleInformation(
        identity=safeio.FileIdentity(
            44,
            0,
            123456,
            safeio._GENERATION_WINDOWS_LEGACY,
        ),
        attributes=0,
    )
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsLegacyHandleInformation", lambda handle: legacy)
        mp.setattr(safeio, "_windowsFileId", lambda handle: (44, 987654321))

        information = safeio._windowsHandleInformation(1)

    assert information.identity.device == 44
    assert information.identity.inode == 987654321
    assert information.identity.generationSource == safeio._GENERATION_WINDOWS_FILE_ID


@pytest.mark.core
def testSafeIO_WindowsLegacyIdentityIncludesVolume(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that the legacy Windows fallback is still volume-scoped."""
    legacy = safeio._WindowsHandleInformation(
        identity=safeio.FileIdentity(
            33,
            9,
            123456,
            safeio._GENERATION_WINDOWS_LEGACY,
        ),
        attributes=0,
    )
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsLegacyHandleInformation", lambda handle: legacy)
        mp.setattr(safeio, "_windowsFileId", lambda handle: None)

        information = safeio._windowsHandleInformation(1)

    assert information.identity.device == 33
    assert information.identity.generationSource == safeio._GENERATION_WINDOWS_LEGACY


@pytest.mark.core
def testSafeIO_WindowsCloseHandleFailureIsReported(monkeypatch: pytest.MonkeyPatch):
    """Test that a failed native handle close is not ignored."""

    class FakeCloseHandle:
        argtypes = None
        restype = None

        def __call__(self, handle: int) -> int:
            return 0

    fakeKernel = SimpleNamespace(CloseHandle=FakeCloseHandle())
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        mp.setattr(safeio, "_windowsLastError", lambda: 5)

        with pytest.raises(OSError):
            safeio._closeWindowsHandle(1)


@pytest.mark.core
def testSafeIO_WindowsSingleDeletionReportsCloseFailure(monkeypatch: pytest.MonkeyPatch):
    """Test that successful deletion still reports a failed handle close."""
    path = Path("C:\\project\\file")
    expectedIdentity = safeio.FileIdentity(0, 1, 2, safeio._GENERATION_BIRTH)
    pathStat = SimpleNamespace(st_mode=0o100000, st_file_attributes=0)

    with monkeypatch.context() as mp:
        mp.setattr(safeio.os, "lstat", lambda observed: pathStat)
        mp.setattr(safeio, "identityMatches", lambda *args, **kwargs: True)
        mp.setattr(safeio, "_openWindowsDeleteHandle", lambda observed, directory: 1)
        mp.setattr(
            safeio,
            "_windowsHandleInformation",
            lambda handle: safeio._WindowsHandleInformation(
                identity=expectedIdentity,
                attributes=0,
            ),
        )
        mp.setattr(safeio, "_setWindowsDeleteDisposition", lambda handle, observed: None)
        mp.setattr(
            safeio,
            "_closeWindowsHandle",
            lambda handle: (_ for _ in ()).throw(OSError("close failed")),
        )

        with pytest.raises(OSError, match="close failed"):
            safeio._deleteWindowsEntryByHandle(path, expectedIdentity)


@pytest.mark.core
def testSafeIO_WindowsTreeDeletionReportsCloseFailure(monkeypatch: pytest.MonkeyPatch):
    """Test that recursive Windows cleanup reports a failed handle close."""
    path = Path("C:\\project\\root")
    expectedIdentity = safeio.FileIdentity(0, 1, 2, safeio._GENERATION_BIRTH)
    pathStat = SimpleNamespace(st_mode=0o040000, st_file_attributes=0)

    with monkeypatch.context() as mp:
        mp.setattr(safeio.os, "lstat", lambda observed: pathStat)
        mp.setattr(safeio, "isLinkLike", lambda observed: False)
        mp.setattr(safeio, "identityMatches", lambda *args, **kwargs: True)
        mp.setattr(safeio, "_openWindowsDeleteHandle", lambda observed, directory: 1)
        mp.setattr(
            safeio,
            "_windowsHandleInformation",
            lambda handle: safeio._WindowsHandleInformation(
                identity=expectedIdentity,
                attributes=safeio._FILE_ATTRIBUTE_DIRECTORY,
            ),
        )
        mp.setattr(safeio, "_removeWindowsDirectoryContents", lambda *args, **kwargs: None)
        mp.setattr(safeio, "_windowsHandleFinalPath", lambda handle: path)
        mp.setattr(safeio, "_setWindowsDeleteDisposition", lambda handle, observed: None)
        mp.setattr(
            safeio,
            "_closeWindowsHandle",
            lambda handle: (_ for _ in ()).throw(OSError("close failed")),
        )

        with pytest.raises(OSError, match="close failed"):
            safeio._removeWindowsTreeByHandle(path, expectedIdentity)


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows native deletion integration test")
def testSafeIO_WindowsNativeDeletionPreservesRacedReplacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that Windows deletion disposes only the exact validated file."""
    path = tmp_path / "file"
    movedPath = tmp_path / "moved-file"
    path.write_text("original", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(path), path)
    realOpenHandle = safeio._openWindowsDeleteHandle
    replaced = False

    def replaceBeforeOpen(observed: Path, *, directory: bool) -> int:
        nonlocal replaced
        if Path(observed) == path and not replaced:
            replaced = True
            path.rename(movedPath)
            path.write_text("replacement", encoding="utf-8")
        return realOpenHandle(observed, directory=directory)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_openWindowsDeleteHandle", replaceBeforeOpen)
        with pytest.raises(OSError, match="changed before it could be removed"):
            safeio.unlinkEntryIfSameFile(path, expectedIdentity)

    assert replaced is True
    assert path.read_text(encoding="utf-8") == "replacement"
    assert movedPath.read_text(encoding="utf-8") == "original"


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows native cleanup integration test")
def testSafeIO_WindowsNativeCleanupPreservesRacedDescendant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that recursive cleanup preserves a child replaced after its scan."""
    root = tmp_path / "root"
    child = root / "child"
    movedChild = tmp_path / "moved-child"
    root.mkdir()
    child.write_text("original", encoding="utf-8")
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)
    realOpenHandle = safeio._openWindowsDeleteHandle
    replaced = False

    def replaceBeforeOpen(observed: Path, *, directory: bool) -> int:
        nonlocal replaced
        if Path(observed) == child and not replaced:
            replaced = True
            child.rename(movedChild)
            child.write_text("replacement", encoding="utf-8")
        return realOpenHandle(observed, directory=directory)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_openWindowsDeleteHandle", replaceBeforeOpen)
        with pytest.raises(OSError, match="cleanup entry changed"):
            safeio.removeTreeIfOwned(root, rootIdentity)

    assert replaced is True
    assert child.read_text(encoding="utf-8") == "replacement"
    assert movedChild.read_text(encoding="utf-8") == "original"
    assert root.is_dir()


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows native cleanup integration test")
def testSafeIO_WindowsNativeCleanupPreservesReplacedParent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that replacing a cleanup parent cannot redirect root deletion."""
    parent = tmp_path / "parent"
    movedParent = tmp_path / "moved-parent"
    root = parent / "root"
    parent.mkdir()
    root.mkdir()
    parentIdentity = safeio.fileIdentity(os.lstat(parent), parent)
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)
    realOpenHandle = safeio._openWindowsDeleteHandle
    replaced = False

    def replaceParentBeforeOpen(observed: Path, *, directory: bool) -> int:
        nonlocal replaced
        if Path(observed) == root and not replaced:
            replaced = True
            parent.rename(movedParent)
            parent.mkdir()
            root.mkdir()
        return realOpenHandle(observed, directory=directory)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_openWindowsDeleteHandle", replaceParentBeforeOpen)
        with pytest.raises(OSError, match="cleanup path changed"):
            safeio.removeTreeIfOwned(root, rootIdentity, expectedParent=parentIdentity)

    assert replaced is True
    assert root.is_dir()
    assert (movedParent / "root").is_dir()


@pytest.mark.core
def testSafeIO_WindowsExclusiveFileCanShareDelete(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that a publishable staging file permits delete access only."""
    createCalls: list[tuple[object, ...]] = []

    class FakeCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args: object) -> int:
            createCalls.append(args)
            return 123

    fakeKernel = SimpleNamespace(CreateFileW=FakeCreateFile())
    fakeMsvcrt = ModuleType("msvcrt")
    fakeMsvcrt.__dict__["open_osfhandle"] = lambda handle, flags: 456
    fakeOS = SimpleNamespace(**vars(os))
    fakeOS.name = "nt"

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "os", fakeOS)
        mp.setattr(safeio.ctypes, "WinDLL", lambda *args, **kwargs: fakeKernel, raising=False)
        mp.setitem(sys.modules, "msvcrt", fakeMsvcrt)

        assert safeio.openExclusiveFile(Path("C:\\project\\file"), shareDelete=True) == 456
        assert safeio.openExclusiveFile(Path("C:\\project\\private")) == 456

    assert createCalls[0][2] == 0x00000004
    assert createCalls[1][2] == 0


@pytest.mark.core
def testSafeIO_WindowsDescriptorConversionPreservesPrimaryError(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that a close failure does not mask descriptor conversion errors."""

    class FakeCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args: object) -> int:
            return 123

    fakeKernel = SimpleNamespace(CreateFileW=FakeCreateFile())
    fakeMsvcrt = ModuleType("msvcrt")

    def failConversion(handle: int, flags: int) -> int:
        raise RuntimeError("conversion failed")

    fakeMsvcrt.__dict__["open_osfhandle"] = failConversion
    fakeOS = SimpleNamespace(**vars(os))
    fakeOS.name = "nt"

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "os", fakeOS)
        mp.setattr(safeio.ctypes, "WinDLL", lambda *args, **kwargs: fakeKernel, raising=False)
        mp.setitem(sys.modules, "msvcrt", fakeMsvcrt)
        mp.setattr(
            safeio,
            "_closeWindowsHandle",
            lambda handle: (_ for _ in ()).throw(OSError("close failed")),
        )

        with pytest.raises(RuntimeError, match="conversion failed"):
            safeio.openExclusiveFile(Path("C:\\project\\file"))


@pytest.mark.core
def testSafeIO_WindowsRenameValidatesNativeObjects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that the Windows rename binds source and parent handles."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    sourceIdentity = safeio.FileIdentity(44, 1, 100, safeio._GENERATION_WINDOWS_LEGACY)
    parentIdentity = safeio.FileIdentity(44, 2, 200, safeio._GENERATION_WINDOWS_LEGACY)
    closedHandles: list[int] = []
    renameCalls: list[tuple[int, int, str, Path]] = []

    def handleInformation(handle: int, **kwargs: object) -> safeio._WindowsHandleInformation:
        if handle == 11:
            return safeio._WindowsHandleInformation(identity=sourceIdentity, attributes=0)
        return safeio._WindowsHandleInformation(
            identity=parentIdentity,
            attributes=safeio._FILE_ATTRIBUTE_DIRECTORY,
        )

    def setRenameInformation(
        sourceHandle: int,
        targetParentHandle: int,
        targetName: str,
        renameTarget: Path,
    ) -> bool:
        renameCalls.append((sourceHandle, targetParentHandle, targetName, renameTarget))
        return True

    with monkeypatch.context() as mp:
        mp.setattr(
            safeio,
            "fileIdentity",
            lambda observedStat, observedPath=None, *args, **kwargs: (
                sourceIdentity if observedPath is not None and Path(observedPath) == source else parentIdentity
            ),
        )
        mp.setattr(safeio, "_openWindowsDeleteHandle", lambda observed, directory: 11)
        mp.setattr(safeio, "_openWindowsRenameParentHandle", lambda observed: 22)
        mp.setattr(safeio, "_windowsHandleInformation", handleInformation)
        mp.setattr(
            safeio,
            "_windowsHandleFinalPath",
            lambda handle: source if handle == 11 else target.parent,
        )
        mp.setattr(safeio, "_setWindowsRenameInformation", setRenameInformation)
        mp.setattr(safeio, "_closeWindowsHandle", closedHandles.append)

        assert safeio._renameNoReplaceWindows(source, target) is True

    assert renameCalls == [(11, 22, target.name, target)]
    assert sorted(closedHandles) == [11, 22]


@pytest.mark.core
def testSafeIO_WindowsRenameRejectsReparseSource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a Windows rename cannot publish a reparse-point source."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    realLstat = os.lstat

    def observe(path: Path) -> os.stat_result:
        observed = realLstat(path)
        if Path(path) == source:
            return cast(
                os.stat_result,
                SimpleNamespace(
                    st_mode=observed.st_mode,
                    st_file_attributes=safeio._FILE_ATTRIBUTE_REPARSE_POINT,
                ),
            )
        return observed

    with monkeypatch.context() as mp:
        mp.setattr(safeio.os, "lstat", observe)
        with pytest.raises(OSError) as excInfo:
            safeio._renameNoReplaceWindows(source, target)

    assert excInfo.value.errno == errno.ELOOP
    assert source.read_text(encoding="utf-8") == "source"
    assert not target.exists()


@pytest.mark.core
def testSafeIO_WindowsRenameInformationUsesNoReplaceSemantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that native rename information is encoded for no replacement."""
    target = tmp_path / "target"

    class FakeSetFileInformation:
        argtypes = None
        restype = None

        def __call__(self, handle: int, infoClass: int, info: Any, size: int) -> int:
            assert handle == 11
            assert infoClass == 3
            raw = ctypes.string_at(info, size)
            information = safeio._WindowsFileRenameInfo.from_buffer_copy(raw)
            assert information.flags == 0
            assert information.rootDirectory == 22
            assert information.fileNameLength == len("target".encode("utf-16-le"))
            nameOffset = safeio._WindowsFileRenameInfo.fileName.offset
            nameBytes = raw[nameOffset : nameOffset + information.fileNameLength]
            assert nameBytes.decode("utf-16-le") == "target"
            return 1

    fakeKernel = SimpleNamespace(SetFileInformationByHandle=FakeSetFileInformation())
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        assert safeio._setWindowsRenameInformation(11, 22, "target", target) is True


@pytest.mark.core
def testSafeIO_WindowsRenameInformationFallsBackToNativeRootHandle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that Windows' rejected RootDirectory form uses the native path."""
    target = tmp_path / "target"

    class FakeSetFileInformation:
        argtypes = None
        restype = None

        def __call__(self, handle: int, infoClass: int, info: Any, size: int) -> int:
            return 0

    class FakeNtSetInformationFile:
        argtypes = None
        restype = None

        def __call__(
            self,
            handle: int,
            ioStatus: Any,
            info: Any,
            size: int,
            infoClass: int,
        ) -> int:
            assert handle == 11
            assert infoClass == 10
            raw = ctypes.string_at(info, size)
            information = safeio._WindowsFileRenameInfo.from_buffer_copy(raw)
            assert information.flags == 0
            assert information.rootDirectory == 22
            assert information.fileNameLength == len("target".encode("utf-16-le"))
            nameOffset = safeio._WindowsFileRenameInfo.fileName.offset
            nameBytes = raw[nameOffset : nameOffset + information.fileNameLength]
            assert nameBytes.decode("utf-16-le") == "target"
            return 0

    fakeKernel = SimpleNamespace(SetFileInformationByHandle=FakeSetFileInformation())
    fakeNtdll = SimpleNamespace(NtSetInformationFile=FakeNtSetInformationFile())
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        mp.setattr(safeio, "_windowsNtdll", lambda: fakeNtdll)
        mp.setattr(safeio, "_windowsLastError", lambda: safeio._WINDOWS_ERROR_INVALID_PARAMETER)
        assert safeio._setWindowsRenameInformation(11, 22, "target", target) is True


@pytest.mark.core
def testSafeIO_WindowsNativeRenameCollisionClassification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a native rename collision is not treated as an error."""
    target = tmp_path / "target"

    class FakeSetFileInformation:
        argtypes = None
        restype = None

        def __call__(self, handle: int, infoClass: int, info: Any, size: int) -> int:
            return 0

    class FakeNtSetInformationFile:
        argtypes = None
        restype = None

        def __call__(
            self,
            handle: int,
            ioStatus: Any,
            info: Any,
            size: int,
            infoClass: int,
        ) -> int:
            return safeio._WINDOWS_STATUS_OBJECT_NAME_COLLISION

    fakeKernel = SimpleNamespace(SetFileInformationByHandle=FakeSetFileInformation())
    fakeNtdll = SimpleNamespace(NtSetInformationFile=FakeNtSetInformationFile())
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        mp.setattr(safeio, "_windowsNtdll", lambda: fakeNtdll)
        mp.setattr(safeio, "_windowsLastError", lambda: safeio._WINDOWS_ERROR_INVALID_PARAMETER)
        assert safeio._setWindowsRenameInformation(11, 22, "target", target) is False


@pytest.mark.core
def testSafeIO_WindowsRenameCollisionClassification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that Windows rename collisions are distinguished from ACL errors."""
    target = tmp_path / "target"

    class FakeSetFileInformation:
        argtypes = None
        restype = None

        def __call__(self, handle: int, infoClass: int, info: object, size: int) -> int:
            return 0

    fakeKernel = SimpleNamespace(SetFileInformationByHandle=FakeSetFileInformation())
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        mp.setattr(safeio, "_windowsLastError", lambda: safeio._WINDOWS_ERROR_FILE_EXISTS)
        assert safeio._setWindowsRenameInformation(11, 22, "target", target) is False

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        mp.setattr(safeio, "_windowsLastError", lambda: safeio._WINDOWS_ERROR_ACCESS_DENIED)
        mp.setattr(safeio.os, "lstat", lambda observed: SimpleNamespace(st_mode=0o100000))
        assert safeio._setWindowsRenameInformation(11, 22, "target", target) is False

    def missingTarget(observed: Path) -> os.stat_result:
        raise FileNotFoundError(str(observed))

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_windowsKernel32", lambda: fakeKernel)
        mp.setattr(safeio, "_windowsLastError", lambda: safeio._WINDOWS_ERROR_ACCESS_DENIED)
        mp.setattr(safeio.os, "lstat", missingTarget)
        with pytest.raises(OSError) as excInfo:
            safeio._setWindowsRenameInformation(11, 22, "target", target)

    assert excInfo.value.errno == safeio._WINDOWS_ERROR_ACCESS_DENIED


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows native rename integration test")
def testSafeIO_WindowsNativeRenameNoReplace(tmp_path: Path):
    """Test the native Windows rename against real files."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")

    assert safeio.renameNoReplace(source, target) is False
    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "target"

    target.unlink()
    assert safeio.renameNoReplace(source, target) is True
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "source"


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows native rename integration test")
def testSafeIO_WindowsNativeRenameUsesExactSource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replaced source pathname cannot redirect publication."""
    source = tmp_path / "source"
    movedSource = tmp_path / "moved-source"
    target = tmp_path / "target"
    source.write_text("original", encoding="utf-8")
    realSetRename = safeio._setWindowsRenameInformation
    replaced = False

    def replaceSource(
        sourceHandle: int,
        targetParentHandle: int,
        targetName: str,
        renameTarget: Path,
    ) -> bool:
        nonlocal replaced
        if not replaced:
            replaced = True
            source.rename(movedSource)
            source.write_text("replacement", encoding="utf-8")
        return realSetRename(sourceHandle, targetParentHandle, targetName, renameTarget)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_setWindowsRenameInformation", replaceSource)
        assert safeio.renameNoReplace(source, target) is True

    assert replaced is True
    assert source.read_text(encoding="utf-8") == "replacement"
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows native rename integration test")
def testSafeIO_WindowsNativeRenameBindsReplacedParent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replaced target parent cannot redirect publication."""
    sourceDir = tmp_path / "source"
    targetDir = tmp_path / "target"
    movedTargetDir = tmp_path / "moved-target"
    sourceDir.mkdir()
    targetDir.mkdir()
    source = sourceDir / "source"
    source.write_text("source", encoding="utf-8")
    realSetRename = safeio._setWindowsRenameInformation

    def replaceParent(
        sourceHandle: int,
        targetParentHandle: int,
        targetName: str,
        target: Path,
    ) -> bool:
        targetDir.rename(movedTargetDir)
        targetDir.mkdir()
        return realSetRename(sourceHandle, targetParentHandle, targetName, target)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_setWindowsRenameInformation", replaceParent)
        assert safeio.renameNoReplace(source, targetDir / "published") is True

    assert (movedTargetDir / "published").read_text(encoding="utf-8") == "source"
    assert not (targetDir / "published").exists()
    assert not source.exists()


@pytest.mark.core
def testSafeIO_UnlinkIfSameFileRejectsReplacement(tmp_path: Path):
    """Test that identity-checked cleanup preserves a replacement file."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")
    identity = safeio.fileIdentity(os.lstat(path), path)
    path.unlink()
    path.write_text("replacement", encoding="utf-8")

    with pytest.raises(OSError):
        safeio.unlinkIfSameFile(path, identity)

    assert path.read_text(encoding="utf-8") == "replacement"


@pytest.mark.core
@pytest.mark.skipif(not safeio.sys.platform.startswith("linux"), reason="Linux file-handle identity")
def testSafeIO_LinuxFileHandleDistinguishesReplacement(tmp_path: Path):
    """Test that Linux file handles distinguish a reused inode."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")
    identity = safeio.fileIdentity(os.lstat(path), path)
    if identity.generationSource != safeio._GENERATION_FILE_HANDLE:
        pytest.skip("The filesystem does not expose Linux file handles")

    path.unlink()
    path.write_text("replacement", encoding="utf-8")
    replacementIdentity = safeio.fileIdentity(os.lstat(path), path)

    assert replacementIdentity != identity


@pytest.mark.core
@pytest.mark.skipif(not safeio.sys.platform.startswith("linux"), reason="Linux descriptor witness")
def testSafeIO_LinuxWitnessPreventsInodeReuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that the descriptor fallback prevents inode-number reuse."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_linuxFileHandleBytes", lambda descriptor: None)
        mp.setattr(safeio, "_linuxBirthTime", lambda *args, **kwargs: (0, 0))
        identity = safeio.fileIdentity(os.lstat(path), path)

        assert identity.generationSource == safeio._GENERATION_WITNESS
        assert identity._witness is not None

        path.unlink()
        path.write_text("replacement", encoding="utf-8")
        replacementIdentity = safeio.fileIdentity(os.lstat(path), path)

    assert replacementIdentity.inode != identity.inode
    assert replacementIdentity != identity


@pytest.mark.core
@pytest.mark.skipif(not safeio.sys.platform.startswith("linux"), reason="Linux descriptor witness")
def testSafeIO_LinuxWitnessIsSharedForOneObject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that repeated observations share one inode witness."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_linuxFileHandleBytes", lambda descriptor: None)
        mp.setattr(safeio, "_linuxBirthTime", lambda *args, **kwargs: (0, 0))
        firstIdentity = safeio.fileIdentity(os.lstat(path), path)
        secondIdentity = safeio.fileIdentity(os.lstat(path), path)

    assert firstIdentity.generationSource == safeio._GENERATION_WITNESS
    assert firstIdentity._witness is not None
    assert secondIdentity._witness is firstIdentity._witness


@pytest.mark.core
@pytest.mark.skipif(not safeio.sys.platform.startswith("linux"), reason="Linux descriptor witness")
def testSafeIO_LinuxBirthTimeDoesNotReplaceWitness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a repeated birth time cannot replace the witness fallback."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")
    pathStat = os.lstat(path)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_linuxFileHandleBytes", lambda descriptor: None)
        mp.setattr(safeio, "_linuxBirthTime", lambda *args, **kwargs: (123456, pathStat.st_ino))
        identity = safeio.fileIdentity(pathStat, path)

    assert identity.generationSource == safeio._GENERATION_WITNESS
    assert identity._witness is not None


@pytest.mark.core
@pytest.mark.skipif(not safeio.sys.platform.startswith("linux"), reason="Linux descriptor witness")
def testSafeIO_LinuxWitnessSurvivesDirectoryMetadataChange(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a witness identity tolerates a child directory update."""
    root = tmp_path / "root"
    root.mkdir()

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_linuxFileHandleBytes", lambda descriptor: None)
        mp.setattr(safeio, "_linuxBirthTime", lambda *args, **kwargs: (0, 0))
        identity = safeio.fileIdentity(os.lstat(root), root)
        (root / "child").mkdir()
        currentIdentity = safeio.fileIdentity(os.lstat(root), root)

    assert identity.generationSource == safeio._GENERATION_WITNESS
    assert currentIdentity == identity


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_ModeProbeUsesValidatedCentralQuarantine(tmp_path: Path):
    """Test that the mode probe cannot create a nested quarantine folder."""
    parent = tmp_path / "parent"
    central = tmp_path / "central"
    parent.mkdir()
    central.mkdir()
    parentIdentity = safeio.fileIdentity(os.lstat(parent), parent)
    centralIdentity = safeio.fileIdentity(os.lstat(central), central)

    mode = safeio.getDefaultDirectoryMode(
        parent,
        expectedParent=parentIdentity,
        quarantineParent=central,
        expectedQuarantineParent=centralIdentity,
    )

    assert mode > 0
    assert not (parent / safeio.QUARANTINE_DIRECTORY_NAME).exists()
    quarantine = central / safeio.QUARANTINE_DIRECTORY_NAME
    assert quarantine.is_dir()
    assert list(quarantine.iterdir())


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_ModeProbeRequiresCentralQuarantine(tmp_path: Path):
    """Test that POSIX mode probing fails without a validated quarantine."""
    parent = tmp_path / "parent"
    parent.mkdir()

    with pytest.raises(ValueError, match="central cleanup quarantine"):
        safeio.getDefaultDirectoryMode(parent)


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_EmptyDirectoryQuarantineBindsOpenedIdentity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replaced quarantined directory is not accepted as empty."""
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)
    nestedIdentity = safeio.fileIdentity(os.lstat(nested), nested)
    realOpenDirectoryAt = safeio.openDirectoryAt
    realOpenQuarantine = safeio._openQuarantineDirectory
    quarantineRoot: Optional[Path] = None

    def captureQuarantine(parentPath: Path, parentFd: int) -> tuple[int, Path]:
        nonlocal quarantineRoot
        result = realOpenQuarantine(parentPath, parentFd)
        quarantineRoot = result[1]
        return result

    def replaceQuarantinedDirectory(parentFd: int, name: str) -> int:
        if quarantineRoot is not None and name.startswith("entry-"):
            target = quarantineRoot / name
            os.rename(
                target,
                quarantineRoot / "expected-preserved",
                src_dir_fd=parentFd,
                dst_dir_fd=parentFd,
            )
            os.mkdir(name, 0o700, dir_fd=parentFd)
        return realOpenDirectoryAt(parentFd, name)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_openQuarantineDirectory", captureQuarantine)
        mp.setattr(safeio, "openDirectoryAt", replaceQuarantinedDirectory)

        with pytest.raises(OSError) as exc:
            safeio.removeEmptyDirectoryIfOwned(
                nested,
                nestedIdentity,
                expectedParent=rootIdentity,
                quarantineParent=root,
                expectedQuarantineParent=rootIdentity,
            )

    assert exc.value.errno == errno.EINVAL
    assert quarantineRoot is not None
    assert (quarantineRoot / "expected-preserved").is_dir()
    assert (
        quarantineRoot / next(path.name for path in quarantineRoot.iterdir() if path.name.startswith("entry-"))
    ).is_dir()


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_RenameTolerantGenerationSurvivesPublication(tmp_path: Path):
    """Test that rename-induced change times do not invalidate identities."""
    renameSource = tmp_path / "rename-source"
    renameTarget = tmp_path / "rename-target"
    renameSource.write_text("rename", encoding="utf-8")
    renameStat = os.lstat(renameSource)
    changeIdentity = safeio.FileIdentity(
        renameStat.st_dev,
        renameStat.st_ino,
        renameStat.st_ctime_ns - 1,
        safeio._GENERATION_CHANGE,
    )

    assert safeio.renameNoReplaceIfSameFile(renameSource, renameTarget, changeIdentity) is True
    assert renameTarget.read_text(encoding="utf-8") == "rename"

    linkSource = tmp_path / "link-source"
    linkTarget = tmp_path / "link-target"
    linkSource.write_text("link", encoding="utf-8")
    linkStat = os.lstat(linkSource)
    linkIdentity = safeio.FileIdentity(
        linkStat.st_dev,
        linkStat.st_ino,
        linkStat.st_ctime_ns - 1,
        safeio._GENERATION_CHANGE,
    )

    assert safeio.linkNoReplaceIfSameFile(linkSource, linkTarget, linkIdentity) is True
    assert linkTarget.read_text(encoding="utf-8") == "link"

    writeTarget = tmp_path / "write-target"
    writeTarget.write_text("old", encoding="utf-8")
    writeStat = os.lstat(writeTarget)
    writeIdentity = safeio.FileIdentity(
        writeStat.st_dev,
        writeStat.st_ino,
        writeStat.st_ctime_ns - 1,
        safeio._GENERATION_CHANGE,
    )
    safeio.writeFileAtomic(
        writeTarget,
        b"new",
        expectedTarget=writeIdentity,
        replaceExisting=True,
    )
    assert writeTarget.read_text(encoding="utf-8") == "new"

    publishSource = tmp_path / "publish-source"
    publishTarget = tmp_path / "publish-target"
    publishSource.write_text("publish", encoding="utf-8")
    publishStat = os.lstat(publishSource)
    publishIdentity = safeio.FileIdentity(
        publishStat.st_dev,
        publishStat.st_ino,
        publishStat.st_ctime_ns - 1,
        safeio._GENERATION_CHANGE,
    )
    safeio.publishRegularFileNoReplace(publishSource, publishTarget, publishIdentity)
    assert publishTarget.read_text(encoding="utf-8") == "publish"


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX identity fallback test")
def testSafeIO_ChangeGenerationToleratesParentUpdates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that child operations tolerate parent change-time updates."""
    realFileIdentity = safeio.fileIdentity

    def changeOnlyIdentity(
        pathStat: os.stat_result,
        path: Optional[Path] = None,
        *,
        dirFd: Optional[int] = None,
        fileDescriptor: Optional[int] = None,
        generationSource: Optional[int] = None,
    ) -> safeio.FileIdentity:
        """Return an identity using only the change-time fallback."""
        return realFileIdentity(
            pathStat,
            path,
            dirFd=dirFd,
            fileDescriptor=fileDescriptor,
            generationSource=safeio._GENERATION_CHANGE,
        )

    monkeypatch.setattr(safeio, "fileIdentity", changeOnlyIdentity)

    copySource = tmp_path / "copy-source"
    copySource.write_text("copy", encoding="utf-8")
    copyTarget = tmp_path / "copy-target"
    safeio.copyRegularFile(copySource, copyTarget)
    assert copyTarget.read_text(encoding="utf-8") == "copy"

    writeTarget = tmp_path / "write-target"
    safeio.writeFileAtomic(writeTarget, b"written")
    assert writeTarget.read_bytes() == b"written"

    publishSource = tmp_path / "publish-source"
    publishSource.write_text("publish", encoding="utf-8")
    publishIdentity = safeio.fileIdentity(os.lstat(publishSource), publishSource)
    publishTarget = tmp_path / "publish-target"
    safeio.publishRegularFileNoReplace(publishSource, publishTarget, publishIdentity)
    assert publishTarget.read_text(encoding="utf-8") == "publish"


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_UnlinkUsesValidatedCentralQuarantine(tmp_path: Path):
    """Test that nested cleanup does not create a nested quarantine folder."""
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    path = nested / "file"
    path.write_text("content", encoding="utf-8")
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)
    identity = safeio.fileIdentity(os.lstat(path), path)

    assert safeio.unlinkIfSameFile(
        path,
        identity,
        quarantineParent=root,
        expectedQuarantineParent=rootIdentity,
    )
    assert not path.exists()
    assert not (nested / safeio.QUARANTINE_DIRECTORY_NAME).exists()
    quarantine = root / safeio.QUARANTINE_DIRECTORY_NAME
    assert quarantine.is_dir()
    assert list(quarantine.iterdir())


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_UnlinkRejectsChangedCentralQuarantine(tmp_path: Path):
    """Test that a changed quarantine parent cannot redirect cleanup."""
    root = tmp_path / "root"
    other = tmp_path / "other"
    nested = root / "nested"
    nested.mkdir(parents=True)
    other.mkdir()
    path = nested / "file"
    path.write_text("content", encoding="utf-8")
    identity = safeio.fileIdentity(os.lstat(path), path)
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)

    with pytest.raises(OSError):
        safeio.unlinkIfSameFile(
            path,
            identity,
            quarantineParent=other,
            expectedQuarantineParent=rootIdentity,
        )

    assert path.read_text(encoding="utf-8") == "content"
    assert not (other / safeio.QUARANTINE_DIRECTORY_NAME).exists()


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_EmptyDirectoryTreatsNestedQuarantineAsContent(tmp_path: Path):
    """Test that a nested quarantine lookalike is not silently ignored."""
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / safeio.QUARANTINE_DIRECTORY_NAME).mkdir()
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)
    nestedIdentity = safeio.fileIdentity(os.lstat(nested), nested)

    with pytest.raises(OSError) as exc:
        safeio.removeEmptyDirectoryIfOwned(
            nested,
            nestedIdentity,
            expectedParent=rootIdentity,
            quarantineParent=root,
            expectedQuarantineParent=rootIdentity,
        )

    assert exc.value.errno == errno.ENOTEMPTY
    assert (nested / safeio.QUARANTINE_DIRECTORY_NAME).is_dir()


@pytest.mark.core
def testSafeIO_RemoveOwnedTree(tmp_path: Path):
    """Test that owned-tree cleanup removes contents without following links."""
    owned = tmp_path / "owned"
    nested = owned / "nested"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_text("content", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.symlink(outside, owned / "link", target_is_directory=True)

    identity = safeio.fileIdentity(os.lstat(owned), owned)
    assert safeio.removeTreeIfOwned(owned, identity) is True
    assert not owned.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.core
def testSafeIO_RemoveOwnedTreeRejectsReplacement(tmp_path: Path):
    """Test that owned-tree cleanup preserves a replacement directory."""
    owned = tmp_path / "owned"
    owned.mkdir()
    identity = safeio.fileIdentity(os.lstat(owned), owned)
    owned.rmdir()
    owned.mkdir()
    (owned / "foreign.txt").write_text("foreign", encoding="utf-8")

    with pytest.raises(OSError):
        safeio.removeTreeIfOwned(owned, identity)

    assert (owned / "foreign.txt").read_text(encoding="utf-8") == "foreign"


@pytest.mark.core
def testSafeIO_LinuxRawRenameat2Fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that old glibc versions can use the raw renameat2 syscall."""
    fakeLibc = _FakeLibc()
    monkeypatch.setattr(safeio.ctypes, "CDLL", lambda *args, **kwargs: fakeLibc)
    monkeypatch.setattr(safeio.platform, "machine", lambda: "x86_64")

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")

    assert safeio._renameNoReplaceLinux(source, target) is True
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "source"
    assert len(fakeLibc.syscall.calls) == 1


@pytest.mark.core
def testSafeIO_LinuxRawRenameat2ExistingTarget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that the raw syscall fallback does not replace an existing target."""
    fakeSyscall = _FakeExistingSyscall()
    fakeLibc = SimpleNamespace(syscall=fakeSyscall)
    monkeypatch.setattr(safeio.ctypes, "CDLL", lambda *args, **kwargs: fakeLibc)
    monkeypatch.setattr(safeio.platform, "machine", lambda: "x86_64")

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")

    assert safeio._renameNoReplaceLinux(source, target) is False
    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "target"
    assert len(fakeSyscall.calls) == 1


@pytest.mark.core
def testSafeIO_LinuxRenameat2Unsupported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that an unsupported Linux platform fails without replacing."""
    fakeLibc = _FakeLibc()
    monkeypatch.setattr(safeio.ctypes, "CDLL", lambda *args, **kwargs: fakeLibc)
    monkeypatch.setattr(safeio.platform, "machine", lambda: "unsupported")

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")

    with pytest.raises(OSError) as exc:
        safeio._renameNoReplaceLinux(source, target)
    assert exc.value.errno == errno.ENOTSUP
    assert source.exists()
    assert not target.exists()


@pytest.mark.core
def testSafeIO_WriteFileAtomicDoesNotOverwriteConcurrentTarget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a concurrent document target is never overwritten."""
    target = tmp_path / "document.md"
    target.write_text("original", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(target), target)
    realBetween = safeio.renameNoReplaceBetween
    realPathRename = safeio.renameNoReplace
    injected = False

    def injectBetween(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        nonlocal injected
        if not injected and source.name.startswith(".umbraedit-write-"):
            injected = True
            target.write_text("foreign", encoding="utf-8")
        return realBetween(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    def injectPathRename(source: Path, destination: Path) -> bool:
        nonlocal injected
        if not injected and source.name.startswith(".umbraedit-write-"):
            injected = True
            target.write_text("foreign", encoding="utf-8")
        return realPathRename(source, destination)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", injectBetween)
        mp.setattr(safeio, "renameNoReplace", injectPathRename)
        with pytest.raises(OSError):
            safeio.writeFileAtomic(
                target,
                b"replacement",
                expectedTarget=expectedIdentity,
                replaceExisting=True,
            )

    assert injected is True
    assert target.read_text(encoding="utf-8") == "foreign"
    preserved = list(tmp_path.glob(".umbraedit-replaced-*"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == "original"


@pytest.mark.core
def testSafeIO_AtomicWriteDoesNotReplaceUnknownTarget(tmp_path: Path):
    """Test that replacement requires an explicitly observed identity."""
    target = tmp_path / "document.md"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(OSError):
        safeio.writeFileAtomic(
            target,
            b"replacement",
            replaceExisting=True,
        )

    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.core
def testSafeIO_WriteFileAtomicRetainsPublishedIdentityOnValidationFailure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a post-publication failure exposes the published object."""
    target = tmp_path / "document.md"
    realEntryStat = safeio._entryStat

    def failPublishedStat(path: Path, dirFd: Optional[int]) -> os.stat_result:
        if path == target and path.exists():
            raise OSError(errno.EIO, "Simulated validation failure", str(path))
        return realEntryStat(path, dirFd)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "_entryStat", failPublishedStat)
        with pytest.raises(safeio.PublishedFileError) as exc:
            safeio.writeFileAtomic(target, b"published")

    assert target.read_bytes() == b"published"
    assert exc.value.publishedIdentity == safeio.fileIdentity(os.lstat(target), target)


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine race test")
def testSafeIO_UnlinkRacePreservesReplacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a file replaced during quarantine is restored and preserved."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(path), path)
    realBetween = safeio.renameNoReplaceBetween
    realPathRename = safeio.renameNoReplace
    injected = False

    def injectBetween(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        nonlocal injected
        if not injected and sourceDirFd is not None:
            injected = True
            sourcePath = path.parent / source.name
            sourcePath.unlink()
            sourcePath.write_text("replacement", encoding="utf-8")
        return realBetween(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    def injectPathRename(source: Path, destination: Path) -> bool:
        nonlocal injected
        if not injected:
            injected = True
            sourcePath = Path(source)
            sourcePath.unlink()
            sourcePath.write_text("replacement", encoding="utf-8")
        return realPathRename(source, destination)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", injectBetween)
        mp.setattr(safeio, "renameNoReplace", injectPathRename)
        with pytest.raises(OSError):
            safeio.unlinkIfSameFile(path, expectedIdentity)

    assert injected is True
    assert path.read_text(encoding="utf-8") == "replacement"


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX replaceable-target race test")
def testSafeIO_CopyPreservesReplacedTarget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a copied target replaced during the copy is preserved."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    realCopy = safeio.shutil.copyfileobj

    def replaceTarget(sourceFile: BinaryIO, targetFile: BinaryIO, length: int = 0) -> None:
        realCopy(sourceFile, targetFile, length)
        target.unlink()
        target.write_text("foreign", encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(safeio.shutil, "copyfileobj", replaceTarget)
        with pytest.raises(OSError):
            safeio.copyRegularFile(source, target)

    assert target.read_text(encoding="utf-8") == "foreign"


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive-sharing integration test")
def testSafeIO_WindowsCopyTargetCannotBeReplaced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that Windows copy locks the target against pathname replacement."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    realCopy = safeio.shutil.copyfileobj

    def rejectReplacement(sourceFile: BinaryIO, targetFile: BinaryIO, length: int = 0) -> None:
        realCopy(sourceFile, targetFile, length)
        with pytest.raises(PermissionError):
            target.unlink()

    with monkeypatch.context() as mp:
        mp.setattr(safeio.shutil, "copyfileobj", rejectReplacement)
        identity = safeio.copyRegularFile(source, target)

    assert identity == safeio.fileIdentity(os.lstat(target), target)
    assert target.read_text(encoding="utf-8") == "source"


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_CopyFailureUsesCentralQuarantine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a failed staged copy does not create a nested quarantine."""
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    source = tmp_path / "source"
    target = nested / "target"
    source.write_text("source", encoding="utf-8")
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)

    def failCopy(sourceFile: BinaryIO, targetFile: BinaryIO, length: int = 0) -> None:
        """Fail after the exclusive target has been created."""
        raise OSError("copy failed")

    with monkeypatch.context() as mp:
        mp.setattr(safeio.shutil, "copyfileobj", failCopy)
        with pytest.raises(OSError, match="copy failed"):
            safeio.copyRegularFile(
                source,
                target,
                quarantineParent=root,
                expectedQuarantineParent=rootIdentity,
            )

    assert not target.exists()
    assert not (nested / safeio.QUARANTINE_DIRECTORY_NAME).exists()
    quarantine = root / safeio.QUARANTINE_DIRECTORY_NAME
    assert quarantine.is_dir()
    assert list(quarantine.iterdir())


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine test")
def testSafeIO_AtomicWriteFailureUsesCentralQuarantine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a failed staged write does not create a nested quarantine."""
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    target = nested / "target"
    rootIdentity = safeio.fileIdentity(os.lstat(root), root)
    realBetween = safeio.renameNoReplaceBetween
    realPathRename = safeio.renameNoReplace

    def failBetween(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        """Fail publication of the private staging file."""
        if source.name.startswith(".umbraedit-write-") and destination.name == target.name:
            raise OSError("publication failed")
        return realBetween(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    def failPathRename(source: Path, destination: Path) -> bool:
        """Fail publication on platforms without directory descriptors."""
        if source.name.startswith(".umbraedit-write-") and destination.name == target.name:
            raise OSError("publication failed")
        return realPathRename(source, destination)

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", failBetween)
        mp.setattr(safeio, "renameNoReplace", failPathRename)
        with pytest.raises(OSError, match="publication failed"):
            safeio.writeFileAtomic(
                target,
                b"content",
                quarantineParent=root,
                expectedQuarantineParent=rootIdentity,
            )

    assert not target.exists()
    assert list(nested.glob(".umbraedit-write-*")) == []
    assert not (nested / safeio.QUARANTINE_DIRECTORY_NAME).exists()
    quarantine = root / safeio.QUARANTINE_DIRECTORY_NAME
    assert quarantine.is_dir()
    assert list(quarantine.iterdir())


@pytest.mark.core
def testSafeIO_WriteFileAtomicRestoresRacedQuarantine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replacement moved during quarantine is restored."""
    target = tmp_path / "document.md"
    target.write_text("original", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(target), target)
    realBetween = safeio.renameNoReplaceBetween
    injected = False

    def injectBetween(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        nonlocal injected
        if not injected and source.name == target.name:
            injected = True
            target.unlink()
            target.write_text("foreign", encoding="utf-8")
        return realBetween(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", injectBetween)
        with pytest.raises(OSError):
            safeio.writeFileAtomic(
                target,
                b"replacement",
                expectedTarget=expectedIdentity,
                replaceExisting=True,
            )

    assert injected is True
    assert target.read_text(encoding="utf-8") == "foreign"
    assert list(tmp_path.glob(".umbraedit-replaced-*")) == []
    assert list(tmp_path.glob(".umbraedit-write-*")) == []


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link symlink race test")
def testSafeIO_PublishRejectsRacedSourceEntry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a raced staging entry is never published as the target."""
    source = tmp_path / "stage"
    target = tmp_path / "published"
    outside = tmp_path / "outside"
    source.write_text("validated", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)
    realLink = os.link

    def replaceSource(sourceName, targetName, **kwargs):
        sourcePath = tmp_path / str(sourceName)
        sourcePath.unlink()
        try:
            os.symlink(outside, sourcePath)
        except OSError:
            pytest.skip("Symbolic links are not supported on this platform")
        return realLink(sourceName, targetName, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr(safeio.os, "link", replaceSource)
        with pytest.raises(OSError):
            safeio.publishRegularFileNoReplace(source, target, expectedIdentity)

    assert not target.exists()
    conflicts = list(tmp_path.glob(".umbraedit-conflict-*"))
    assert len(conflicts) == 1
    assert conflicts[0].is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"


@pytest.mark.core
def testSafeIO_PublishPreservesConcurrentTarget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replaced publication target is never removed or retried."""
    source = tmp_path / "stage"
    target = tmp_path / "published"
    source.write_text("validated", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(source), source)
    realLink = os.link

    def replaceTarget(sourceName, targetName, **kwargs):
        result = realLink(sourceName, targetName, **kwargs)
        targetPath = tmp_path / str(targetName)
        targetPath.unlink()
        targetPath.write_text("foreign", encoding="utf-8")
        return result

    with monkeypatch.context() as mp:
        mp.setattr(safeio.os, "link", replaceTarget)
        with pytest.raises(OSError):
            safeio.publishRegularFileNoReplace(source, target, expectedIdentity)

    assert target.read_text(encoding="utf-8") == "foreign"
    assert source.read_text(encoding="utf-8") == "validated"
    assert list(tmp_path.glob(".umbraedit-conflict-*")) == []


@pytest.mark.core
def testSafeIO_SnapshotRejectsReplacedFile(tmp_path: Path):
    """Test that a directory snapshot binds copies to the scanned file."""
    sourceDir = tmp_path / "source"
    sourceDir.mkdir()
    source = sourceDir / "document.md"
    source.write_text("original", encoding="utf-8")
    snapshot = safeio.scanRegularFiles(sourceDir)
    expectedIdentity = snapshot.fileIdentities[source.name]

    source.unlink()
    source.write_text("replacement", encoding="utf-8")

    with pytest.raises(OSError):
        safeio.openRegularFile(source, expectedIdentity=expectedIdentity)


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative copy test")
def testSafeIO_CopyDoesNotFollowReplacedTargetParent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a copied file stays bound to its target directory."""
    source = tmp_path / "source"
    targetDir = tmp_path / "target"
    outside = tmp_path / "outside"
    source.write_text("source", encoding="utf-8")
    targetDir.mkdir()
    outside.mkdir()
    target = targetDir / "copy.md"
    realCopy = safeio.shutil.copyfileobj

    def replaceParent(sourceFile, targetFile, length: int = 0) -> None:
        realCopy(sourceFile, targetFile, length)
        targetDir.rename(tmp_path / "moved-target")
        os.symlink(outside, targetDir, target_is_directory=True)

    with monkeypatch.context() as mp:
        mp.setattr(safeio.shutil, "copyfileobj", replaceParent)
        parentFd = safeio.openDirectory(targetDir)
        try:
            with pytest.raises(OSError):
                safeio.copyRegularFile(source, target, targetDirFd=parentFd)
        finally:
            os.close(parentFd)

    assert list(outside.iterdir()) == []
    assert not (tmp_path / "moved-target" / "copy.md").exists()


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative cleanup test")
def testSafeIO_RemoveOwnedTreeUsesDescriptorRelativeCleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that owned-tree cleanup does not fall back to shutil.rmtree."""
    assert os.listdir in os.supports_fd
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "file.txt").write_text("content", encoding="utf-8")
    identity = safeio.fileIdentity(os.lstat(owned), owned)

    def failRmtree(*args: object, **kwargs: object) -> None:
        raise AssertionError("The unsafe path-based cleanup fallback was used")

    with monkeypatch.context() as mp:
        mp.setattr(safeio.shutil, "rmtree", failRmtree)
        assert safeio.removeTreeIfOwned(owned, identity) is True

    assert not owned.exists()


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative cleanup test")
def testSafeIO_RemoveEmptyDirectoryUsesDescriptorRelativeCleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that empty-directory cleanup does not use the path-based fallback."""
    parent = tmp_path / "parent"
    owned = parent / "owned"
    parent.mkdir()
    owned.mkdir()
    parentIdentity = safeio.fileIdentity(os.lstat(parent), parent)
    ownedIdentity = safeio.fileIdentity(os.lstat(owned), owned)

    realRename = safeio.renameNoReplaceBetween

    def failPathRename(
        source: Path,
        target: Path,
        *,
        sourceDirFd: Optional[int] = None,
        targetDirFd: Optional[int] = None,
    ) -> bool:
        if sourceDirFd is None and targetDirFd is None:
            raise AssertionError("The path-based cleanup fallback was used")
        return realRename(
            source,
            target,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplaceBetween", failPathRename)
        assert safeio.removeEmptyDirectoryIfOwned(
            owned,
            ownedIdentity,
            expectedParent=parentIdentity,
        )

    assert not owned.exists()


@pytest.mark.core
def testSafeIO_RemoveEmptyDirectoryRejectsChangedParent(tmp_path: Path):
    """Test that an expected parent identity prevents cleanup after replacement."""
    parent = tmp_path / "parent"
    movedParent = tmp_path / "moved-parent"
    owned = parent / "owned"
    parent.mkdir()
    owned.mkdir()
    parentIdentity = safeio.fileIdentity(os.lstat(parent), parent)
    ownedIdentity = safeio.fileIdentity(os.lstat(owned), owned)
    owned.rmdir()
    parent.rename(movedParent)
    parent.mkdir()

    with pytest.raises(OSError):
        safeio.removeEmptyDirectoryIfOwned(
            owned,
            ownedIdentity,
            expectedParent=parentIdentity,
        )

    assert parent.is_dir()


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative cleanup test")
def testSafeIO_RemoveEmptyDirectoryRemainsBoundToOpenedParent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replaced parent path cannot redirect empty-directory cleanup."""
    parent = tmp_path / "parent"
    movedParent = tmp_path / "moved-parent"
    owned = parent / "owned"
    parent.mkdir()
    owned.mkdir()
    parentIdentity = safeio.fileIdentity(os.lstat(parent), parent)
    ownedIdentity = safeio.fileIdentity(os.lstat(owned), owned)
    realOpenDirectory = safeio.openDirectory
    replaced = False

    def replaceParentAfterOpen(path: Path) -> int:
        nonlocal replaced
        fileDesc = realOpenDirectory(path)
        if path == parent and not replaced:
            replaced = True
            parent.rename(movedParent)
            parent.mkdir()
        return fileDesc

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "openDirectory", replaceParentAfterOpen)
        with pytest.raises(OSError):
            safeio.removeEmptyDirectoryIfOwned(
                owned,
                ownedIdentity,
                expectedParent=parentIdentity,
            )

    assert replaced is True
    assert not (movedParent / "owned").exists()
    assert parent.is_dir()
