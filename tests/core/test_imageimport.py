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

from pathlib import Path
from time import time
from zipfile import ZipFile

import PIL.Image
import pytest

from umbraedit import SHARED
from umbraedit.constants import nwFiles
from umbraedit.core.imageimport import ImageImportError, ImageImportReason, importProjectImage
from umbraedit.core.project import NWProject
from umbraedit.core.safeio import renameNoReplace, renameNoReplaceAt

from tests.helpers import MockRnd, buildTestProject
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

    truncatedSource = fncPath / "truncated.jpg"
    _writeImage(truncatedSource, "JPEG", (100, 100))
    imageData = truncatedSource.read_bytes()
    truncatedSource.write_bytes(imageData[: int(len(imageData) * 0.9)])
    with pytest.raises(ImageImportError) as exc:
        importProjectImage(project, truncatedSource)
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
    monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 100)

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

    reserved = fncPath / "CON.png"
    _writeImage(reserved)
    reservedResult = importProjectImage(project, reserved)
    assert reservedResult.relativePath == "assets/img/_CON.png"

    longSource = fncPath / f"{'a' * 240}.png"
    _writeImage(longSource)
    first = importProjectImage(project, longSource)
    second = importProjectImage(project, longSource)
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
    realCopy = shutil.copy2
    stageParents = []

    def inspectStage(src, dst, *args, **kwargs):
        stageParents.append(Path(dst).parent)
        zipFile = fncPath / "during-import.zip"
        assert project.storage.zipIt(zipFile, time()) is True
        with ZipFile(zipFile, mode="r") as archive:
            assert not any(name.startswith(".umbraedit-image-") for name in archive.namelist())
        return realCopy(src, dst, *args, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.shutil.copy2", inspectStage)
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
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceAt", unsupportedRename)
        mp.setattr("umbraedit.core.imageimport.os.fsync", causeOSError)
        with pytest.raises(ImageImportError) as exc:
            importProjectImage(project, source)

    assert exc.value.reason == ImageImportReason.WRITE_FAILED
    assert not (projPath / "assets" / "img" / "cover.png").exists()
    assert list(projPath.glob(".umbraedit-image-*.tmp")) == []


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="Atomic no-replace rename is not available on Windows")
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
    realRename = renameNoReplaceAt

    def causeOSError(*args, **kwargs):
        raise OSError(errno.EPERM, "Hard links are not supported")

    def trackRename(*args, **kwargs):
        nonlocal renameCalls
        renameCalls += 1
        return realRename(*args, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeOSError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceAt", trackRename)
        first = importProjectImage(project, source)
        second = importProjectImage(project, source)

    assert renameCalls == 3
    assert first.relativePath == "assets/img/cover.png"
    assert second.relativePath == "assets/img/cover_1.png"
    assert first.path.read_bytes() == source.read_bytes()
    assert second.path.read_bytes() == source.read_bytes()


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
        raise OSError("Hard links are not supported")

    def unsupportedRename(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "Atomic rename is not supported")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.imageimport.os.link", causeOSError)
        mp.setattr("umbraedit.core.imageimport.renameNoReplaceAt", unsupportedRename)
        result = importProjectImage(project, source)

    assert result.relativePath == "assets/img/cover.png"
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

    def failAssetCopy(src, dst):
        if Path(src).parent == originalRuntimePath / "assets" / "img":
            raise OSError("Asset copy failed")

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

    def failAssetCopy(src, dst):
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
    realRename = renameNoReplace

    def replaceTarget(source, destination):
        if destination == target and not destination.exists():
            outsideTarget = fncPath / "outside-target"
            outsideTarget.mkdir()
            try:
                os.symlink(outsideTarget, destination, target_is_directory=True)
            except OSError:
                pytest.skip("Symbolic links are not supported on this platform")
        return realRename(source, destination)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.renameNoReplace", replaceTarget)
        assert project.saveProjectAs(target, "Project Copy") is False

    assert target.is_symlink()
    assert list(target.resolve().iterdir()) == []
