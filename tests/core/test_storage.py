"""
UmbraEdit - Project Storage Tests
===================================

This file is a part of UmbraEdit.

Copyright (C) 2022 Veronica Berglyd Olsen and UmbraEdit contributors.

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
import logging
import os

from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from umbraedit import CONFIG, __hexversion__, __version__
from umbraedit.common import formatTimeStamp
from umbraedit.constants import nwFiles
from umbraedit.core.document import ProjectDocument
from umbraedit.core.project import NWProject
from umbraedit.core.projectxml import FILE_REVISION, FILE_VERSION, ProjectXMLReader, ProjectXMLWriter
from umbraedit.core.safeio import fileIdentity, openDirectoryAt
from umbraedit.core.storage import (
    MANIFEST_VERSION,
    ProjectStorage,
    ProjectStorageCreate,
    ProjectStorageOpen,
    _addFileToZip,
    _LegacyDocuments,
    _LegacyStorage,
)
from umbraedit.enum import nwItemClass, nwItemLayout, nwProjectKind

from tests.helpers import C, MockRnd, TstPaths, buildTestProject
from tests.mocked import MockGuiMain, causeOSError


class MockProject:
    """Test class for projects."""


@pytest.mark.core
def testProjectStorage_CreateNewProject(mockGUI: MockGuiMain, fncPath: Path):
    """Test creating a project in a folder."""
    project = NWProject()

    # Create instance
    storage = ProjectStorage(project)

    # Check defaults
    assert storage.storagePath is None
    assert storage.runtimePath is None
    assert storage.contentPath is None
    assert storage._openMode == ProjectStorage.MODE_INACTIVE
    assert storage._ready is False

    # Check closed project return values
    assert storage.isOpen() is False
    assert storage.getXmlReader() is None
    assert storage.getXmlWriter() is None
    assert bool(storage.getDocument(C.hSceneDoc)) is False
    assert storage.getMetaFile("file") is None
    assert storage.scanContent() == []
    assert storage.getDocumentText(C.hSceneDoc) == ""

    # Cannot prepare a non-empty folder
    (fncPath / "foobar.txt").touch()
    assert storage.createNewProject(fncPath) == ProjectStorageCreate.NOT_EMPTY

    # Try creating in a non-existent subfolder instead
    assert storage.createNewProject(fncPath / "project1") == ProjectStorageCreate.READY
    assert (fncPath / "project1").is_dir()
    assert (fncPath / "project1" / "meta").is_dir()
    assert (fncPath / "project1" / "content").is_dir()

    # However, the parent folder must exist
    assert storage.createNewProject(fncPath / "foobar" / "project1") == ProjectStorageCreate.OS_ERROR
    assert isinstance(storage.exc, FileNotFoundError)

    project.closeProject()


@pytest.mark.core
def testProjectStorage_InitProjectStorage(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test initialising a project in a folder."""
    project = NWProject()

    # Create instance
    storage = ProjectStorage(project)

    # Check defaults
    assert storage.storagePath is None
    assert storage.runtimePath is None
    assert storage.contentPath is None
    assert storage._openMode == ProjectStorage.MODE_INACTIVE
    assert storage._ready is False

    # Check closed project return values
    assert storage.isOpen() is False
    assert storage.getXmlReader() is None
    assert storage.getXmlWriter() is None
    assert bool(storage.getDocument(C.hSceneDoc)) is False
    assert storage.getMetaFile("file") is None
    assert storage.scanContent() == []

    # Create a new project
    buildTestProject(project, fncPath)

    # Init with the wrong file
    foo = fncPath / "foobar.txt"
    foo.touch()
    assert storage.initProjectStorage(fncPath / "foobar.txt") == ProjectStorageOpen.UNKOWN
    foo.unlink()
    storage._clearLockFile()
    storage.clear()

    # Init with the user's home dir
    assert storage.initProjectStorage(Path.home()) == ProjectStorageOpen.NOT_FOUND
    storage._clearLockFile()
    storage.clear()

    # Init with the project folder is OK
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.READY
    assert storage.runtimePath == fncPath
    assert storage.storagePath == fncPath
    assert storage.contentPath == fncPath / "content"
    assert storage._openMode == ProjectStorage.MODE_INPLACE
    storage._clearLockFile()
    storage.clear()

    # Init with the project main file is OK
    assert storage.initProjectStorage(fncPath / nwFiles.PROJ_FILE) == ProjectStorageOpen.READY
    assert storage.runtimePath == fncPath
    assert storage.storagePath == fncPath
    assert storage.contentPath == fncPath / "content"
    assert storage._openMode == ProjectStorage.MODE_INPLACE
    storage._clearLockFile()
    storage.clear()

    # Locking does nothing before the storage is ready
    unreadyStorage = ProjectStorage(MockProject())  # type: ignore
    unreadyStorage.lockSession()

    # Open twice, where second should fail due to lockfile
    # Note that locking is only possible after a successful open
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.READY
    storage.lockSession()
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.LOCKED
    assert isinstance(storage.lockStatus, list)
    assert len(storage.lockStatus) == 4

    # But open again with clear lock file flag set is OK
    assert storage.initProjectStorage(fncPath, clearLock=True) == ProjectStorageOpen.READY
    assert storage.lockStatus is None

    # We should now have access to project resources
    assert isinstance(storage.getXmlReader(), ProjectXMLReader)
    assert isinstance(storage.getXmlWriter(), ProjectXMLWriter)
    assert isinstance(storage.getDocument(C.hSceneDoc), ProjectDocument)
    assert repr(storage.getDocument(C.hSceneDoc)) == f"<ProjectDocument handle={C.hSceneDoc}>"

    # We can directly access the content of a document
    assert storage.getDocumentText(C.hSceneDoc) == "### New Scene\n\n"

    project.closeProject()


