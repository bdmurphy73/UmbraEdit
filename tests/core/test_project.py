"""
UmbraEdit - NWProject Tests
=============================

This file is a part of UmbraEdit.

Copyright (C) 2019 Veronica Berglyd Olsen and UmbraEdit contributors.

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

from datetime import datetime
from pathlib import Path
from shutil import copyfile
from typing import Any
from zipfile import ZipFile

import pytest

from umbraedit import CONFIG, SHARED
from umbraedit.constants import nwFiles
from umbraedit.core.project import NWProject, NWProjectState
from umbraedit.core.projectxml import ProjectXMLReader, ProjectXMLWriter, XMLReadState
from umbraedit.core.safeio import FileIdentity, copyRegularFile, renameNoReplace
from umbraedit.enum import nwItemClass, nwProjectKind
from umbraedit.shared import _GuiAlert

from tests.helpers import XML_IGNORE, C, MockRnd, TstPaths, buildTestProject, cmpFiles
from tests.mocked import MockGuiMain, causeOSError


@pytest.mark.core
def testNWProject_HeadlessConstruction(monkeypatch: pytest.MonkeyPatch):
    """Test that core project objects can be built without a GUI theme."""
    monkeypatch.setattr(SHARED, "_gui", None)
    monkeypatch.setattr(SHARED, "_theme", None)

    project = NWProject()

    assert project.isValid is False
    assert project.state == NWProjectState.UNKNOWN
    SHARED.error("Headless error")
    assert SHARED.question("Headless question", default=True) is True


@pytest.mark.core
def testNWProject_NewRoot(fncPath: Path, tstPaths: TstPaths, mockGUI: MockGuiMain, mockRnd: MockRnd):
    """Check that new root folders can be added to the project."""
    projFile = fncPath / "UEProject.UEx"
    testFile = tstPaths.outDir / "coreProject_NewRoot_UEProject.UEx"
    compFile = tstPaths.refDir / "coreProject_NewRoot_UEProject.UEx"

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    assert project.newRoot(nwItemClass.NOVEL) == "0000000000010"
    assert project.newRoot(nwItemClass.PLOT) == "0000000000011"
    assert project.newRoot(nwItemClass.CHARACTER) == "0000000000012"
    assert project.newRoot(nwItemClass.WORLD) == "0000000000013"
    assert project.newRoot(nwItemClass.TIMELINE) == "0000000000014"
    assert project.newRoot(nwItemClass.OBJECT) == "0000000000015"
    assert project.newRoot(nwItemClass.CUSTOM) == "0000000000016"
    assert project.newRoot(nwItemClass.CUSTOM) == "0000000000017"

    assert project.projChanged is True
    assert project.saveProject() is True
    project.closeProject()

    copyfile(projFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)
    assert project.projChanged is False

    # Delete the new items
    assert project.removeItem("0000000000010") is True
    assert project.removeItem("0000000000011") is True
    assert project.removeItem("0000000000012") is True
    assert project.removeItem("0000000000013") is True
    assert project.removeItem("0000000000014") is True
    assert project.removeItem("0000000000015") is True
    assert project.removeItem("0000000000016") is True
    assert project.removeItem("0000000000017") is True

    assert "0000000000010" not in project.tree
    assert "0000000000011" not in project.tree
    assert "0000000000012" not in project.tree
    assert "0000000000013" not in project.tree
    assert "0000000000014" not in project.tree
    assert "0000000000015" not in project.tree
    assert "0000000000016" not in project.tree
    assert "0000000000017" not in project.tree


@pytest.mark.core
def testNWProject_NewFileFolder(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    tstPaths: TstPaths,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
):
    """Check that new files can be added to the project."""
    projFile = fncPath / "UEProject.UEx"
    testFile = tstPaths.outDir / "coreProject_NewFileFolder_UEProject.UEx"
    compFile = tstPaths.refDir / "coreProject_NewFileFolder_UEProject.UEx"

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    aHandle = "0000000000010"
    bHandle = "0000000000011"
    cHandle = "0000000000012"
    dHandle = "0000000000013"
    eHandle = "0000000000014"
    xHandle = "1234567890abc"

    # Invalid call
    assert project.newFolder("New Folder", xHandle) is None
    assert project.newFile("New File", xHandle) is None

    # Add files properly
    assert project.newFolder("Stuff", C.hNovelRoot) == aHandle
    assert project.newFile("Hello", aHandle) == bHandle
    assert project.newFile("Jane", C.hCharRoot) == cHandle
    assert project.newFile("John", C.hCharRoot) == dHandle
    assert project.newFile("Mike", C.hCharRoot) == eHandle

    assert aHandle in project.tree
    assert bHandle in project.tree
    assert cHandle in project.tree
    assert dHandle in project.tree
    assert eHandle in project.tree

    # Write to file, failed
    assert project.writeNewFile("blabla", 1, True) is False  # Not a handle
    assert project.writeNewFile(aHandle, 1, True) is False  # Not a file
    assert project.writeNewFile(C.hTitlePage, 1, True) is False  # Already has content

    # Write to file, success
    assert project.writeNewFile(bHandle, 2, True) is True
    assert project.storage.getDocument(bHandle).readDocument() == "## Hello\n\n"

    # Write to file with additional text, success
    assert project.writeNewFile(cHandle, 1, False, "Hi Jane\n\n") is True
    assert project.storage.getDocument(cHandle).readDocument() == ("# Jane\n\nHi Jane\n\n")

    # Copy file content, invalid target
    assert project.copyFileContent(xHandle, cHandle) is False  # Unknown handle
    assert project.copyFileContent(aHandle, cHandle) is False  # Target is a folder

    # Copy file content, invalid source
    assert project.copyFileContent(dHandle, xHandle) is False  # Unknown handle
    assert project.copyFileContent(dHandle, aHandle) is False  # Source is a folder

    # Copy file content, target not empty
    assert project.copyFileContent(bHandle, cHandle) is False

    # Copy file content, success
    assert project.copyFileContent(dHandle, cHandle) is True

    cText = project.storage.getDocument(cHandle).readDocument()
    dText = project.storage.getDocument(dHandle).readDocument()

    assert dText == cText

    # Copy file content, and update title
    assert project.copyFileContent(eHandle, cHandle, "Lars") is True
    assert project.storage.getDocument(eHandle).readDocument() == "# Lars\n\nHi Jane\n\n"

    # Save, close and check
    assert project.projChanged is True
    assert project.saveProject() is True

    copyfile(projFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)
    assert project.projChanged is False

    # Delete new file, but block access
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.document.unlinkIfSameFile", causeOSError)
        assert project.removeItem(bHandle) is False
        assert bHandle in project.tree

    # Delete new files and folders
    assert (fncPath / "content" / f"{dHandle}.md").exists()
    assert (fncPath / "content" / f"{cHandle}.md").exists()
    assert (fncPath / "content" / f"{bHandle}.md").exists()

    assert project.removeItem(dHandle) is True
    assert project.removeItem(cHandle) is True
    assert project.removeItem(bHandle) is True
    assert project.removeItem(aHandle) is True

    assert not (fncPath / "content" / f"{dHandle}.md").exists()
    assert not (fncPath / "content" / f"{cHandle}.md").exists()
    assert not (fncPath / "content" / f"{bHandle}.md").exists()

    assert aHandle not in project.tree
    assert bHandle not in project.tree
    assert cHandle not in project.tree
    assert dHandle not in project.tree

    project.closeProject()


@pytest.mark.core
def testNWProject_CreateNewNote(monkeypatch: pytest.MonkeyPatch, fncPath: Path, mockGUI: MockGuiMain, mockRnd: MockRnd):
    """Check that new notes can be created for a given tag."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    # A NO_CLASS item class does nothing
    project.createNewNote("jane", nwItemClass.NO_CLASS)
    assert project.tree.findRoot(nwItemClass.CHARACTER) == C.hCharRoot
    assert list(project.tree.subTree(C.hCharRoot)) == []

    # A valid class creates the root folder and the note file
    project.createNewNote("jane", nwItemClass.CHARACTER)
    noteHandles = project.tree.subTree(C.hCharRoot)
    assert len(noteHandles) == 1
    assert project.tree[noteHandles[0]].itemName == "Jane"  # type: ignore
    assert project.storage.getDocument(noteHandles[0]).readDocument() == "# Jane\n\n@tag: jane\n\n"

    # A class with no existing root folder creates a new one
    assert project.tree.findRoot(nwItemClass.OBJECT) is None
    project.createNewNote("gun", nwItemClass.OBJECT)
    objRoot = project.tree.findRoot(nwItemClass.OBJECT)
    assert objRoot is not None
    assert len(project.tree.subTree(objRoot)) == 1

    # If the note file cannot be created, nothing else happens
    with monkeypatch.context() as mp:
        mp.setattr(NWProject, "newFile", lambda *a, **k: None)
        project.createNewNote("mike", nwItemClass.OBJECT)
    assert len(project.tree.subTree(objRoot)) == 1

    project.closeProject()


