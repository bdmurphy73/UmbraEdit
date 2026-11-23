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

from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, Optional

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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))

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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))

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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))
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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))
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
    assert target.read_text(encoding="utf-8") == "concurrent"


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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))

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
def testSafeIO_WindowsRenameFallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that the Windows path-based fallback never replaces a target."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")
    realRename = os.rename

    def windowsRename(sourcePath, targetPath):
        if Path(targetPath).exists():
            raise FileExistsError(errno.EEXIST, "File exists", str(targetPath))
        return realRename(sourcePath, targetPath)

    fakeOS = SimpleNamespace(name="nt", rename=windowsRename)
    with monkeypatch.context() as mp:
        mp.setattr(safeio, "os", fakeOS)
        assert safeio.renameNoReplace(source, target) is False

    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "target"


@pytest.mark.core
def testSafeIO_UnlinkIfSameFileRejectsReplacement(tmp_path: Path):
    """Test that identity-checked cleanup preserves a replacement file."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")
    identity = safeio.fileIdentity(os.lstat(path))
    path.unlink()
    path.write_text("replacement", encoding="utf-8")

    with pytest.raises(OSError):
        safeio.unlinkIfSameFile(path, identity)

    assert path.read_text(encoding="utf-8") == "replacement"


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

    identity = safeio.fileIdentity(os.lstat(owned))
    assert safeio.removeTreeIfOwned(owned, identity) is True
    assert not owned.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.core
def testSafeIO_RemoveOwnedTreeRejectsReplacement(tmp_path: Path):
    """Test that owned-tree cleanup preserves a replacement directory."""
    owned = tmp_path / "owned"
    owned.mkdir()
    identity = safeio.fileIdentity(os.lstat(owned))
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
    expectedIdentity = safeio.fileIdentity(os.lstat(target))
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
def testSafeIO_UnlinkRacePreservesReplacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a file replaced during quarantine is restored and preserved."""
    path = tmp_path / "file"
    path.write_text("original", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(path))
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
def testSafeIO_WriteFileAtomicRestoresRacedQuarantine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Test that a replacement moved during quarantine is restored."""
    target = tmp_path / "document.md"
    target.write_text("original", encoding="utf-8")
    expectedIdentity = safeio.fileIdentity(os.lstat(target))
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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))
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
    expectedIdentity = safeio.fileIdentity(os.lstat(source))
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
    identity = safeio.fileIdentity(os.lstat(owned))

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
    parentIdentity = safeio.fileIdentity(os.lstat(parent))
    ownedIdentity = safeio.fileIdentity(os.lstat(owned))

    def failPathRename(*args: object, **kwargs: object) -> bool:
        raise AssertionError("The path-based cleanup fallback was used")

    with monkeypatch.context() as mp:
        mp.setattr(safeio, "renameNoReplace", failPathRename)
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
    parentIdentity = safeio.fileIdentity(os.lstat(parent))
    ownedIdentity = safeio.fileIdentity(os.lstat(owned))
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
    parentIdentity = safeio.fileIdentity(os.lstat(parent))
    ownedIdentity = safeio.fileIdentity(os.lstat(owned))
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
