"""
UmbraEdit - Project Image Import Tests
=======================================

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

import errno
import os
import shutil
import stat
import subprocess

from pathlib import Path
from time import time
from zipfile import ZipFile

import PIL.Image
import pytest

from umbraedit import SHARED
from umbraedit.constants import nwFiles
from umbraedit.core import imageimport
from umbraedit.core.imageimport import ImageImportError, ImageImportReason, importProjectImage, safeImageStem
from umbraedit.core.project import NWProject, copyRegularFile
from umbraedit.core.safeio import renameNoReplace, renameNoReplaceBetween, renameNoReplaceIfSameFile
from umbraedit.core.storage import _addFileToZip

from tests.helpers import C, MockRnd, buildTestProject
from tests.mocked import MockGuiMain


def _writeImage(path: Path, imageFormat: str = "PNG", size: tuple[int, int] = (4, 4)) -> None:
    """Write a small valid test image."""
    path.parent.mkdir(parents=True, exist_ok=True)
    PIL.Image.new("RGB", size, (20, 40, 60)).save(path, format=imageFormat)


@pytest.mark.core
def testImageImport_ValidImages(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test importing valid PNG and JPEG images."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    pngSource = fncPath / "cover.png"
    _writeImage(pngSource)
    pngResult = importProjectImage(project, pngSource)
    assert pngResult.relativePath == "assets/img/cover.png"
    assert pngResult.path == projPath / "assets" / "img" / "cover.png"
    assert pngResult.path.read_bytes() == pngSource.read_bytes()

    jpgSource = fncPath / "cover.jpg"
    _writeImage(jpgSource, "JPEG")
    jpgResult = importProjectImage(project, jpgSource)
    assert jpgResult.relativePath == "assets/img/cover.jpg"
    assert jpgResult.path == projPath / "assets" / "img" / "cover.jpg"
    assert jpgResult.path.read_bytes() == jpgSource.read_bytes()


@pytest.mark.core
def testImageImport_CollisionSuffix(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that existing project images are never overwritten."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    original = source.read_bytes()

    first = importProjectImage(project, source)
    second = importProjectImage(project, source)

    assert first.relativePath == "assets/img/cover.png"
    assert second.relativePath == "assets/img/cover_1.png"
    assert first.path.read_bytes() == original
    assert second.path.read_bytes() == original


@pytest.mark.core
def testImageImport_Validation(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test validation of missing, unsupported, and invalid images."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, fncPath / "missing.png")
    assert exc.value.reason == ImageImportReason.NOT_FOUND

    textSource = fncPath / "cover.txt"
    textSource.write_text("Not an image", encoding="utf-8")
    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, textSource)
    assert exc.value.reason == ImageImportReason.UNSUPPORTED_TYPE

    invalidSource = fncPath / "invalid.png"
    invalidSource.write_bytes(b"not an image")
    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, invalidSource)
    assert exc.value.reason == ImageImportReason.INVALID_IMAGE

    mismatchSource = fncPath / "mismatch.jpg"
    _writeImage(mismatchSource, "PNG")
    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, mismatchSource)
    assert exc.value.reason == ImageImportReason.FORMAT_MISMATCH

    otherFormatSource = fncPath / "other-format.jpg"
    _writeImage(otherFormatSource, "GIF")
    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, otherFormatSource)
    assert exc.value.reason == ImageImportReason.FORMAT_MISMATCH

    truncatedSource = fncPath / "truncated.jpg"
    _writeImage(truncatedSource, "JPEG", (100, 100))
    imageData = truncatedSource.read_bytes()
    truncatedSource.write_bytes(imageData[: int(len(imageData) * 0.9)])
    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, truncatedSource)
    assert exc.value.reason == ImageImportReason.INVALID_IMAGE

    assert not (projPath / "assets" / "img").exists()


@pytest.mark.core
@pytest.mark.parametrize(("imageFormat", "extension"), [("PNG", ".png"), ("JPEG", ".jpg")])
def testImageImport_RejectsTruncatedImageEnd(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
    imageFormat: str,
    extension: str,
):
    """Test that a missing PNG IEND or JPEG EOI marker is rejected."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / f"truncated{extension}"
    _writeImage(source, imageFormat, (1000, 1000))
    source.write_bytes(source.read_bytes()[:-1])

    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, source)
    assert exc.value.reason == ImageImportReason.INVALID_IMAGE
    assert not (projPath / "assets" / "img").exists()