@pytest.mark.core
def testNWProject_Open(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test opening a project."""
    project = NWProject()
    mockRnd.reset()
    # buildTestProject(project, fncPath)

    # Unknown project file
    fooBar = fncPath / "foobar.txt"
    fooBar.touch()
    caplog.clear()
    assert project.openProject(fooBar) is False
    assert "Not a known project file format." in caplog.text
    assert project.isValid is False
    assert project.lockStatus is None

    # No project file
    caplog.clear()
    assert project.openProject(fncPath) is False
    assert "Project file not found." in caplog.text
    fooBar.unlink()

    # Fail to open project location
    projFile = fncPath / nwFiles.PROJ_FILE
    metaFile = fncPath / "meta"
    projFile.touch()
    metaFile.touch()
    caplog.clear()
    assert project.openProject(fncPath) is False
    assert "Failed to open project." in caplog.text
    metaFile.unlink()
    projFile.unlink()

    # Create test project
    buildTestProject(project, fncPath)

    # Open successfully
    assert project.openProject(fncPath) is True

    # Open again should fail on lock file
    assert project.openProject(fncPath) is False
    assert project.state == NWProjectState.LOCKED
    assert project.isValid is True
    assert project.lockStatus is not None

    # Force re-open
    assert project.openProject(fncPath, clearLock=True) is True
    assert project.state == NWProjectState.READY
    assert project.isValid is True
    assert project.lockStatus is None

    # Fail getting xml reader
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.getXmlReader", lambda *a: None)
        assert project.openProject(fncPath, clearLock=True) is False

    # Not a umbraedit XML file
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "read", lambda *a: False)
        mp.setattr(ProjectXMLReader, "state", property(lambda *a: XMLReadState.NOT_NWX_FILE))
        assert project.openProject(fncPath, clearLock=True) is False
        assert "Project file does not appear" in SHARED.lastAlert[0]

    # Unknown project file version
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "read", lambda *a: False)
        mp.setattr(ProjectXMLReader, "state", property(lambda *a: XMLReadState.UNKNOWN_VERSION))
        assert project.openProject(fncPath, clearLock=True) is False
        assert "Unknown or unsupported UmbraEdit project file" in SHARED.lastAlert[0]

    # Other parse error
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "read", lambda *a: False)
        mp.setattr(ProjectXMLReader, "state", property(lambda *a: XMLReadState.CANNOT_PARSE))
        assert project.openProject(fncPath, clearLock=True) is False
        assert "Failed to parse project xml" in SHARED.lastAlert[0]

    # Won't convert legacy file
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "state", property(lambda *a: XMLReadState.WAS_LEGACY))
        mp.setattr(_GuiAlert, "finalState", False)
        assert project.openProject(fncPath, clearLock=True) is False
        assert "The file format of your project is about to be" in SHARED.lastAlert[0]

    # Also won't convert old document files, even if the xml itself isn't flagged as legacy
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.hasBreakingChanges", lambda *a: True)
        mp.setattr(_GuiAlert, "finalState", False)
        assert project.openProject(fncPath, clearLock=True) is False
        assert "The file format of your project is about to be" in SHARED.lastAlert[0]

    # Won't open project from newer version
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "hexVersion", property(lambda *a: 0x99999999))
        mp.setattr(_GuiAlert, "finalState", False)
        assert project.openProject(fncPath, clearLock=True) is False
        assert "This project was saved by a newer version" in SHARED.lastAlert[0]

    # Will open a newer version project if the user accepts
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "hexVersion", property(lambda *a: 0x99999999))
        assert project.openProject(fncPath, clearLock=True) is True

    # If the storage path is unavailable, recent projects are not updated
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.storagePath", property(lambda *a: None))
        assert project.openProject(fncPath, clearLock=True) is True

    # A copied project keeps its ID if the user declines
    copyPath = fncPath / "copy"
    copyPath.mkdir()
    (copyPath / nwFiles.PROJ_FILE).touch()
    oldUuid = project.data.uuid
    CONFIG.recentProjects.update(copyPath, project.data, 0)
    with monkeypatch.context() as mp:
        mp.setattr(_GuiAlert, "finalState", False)
        assert project.openProject(fncPath, clearLock=True) is True
        assert "This project appears to be a copy of another project" in SHARED.lastAlert[0]
        assert project.data.uuid == oldUuid
        assert project.projChanged is False

    # A copied project gets a new ID if the user accepts
    CONFIG.recentProjects.update(copyPath, project.data, 0)
    assert project.openProject(fncPath, clearLock=True) is True
    assert project.data.uuid != oldUuid
    assert project.projChanged is True

    # A backup keeps its ID if the user declines, and skips the copy check
    manifest = fncPath / nwFiles.MANIFEST_FILE
    manifest.write_text(project.storage._generateManifest(nwProjectKind.BACKUP, 1000.0), encoding="utf-8")
    CONFIG.recentProjects.update(copyPath, project.data, 0)
    with monkeypatch.context() as mp:
        mp.setattr(_GuiAlert, "finalState", False)
        assert project.openProject(fncPath, clearLock=True) is True
        assert "This project is a backup copy" in SHARED.lastAlert[0]
        assert project.data.uuid == oldUuid
        assert project.projChanged is True

    # A backup gets a new ID if the user accepts
    assert project.openProject(fncPath, clearLock=True) is True
    assert "This project is a backup copy" in SHARED.lastAlert[0]
    assert project.data.uuid != oldUuid
    assert project.projChanged is True
    CONFIG.recentProjects.remove(copyPath)

    # Once saved, the backup is a regular project
    assert project.saveProject() is True
    assert project.openProject(fncPath, clearLock=True) is True
    assert project.storage.kind == nwProjectKind.PROJECT
    assert project.projChanged is False

    # Fail checking items should still pass
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.tree.ProjectTree.checkConsistency", lambda *a: (1, 0))
        assert project.openProject(fncPath, clearLock=True) is True

    # Trigger an index rebuild
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLReader, "state", property(lambda *a: XMLReadState.WAS_LEGACY))
        mp.setattr("umbraedit.core.index.Index.loadIndex", lambda *a: True)
        project.index._indexRevision = 0
        assert project.openProject(fncPath, clearLock=True) is True
        assert "The file format of your project is about to be" in SHARED.lastAlert[0]
        assert project.index._indexRevision == 4

    project.closeProject()


@pytest.mark.core
def testNWProject_ReopenResetsFileIdentityReceipts(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a reused project instance can open a new session."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    assert project.openProject(fncPath) is True
    assert project.saveProject() is True
    project.closeProject()

    # The options and index files were published by the previous session.
    # Reopening must re-observe them instead of treating the new file
    # identities as a concurrent replacement from the old session.
    assert project.openProject(fncPath) is True
    assert project.options.lastIdentityKnown is True
    assert project.index.lastIdentityKnown is True
    project.closeProject()


@pytest.mark.core
def testNWProject_CloseDoesNotFollowMetadataLinks(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that close-time metadata writes cannot follow symbolic links."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    tocTarget = fncPath.parent / "outside-toc.txt"
    sessionTarget = fncPath.parent / "outside-sessions.jsonl"
    tocTarget.write_text("outside toc", encoding="utf-8")
    sessionTarget.write_text("outside session", encoding="utf-8")

    tocPath = fncPath / nwFiles.TOC_FILE
    sessionPath = fncPath / "meta" / nwFiles.SESS_FILE
    tocPath.unlink(missing_ok=True)
    sessionPath.unlink(missing_ok=True)
    try:
        os.symlink(tocTarget, tocPath)
        os.symlink(sessionTarget, sessionPath)
    except OSError:
        pytest.skip("Symbolic links are not available")

    project.data.setInitCounts(50, 60, 500, 600)
    project.data.setCurrCounts(160, 150, 1600, 1500)
    project.session._start -= 350.0

    project.closeProject()

    assert tocTarget.read_text(encoding="utf-8") == "outside toc"
    assert sessionTarget.read_text(encoding="utf-8") == "outside session"
    assert tocPath.is_symlink()
    assert sessionPath.is_symlink()


@pytest.mark.core
def testNWProject_CloseRejectsReplacedProjectRoot(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that close-time writes cannot enter a replacement project root."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    movedProject = fncPath.parent / f"{fncPath.name}-moved"
    externalProject = fncPath.parent / f"{fncPath.name}-external"
    externalProject.mkdir()
    fncPath.rename(movedProject)
    try:
        os.symlink(externalProject, fncPath, target_is_directory=True)
    except OSError:
        movedProject.rename(fncPath)
        pytest.skip("Symbolic links are not available")

    project.closeProject()

    assert list(externalProject.iterdir()) == []
    assert fncPath.is_symlink()

    # Restore the fixture path for the shared test cleanup.
    fncPath.unlink()
    movedProject.rename(fncPath)


@pytest.mark.core
def testNWProject_OpenRecentTrackingPolicy(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that standalone opens can opt out of recent-project tracking."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    project.closeProject()
    CONFIG.recentProjects.remove(str(fncPath))

    assert project.openProject(fncPath / "missing", updateRecent=False) is False
    assert project.openProject(fncPath, updateRecent=False) is True
    assert str(fncPath) not in [entry[0] for entry in CONFIG.recentProjects.listEntries()]
    assert project.saveProject() is True
    assert str(fncPath) not in [entry[0] for entry in CONFIG.recentProjects.listEntries()]
    project.closeProject()

    assert project.openProject(fncPath) is True
    assert str(fncPath) in [entry[0] for entry in CONFIG.recentProjects.listEntries()]
    project.closeProject()


@pytest.mark.core
def testNWProject_ReleaseSessionRemovesLockAndAllowsSecondOpen(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a standalone release removes the exclusive lock."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    assert project.openProject(fncPath, updateRecent=False) is True
    lockPath = fncPath / nwFiles.PROJ_LOCK
    assert lockPath.exists()

    assert project.releaseSession() is True
    assert not lockPath.exists()
    assert project.isValid is False
    assert project.state == NWProjectState.UNKNOWN

    # Releasing again is idempotent.
    assert project.releaseSession() is True
    assert project.openProject(fncPath, updateRecent=False) is True
    project.releaseSession()


@pytest.mark.core
def testNWProject_OpenExceptionReleasesLock(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that an exception after lock acquisition releases the lock."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    lockPath = fncPath / nwFiles.PROJ_LOCK

    def failLoadIndex(*args: object, **kwargs: object) -> None:
        raise RuntimeError("index load failed")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.index.Index.loadIndex", failLoadIndex)
        assert project.openProject(fncPath, updateRecent=False) is False

    assert not lockPath.exists()
    assert project.isValid is False
    assert project.openProject(fncPath, updateRecent=False) is True
    project.releaseSession()


@pytest.mark.core
def testNWProject_CloseWriteFailureStillReleasesLock(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that close-time write failures cannot retain the project lock."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    assert project.openProject(fncPath, updateRecent=False) is True
    lockPath = fncPath / nwFiles.PROJ_LOCK
    assert lockPath.exists()

    def failSave(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("settings write failed")

    monkeypatch.setattr("umbraedit.core.options.OptionState.saveSettings", failSave)
    assert project.closeProject() is True
    assert not lockPath.exists()
    assert project.isValid is False
    assert project.state == NWProjectState.UNKNOWN


@pytest.mark.core
def testNWProject_ReleaseSessionRetainsFailedCleanupOwnership(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that failed lock cleanup can be retried with the same identity."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    assert project.openProject(fncPath, updateRecent=False) is True
    lockPath = fncPath / nwFiles.PROJ_LOCK
    assert lockPath.exists()

    def failUnlink(*args: object, **kwargs: object) -> bool:
        raise OSError("cleanup failed")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.unlinkEntryIfSameFile", failUnlink)
        assert project.releaseSession() is False

    assert lockPath.exists()
    assert project.storage.isOpen() is True
    assert project.storage._lockFileIdentity is not None

    assert project.releaseSession() is True
    assert not lockPath.exists()
    assert project.storage.isOpen() is False


@pytest.mark.core
def testNWProject_OpenConvertsOldDocuments(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that an old .nwd document file is only converted to .md
    once the user accepts the upgrade prompt.
    """
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    project.closeProject()

    contentPath = fncPath / "content"
    nwdFile = contentPath / f"{C.hSceneDoc}.nwd"
    mdFile = contentPath / f"{C.hSceneDoc}.md"
    mdFile.unlink()
    nwdFile.write_text("### New Scene\n\n", encoding="utf-8")

    # Declining the prompt leaves the file untouched
    project = NWProject()
    with monkeypatch.context() as mp:
        mp.setattr(_GuiAlert, "finalState", False)
        assert project.openProject(fncPath) is False
    assert nwdFile.exists()
    assert not mdFile.exists()

    # Accepting converts the file and the project opens normally
    project = NWProject()
    assert project.openProject(fncPath, clearLock=True) is True
    assert not nwdFile.exists()
    assert mdFile.exists()
    assert C.hSceneDoc in project.tree

    project.closeProject()


@pytest.mark.core
def testNWProject_OpenPreservesConflictingLegacyDocument(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that an existing converted document does not block open."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    project.closeProject()

    contentPath = fncPath / "content"
    nwdFile = contentPath / f"{C.hSceneDoc}.nwd"
    mdFile = contentPath / f"{C.hSceneDoc}.md"
    nwdText = "### Legacy Scene\n"
    mdText = mdFile.read_text(encoding="utf-8")
    nwdFile.write_text(nwdText, encoding="utf-8")

    # The current document is already present, so it is used without
    # overwriting it. The legacy source is retained for recovery.
    assert project.openProject(fncPath) is True
    assert nwdFile.read_text(encoding="utf-8") == nwdText
    assert mdFile.read_text(encoding="utf-8") == mdText
    project.closeProject()


@pytest.mark.core
def testNWProject_SaveRejectsReplacedProjectFiles(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
):
    """Test that normal saves never overwrite concurrently replaced files."""
    fileNames = (
        nwFiles.PROJ_FILE,
        f"meta/{nwFiles.OPTS_FILE}",
        f"meta/{nwFiles.INDEX_FILE}",
        nwFiles.MANIFEST_FILE,
    )
    for fileName in fileNames:
        projectPath = fncPath / fileName.replace("/", "-")
        projectPath.mkdir()
        project = NWProject()
        mockRnd.reset()
        buildTestProject(project, projectPath)

        target = projectPath / fileName
        replacement = b"foreign replacement\n"
        target.unlink()
        target.write_bytes(replacement)

        assert project.saveProject() is False
        assert target.read_bytes() == replacement
        project.closeProject()


@pytest.mark.core
def testNWProject_SaveUsesRetainedFileIdentities(
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
):
    """Test that each successful save replaces the identity it published."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    xmlPath = fncPath / nwFiles.PROJ_FILE
    firstIdentity = xmlPath.stat().st_ino
    assert project.saveProject() is True
    assert xmlPath.stat().st_ino != firstIdentity

    secondIdentity = xmlPath.stat().st_ino
    assert project.saveProject() is True
    assert xmlPath.stat().st_ino != secondIdentity
    project.closeProject()


@pytest.mark.core
def testNWProject_Save(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, mockRnd: MockRnd, fncPath: Path):
    """Test saving a project."""
    project = NWProject()

    # Nothing to save
    assert project.saveProject() is False

    mockRnd.reset()
    buildTestProject(project, fncPath)

    # Fail getting xml writer
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.getXmlWriter", lambda *a: None)
        assert project.saveProject() is False

    # Fail writing
    with monkeypatch.context() as mp:
        mp.setattr(ProjectXMLWriter, "write", lambda *a, **kwargs: False)
        assert project.saveProject() is False

    # Save with and without autosave
    assert project.saveProject(autoSave=False) is True
    assert project.saveProject(autoSave=True) is True
    assert (fncPath / nwFiles.MANIFEST_FILE).is_file()

    # If the storage path is unavailable, recent projects are not updated
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.storagePath", property(lambda *a: None))
        assert project.saveProject() is True

    project.closeProject()


@pytest.mark.core
def testNWProject_OpenLockRaceFailsClosed(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a lock appearing during open is not replaced."""
    builder = NWProject()
    mockRnd.reset()
    buildTestProject(builder, fncPath)
    builder.closeProject()

    lockPath = fncPath / nwFiles.PROJ_LOCK

    def installForeignLock(path, data, **kwargs):
        Path(path).write_text("foreign session", encoding="utf-8")
        raise FileExistsError("The project lockfile already exists", str(path))

    project = NWProject()
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.writeFileAtomic", installForeignLock)
        assert project.openProject(fncPath) is False

    assert project.isValid is False
    assert project.state == NWProjectState.LOCKED
    assert lockPath.read_text(encoding="utf-8") == "foreign session"


@pytest.mark.core
def testNWProject_SaveAsRejectsUnsafeTargets(
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
    projPath: Path,
):
    """Test that Save As rejects self-copy and symlinked destinations."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    originalPath = project.storage.storagePath
    assert project.saveProjectAs(projPath, "Self Copy") is False
    assert SHARED.lastAlert[0] == "The target project location cannot be inside the current project."
    assert project.storage.storagePath == originalPath

    nestedPath = projPath / "nested-project"
    assert project.saveProjectAs(nestedPath, "Nested Copy") is False
    assert SHARED.lastAlert[0] == "The target project location cannot be inside the current project."
    assert project.storage.storagePath == originalPath
    assert not nestedPath.exists()

    outsidePath = fncPath / "outside-target"
    outsidePath.mkdir()
    linkedPath = fncPath / "linked-target"
    try:
        os.symlink(outsidePath, linkedPath, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    assert project.saveProjectAs(linkedPath, "Linked Copy") is False
    assert SHARED.lastAlert[0] == "The target project location cannot be a symbolic link."
    assert project.storage.storagePath == originalPath
    assert list(outsidePath.iterdir()) == []


@pytest.mark.core
def testNWProject_SaveAsRejectsMissingMetadataFolder(
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
    projPath: Path,
):
    """Test that Save As does not silently omit validated metadata."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    metaPath = projPath / "meta"
    movedMetaPath = fncPath / "moved-meta"
    metaPath.rename(movedMetaPath)
    target = fncPath / "missing-meta-copy"
    try:
        assert project.saveProjectAs(target, "Missing Metadata Copy") is False
    finally:
        movedMetaPath.rename(metaPath)

    assert not target.exists()
    assert project.storage.storagePath == projPath


@pytest.mark.core
def testNWProject_SaveAsPathFallback(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
    projPath: Path,
):
    """Test that Save As works without directory-descriptor support."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / "path-fallback-copy"
    target.mkdir()
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.supportsDirectoryDescriptors", lambda: False)
        mp.setattr("umbraedit.core.storage.supportsDirectoryDescriptors", lambda: False)
        assert project.saveProjectAs(target, "Path Fallback Copy") is True

    assert project.storage.storagePath == target
    assert (target / "meta").is_dir()
    assert (target / "content").is_dir()
    assert (target / nwFiles.PROJ_FILE).is_file()
    assert not list(fncPath.glob(".umbraedit-stage-*"))


@pytest.mark.core
def testNWProject_SaveAsRetainsPublishedFileIdentities(
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
    projPath: Path,
):
    """Test that a project remains saveable after Save As."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    target = fncPath / "save-as-copy"
    assert project.saveProjectAs(target, "Save As Copy") is True
    assert project.storage.xmlIdentity is not None
    assert project.storage.lastManifestIdentity is not None

    assert project.saveProject() is True
    assert project.saveProject() is True
    project.closeProject()


@pytest.mark.core
def testNWProject_SaveAsRejectsReplacedAssetFolder(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    projPath: Path,
    mockRnd: MockRnd,
):
    """Test that Save As copies assets from the validated source snapshot."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)

    assetDir = projPath / "assets" / "img"
    assetDir.mkdir(parents=True)
    assetFile = assetDir / "cover.png"
    assetFile.write_bytes(b"original image")
    originalPath = project.storage.storagePath

    realCopy = copyRegularFile
    movedDir = projPath / "assets" / "img-original"

    def replaceAssetFolder(source: Path, target: Path, **kwargs: Any) -> FileIdentity:
        if source.parent == assetDir:
            assetDir.rename(movedDir)
            assetDir.mkdir()
            (assetDir / source.name).write_bytes(b"replacement image")
        return realCopy(source, target, **kwargs)

    target = fncPath / "replaced-asset-copy"
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.copyRegularFile", replaceAssetFolder)
        assert project.saveProjectAs(target, "Replaced Asset Copy") is False

    assert project.storage.storagePath == originalPath
    assert not target.exists()
    assert (movedDir / "cover.png").read_bytes() == b"original image"
    assert (assetDir / "cover.png").read_bytes() == b"replacement image"
    assert not list(fncPath.glob(".umbraedit-stage-*"))


@pytest.mark.core
def testNWProject_SaveAsPathFallbackRollsBack(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
    fncPath: Path,
    projPath: Path,
):
    """Test that path-based Save As restores an existing empty target."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, projPath)
    originalPath = project.storage.storagePath

    target = fncPath / "path-fallback-rollback"
    target.mkdir()
    realRename = renameNoReplace

    def failPublication(sourcePath: Path, targetPath: Path) -> bool:
        if Path(sourcePath).name.startswith(".umbraedit-stage-") and Path(targetPath) == target:
            raise OSError(errno.EIO, "Simulated publication failure", str(targetPath))
        return realRename(sourcePath, targetPath)

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.supportsDirectoryDescriptors", lambda: False)
        mp.setattr("umbraedit.core.storage.supportsDirectoryDescriptors", lambda: False)
        mp.setattr("umbraedit.core.project.renameNoReplace", failPublication)
        assert project.saveProjectAs(target, "Failed Copy") is False

    assert project.storage.storagePath == originalPath
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert not list(fncPath.glob(".umbraedit-stage-*"))
    assert not list(fncPath.glob(".umbraedit-saveas-*"))


@pytest.mark.core
def testNWProject_AutoSaveIndexRevision(mockGUI: MockGuiMain, mockRnd: MockRnd, fncPath: Path):
    """Test that the index revision is kept current in the project file
    on every save, including autosave.
    """
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)  # Performs a full save

    savedRevision = project.index.indexRevision
    assert project.data.indexRevision == savedRevision

    # Edit a document and only autosave, so the index cache on disk is left untouched
    tHandle = next(i.itemHandle for i in project.tree if i.isFileType())
    doc = project.storage.getDocument(tHandle)
    doc.writeDocument("### More Content\n\n")
    project.index.reIndexHandle(tHandle)
    assert project.index.indexRevision > savedRevision

    assert project.saveProject(autoSave=True) is True
    autoSavedRevision = project.index.indexRevision
    assert project.data.indexRevision == autoSavedRevision
    assert autoSavedRevision > savedRevision
    project.closeProject()

    # Simulate recovering after a crash.
    # The cached index.json on disk still reflects the state as of the
    # last full save, so it must be flagged as needing a rebuild.
    recovered = NWProject()
    assert recovered.openProject(fncPath, clearLock=True) is True
    assert recovered.index.indexRevision == savedRevision
    assert recovered.data.indexRevision == autoSavedRevision
    assert recovered.index.indexRebuild is True
    recovered.closeProject()


@pytest.mark.core
def testNWProject_Methods(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path, mockRnd: MockRnd):
    """Test other project class methods and functions."""
    project = NWProject()
    buildTestProject(project, fncPath)

    # Project Name
    project.data.setName("  A Name ")
    assert project.data.name == "A Name"

    # Project Author
    project.data.setAuthor("  Jane\tDoe ")
    assert project.data.author == "Jane Doe"

    # Spell check
    project.setProjectChanged(False)
    project.data.setSpellCheck(True)
    project.data.setSpellCheck(False)
    assert project.projChanged is True
    assert project.projOpened > 0

    # Spell language
    project.setProjectChanged(False)
    assert project.data.spellLang is None
    project.data.setSpellLang(None)
    assert project.data.spellLang is None
    project.data.setSpellLang("None")  # Should be interpreted as None
    assert project.data.spellLang is None
    project.data.setSpellLang("en_GB")
    assert project.data.spellLang == "en_GB"
    assert project.projChanged is True

    # Project Language
    project.setProjectChanged(False)
    project.data.setLanguage("en", False)
    project.setProjectLang(None, False)
    assert project.data.language is None
    project.setProjectLang("en_GB", False)
    assert project.data.language == "en_GB"

    # Setting the same language again does nothing
    project.setProjectChanged(False)
    project.setProjectLang("en_GB", False)
    assert project.projChanged is False

    # A non-bool value does not change the project changed flag
    assert project.setProjectChanged("not a bool") is False  # type: ignore

    # Changing only the direction is a change
    project.setProjectLang("en_GB", True)
    assert project.data.isRTL is True
    assert project.projChanged is True

    # Language Lookup
    assert project.localLookup(1) == "One"
    assert project.localLookup(10) == "Ten"

    # Set invalid language
    project.data.setLanguage("foo", False)
    project._loadProjectLocalisation()
    assert project.localLookup(1) == "One"
    assert project.localLookup(10) == "Ten"

    # Block reading language data
    project.data.setLanguage("en", False)
    with monkeypatch.context() as mp:
        mp.setattr("builtins.open", causeOSError)
        project._loadProjectLocalisation()
        assert project.localLookup(1) == "One"
        assert project.localLookup(10) == "Ten"

    # Last edited
    project.setProjectChanged(False)
    project._data.setLastHandle("0123456789abc", "editor")
    assert project._data.getLastHandle("editor") == "0123456789abc"
    assert project.projChanged

    # Last viewed
    project.setProjectChanged(False)
    project._data.setLastHandle("0123456789abc", "viewer")
    assert project._data.getLastHandle("viewer") == "0123456789abc"
    assert project.projChanged

    # Auto Replace
    project.setProjectChanged(False)
    project.data.setAutoReplace({"A": "B", "C": "D"}, False)
    assert project.data.autoReplace == {"A": "B", "C": "D"}
    assert project.projChanged

    # Error Report
    SHARED.appendErrorMessage("Error 1")
    SHARED.appendErrorMessage("Error 2")
    project._reportErrors("Opps!")
    assert SHARED.lastAlert == ["Opps!", "Error 1<br><br>Error 2"]


@pytest.mark.core
def testNWProject_Backup(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path, tstPaths: TstPaths):
    """Test the automated backup feature of the project class. The test
    creates a backup of the Minimal test project, and then unzips the
    backup file and checks that the project XML file is identical to
    the original file.
    """
    project = NWProject()

    # No Project
    assert project.backupProject(doNotify=False) is False

    buildTestProject(project, fncPath)

    # Invalid Settings
    # ================

    # Missing project name
    CONFIG._backupPath = tstPaths.tmpDir
    project.data.setName("")
    assert project.backupProject(doNotify=False) is False

    # Valid Settings
    # ==============
    CONFIG._backupPath = tstPaths.tmpDir
    project.data.setName("Test Minimal")

    # Can't make folder
    with monkeypatch.context() as mp:
        mp.setattr("pathlib.Path.mkdir", causeOSError)
        assert project.backupProject(doNotify=False) is False

    # Can't write archive
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage._addFileToZip", causeOSError)
        assert project.backupProject(doNotify=False) is False

    # Test correct settings
    assert project.backupProject(doNotify=True) is True

    files = sorted(item for item in (tstPaths.tmpDir / "Test Minimal").iterdir() if item.suffix == ".zip")
    assert len(files) in (1, 2)  # Sometimes 2 due to clock tick

    zipFile = files[0]
    assert zipFile.name.startswith("Test Minimal")
    assert zipFile.suffix == ".zip"

    # Extract the archive
    with ZipFile(tstPaths.tmpDir / "Test Minimal" / zipFile.name, mode="r") as inZip:
        inZip.extractall(tstPaths.tmpDir / "extract")

    # Check that the main project file was restored
    assert cmpFiles(fncPath / "UEProject.UEx", tstPaths.tmpDir / "extract" / "UEProject.UEx")

    # Test intervals
    fixedTime = 1783722600.0
    fixedLocal = datetime.fromtimestamp(fixedTime)
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.project.time", lambda *a, **k: fixedTime)
        CONFIG.backupInterval = "session"
        assert project.backupProject(doNotify=False) is True
        stamp = fixedLocal.strftime("%Y-%m-%d %H.%M.%S")
        assert (tstPaths.tmpDir / "Test Minimal" / f"Test Minimal {stamp}.zip").exists()

        CONFIG.backupInterval = "day"
        assert project.backupProject(doNotify=False) is True
        stamp = fixedLocal.strftime("%Y-%m-%d")
        assert (tstPaths.tmpDir / "Test Minimal" / f"Test Minimal {stamp}.zip").exists()

        CONFIG.backupInterval = "week"
        assert project.backupProject(doNotify=False) is True
        stamp = fixedLocal.strftime("%G-W%V")
        assert (tstPaths.tmpDir / "Test Minimal" / f"Test Minimal {stamp}.zip").exists()

        CONFIG.backupInterval = "month"
        assert project.backupProject(doNotify=False) is True
        stamp = fixedLocal.strftime("%Y-%m")
        assert (tstPaths.tmpDir / "Test Minimal" / f"Test Minimal {stamp}.zip").exists()