@pytest.mark.core
def testProjectStorage_InitProjectStorage_PathFallback(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that project opening works without directory-descriptor support."""
    (fncPath / "meta").mkdir()
    (fncPath / "content").mkdir()
    (fncPath / nwFiles.PROJ_FILE).touch()

    storage = ProjectStorage(MockProject())  # type: ignore
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.supportsDirectoryDescriptors", lambda: False)
        assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.READY

    assert storage.runtimePath == fncPath
    assert storage.metaIdentity is not None
    assert storage.contentIdentity is not None
    storage.closeSession()


@pytest.mark.core
def testProjectStorage_InitProjectStorage_Invalid(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test initialising a project in an invalid folder."""
    project = NWProject()

    # Create instance
    storage = ProjectStorage(project)

    # Check defaults
    assert storage.storagePath is None
    assert storage.runtimePath is None
    assert storage.contentPath is None
    assert storage._openMode == ProjectStorage.MODE_INACTIVE
    assert storage._ready is False

    # Check closed project return values
    assert storage.isOpen() is False
    assert storage.getXmlReader() is None
    assert storage.getXmlWriter() is None
    assert bool(storage.getDocument(C.hSceneDoc)) is False
    assert storage.getMetaFile("file") is None
    assert storage.scanContent() == []

    # Populate folder with invalid files
    (fncPath / "meta").touch()  # These are now files but should be folders
    (fncPath / "content").touch()  # These are now files but should be folders

    # Try opening the folder, but there is no project file
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.NOT_FOUND

    # Add the project file, and we should now fail on the folders
    (fncPath / nwFiles.PROJ_FILE).touch()
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.FAILED

    # Remove the files blocking the folders, but make the legacy storage scan fail
    (fncPath / "meta").unlink()
    (fncPath / "content").unlink()
    with monkeypatch.context() as mp:
        mp.setattr(_LegacyStorage, "deprecatedFiles", causeOSError)
        assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.FAILED

    project.closeProject()


@pytest.mark.core
def testProjectStorage_LockFile(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test the project lock file."""
    monkeypatch.setattr("umbraedit.core.storage.time", lambda: 1000.0)

    storage = ProjectStorage(MockProject())  # type: ignore
    assert storage.isOpen() is False

    # Project not open, so cannot read/write/clear lock file
    storage._readLockFile()
    assert storage.lockStatus is None
    storage._writeLockFile()
    storage._lockedBy = ["a", "b", "c", "d"]
    storage._clearLockFile()
    assert storage.lockStatus == ["a", "b", "c", "d"]
    assert not (fncPath / nwFiles.PROJ_LOCK).exists()
    storage._lockedBy = None

    # Set a path to work with
    lockFilePath = fncPath / nwFiles.PROJ_LOCK
    storage._lockFilePath = lockFilePath

    # Path is set, but there is no lockfile
    storage._readLockFile()
    assert storage.lockStatus is None

    # Write lockfile fails
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.writeFileAtomic", causeOSError)
        storage._writeLockFile()
        assert not lockFilePath.exists()

    # Successful write
    storage._writeLockFile()
    assert lockFilePath.exists()
    assert lockFilePath.read_text().split(";")[3] == "1000"

    # Read lockfile fails
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.openRegularFile", causeOSError)
        storage._readLockFile()
        assert storage.lockStatus == ["ERROR", "ERROR", "ERROR", "ERROR"]
        assert lockFilePath.exists()

    # Successful read
    storage._readLockFile()
    assert storage.lockStatus == [
        CONFIG.hostName,
        CONFIG.osType,
        CONFIG.kernelVer,
        "1000",
    ]

    # Write an invalid lockfile
    lockFilePath.write_text("a;b;c")
    storage._readLockFile()
    assert storage.lockStatus is None

    # Fail to remove lockfile
    storage._lockFileIdentity = fileIdentity(os.lstat(lockFilePath))
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.unlinkEntryIfSameFile", causeOSError)
        storage._clearLockFile()
        assert lockFilePath.exists()

    # A replacement lock is not removed by normal session cleanup
    lockFilePath.unlink()
    lockFilePath.write_text("replacement", encoding="utf-8")
    storage._clearLockFile()
    assert lockFilePath.read_text(encoding="utf-8") == "replacement"

    # The explicit recovery action can remove the replacement
    storage._clearLockFile(force=True)
    assert not lockFilePath.exists()


@pytest.mark.core
def testProjectStorage_Manifest(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test the project manifest file."""
    storage = ProjectStorage(MockProject())  # type: ignore
    manifestPath = fncPath / nwFiles.MANIFEST_FILE

    # Project not open, so no manifest is written or read
    assert storage.runPostSaveTasks(1000.0) is True
    storage._writeManifest(nwProjectKind.PROJECT, 1000.0)
    assert not manifestPath.exists()
    storage._readManifest()
    assert storage.kind == nwProjectKind.PROJECT
    assert storage.timeStamp is None

    # Set a path to work with
    storage._manifestPath = manifestPath
    storage._openMode = ProjectStorage.MODE_INPLACE

    # Write manifest fails
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.writeFileAtomic", causeOSError)
        assert storage.runPostSaveTasks(1000.0) is False
        assert not manifestPath.exists()

    # Successful write
    assert storage.runPostSaveTasks(1000.0) is True
    manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
    assert manifest == {
        "format": "UmbraEdit Project",
        "formatVersion": MANIFEST_VERSION,
        "projectVersion": f"{FILE_VERSION}-{FILE_REVISION}",
        "kind": "project",
        "timeStamp": formatTimeStamp(1000.0),
        "appVersion": __version__,
        "hexVersion": __hexversion__,
    }

    # Read a backup manifest
    storage._writeManifest(nwProjectKind.BACKUP, 1000.0)
    storage._readManifest()
    assert storage.kind == nwProjectKind.BACKUP
    assert storage.timeStamp == datetime.fromtimestamp(1000.0)

    # Saving turns it into a project
    assert storage.runPostSaveTasks(1000.0) is True
    assert storage.kind == nwProjectKind.PROJECT
    storage._readManifest()
    assert storage.kind == nwProjectKind.PROJECT

    # Invalid manifests are read as a project
    manifestPath.write_text("{", encoding="utf-8")
    storage._readManifest()
    assert storage.kind == nwProjectKind.PROJECT
    assert storage.timeStamp is None

    manifestPath.write_text('{"kind": "foo", "timeStamp": "bar"}', encoding="utf-8")
    storage._readManifest()
    assert storage.kind == nwProjectKind.PROJECT
    assert storage.timeStamp is None

    # An invalid time stamp keeps the kind
    manifestPath.write_text('{"kind": "backup"}', encoding="utf-8")
    storage._readManifest()
    assert storage.kind == nwProjectKind.BACKUP
    assert storage.timeStamp is None

    # Clearing resets the values
    storage._writeManifest(nwProjectKind.BACKUP, 1000.0)
    storage._readManifest()
    assert storage.kind == nwProjectKind.BACKUP
    storage.clear()
    assert storage.kind == nwProjectKind.PROJECT
    assert storage.timeStamp is None


@pytest.mark.core
def testProjectStorage_ZipIt(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    tstPaths: TstPaths,
    mockRnd: MockRnd,
):
    """Test making a zip archive of a project."""
    zipFile = tstPaths.tmpDir / "project.zip"

    project = NWProject()
    storage = project.storage
    assert storage.zipIt(zipFile, 1000.0) is False

    # Make a project
    mockRnd.reset()
    buildTestProject(project, fncPath)

    # Fail to list content
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.os.scandir", causeOSError)
        assert storage.zipIt(zipFile, 1000.0) is False
        assert not zipFile.exists()

    # Fail to create archive, and fail to clean up the private staging file
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage._addFileToZip", causeOSError)
        mp.setattr("umbraedit.core.storage.unlinkEntryIfSameFile", causeOSError)
        assert storage.zipIt(zipFile, 1000.0) is False
        assert not zipFile.exists()
        stagedFiles = list(tstPaths.tmpDir.glob(".umbraedit-backup-*.tmp"))
        assert len(stagedFiles) == 1
    stagedFiles[0].unlink()

    # Fail to create archive, and clean up
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage._addFileToZip", causeOSError)
        assert storage.zipIt(zipFile, 1000.0) is False
        assert not zipFile.exists()

    # Add a stray file that should not be included
    strayFile = fncPath / "content" / "not-a-handle.txt"
    strayFile.write_text("stray")

    # Create archive
    assert storage.zipIt(zipFile, 1000.0) is True

    # Check content
    with ZipFile(zipFile, mode="r") as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read(nwFiles.MANIFEST_FILE))
        assert manifest["kind"] == "backup"
        assert manifest["timeStamp"] == formatTimeStamp(1000.0)
        assert nwFiles.PROJ_FILE in names
        assert f"meta/{nwFiles.OPTS_FILE}" in names
        assert f"meta/{nwFiles.INDEX_FILE}" in names
        assert f"content/{C.hTitlePage}.md" in names
        assert f"content/{C.hChapterDoc}.md" in names
        assert f"content/{C.hSceneDoc}.md" in names
        assert "content/not-a-handle.txt" not in names

    project.closeProject()


@pytest.mark.core
def testProjectStorage_ZipRejectsSymlinkedTarget(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a backup never truncates or replaces a linked target."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    outside = fncPath / "outside.zip"
    outside.write_bytes(b"outside data")
    target = fncPath / "project.zip"
    try:
        os.symlink(outside, target)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    assert project.storage.zipIt(target, 1000.0) is False
    assert outside.read_bytes() == b"outside data"
    assert target.is_symlink()


@pytest.mark.core
def testProjectStorage_ZipRejectsReplacedParent(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that backup staging stays bound to the validated parent."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    backupDir = fncPath / "backups"
    backupDir.mkdir()
    originalParent = fncPath / "backups-original"
    target = backupDir / "project.zip"
    originalAdd = _addFileToZip
    replaced = False

    def replaceParent(*args: Any, **kwargs: Any) -> None:
        nonlocal replaced
        originalAdd(*args, **kwargs)
        if not replaced:
            replaced = True
            backupDir.rename(originalParent)
            backupDir.mkdir()

    monkeypatch.setattr("umbraedit.core.storage._addFileToZip", replaceParent)
    assert project.storage.zipIt(target, 1000.0) is False
    assert list(backupDir.iterdir()) == []
    assert list(originalParent.iterdir()) == []


@pytest.mark.core
def testProjectStorage_LockPrecedesLegacyConversion(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that the exclusive lock exists before legacy data is changed."""
    storage = ProjectStorage(MockProject())  # type: ignore
    (fncPath / nwFiles.PROJ_FILE).touch()
    legacyFolder = fncPath / "data_0"
    legacyFolder.mkdir()
    (legacyFolder / "000000000000_main.bak").write_text("backup", encoding="utf-8")

    lockWasPresent = False
    originalDeprecated = _LegacyStorage.deprecatedFiles

    def checkLock(self: _LegacyStorage, path: Path, **kwargs: Any) -> None:
        nonlocal lockWasPresent
        lockWasPresent = (path / nwFiles.PROJ_LOCK).is_file()
        originalDeprecated(self, path, **kwargs)

    monkeypatch.setattr(_LegacyStorage, "deprecatedFiles", checkLock)
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.READY
    assert lockWasPresent is True
    assert (fncPath / nwFiles.PROJ_LOCK).is_file()


@pytest.mark.core
def testProjectStorage_ForeignLockPreventsLegacyConversion(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a foreign lock prevents all legacy project mutation."""
    storage = ProjectStorage(MockProject())  # type: ignore
    (fncPath / nwFiles.PROJ_FILE).touch()
    lockPath = fncPath / nwFiles.PROJ_LOCK
    lockPath.write_text("foreign;lock;holder;1", encoding="utf-8")
    conversionCalled = False

    def markConversion(self: _LegacyStorage, path: Path) -> None:
        nonlocal conversionCalled
        conversionCalled = True

    monkeypatch.setattr(_LegacyStorage, "deprecatedFiles", markConversion)
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.LOCKED
    assert conversionCalled is False
    assert lockPath.read_text(encoding="utf-8") == "foreign;lock;holder;1"


@pytest.mark.core
def testProjectStorage_RootReplacementPreventsLockAcquisition(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a replaced project root cannot receive a new lock."""
    storage = ProjectStorage(MockProject())  # type: ignore
    (fncPath / nwFiles.PROJ_FILE).touch()
    originalRoot = fncPath.with_name(f"{fncPath.name}-original")
    replaced = False

    def replaceRoot(self: ProjectStorage) -> None:
        nonlocal replaced
        if not replaced:
            replaced = True
            fncPath.rename(originalRoot)
            fncPath.mkdir()

    monkeypatch.setattr(ProjectStorage, "_readLockFile", replaceRoot)
    assert storage.initProjectStorage(fncPath) == ProjectStorageOpen.LOCKED
    assert list(fncPath.iterdir()) == []
    assert (originalRoot / nwFiles.PROJ_FILE).is_file()


@pytest.mark.core
def testProjectStorage_LockAcquisitionIsExclusive(fncPath: Path):
    """Test that two sessions cannot both acquire the same project lock."""
    lockPath = fncPath / nwFiles.PROJ_LOCK
    first = ProjectStorage(MockProject())  # type: ignore
    second = ProjectStorage(MockProject())  # type: ignore
    first._lockFilePath = lockPath
    second._lockFilePath = lockPath

    assert first._writeLockFile() is True
    assert second._writeLockFile() is False
    assert lockPath.is_file()

    second._clearLockFile()
    assert lockPath.is_file()
    first._clearLockFile()
    assert not lockPath.exists()


@pytest.mark.core
def testProjectStorage_LockFileRejectsSymlinks(fncPath: Path):
    """Test that lock-file operations never follow or remove a link."""
    storage = ProjectStorage(MockProject())  # type: ignore
    outside = fncPath / "outside.lock"
    outside.write_text("outside data", encoding="utf-8")
    lockPath = fncPath / nwFiles.PROJ_LOCK
    storage._lockFilePath = lockPath
    try:
        os.symlink(outside, lockPath)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    storage._writeLockFile()
    assert outside.read_text(encoding="utf-8") == "outside data"
    assert lockPath.is_symlink()

    storage._readLockFile()
    assert storage.lockStatus == ["ERROR", "ERROR", "ERROR", "ERROR"]

    storage._clearLockFile()
    assert lockPath.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside data"


@pytest.mark.core
def testProjectStorage_DanglingLockSymlinkIsNotCreated(fncPath: Path):
    """Test that writing a dangling lock link does not create its target."""
    storage = ProjectStorage(MockProject())  # type: ignore
    outside = fncPath / "missing.lock"
    lockPath = fncPath / nwFiles.PROJ_LOCK
    storage._lockFilePath = lockPath
    try:
        os.symlink(outside, lockPath)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    storage._writeLockFile()
    assert not outside.exists()
    assert lockPath.is_symlink()


@pytest.mark.core
def testProjectStorage_LegacyDataFolder(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test project file format 1.0 folder structure conversion."""
    project = MockProject()
    storage = ProjectStorage(project)  # type: ignore
    assert storage.isOpen() is False
    storage._runtimePath = fncPath
    (fncPath / nwFiles.PROJ_FILE).touch()
    storage.initProjectStorage(fncPath)
    legacy = _LegacyStorage(project)  # type: ignore

    data = []
    files = []
    for c in "0123456789abcdefX":
        dataDir = fncPath / f"data_{c}"
        dataDir.mkdir()
        data.append(dataDir)

        nwdFile = dataDir / f"00000000000{c}_main.nwd"
        bakFile = dataDir / f"00000000000{c}_main.bak"
        nwdFile.write_text("#")
        bakFile.write_text("#")
        files.append(nwdFile)
        files.append(bakFile)

    for item in files:
        assert item.exists()

    # Pollute folder 7 and 8
    (data[7] / "stuff.txt").write_text("foo")
    (data[8] / "bar").mkdir()

    # Process folders
    for i in range(9):
        legacy.legacyDataFolder(fncPath, data[i])

    # Files form 0 to 8 should now be in content
    for i in range(9):
        assert (fncPath / "content" / f"{i}00000000000{i}.nwd").exists()

    # Folders 0 to 6 should be deleted
    for i in range(7):
        assert not data[i].exists()

    # While 7 and 8 remain
    assert data[7].exists()
    assert data[8].exists()

    # So does folder X, which is invalid
    legacy.legacyDataFolder(fncPath, data[16])
    assert data[16].exists()

    # Fail cleanup of folder 9
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.renameNoReplaceIfSameFile", causeOSError)
        legacy.legacyDataFolder(fncPath, data[9])
        assert data[9].exists()
        assert not (fncPath / "content" / "9000000000009.nwd").exists()

    # Run the remaining through the prepare storage call, which finds
    # the moved .nwd files, but does not convert them yet
    assert storage.initProjectStorage(fncPath, clearLock=True) == ProjectStorageOpen.READY
    assert storage.hasBreakingChanges() is True
    for c in "0123456789abcdef":
        assert (fncPath / "content" / f"{c}00000000000{c}.nwd").exists()


@pytest.mark.core
def testProjectStorage_LegacyDataFolder_PathFallback(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that legacy conversion works without directory descriptors."""
    content = fncPath / "content"
    content.mkdir()
    legacyFolder = fncPath / "data_0"
    legacyFolder.mkdir()
    legacyFile = legacyFolder / "000000000000_main.nwd"
    legacyFile.write_text("legacy", encoding="utf-8")

    rootIdentity = fileIdentity(os.lstat(fncPath))
    contentIdentity = fileIdentity(os.lstat(content))
    legacy = _LegacyStorage(MockProject())  # type: ignore
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.supportsDirectoryDescriptors", lambda: False)
        legacy.legacyDataFolder(
            fncPath,
            legacyFolder,
            expectedRoot=rootIdentity,
            expectedContent=contentIdentity,
        )

    assert (content / "0000000000000.nwd").read_text(encoding="utf-8") == "legacy"
    assert not legacyFolder.exists()


@pytest.mark.core
def testProjectStorage_LegacyDataFolderRejectsReplacedChild(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a replaced legacy child is never converted or removed."""
    content = fncPath / "content"
    content.mkdir()
    legacyFolder = fncPath / "data_0"
    legacyFolder.mkdir()
    legacyFile = legacyFolder / "000000000000_main.nwd"
    legacyFile.write_text("legacy", encoding="utf-8")
    movedFolder = fncPath / "data_0-original"

    injected = False

    def replaceChild(parentFd: int, name: str) -> int:
        nonlocal injected
        if not injected and name == "data_0":
            injected = True
            legacyFolder.rename(movedFolder)
            legacyFolder.mkdir()
            (legacyFolder / "foreign.txt").write_text("foreign", encoding="utf-8")
        return openDirectoryAt(parentFd, name)

    rootIdentity = fileIdentity(os.lstat(fncPath))
    contentIdentity = fileIdentity(os.lstat(content))
    legacy = _LegacyStorage(MockProject())  # type: ignore
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.openDirectoryAt", replaceChild)
        legacy.legacyDataFolder(
            fncPath,
            legacyFolder,
            expectedRoot=rootIdentity,
            expectedContent=contentIdentity,
        )

    assert injected is True
    assert (legacyFolder / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert (movedFolder / legacyFile.name).read_text(encoding="utf-8") == "legacy"
    assert not (content / "0000000000000.nwd").exists()


@pytest.mark.core
def testProjectStorage_LegacyDataFolderRejectsReplacedContent(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a replaced content folder is never used or removed."""
    content = fncPath / "content"
    content.mkdir()
    legacyFolder = fncPath / "data_0"
    legacyFolder.mkdir()
    legacyFile = legacyFolder / "000000000000_main.nwd"
    legacyFile.write_text("legacy", encoding="utf-8")
    movedContent = fncPath / "content-original"

    injected = False

    def replaceContent(parentFd: int, name: str) -> int:
        nonlocal injected
        if not injected and name == "content":
            injected = True
            content.rename(movedContent)
            content.mkdir()
            (content / "foreign.txt").write_text("foreign", encoding="utf-8")
        return openDirectoryAt(parentFd, name)

    rootIdentity = fileIdentity(os.lstat(fncPath))
    contentIdentity = fileIdentity(os.lstat(content))
    legacy = _LegacyStorage(MockProject())  # type: ignore
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.openDirectoryAt", replaceContent)
        legacy.legacyDataFolder(
            fncPath,
            legacyFolder,
            expectedRoot=rootIdentity,
            expectedContent=contentIdentity,
        )

    assert injected is True
    assert (content / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert legacyFile.read_text(encoding="utf-8") == "legacy"
    assert not (content / "0000000000000.nwd").exists()


@pytest.mark.core
def testProjectStorage_FindOldDocuments(fncPath: Path):
    """Test scanning the content folder for old .nwd document files."""
    project = MockProject()
    storage = ProjectStorage(project)  # type: ignore
    storage._runtimePath = fncPath
    (fncPath / nwFiles.PROJ_FILE).touch()
    storage.initProjectStorage(fncPath)
    legacy = _LegacyStorage(project)  # type: ignore

    content = fncPath / "content"
    nwdFile = content / f"{C.hSceneDoc}.nwd"
    nwdFile.write_text("### Text\n", encoding="utf-8")
    (content / f"{C.hChapterDoc}.md").write_text("### Text\n", encoding="utf-8")
    (content / "folder.nwd").mkdir()

    assert [document.path for document in legacy.findOldDocuments(content)] == [nwdFile]


@pytest.mark.core
def testProjectStorage_RunPostXMLTasks(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test running the post-XML-load document conversion tasks."""
    project = MockProject()
    storage = ProjectStorage(project)  # type: ignore
    storage._runtimePath = fncPath
    (fncPath / nwFiles.PROJ_FILE).touch()
    storage.initProjectStorage(fncPath)

    # No old documents found, so there is nothing to do
    assert storage.hasBreakingChanges() is False
    assert storage.runPostXMLTasks() is True

    # Add an old-format document and re-scan for it
    content = fncPath / "content"
    nwdFile = content / f"{C.hSceneDoc}.nwd"
    nwdFile.write_text("### Text\n", encoding="utf-8")
    storage._oldDocuments = _LegacyStorage(project).findOldDocuments(content)  # type: ignore
    assert storage.hasBreakingChanges() is True

    # A successful conversion
    assert storage.runPostXMLTasks() is True
    assert not nwdFile.exists()
    assert (content / f"{C.hSceneDoc}.md").exists()

    # A failed conversion records the exception
    storage._oldDocuments = [nwdFile]  # type: ignore[assignment]
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage._LegacyDocuments.convertDocuments", causeOSError)
        assert storage.runPostXMLTasks() is False
        assert isinstance(storage.exc, OSError)


@pytest.mark.core
def testLegacyDocuments_ConvertDocuments(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test conversion of old .nwd document files to .md with a TOML header."""
    project = MockProject()
    storage = ProjectStorage(project)  # type: ignore
    storage._runtimePath = fncPath
    (fncPath / nwFiles.PROJ_FILE).touch()
    storage.initProjectStorage(fncPath)
    legacy = _LegacyDocuments(project)  # type: ignore

    content = fncPath / "content"

    # A regular old-format document with a full meta header
    nwdFile = content / f"{C.hSceneDoc}.nwd"
    nwdFile.write_text(
        (
            "%%~name: Scene One\n"
            f"%%~path: {C.hChapterDir}/{C.hSceneDoc}\n"
            "%%~kind: NOVEL/DOCUMENT\n"
            "%%~hash: abc123\n"
            "%%~date: 2020-01-01 00:00:00/2020-01-02 00:00:00\n"
            "### Scene One\n\nSome text.\n"
        ),
        encoding="utf-8",
    )

    legacy.convertDocuments([nwdFile])

    assert not nwdFile.exists()
    mdFile = content / f"{C.hSceneDoc}.md"
    assert mdFile.read_text(encoding="utf-8") == (
        "+++\n"
        'name = "Scene One"\n'
        f'parent = "{C.hChapterDir}"\n'
        f'handle = "{C.hSceneDoc}"\n'
        'class = "NOVEL"\n'
        'layout = "DOCUMENT"\n'
        'textHash = "abc123"\n'
        'createdDate = "2020-01-01 00:00:00"\n'
        'updatedDate = "2020-01-02 00:00:00"\n'
        "+++\n"
        "### Scene One\n\nSome text.\n"
    )

    # A document with more than 10 meta lines never reaches the body
    # text, but is still converted
    longFile = content / f"{C.hTitlePage}.nwd"
    longFile.write_text("".join(f"%%~junk{i}: value\n" for i in range(12)), encoding="utf-8")
    legacy.convertDocuments([longFile])
    assert not longFile.exists()
    assert (content / f"{C.hTitlePage}.md").exists()

    # A path that is not a .nwd file is ignored
    txtFile = content / "not-a-doc.txt"
    txtFile.write_text("stuff", encoding="utf-8")
    legacy.convertDocuments([txtFile])
    assert txtFile.exists()

    # If conversion fails, the file is renamed to .md as a fallback so
    # it can still be opened, even with its raw, unconverted content
    badFile = content / f"{C.hChapterDoc}.nwd"
    rawText = "%%~name: Bad\n### Text\n"
    badFile.write_text(rawText, encoding="utf-8")
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.writeFileAtomic", causeOSError)
        legacy.convertDocuments([badFile])
    assert not badFile.exists()
    fallbackFile = content / f"{C.hChapterDoc}.md"
    assert fallbackFile.read_text(encoding="utf-8") == rawText

    # An existing output is never overwritten by the fallback. Both the
    # source and the conflicting output are preserved, and the conflict
    # does not block the caller from continuing.
    fallbackFile.unlink()
    badFile.write_text(rawText, encoding="utf-8")
    fallbackFile.write_text("partial junk", encoding="utf-8")
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.writeFileAtomic", causeOSError)
        legacy.convertDocuments([badFile])
    assert badFile.read_text(encoding="utf-8") == rawText
    assert fallbackFile.read_text(encoding="utf-8") == "partial junk"

    # If the fallback rename also fails, there is nothing more that can
    # be done, so the exception is left to propagate to the caller
    fallbackFile.unlink()
    badFile.write_text(rawText, encoding="utf-8")
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.writeFileAtomic", causeOSError)
        mp.setattr("umbraedit.core.storage.renameNoReplaceIfSameFile", causeOSError)
        with pytest.raises(OSError, match="Mock OSError"):
            legacy.convertDocuments([badFile])
    assert badFile.exists()
    assert not fallbackFile.exists()

    # A cleanup failure after successful publication is recoverable. The
    # converted file remains usable and the legacy source is preserved.
    fallbackFile.unlink(missing_ok=True)
    badFile.write_text(rawText, encoding="utf-8")
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage._LegacyDocuments._removeConvertedSource", causeOSError)
        legacy.convertDocuments([badFile])
    assert badFile.read_text(encoding="utf-8") == rawText
    assert fallbackFile.exists()


@pytest.mark.core
def testLegacyDocuments_ParseOldDocumentMeta(caplog: pytest.LogCaptureFixture):
    """Test parsing of individual old-format meta data lines."""
    caplog.set_level(logging.DEBUG, logger="umbraedit")
    legacy = _LegacyDocuments(MockProject())  # type: ignore

    # Name
    assert legacy._parseOldDocumentMeta(["%%~name: Test File\n"]) == {"name": "Test File"}

    # Name: control characters from an old, unvalidated file are cleaned,
    # as they would otherwise end up unescaped in the new TOML header
    assert legacy._parseOldDocumentMeta(["%%~name: Bad\x1bTitle\n"]) == {"name": "BadTitle"}

    # Path: valid parent and handle
    meta = legacy._parseOldDocumentMeta([f"%%~path: {C.hChapterDir}/{C.hSceneDoc}\n"])
    assert meta == {"parent": C.hChapterDir, "handle": C.hSceneDoc}

    # Path: malformed value is ignored entirely
    assert legacy._parseOldDocumentMeta(["%%~path: onlyonepart\n"]) == {}

    # Path: invalid handles are dropped individually
    assert legacy._parseOldDocumentMeta(["%%~path: notahandle/alsonot\n"]) == {}

    # Kind: valid class and layout
    meta = legacy._parseOldDocumentMeta(["%%~kind: NOVEL/DOCUMENT\n"])
    assert meta == {"class": nwItemClass.NOVEL, "layout": nwItemLayout.DOCUMENT}

    # Kind: malformed value is ignored entirely
    assert legacy._parseOldDocumentMeta(["%%~kind: onlyonepart\n"]) == {}

    # Kind: unknown class/layout names are dropped individually
    assert legacy._parseOldDocumentMeta(["%%~kind: BADCLASS/BADLAYOUT\n"]) == {}

    # Hash
    assert legacy._parseOldDocumentMeta(["%%~hash: abc123\n"]) == {"textHash": "abc123"}

    # Date: valid
    meta = legacy._parseOldDocumentMeta(["%%~date: 2020-01-01 00:00:00/2020-01-02 00:00:00\n"])
    assert meta == {"createdDate": "2020-01-01 00:00:00", "updatedDate": "2020-01-02 00:00:00"}

    # Date: malformed value is ignored entirely
    assert legacy._parseOldDocumentMeta(["%%~date: onlyonepart\n"]) == {}

    # Unknown meta lines are logged and otherwise ignored
    assert legacy._parseOldDocumentMeta(["%%~unknown: stuff\n"]) == {}
    assert "Unknown meta data" in caplog.text


@pytest.mark.core
def testProjectStorage_DeprecatedFiles(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test cleanup of deprecated files."""
    project = MockProject()
    storage = ProjectStorage(project)  # type: ignore
    assert storage.isOpen() is False
    storage._runtimePath = fncPath
    (fncPath / nwFiles.PROJ_FILE).touch()
    storage.initProjectStorage(fncPath)
    legacy = _LegacyStorage(project)  # type: ignore

    # Files/Folders to be Deleted or Renamed
    # ======================================

    remove = [
        fncPath / "meta" / "tagsIndex.json",
        fncPath / "meta" / "mainOptions.json",
        fncPath / "meta" / "exportOptions.json",
        fncPath / "meta" / "outlineOptions.json",
        fncPath / "meta" / "timelineOptions.json",
        fncPath / "meta" / "docMergeOptions.json",
        fncPath / "meta" / "sessionLogOptions.json",
        fncPath / "cache" / "prevBuild.json",
        fncPath / "ToC.json",
    ]
    (fncPath / "cache").mkdir()
    for depFile in remove:
        depFile.write_text("foo")
        assert depFile.exists()

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.unlinkEntryIfSameFile", causeOSError)
        legacy.deprecatedFiles(fncPath)
        for depFile in remove:
            assert depFile.exists()

    legacy.deprecatedFiles(fncPath)
    for depFile in remove:
        assert not depFile.exists()


@pytest.mark.core
def testProjectStorage_OldFormatConvert(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path):
    """Test cleanup of deprecated files that needs to be converted."""
    project = NWProject()
    buildTestProject(project, fncPath)
    legacy = _LegacyStorage(project)

    # Word List
    wordListOld: Path = fncPath / "meta" / "wordlist.txt"
    wordListNew: Path = fncPath / "meta" / nwFiles.DICT_FILE

    wordListOld.write_text(("word_a\n\nword_b\nword_c\n"), encoding="utf-8")

    assert wordListOld.exists() is True
    assert wordListNew.exists() is False

    # Log File
    sessLogOld: Path = fncPath / "meta" / "sessionStats.log"
    sessLogNew: Path = fncPath / "meta" / nwFiles.SESS_FILE

    sessLogOld.write_text(
        (
            "# Offset 150\n"
            "# Start Time         End Time                Novel     Notes    Idle\n"
            "2021-02-02 02:02:02  2021-02-02 03:03:03       200       200      10\n"
            "2021-03-03 03:03:03  2021-03-03 04:04:04       300       300      20\n"
        ),
        encoding="utf-8",
    )

    assert sessLogOld.exists() is True
    assert sessLogNew.exists() is False

    # Check Failure
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.openRegularFile", causeOSError)
        legacy.deprecatedFiles(fncPath)
        assert wordListOld.exists() is True
        assert wordListNew.exists() is False
        assert sessLogOld.exists() is True
        assert sessLogNew.exists() is False

    # Check Success
    legacy.deprecatedFiles(fncPath)
    assert wordListOld.exists() is False
    assert wordListNew.exists() is True
    assert sessLogOld.exists() is False
    assert sessLogNew.exists() is True

    # Check Word List
    data = json.loads(wordListNew.read_text(encoding="utf-8"))
    assert "word_a" in data["UmbraEdit.userDict"]
    assert "word_b" in data["UmbraEdit.userDict"]
    assert "word_c" in data["UmbraEdit.userDict"]

    # Check Session Log
    data = list(project.session.iterRecords())
    assert data[0] == {"type": "initial", "offset": 150}
    assert data[1] == {
        "type": "record",
        "start": "2021-02-02 02:02:02",
        "end": "2021-02-02 03:03:03",
        "novel": 200,
        "notes": 200,
        "cnovel": 0,
        "cnotes": 0,
        "idle": 10,
    }
    assert data[2] == {
        "type": "record",
        "start": "2021-03-03 03:03:03",
        "end": "2021-03-03 04:04:04",
        "novel": 300,
        "notes": 300,
        "cnovel": 0,
        "cnotes": 0,
        "idle": 20,
    }