@pytest.mark.core
def testImageImport_RejectsDecompressionBombWarning(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that images above Pillow's warning limit are rejected."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "large.png"
    _writeImage(source, size=(32, 32))
    monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 600)

    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, source)
    assert exc.value.reason == ImageImportReason.IMAGE_TOO_LARGE
    assert not (projPath / "assets" / "img").exists()


@pytest.mark.core
def testImageImport_PortableFilename(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that imported names are portable and leave room for suffixes."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    assert safeImageStem(Path("CON.png")) == "_CON"
    assert safeImageStem(Path("com1.png")) == "_com1"

    longStem = safeImageStem(Path(f"{'a' * 240}.png"))
    assert len(longStem.encode("utf-8")) + len(b".png") + 16 <= 255

    source = fncPath / "cover.png"
    _writeImage(source)
    first = importProjectImage(project, source)
    second = importProjectImage(project, source)
    assert len(first.path.name.encode("utf-8")) <= 255
    assert len(second.path.name.encode("utf-8")) <= 255
    assert second.path.name.endswith("_1.png")


@pytest.mark.core
def testImageImport_StagesOutsideAssetFolder(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that staging files cannot be captured by a backup."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    realCreateStage = imageimport._createStagingFile
    stageParents = []

    def inspectStage(projectRoot: Path, rootFd: int | None):
        stageParents.append(projectRoot)
        zipFile = fncPath / "during-import.zip"
        assert project.storage.zipIt(zipFile, time()) is True
        with ZipFile(zipFile, mode="r") as archive:
            assert not any(name.startswith(".umbraedit-image-") for name in archive.namelist())
        return realCreateStage(projectRoot, rootFd)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport._createStagingFile", inspectStage)
        result = importProjectImage(project, source)

    assert stageParents == [projPath]
    assert result.path.is_file()
    assert list(projPath.glob(".umbraedit-image-*.tmp")) == []


@pytest.mark.core
def testImageImport_NoProject(mockGUI: MockGuiMain, fncPath: Path):
    """Test importing an image without an open project."""
    source = fncPath / "cover.png"
    _writeImage(source)

    with pytest.raises(ImageImportError) as exc:
        importProjectImage(NWProject(), source)
    assert exc.value.reason == ImageImportReason.NO_PROJECT


@pytest.mark.core
def testImageImport_PublishFailure(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a failed atomic publish leaves no partial project image."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)

    def causeOSError(*args, **kwargs):
        raise OSError("Publish failed")

    def unsupportedRename(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Atomic rename is not supported")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeOSError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceIfSameFile", unsupportedRename)
        mp.setattr("umbraedit.core.imageimport.os.fsync", causeOSError)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    assert not (projPath / "assets" / "img" / "cover.png").exists()
    assert list(projPath.glob(".umbraedit-image-*.tmp")) == []


@pytest.mark.core
def testImageImport_AtomicRenameFallback(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that atomic no-replace rename is used when hard links are unavailable."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    renameCalls = 0
    realRename = renameNoReplaceIfSameFile

    def causeOSError(*args, **kwargs):
        raise OSError(errno.EPERM, "Hard links are not supported")

    def trackRename(*args, **kwargs):
        nonlocal renameCalls
        renameCalls += 1
        return realRename(*args, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeOSError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceIfSameFile", trackRename)
        first = importProjectImage(project, source)
        second = importProjectImage(project, source)

    assert renameCalls == 3
    assert first.relativePath == "assets/img/cover.png"
    assert second.relativePath == "assets/img/cover_1.png"
    assert first.path.read_bytes() == source.read_bytes()
    assert second.path.read_bytes() == source.read_bytes()


@pytest.mark.core
def testImageImport_AtomicRenameFallbackRestoresRacedStagingEntry(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a raced staging entry is restored and never published."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    realRename = renameNoReplaceBetween
    injected = False

    def causeLinkError(*args, **kwargs):
        raise OSError(errno.EPERM, "Hard links are not supported")

    def raceStagingEntry(
        renameSource: Path,
        renameTarget: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        nonlocal injected
        if (
            not injected
            and renameSource.name.startswith(".umbraedit-image-")
            and renameTarget.name.startswith(".umbraedit-rename-")
        ):
            injected = True
            stagePath = projPath / renameSource.name
            stagePath.unlink()
            stagePath.write_bytes(b"invalid concurrent staging data")
        return realRename(
            renameSource,
            renameTarget,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeLinkError)
        mp.setattr("umbraedit.core.safeio.renameNoReplaceBetween", raceStagingEntry)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    assert injected is True
    target = projPath / "assets" / "img" / "cover.png"
    assert not target.exists()
    stageFiles = list(projPath.glob(".umbraedit-image-*.tmp"))
    assert len(stageFiles) == 1
    assert stageFiles[0].read_bytes() == b"invalid concurrent staging data"


@pytest.mark.core
def testImageImport_AtomicRenameFallbackPreservesConcurrentTarget(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a concurrent target replacement is not removed on failure."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    concurrentSource = fncPath / "concurrent.png"
    _writeImage(concurrentSource)
    concurrentBytes = concurrentSource.read_bytes()
    realRename = renameNoReplaceBetween
    injected = False

    def causeLinkError(*args, **kwargs):
        raise OSError(errno.EPERM, "Hard links are not supported")

    def replacePublishedTarget(
        renameSource: Path,
        renameTarget: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        nonlocal injected
        result = realRename(
            renameSource,
            renameTarget,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )
        if not injected and renameTarget.name == "cover.png" and renameSource.name.startswith(".umbraedit-rename-"):
            injected = True
            target = projPath / "assets" / "img" / "cover.png"
            target.unlink()
            target.write_bytes(concurrentBytes)
        return result

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeLinkError)
        mp.setattr("umbraedit.core.safeio.renameNoReplaceBetween", replacePublishedTarget)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    assert injected is True
    target = projPath / "assets" / "img" / "cover.png"
    assert target.read_bytes() == concurrentBytes


@pytest.mark.core
@pytest.mark.parametrize(
    ("mutationKind", "expectedReason"),
    [
        ("invalid", ImageImportReason.INVALID_IMAGE),
        ("mismatch", ImageImportReason.FORMAT_MISMATCH),
    ],
)
def testImageImport_ExclusiveFallbackValidatesPublishedBytes(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
    mutationKind: str,
    expectedReason: ImageImportReason,
):
    """Test that the exclusive fallback rejects invalid or mismatched bytes."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    mismatchSource = fncPath / "mismatch.jpg"
    _writeImage(mismatchSource, "JPEG")
    mutationBytes = b"invalid image bytes" if mutationKind == "invalid" else mismatchSource.read_bytes()
    realCopy = shutil.copyfileobj
    copyCalls = 0

    def causeLinkError(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Hard links are not supported")

    def unsupportedRename(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Atomic rename is not supported")

    def mutateStagingFile(sourceFile, targetFile, *args, **kwargs):
        nonlocal copyCalls
        copyCalls += 1
        if copyCalls == 2:
            sourceFile.seek(0)
            sourceFile.truncate()
            sourceFile.write(mutationBytes)
            sourceFile.seek(0)
        return realCopy(sourceFile, targetFile, *args, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeLinkError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceIfSameFile", unsupportedRename)
        mp.setattr("umbraedit.core.imageimport.shutil.copyfileobj", mutateStagingFile)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == expectedReason
    assert copyCalls == 2
    assert not (projPath / "assets" / "img" / "cover.png").exists()
    assert list(projPath.glob(".umbraedit-image-*.tmp")) == []


@pytest.mark.core
def testImageImport_FallbackWithoutHardLinks(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test the exclusive-copy fallback when hard links are unavailable."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)

    def causeOSError(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Hard links are not supported")

    def unsupportedRename(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Atomic rename is not supported")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeOSError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceIfSameFile", unsupportedRename)
        mp.setattr("umbraedit.core.imageimport.renameNoReplace", unsupportedRename)
        result = importProjectImage(project, source)

    assert result.relativePath == "assets/img/cover.png"
    assert result.path.read_bytes() == source.read_bytes()


@pytest.mark.core
def testImageImport_RejectsReplacedStagingFile(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that bytes replaced after validation are never published."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    realLink = os.link

    def replaceSource(sourcePath, targetPath, **kwargs):
        sourceFile = projPath / Path(sourcePath).name if kwargs.get("src_dir_fd") is not None else Path(sourcePath)
        sourceFile.unlink()
        sourceFile.write_bytes(b"replaced after validation")
        return realLink(sourcePath, targetPath, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", replaceSource)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    assert not (projPath / "assets" / "img" / "cover.png").exists()
    for stageFile in projPath.glob(".umbraedit-image-*.tmp"):
        stageFile.unlink()


@pytest.mark.core
def testImageImport_PreservesForeignPublishedTarget(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a replaced publication target is never removed as cleanup."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    realLink = os.link

    def replaceTarget(sourcePath, targetPath, **kwargs):
        result = realLink(sourcePath, targetPath, **kwargs)
        target = projPath / "assets" / "img" / Path(targetPath).name
        target.unlink()
        target.write_bytes(b"foreign target")
        return result

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", replaceTarget)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    target = projPath / "assets" / "img" / "cover.png"
    assert target.read_bytes() == b"foreign target"
    assert list(projPath.glob(".umbraedit-image-*.tmp")) == []


@pytest.mark.core
def testImageImport_ExclusiveFallbackHidesPartialFile(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that the exclusive fallback cannot expose partial image data."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    realCopy = shutil.copyfileobj
    copyCalls = 0

    def causeOSError(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Hard links are not supported")

    def unsupportedRename(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Atomic rename is not supported")

    def inspectCopy(sourceFile, targetFile, *args, **kwargs):
        nonlocal copyCalls
        copyCalls += 1
        if copyCalls == 2:
            target = projPath / "assets" / "img" / "cover.png"
            assert target.exists()
            with pytest.raises(OSError):
                target.read_bytes()
        return realCopy(sourceFile, targetFile, *args, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeOSError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceIfSameFile", unsupportedRename)
        mp.setattr("umbraedit.core.imageimport.renameNoReplace", unsupportedRename)
        mp.setattr("umbraedit.core.imageimport.shutil.copyfileobj", inspectCopy)
        result = importProjectImage(project, source)

    assert copyCalls == 2
    assert result.path.read_bytes() == source.read_bytes()


@pytest.mark.core
@pytest.mark.parametrize("sourceName", ["cover,front.png", "cover，front.png"])
def testImageImport_SanitisesMetadataDelimiter(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
    sourceName: str,
):
    """Test that commas are removed from filenames used in metadata."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / sourceName
    _writeImage(source)
    result = importProjectImage(project, source)

    assert result.relativePath == "assets/img/cover_front.png"
    assert result.path.read_bytes() == source.read_bytes()


@pytest.mark.core
def testImageImport_BackupAndSaveAs(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that imported images are included in backups and Save As copies."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    importProjectImage(project, source)

    oldLockPath = projPath / nwFiles.PROJ_LOCK
    project.storage.lockSession()
    assert oldLockPath.is_file()

    zipFile = fncPath / "project.zip"
    assert project.storage.zipIt(zipFile, time()) is True
    with ZipFile(zipFile, mode="r") as archive:
        assert "assets/img/cover.png" in archive.namelist()

    newPath = fncPath / "project-copy"
    assert project.saveProjectAs(newPath, "Project Copy") is True
    assert (newPath / "assets" / "img" / "cover.png").read_bytes() == source.read_bytes()
    assert not oldLockPath.exists()
    assert (newPath / nwFiles.PROJ_LOCK).is_file()


@pytest.mark.core
def testImageImport_SaveAsAssetCopyFailureRollsBack(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a failed asset copy rolls back Save Project As."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    imported = importProjectImage(project, source)

    originalStoragePath = project.storage.storagePath
    originalRuntimePath = project.storage.runtimePath
    assert isinstance(originalRuntimePath, Path)
    originalUuid = project.data.uuid
    originalName = project.data.name
    originalChanged = project.projChanged
    newPath = fncPath / "failed-project-copy"

    realCopy = copyRegularFile

    def failAssetCopy(src, dst, **kwargs):
        if Path(src).parent == originalRuntimePath / "assets" / "img":
            raise OSError("Asset copy failed")
        return realCopy(src, dst, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.copyRegularFile", failAssetCopy)
        assert project.saveProjectAs(newPath, "Failed Project Copy") is False

    assert SHARED.lastAlert[0] == "Failed to copy project image file."
    assert project.storage.storagePath == originalStoragePath
    assert project.storage.runtimePath == originalRuntimePath
    assert project.data.uuid == originalUuid
    assert project.data.name == originalName
    assert project.projChanged is originalChanged
    assert imported.path.is_file()
    assert not newPath.exists()


@pytest.mark.core
def testImageImport_RejectsSymlinkedAssetFolder(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that the asset folder cannot resolve outside the project."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)

    outside = fncPath / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, projPath / "assets", target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, source)
    assert exc.value.reason == ImageImportReason.WRITE_FAILED


@pytest.mark.core
@pytest.mark.skipif(os.open not in os.supports_dir_fd, reason="Requires directory descriptors")
def testImageImport_RejectsReplacedAssetDirectoryDuringPublish(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a replaced asset directory cannot redirect publication."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    assetDir = projPath / "assets" / "img"
    movedAssetDir = projPath / "assets" / "img-original"
    outside = fncPath / "outside-assets"
    outside.mkdir()
    realLink = os.link

    def replaceAssetDir(sourcePath, targetPath, **kwargs):
        if not movedAssetDir.exists():
            assetDir.rename(movedAssetDir)
            try:
                os.symlink(outside, assetDir, target_is_directory=True)
            except OSError:
                movedAssetDir.rename(assetDir)
                pytest.skip("Symbolic links are not supported on this platform")
        return realLink(sourcePath, targetPath, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", replaceAssetDir)
        mp.setattr(
            "umbraedit.core.imageimport.os.supports_dir_fd",
            os.supports_dir_fd | {replaceAssetDir},
        )
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    assert list(outside.iterdir()) == []
    if assetDir.is_symlink():
        assetDir.unlink()
    if movedAssetDir.exists():
        movedAssetDir.rename(assetDir)


@pytest.mark.core
def testImageImport_BackupRejectsSymlinkedAsset(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that backup does not silently omit a linked image."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    imported = importProjectImage(project, source)
    outside = fncPath / "outside.png"
    outside.write_bytes(source.read_bytes())
    imported.path.unlink()
    try:
        os.symlink(outside, imported.path)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    zipFile = fncPath / "project.zip"
    assert project.storage.zipIt(zipFile, time()) is False
    assert not zipFile.exists()


@pytest.mark.core
def testImageImport_SaveAsRejectsSymlinkedAsset(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that Save As fails rather than omitting a linked image."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    imported = importProjectImage(project, source)
    outside = fncPath / "outside.png"
    outside.write_bytes(source.read_bytes())
    imported.path.unlink()
    try:
        os.symlink(outside, imported.path)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    newPath = fncPath / "project-copy"
    assert project.saveProjectAs(newPath, "Project Copy") is False
    assert SHARED.lastAlert[0] == "Failed to copy project image file."
    assert not newPath.exists()


@pytest.mark.core
def testImageImport_SaveAsRejectsReplacedAssetDirectory(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that Save As cannot copy through a replaced asset directory."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    importProjectImage(project, source)
    assetDir = projPath / "assets" / "img"
    movedAssetDir = projPath / "assets" / "img-original"
    outside = fncPath / "outside-assets"
    outside.mkdir()
    realCopy = copyRegularFile

    def replaceAssetDir(sourcePath, targetPath, **kwargs):
        if Path(sourcePath).parent == assetDir and not movedAssetDir.exists():
            assetDir.rename(movedAssetDir)
            try:
                os.symlink(outside, assetDir, target_is_directory=True)
            except OSError:
                movedAssetDir.rename(assetDir)
                pytest.skip("Symbolic links are not supported on this platform")
        return realCopy(sourcePath, targetPath, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.copyRegularFile", replaceAssetDir)
        newPath = fncPath / "project-copy"
        assert project.saveProjectAs(newPath, "Project Copy") is False

    assert SHARED.lastAlert[0] == "Failed to copy project image file."
    assert list(outside.iterdir()) == []
    assert not newPath.exists()
    if assetDir.is_symlink():
        assetDir.unlink()
    if movedAssetDir.exists():
        movedAssetDir.rename(assetDir)


@pytest.mark.core
def testImageImport_SaveAsDoesNotWriteThroughReplacedStagedDirectory(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a replaced staged directory cannot redirect a copy."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    target = fncPath / "project-copy"
    outside = fncPath / "outside-content"
    outside.mkdir()
    realCopy = copyRegularFile
    injected = False

    def replaceStagedDirectory(sourcePath, targetPath, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            contentDir = Path(targetPath).parent
            movedDir = contentDir.parent / "content-original"
            contentDir.rename(movedDir)
            try:
                os.symlink(outside, contentDir, target_is_directory=True)
            except OSError:
                movedDir.rename(contentDir)
                pytest.skip("Symbolic links are not supported on this platform")
        return realCopy(sourcePath, targetPath, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.copyRegularFile", replaceStagedDirectory)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert injected is True
    assert list(outside.iterdir()) == []
    assert not target.exists()
    assert list(fncPath.glob(".umbraedit-stage-*")) == []


@pytest.mark.core
def testImageImport_SaveAsRejectsReplacedSourceFile(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that Save As copies only the file identities it scanned."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    target = fncPath / "project-copy"
    realCopy = copyRegularFile
    injected = False

    def replaceSource(sourcePath, targetPath, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            sourceFile = Path(sourcePath)
            sourceFile.unlink()
            sourceFile.write_text("replacement", encoding="utf-8")
        return realCopy(sourcePath, targetPath, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.copyRegularFile", replaceSource)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert injected is True
    assert not target.exists()


@pytest.mark.core
def testImageImport_SaveAsRejectsForeignStagedProjectFile(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a foreign staged project file is never replaced."""
    from umbraedit.core import projectxml

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    target = fncPath / "project-copy"
    realAtomic = projectxml.writeFileAtomic

    def installForeign(stagedTarget, data, **kwargs):
        stagedTarget.write_text("foreign", encoding="utf-8")
        return realAtomic(stagedTarget, data, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.projectxml.writeFileAtomic", installForeign)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert not target.exists()
    assert list(fncPath.glob(".umbraedit-stage-*")) == []


@pytest.mark.core
@pytest.mark.parametrize(
    ("atomicPath", "fileName"),
    [
        ("umbraedit.core.options.writeFileAtomic", nwFiles.OPTS_FILE),
        ("umbraedit.core.index.writeFileAtomic", nwFiles.INDEX_FILE),
        ("umbraedit.core.storage.writeFileAtomic", nwFiles.MANIFEST_FILE),
    ],
)
def testImageImport_SaveAsRejectsReplacedStagedMetadata(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
    atomicPath: str,
    fileName: str,
):
    """Test that staged metadata replaced after publication is detected."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    target = fncPath / "project-copy"
    moduleName, functionName = atomicPath.rsplit(".", 1)
    atomicModule = __import__(moduleName, fromlist=[functionName])
    realAtomic = getattr(atomicModule, functionName)

    def replaceAfterWrite(stagedTarget, data, **kwargs):
        identity = realAtomic(stagedTarget, data, **kwargs)
        if stagedTarget.name == fileName:
            stagedTarget.unlink()
            stagedTarget.write_text("foreign", encoding="utf-8")
        return identity

    with monkeypatch.context() as mp:
        mp.setattr(atomicPath, replaceAfterWrite)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert not target.exists()
    assert list(fncPath.glob(".umbraedit-stage-*")) == []


@pytest.mark.core
@pytest.mark.parametrize("failure", ["read", "write"])
def testImageImport_SaveAsRequiresEveryDocumentSave(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
    failure: str,
):
    """Test that a failed document read or write aborts Save Project As."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    target = fncPath / "project-copy"
    originalPath = project.storage.storagePath

    with monkeypatch.context() as mp:
        if failure == "read":
            mp.setattr("umbraedit.core.document.ProjectDocument.readDocument", lambda *a: None)
        else:
            mp.setattr("umbraedit.core.document.ProjectDocument.writeDocument", lambda *a, **kw: False)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert not target.exists()
    assert project.storage.storagePath == originalPath
    assert list(fncPath.glob(".umbraedit-stage-*")) == []
    if failure == "read":
        assert SHARED.lastAlert[0] == "Failed to read a project document before saving."
    else:
        assert SHARED.lastAlert[0] == "Failed to save a project document before saving."


@pytest.mark.core
def testImageImport_SaveAsRejectsForeignStagingTree(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a replaced staging tree is never published as the project."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    target = fncPath / "project-copy"
    originalStage = fncPath / ".umbraedit-original-stage"
    realRename = renameNoReplaceBetween

    def replaceStage(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        if destination.name == target.name and source.name.startswith(".umbraedit-stage-"):
            stagePath = fncPath / source.name
            stagePath.rename(originalStage)
            stagePath.mkdir()
            (stagePath / "foreign.txt").write_text("foreign", encoding="utf-8")
        return realRename(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.renameNoReplaceBetween", replaceStage)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert not target.exists()
    conflicts = list(fncPath.glob(".umbraedit-conflict-*"))
    assert len(conflicts) == 1
    assert (conflicts[0] / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert originalStage.is_dir()
    assert "unexpected published project folder" in "\n".join(SHARED.lastAlert).lower()

    shutil.rmtree(conflicts[0])
    shutil.rmtree(originalStage)


@pytest.mark.core
def testImageImport_SaveAsPreservesExistingTargetOnFailure(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that rollback never deletes a pre-existing target folder."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    importProjectImage(project, source)
    target = fncPath / "existing-target"
    target.mkdir()
    originalPath = project.storage.storagePath

    def failAssetCopy(src, dst, **kwargs):
        raise OSError("Asset copy failed")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.copyRegularFile", failAssetCopy)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert project.storage.storagePath == originalPath
    assert list(fncPath.glob(".umbraedit-stage-*")) == []


@pytest.mark.core
def testImageImport_SaveAsDoesNotOverwriteLateSymlink(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a late target symlink is preserved and not overwritten."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / "project-copy"
    realRename = renameNoReplaceBetween

    def replaceTarget(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        if destination.name == target.name and not (fncPath / destination.name).exists():
            outsideTarget = fncPath / "outside-target"
            outsideTarget.mkdir()
            try:
                os.symlink(outsideTarget, fncPath / destination.name, target_is_directory=True)
            except OSError:
                pytest.skip("Symbolic links are not supported on this platform")
        return realRename(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.renameNoReplaceBetween", replaceTarget)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert target.is_symlink()
    assert list(target.resolve().iterdir()) == []


@pytest.mark.core
def testImageImport_SaveAsReportsAllRollbackFailures(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that rollback failures are all reported to the user."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / "existing-target"
    target.mkdir()
    realRename = renameNoReplaceBetween

    def replaceTarget(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        if destination.name == target.name and not (fncPath / destination.name).exists():
            outsideTarget = fncPath / "outside-target"
            outsideTarget.mkdir()
            try:
                os.symlink(outsideTarget, fncPath / destination.name, target_is_directory=True)
            except OSError:
                pytest.skip("Symbolic links are not supported on this platform")
        return realRename(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    def failCleanup(*args, **kwargs):
        raise OSError("Cleanup failed")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.renameNoReplaceBetween", replaceTarget)
        mp.setattr("umbraedit.core.project.removeTreeIfOwned", failCleanup)
        assert project.saveProjectAs(target, "Project Copy") is False

    alertText = "\n".join(SHARED.lastAlert)
    assert "The incomplete destination could not be removed." in alertText
    assert "The previous target project folder is preserved at:" in alertText

    if target.is_symlink():
        target.unlink()
    for path in fncPath.glob(".umbraedit-stage-*"):
        shutil.rmtree(path)
    for path in fncPath.glob(".umbraedit-saveas-*"):
        shutil.rmtree(path)


@pytest.mark.core
def testImageImport_SaveAsDoesNotRestoreReplacedBackup(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that rollback never moves a replaced backup directory."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / "existing-target"
    target.mkdir()
    realRename = renameNoReplaceBetween

    def replaceBackup(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        if source.name == target.name:
            result = realRename(
                source,
                destination,
                sourceDirFd=sourceDirFd,
                targetDirFd=targetDirFd,
            )
            backupPath = fncPath / destination.name
            backupPath.rmdir()
            backupPath.mkdir()
            (backupPath / "foreign.txt").write_text("foreign", encoding="utf-8")
            return result
        if destination.name == target.name:
            raise OSError("Publication failed")
        return realRename(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.renameNoReplaceBetween", replaceBackup)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert not target.exists()
    backups = list(fncPath.glob(".umbraedit-saveas-*"))
    assert len(backups) == 1
    assert (backups[0] / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    for path in fncPath.glob(".umbraedit-stage-*"):
        shutil.rmtree(path)
    shutil.rmtree(backups[0])


@pytest.mark.core
def testImageImport_SaveAsPreservesReplacedPublishedBackup(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a replaced backup is preserved after successful publication."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / "existing-target"
    target.mkdir()
    realRename = renameNoReplaceBetween

    def replaceBackup(
        source: Path,
        destination: Path,
        *,
        sourceDirFd: int | None = None,
        targetDirFd: int | None = None,
    ) -> bool:
        result = realRename(
            source,
            destination,
            sourceDirFd=sourceDirFd,
            targetDirFd=targetDirFd,
        )
        if destination.name == target.name and source.name != target.name:
            backups = list(fncPath.glob(".umbraedit-saveas-*"))
            assert len(backups) == 1
            backups[0].rmdir()
            backups[0].mkdir()
            (backups[0] / "foreign.txt").write_text("foreign", encoding="utf-8")
        return result

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.renameNoReplaceBetween", replaceBackup)
        assert project.saveProjectAs(target, "Project Copy") is True

    assert (target / nwFiles.PROJ_FILE).is_file()
    backups = list(fncPath.glob(".umbraedit-saveas-*"))
    assert len(backups) == 1
    assert (backups[0] / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert "The previous target project folder is preserved at:" in "\n".join(SHARED.lastAlert)
    shutil.rmtree(backups[0])


@pytest.mark.core
def testImageImport_BackupAndSaveAsRejectSymlinkedContent(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that linked document files are not copied into project copies."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    contentFile = projPath / "content" / f"{C.hSceneDoc}.md"
    outside = fncPath / "outside-content.md"
    outside.write_text("secret", encoding="utf-8")
    contentFile.unlink()
    try:
        os.symlink(outside, contentFile)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    zipFile = fncPath / "project.zip"
    assert project.storage.zipIt(zipFile, time()) is False
    assert not zipFile.exists()

    newPath = fncPath / "project-copy"
    assert project.saveProjectAs(newPath, "Project Copy") is False
    assert not newPath.exists()


@pytest.mark.core
def testImageImport_BackupAndSaveAsRejectMalformedAssetFolder(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a non-directory asset folder is not silently ignored."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    assetPath = projPath / "assets"
    if assetPath.exists():
        shutil.rmtree(assetPath)
    assetPath.write_text("not a directory", encoding="utf-8")

    zipFile = fncPath / "project.zip"
    assert project.storage.zipIt(zipFile, time()) is False
    assert not zipFile.exists()

    newPath = fncPath / "project-copy"
    assert project.saveProjectAs(newPath, "Project Copy") is False
    assert SHARED.lastAlert[0] == "Failed to copy project image file."
    assert not newPath.exists()


@pytest.mark.core
def testImageImport_BackupRejectsSymlinkedMetadata(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that linked project metadata is not copied into a backup."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    metaFile = projPath / "meta" / nwFiles.INDEX_FILE
    outside = fncPath / "outside-index.json"
    outside.write_text("secret", encoding="utf-8")
    metaFile.unlink()
    try:
        os.symlink(outside, metaFile)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    zipFile = fncPath / "project.zip"
    assert project.storage.zipIt(zipFile, time()) is False
    assert not zipFile.exists()


@pytest.mark.core
def testImageImport_BackupDetectsReplacedAssetFolder(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that replacing the asset folder during a backup is rejected."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    importProjectImage(project, source)

    assetDir = projPath / "assets" / "img"
    movedAssetDir = projPath / "assets" / "img-original"
    outside = fncPath / "outside-assets"
    outside.mkdir()
    (outside / "cover.png").write_bytes(source.read_bytes())

    def replaceAssetFolder(
        zipObj,
        sourcePath,
        archivePath,
        expectedParent=None,
        expectedSourceIdentity=None,
    ):
        if archivePath.startswith("assets/img/") and not movedAssetDir.exists():
            assetDir.rename(movedAssetDir)
            try:
                os.symlink(outside, assetDir, target_is_directory=True)
            except OSError:
                movedAssetDir.rename(assetDir)
                pytest.skip("Symbolic links are not supported on this platform")
        return _addFileToZip(
            zipObj,
            sourcePath,
            archivePath,
            expectedParent,
            expectedSourceIdentity,
        )

    zipFile = fncPath / "project.zip"
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage._addFileToZip", replaceAssetFolder)
        assert project.storage.zipIt(zipFile, time()) is False

    assert not zipFile.exists()
    if assetDir.is_symlink():
        assetDir.unlink()
    if movedAssetDir.exists():
        movedAssetDir.rename(assetDir)


@pytest.mark.core
@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def testImageImport_RejectsJunctionAssetFolder(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a Windows junction cannot redirect the asset folder."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    source = fncPath / "cover.png"
    _writeImage(source)
    outside = fncPath / "outside-junction"
    outside.mkdir()
    assetParent = projPath / "assets"
    assetParent.mkdir()
    junction = assetParent / "img"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Could not create a Windows junction")

    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, source)
    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    junction.rmdir()


@pytest.mark.core
def testImageImport_SaveAsSupportsLongTargetName(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that Save As uses a short sibling name for its rollback copy."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / ("t" * (220 if os.name != "nt" else 150))
    assert project.saveProjectAs(target, "Long Target") is True
    assert (target / nwFiles.PROJ_FILE).is_file()
    assert list(fncPath.glob(".umbraedit-saveas-*")) == []


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="POSIX permission test")
def testImageImport_SaveAsRespectsUmask(
    mockGUI: MockGuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a new Save As target respects the process umask."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    oldUmask = os.umask(0o077)
    try:
        target = fncPath / "private-project"
        assert project.saveProjectAs(target, "Private Project") is True
    finally:
        os.umask(oldUmask)

    assert stat.S_IMODE(target.stat().st_mode) == 0o700
