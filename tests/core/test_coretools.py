"""
UmbraEdit - Core Tools Tests
==============================

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

import shutil
import uuid

from pathlib import Path
from shutil import copyfile
from zipfile import ZipFile

import pytest

from umbraedit import CONFIG
from umbraedit.constants import nwFiles, nwItemClass
from umbraedit.core.coretools import (
    DocDuplicator,
    DocMerger,
    DocSplitter,
    DocxImporter,
    ProjectBuilder,
    containsProjectLock,
    isValidProjectFolder,
    readProjectLock,
    readProjectName,
    replacePath,
    scanProjectFolder,
)
from umbraedit.core.item import ProjectItem
from umbraedit.core.project import NWProject
from umbraedit.core.tree import ProjectTree
from umbraedit.enum import nwBuildFmt
from umbraedit.manuscript.buildsettings import BuildSettings
from umbraedit.manuscript.docbuild import DocumentBuilder

from tests.helpers import (
    NWD_IGNORE,
    XML_IGNORE,
    C,
    MockRnd,
    TstPaths,
    buildTestProject,
    cmpFiles,
    makeDocx,
)
from tests.mocked import MockGuiMain, causeOSError


@pytest.mark.core
def testCoreTools_DocMerger(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    tstPaths: TstPaths,
    mockRnd: MockRnd,
    ipsumText: list[str],
):
    """Test the DocMerger utility."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    # Create Files to Merge
    # =====================

    hChapter1 = project.newFile("Chapter 1", C.hNovelRoot)
    assert hChapter1 is not None

    hSceneOne11 = project.newFile("Scene 1.1", hChapter1)
    hSceneOne12 = project.newFile("Scene 1.2", hChapter1)
    hSceneOne13 = project.newFile("Scene 1.3", hChapter1)
    assert hSceneOne11 is not None
    assert hSceneOne12 is not None
    assert hSceneOne13 is not None

    docText1 = "\n\n".join(ipsumText[0:2]) + "\n\n"
    docText2 = "\n\n".join(ipsumText[1:3]) + "\n\n"
    docText3 = "\n\n".join(ipsumText[2:4]) + "\n\n"
    docText4 = "\n\n".join(ipsumText[3:5]) + "\n\n"

    project.writeNewFile(hChapter1, 2, True, docText1)
    project.writeNewFile(hSceneOne11, 3, True, docText2)
    project.writeNewFile(hSceneOne12, 3, True, docText3)
    project.writeNewFile(hSceneOne13, 3, True, docText4)

    # Basic Checks
    # ============

    docMerger = DocMerger(project)
    assert docMerger.targetHandle is None

    # No writing without a target set
    assert docMerger.writeTargetDoc() is False
    assert docMerger.targetHandle is None

    # Cannot append invalid handle
    docMerger.appendText(C.hInvalid, True, "Merge")
    assert docMerger._text == []

    # Cannot create new target from invalid handle
    docMerger.newTargetDoc(C.hInvalid, "Test")
    assert docMerger.targetHandle is None

    # Merge to New
    # ============

    saveFile = fncPath / "content" / "0000000000014.md"
    testFile = tstPaths.outDir / "coreDocTools_DocMerger_0000000000014.md"
    compFile = tstPaths.refDir / "coreDocTools_DocMerger_0000000000014.md"

    docMerger.newTargetDoc(hChapter1, "All of Chapter 1")
    assert docMerger.targetHandle == "0000000000014"

    docMerger.appendText(hChapter1, True, "Merge")
    assert len(docMerger._text) == 1
    docMerger.appendText(hSceneOne11, True, "Merge")
    assert len(docMerger._text) == 2
    docMerger.appendText(hSceneOne12, True, "Merge")
    assert len(docMerger._text) == 3
    docMerger.appendText(hSceneOne13, True, "Merge")
    assert len(docMerger._text) == 4

    # Block writing and check error handling
    with monkeypatch.context() as mp:
        mp.setattr("builtins.open", causeOSError)
        assert docMerger.writeTargetDoc() is False
        assert not saveFile.exists()
        assert docMerger.getError() != ""

    # Write properly, and compare
    assert docMerger.writeTargetDoc() is True
    copyfile(saveFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=NWD_IGNORE)

    # Merge into Existing
    # ===================

    saveFile = fncPath / "content" / "0000000000010.md"
    testFile = tstPaths.outDir / "coreDocTools_DocMerger_0000000000010.md"
    compFile = tstPaths.refDir / "coreDocTools_DocMerger_0000000000010.md"

    docMerger.setTargetDoc(hChapter1)

    docMerger.appendText(hSceneOne11, True, "Merge")
    assert len(docMerger._text) == 1
    docMerger.appendText(hSceneOne12, True, "Merge")
    assert len(docMerger._text) == 2
    docMerger.appendText(hSceneOne13, True, "Merge")
    assert len(docMerger._text) == 3

    assert docMerger.writeTargetDoc() is True
    copyfile(saveFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=NWD_IGNORE)

    # Appending without a comment header
    countBefore = len(docMerger._text)
    docMerger.appendText(hSceneOne13, False, "Merge")
    assert len(docMerger._text) == countBefore + 1
    assert not docMerger._text[-1].startswith("%")

    # Just for debugging
    docMerger.writeTargetDoc()


@pytest.mark.core
def testCoreTools_DocSplitter(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
    ipsumText: list[str],
):
    """Test the DocSplitter utility."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    # Create File to Split
    # ====================

    hSplitDoc = project.newFile("Split Doc", C.hNovelRoot)

    docData = [
        "# Part One",
        ipsumText[0],
        "## Chapter One",
        ipsumText[1],
        "### Scene One",
        ipsumText[2],
        "#### Section One",
        ipsumText[3],
        "#### Section Two",
        ipsumText[4],
        "### Scene Two",
        ipsumText[0],
        "## Chapter Two",
        ipsumText[1],
        "### Scene Three",
        ipsumText[2],
        "### Scene Four",
        ipsumText[3],
        "### Scene Five",
        ipsumText[4],
    ]
    splitData = [
        (0, 1, "Part One"),
        (4, 2, "Chapter One"),
        (8, 3, "Scene One"),
        (12, 4, "Section One"),
        (16, 4, "Section Two"),
        (20, 3, "Scene Two"),
        (24, 2, "Chapter Two"),
        (28, 3, "Scene Three"),
        (32, 3, "Scene Four"),
        (36, 3, "Scene Five"),
    ]

    docText = "\n\n".join(docData)
    docRaw = docText.splitlines()
    assert project.storage.getDocument(hSplitDoc).writeDocument(docText) is True
    project.tree[hSplitDoc].setStatus(C.sFinished)  # type: ignore
    project.tree[hSplitDoc].setImport(C.iMain)  # type: ignore

    docSplitter = DocSplitter(project, hSplitDoc)  # type: ignore
    assert docSplitter._srcItem.isFileType()  # type: ignore
    assert docSplitter.getError() == ""

    # Run the split algorithm
    docSplitter.splitDocument(splitData, docRaw)  # type: ignore
    for i, (lineNo, hLevel, hLabel) in enumerate(splitData):
        assert docSplitter._rawData[i] == (docRaw[lineNo : lineNo + 4], hLevel, hLabel)
    assert project.tree.subTree(C.hNovelRoot) == [
        "000000000000c",
        "000000000000d",
        "000000000000e",
        "000000000000f",
        "0000000000010",
    ]

    # Test flat split into same parent
    docSplitter.setParentItem(C.hNovelRoot)
    assert docSplitter._inFolder is False
    assert docSplitter._parHandle is not None

    # Cause write error on all chunks
    with monkeypatch.context() as mp:
        mp.setattr("builtins.open", causeOSError)
        assert not any(docSplitter.writeDocuments(False))
        assert docSplitter.getError() == "OSError: Mock OSError"
    assert project.tree.subTree(C.hNovelRoot) == [
        "000000000000c",
        "000000000000d",
        "000000000000e",
        "000000000000f",
        "0000000000010",
        "0000000000011",
        "0000000000012",
        "0000000000013",
        "0000000000014",
        "0000000000015",
        "0000000000016",
        "0000000000017",
        "0000000000018",
        "0000000000019",
        "000000000001a",
    ]

    # Generate as flat structure in root folder
    resStatus = list(docSplitter.writeDocuments(False))
    resDocHandle = project.tree.subTree(C.hNovelRoot)

    assert all(resStatus)
    assert resDocHandle == [
        "000000000000c",
        "000000000000d",
        "000000000000e",
        "000000000000f",
        "0000000000010",
        "0000000000011",
        "0000000000012",
        "0000000000013",
        "0000000000014",
        "0000000000015",
        "0000000000016",
        "0000000000017",
        "0000000000018",
        "0000000000019",
        "000000000001a",
        "000000000001b",
        "000000000001c",
        "000000000001d",
        "000000000001e",
        "000000000001f",
        "0000000000020",
        "0000000000021",
        "0000000000022",
        "0000000000023",
        "0000000000024",
    ]

    # Generate as hierarchy in new folder
    docSplitter.newParentFolder(C.hNovelRoot, "Split Folder")
    assert docSplitter._inFolder is True
    assert docSplitter._parHandle is not None

    resStatus = list(docSplitter.writeDocuments(True))
    resDocHandle = project.tree.subTree(docSplitter._parHandle)

    assert all(resStatus)
    assert resDocHandle == [
        "0000000000026",  # Part One
        "0000000000027",  # Chapter One
        "0000000000028",  # Scene One
        "0000000000029",  # Section One
        "000000000002a",  # Section Two
        "000000000002b",  # Scene Two
        "000000000002c",  # Chapter Two
        "000000000002d",  # Scene Three
        "000000000002e",  # Scene Four
        "000000000002f",  # Scene Five
    ]

    # Check that status and importance has been preserved
    for rHandle in resDocHandle:
        assert project.tree[rHandle].itemStatus == C.sFinished  # type: ignore
        assert project.tree[rHandle].itemImport == C.iMain  # type: ignore

    # An invalid parent handle results in no new item being created
    docSplitter.newParentFolder(C.hInvalid, "Bad Folder")
    assert docSplitter._parHandle is None

    # An invalid parent handle deeper in the hierarchy results in no documents written
    docSplitter.setParentItem(C.hInvalid)
    assert list(docSplitter.writeDocuments(True)) == []

    # Check handling of improper initialisation
    docSplitter = DocSplitter(project, C.hInvalid)
    assert docSplitter._srcHandle is None
    assert docSplitter._srcItem is None
    assert docSplitter.newParentFolder(C.hNovelRoot, "Split Folder") is None
    assert list(docSplitter.writeDocuments(False)) == []

    project.saveProject()


@pytest.mark.core
def testCoreTools_DocDuplicator(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    tstPaths: TstPaths,
    mockRnd: MockRnd,
):
    """Test the DocDuplicator utility."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    dup = DocDuplicator(project)

    ttText = "#! New Novel\n\n>> By Jane Doe <<\n"
    chText = "## New Chapter\n\n"
    scText = "### New Scene\n\n"

    # Check document content
    assert project.storage.getDocument(C.hTitlePage).readDocument() == ttText
    assert project.storage.getDocument(C.hChapterDoc).readDocument() == chText
    assert project.storage.getDocument(C.hSceneDoc).readDocument() == scText

    # Nothing to do
    assert list(dup.duplicate([])) == []

    # Single Document
    # ===============

    # A new copy is created
    assert list(dup.duplicate([C.hSceneDoc])) == [
        "0000000000010"  # The Scene
    ]
    assert list(project.tree._items.keys()) == [
        C.hNovelRoot,
        C.hPlotRoot,
        C.hCharRoot,
        C.hWorldRoot,
        C.hTitlePage,
        C.hChapterDir,
        C.hChapterDoc,
        C.hSceneDoc,
        "0000000000010",
    ]

    # With the same content
    assert project.storage.getDocument("0000000000010").readDocument() == scText

    # They should have the same parent
    assert project.tree["0000000000010"].itemParent == C.hChapterDir  # type: ignore

    # Folder w/Two Files
    # ==================

    # The folder is copied, with two docs
    assert list(dup.duplicate([C.hChapterDir, C.hChapterDoc, C.hSceneDoc])) == [
        "0000000000011",  # The Folder
        "0000000000012",  # The Chapter
        "0000000000013",  # The Scene
    ]
    assert list(project.tree._items.keys()) == [
        C.hNovelRoot,
        C.hPlotRoot,
        C.hCharRoot,
        C.hWorldRoot,
        C.hTitlePage,
        C.hChapterDir,
        C.hChapterDoc,
        C.hSceneDoc,
        "0000000000010",
        "0000000000011",
        "0000000000012",
        "0000000000013",
    ]

    # With the same content
    assert project.storage.getDocument("0000000000012").readDocument() == chText
    assert project.storage.getDocument("0000000000013").readDocument() == scText

    # The chapter dirs should have the same parent
    assert project.tree["0000000000011"].itemParent == C.hNovelRoot  # type: ignore

    # The new files should have the new folder as parent
    assert project.tree["0000000000012"].itemParent == "0000000000011"  # type: ignore
    assert project.tree["0000000000013"].itemParent == "0000000000011"  # type: ignore

    # Full Root Folder
    # ================

    # The root is copied, with three docs and a folder
    assert list(dup.duplicate([C.hNovelRoot, C.hTitlePage, C.hChapterDir, C.hChapterDoc, C.hSceneDoc])) == [
        "0000000000014",  # The Root
        "0000000000015",  # The Title Page
        "0000000000016",  # The Folder
        "0000000000017",  # The Chapter
        "0000000000018",  # The Scene
    ]
    assert list(project.tree._items.keys()) == [
        C.hNovelRoot,
        C.hPlotRoot,
        C.hCharRoot,
        C.hWorldRoot,
        C.hTitlePage,
        C.hChapterDir,
        C.hChapterDoc,
        C.hSceneDoc,
        "0000000000010",
        "0000000000011",
        "0000000000012",
        "0000000000013",
        "0000000000014",
        "0000000000015",
        "0000000000016",
        "0000000000017",
        "0000000000018",
    ]

    # With the same content
    assert project.storage.getDocument("0000000000015").readDocument() == ttText
    assert project.storage.getDocument("0000000000017").readDocument() == chText
    assert project.storage.getDocument("0000000000018").readDocument() == scText

    # The root folder should have no parent
    assert project.tree["0000000000014"].itemParent is None  # type: ignore

    # The folder and files should have the new root
    assert project.tree["0000000000015"].itemRoot == "0000000000014"  # type: ignore
    assert project.tree["0000000000016"].itemRoot == "0000000000014"  # type: ignore
    assert project.tree["0000000000017"].itemRoot == "0000000000014"  # type: ignore
    assert project.tree["0000000000018"].itemRoot == "0000000000014"  # type: ignore

    # And they should have new parents
    assert project.tree["0000000000015"].itemParent == "0000000000014"  # type: ignore
    assert project.tree["0000000000016"].itemParent == "0000000000014"  # type: ignore
    assert project.tree["0000000000017"].itemParent == "0000000000016"  # type: ignore
    assert project.tree["0000000000018"].itemParent == "0000000000016"  # type: ignore

    # Exceptions
    # ==========

    # Handle invalid items
    assert list(dup.duplicate([C.hInvalid])) == []

    # Also stop early if invalid items are encountered
    assert list(dup.duplicate([C.hInvalid, C.hSceneDoc])) == []

    # Don't overwrite existing files
    content = project.storage.contentPath
    assert isinstance(content, Path)
    (content / "0000000000019.md").touch()
    assert (content / "0000000000019.md").exists()
    assert list(dup.duplicate([C.hChapterDoc, C.hSceneDoc])) == ["0000000000019", "000000000001a"]

    # Save and Close
    project.saveProject()

    projFile = fncPath / "UEProject.UEx"
    testFile = tstPaths.outDir / "coreTools_DocDuplicator_UEProject.UEx"
    compFile = tstPaths.refDir / "coreTools_DocDuplicator_UEProject.UEx"

    copyfile(projFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)

    # If duplicating an item fails, later items are still processed
    with monkeypatch.context() as mp:
        original = type(project.tree).duplicate
        state = {"count": 0}

        def flaky(self: ProjectTree, handle: str, pHandle: str | None, after: bool) -> ProjectItem | None:
            state["count"] += 1
            return None if state["count"] == 1 else original(self, handle, pHandle, after)

        mp.setattr(type(project.tree), "duplicate", flaky)
        before = set(project.tree._items.keys())
        result = list(dup.duplicate([C.hChapterDoc, C.hSceneDoc]))
        assert len(result) == 1
        assert result[0] not in before


@pytest.mark.core
def testCoreTools_ProjectBuilderWrapper(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test the wrapper function of the project builder."""
    builder = ProjectBuilder()

    # Setting no data should fail
    assert builder.buildProject({}) is False

    # Wrong type should also fail
    assert builder.buildProject("stuff") is False  # type: ignore

    # Folder not writable
    caplog.clear()
    with monkeypatch.context() as mp:
        mp.setattr("pathlib.Path.mkdir", causeOSError)
        assert builder.buildProject({"path": fncPath}) is False
        assert "An error occurred" in caplog.text

    # Try again with a proper path
    assert builder.buildProject({"path": fncPath}) is True
    assert builder.projPath == fncPath

    # Creating the project once more should fail
    caplog.clear()
    assert builder.buildProject({"path": fncPath}) is False
    assert "The target folder is not empty." in caplog.text


@pytest.mark.core
def testCoreTools_ProjectBuilderA(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    tstPaths: TstPaths,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
):
    """Create a new project from a project dictionary, with chapters."""
    monkeypatch.setattr("uuid.uuid4", lambda *a: uuid.UUID("d0f3fe10-c6e6-4310-8bfd-181eb4224eed"))

    data = {
        "name": "Test Project A",
        "author": "Jane Doe",
        "language": -1,
        "path": fncPath,
        "sample": False,
        "template": None,
        "chapters": 3,
        "scenes": 3,
        "roots": [
            nwItemClass.PLOT,
            nwItemClass.CHARACTER,
            nwItemClass.WORLD,
        ],
        "notes": True,
    }

    builder = ProjectBuilder()
    assert builder.buildProject(data) is True

    projFile = fncPath / "UEProject.UEx"
    testFile = tstPaths.outDir / "coreTools_ProjectBuilderA_UEProject.UEx"
    compFile = tstPaths.refDir / "coreTools_ProjectBuilderA_UEProject.UEx"

    copyfile(projFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)

    # Check Content
    project = NWProject()
    project.openProject(fncPath)

    build = BuildSettings()

    docBuild = DocumentBuilder(project, build)
    docBuild.queueAll()

    testFile = tstPaths.outDir / "coreTools_ProjectBuilderA_Project.md"
    compFile = tstPaths.refDir / "coreTools_ProjectBuilderA_Project.md"

    assert list(docBuild.iterBuildDocument(testFile, nwBuildFmt.EXT_MD))
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)


@pytest.mark.core
def testCoreTools_ProjectBuilderB(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    tstPaths: TstPaths,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
):
    """Create a new project from a project dictionary, without chapters."""
    monkeypatch.setattr("uuid.uuid4", lambda *a: uuid.UUID("d0f3fe10-c6e6-4310-8bfd-181eb4224eed"))

    data = {
        "name": "Test Project B",
        "author": "Jane Doe",
        "language": -1,
        "path": fncPath,
        "sample": False,
        "template": None,
        "chapters": 0,
        "scenes": 6,
        "roots": [
            nwItemClass.PLOT,
            nwItemClass.CHARACTER,
            nwItemClass.WORLD,
        ],
        "notes": True,
    }

    builder = ProjectBuilder()
    assert builder.buildProject(data) is True

    projFile = fncPath / "UEProject.UEx"
    testFile = tstPaths.outDir / "coreTools_ProjectBuilderB_UEProject.UEx"
    compFile = tstPaths.refDir / "coreTools_ProjectBuilderB_UEProject.UEx"

    copyfile(projFile, testFile)
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)

    # Check Content
    project = NWProject()
    project.openProject(fncPath)

    build = BuildSettings()

    docBuild = DocumentBuilder(project, build)
    docBuild.queueAll()

    testFile = tstPaths.outDir / "coreTools_ProjectBuilderB_Project.md"
    compFile = tstPaths.refDir / "coreTools_ProjectBuilderB_Project.md"

    assert list(docBuild.iterBuildDocument(testFile, nwBuildFmt.EXT_MD))
    assert cmpFiles(testFile, compFile, ignStart=XML_IGNORE)


@pytest.mark.core
def testCoreTools_ProjectBuilderNoScenesAndRoots(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockGUI: MockGuiMain,
    mockRnd: MockRnd,
):
    """Create a new project with chapters but no scenes, and check handling
    of invalid root entries and disabled notes.
    """
    monkeypatch.setattr("uuid.uuid4", lambda *a: uuid.UUID("d0f3fe10-c6e6-4310-8bfd-181eb4224eed"))

    data = {
        "name": "Test Project C",
        "author": "Jane Doe",
        "language": -1,
        "path": fncPath,
        "sample": False,
        "template": None,
        "chapters": 2,
        "scenes": 0,
        "roots": [
            nwItemClass.PLOT,
            "not_a_valid_root",
        ],
        "notes": False,
    }

    builder = ProjectBuilder()
    assert builder.buildProject(data) is True

    project = NWProject()
    project.openProject(fncPath)

    # Chapters were created, but no scenes underneath them
    novelRoot = project.tree.findRoot(nwItemClass.NOVEL)
    assert novelRoot is not None
    for cHandle in project.tree.subTree(novelRoot):
        assert project.tree[cHandle].isFileType()  # type: ignore

    # The valid root was created, but no notes since "notes" is False
    plotRoot = project.tree.findRoot(nwItemClass.PLOT)
    assert plotRoot is not None
    assert project.tree.subTree(plotRoot) == []

    # The invalid root entry was ignored (only Novel, Metadata, Plot,
    # Archive, and Trash exist)
    assert project.tree.rootClasses() == {
        nwItemClass.NOVEL,
        nwItemClass.METADATA,
        nwItemClass.PLOT,
        nwItemClass.ARCHIVE,
        nwItemClass.TRASH,
    }


@pytest.mark.core
def testCoreTools_ProjectBuilderCopyPlain(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mockGUI: MockGuiMain,
    prjLipsum: Path,
    fncPath: Path,
):
    """Create a new project copied from existing project."""
    srcPath = prjLipsum / nwFiles.PROJ_FILE
    dstPath = fncPath / "lipsum"
    data = {
        "name": "Test Project",
        "author": "Jane Doe",
        "path": dstPath,
        "template": srcPath,
    }

    builder = ProjectBuilder()

    # No path set
    assert builder.buildProject({"template": srcPath}) is False

    # No project at path
    assert builder.buildProject({"path": fncPath, "template": fncPath}) is False

    # Cannot copy to existing folder
    assert builder.buildProject({"path": fncPath, "template": srcPath}) is False

    # Valid data, but copy fails
    caplog.clear()
    with monkeypatch.context() as mp:
        mp.setattr("pathlib.Path.mkdir", lambda *a, **k: causeOSError)
        assert builder.buildProject(data) is False
        assert "Could not copy project files." in caplog.text
        dstPath.unlink(missing_ok=True)  # The failed mkdir leaves an empty file

    # Add a stray file that should not be copied
    strayFile = prjLipsum / "content" / "not-a-handle.txt"
    strayFile.write_text("stray")

    # Copy project properly
    assert builder.buildProject(data) is True
    assert not (dstPath / "content" / "not-a-handle.txt").exists()

    # Check Copy
    # ==========

    srcProject = NWProject()
    srcProject.openProject(srcPath)

    dstProject = NWProject()
    dstProject.openProject(dstPath)

    # UUID should be different
    assert srcProject.data.uuid != dstProject.data.uuid

    # Name should be different
    assert srcProject.data.name == "Lorem Ipsum"
    assert dstProject.data.name == "Test Project"

    # Author should be different
    assert srcProject.data.author == "lipsum.com"
    assert dstProject.data.author == "Jane Doe"

    # Language should be the same
    assert srcProject.data.language == "en_GB"
    assert dstProject.data.language == "en_GB"

    # Counts should be more or less zeroed
    assert dstProject.data.saveCount < 5
    assert dstProject.data.autoCount < 5
    assert dstProject.data.editTime < 10


@pytest.mark.core
def testCoreTools_ProjectBuilderCopyZipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Create a new project copied from existing zipped project."""
    # Create a project
    origPath = fncPath / "original"
    srcProject = NWProject()
    buildTestProject(srcProject, origPath)

    # Zip it
    shutil.make_archive(str(fncPath / "original"), "zip", origPath)

    # Make fake zip file
    fakeZip = fncPath / "broken.zip"
    fakeZip.write_bytes(b"stuff")

    # Set up the builder
    srcPath = fncPath / "original.zip"
    dstPath = fncPath / "copy"
    data = {
        "name": "Test Project",
        "author": "Jane Doe",
        "language": "en_US",
        "path": dstPath,
        "template": srcPath,
    }

    builder = ProjectBuilder()

    # No path set
    assert builder.buildProject({"template": srcPath}) is False

    # No project at path
    assert builder.buildProject({"path": fncPath, "template": fncPath}) is False

    # Cannot copy to existing folder
    assert builder.buildProject({"path": fncPath, "template": srcPath}) is False

    # Cannot copy to existing folder
    caplog.clear()
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.coretools.is_zipfile", lambda *a: True)
        assert builder.buildProject({"path": dstPath, "template": fakeZip}) is False
        assert "Could not copy project files." in caplog.text
        shutil.rmtree(dstPath, ignore_errors=True)

    # Copy project properly
    assert builder.buildProject(data) is True

    # Check Copy
    # ==========

    dstProject = NWProject()
    dstProject.openProject(dstPath)

    # UUID should be different
    assert srcProject.data.uuid != dstProject.data.uuid

    # Name should be different
    assert srcProject.data.name == "New Project"
    assert dstProject.data.name == "Test Project"

    # Author should be different
    assert srcProject.data.author == "Jane Doe"
    assert dstProject.data.author == "Jane Doe"

    # Language should be the same
    assert srcProject.data.language is None
    assert dstProject.data.language is None

    # Counts should be more or less zeroed
    assert dstProject.data.saveCount < 5
    assert dstProject.data.autoCount < 5
    assert dstProject.data.editTime < 10


@pytest.mark.core
def testCoreTools_ProjectBuilderSample(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    tstPaths: TstPaths,
):
    """Create a new sample project."""
    data = {
        "name": "Test Sample",
        "author": "Jane Doe",
        "path": fncPath / "project",
        "sample": True,
    }

    builder = ProjectBuilder()

    # No path set
    assert builder.buildProject({"sample": True}) is False

    # Force the lookup path for assets to our temp folder
    srcSample = CONFIG._appRoot / "sample"
    bldSample = CONFIG.assetPath("sample.zip")
    dstSample = tstPaths.tmpDir / "sample.zip"
    monkeypatch.setattr("umbraedit.config.Config.assetPath", lambda *a: tstPaths.tmpDir / "sample.zip")

    # Cannot extract when the zip does not exist
    assert builder.buildProject(data) is False

    # Create and open a defective zip file
    with open(dstSample, mode="w+", encoding="utf-8") as outFile:
        outFile.write("foo")

    assert builder.buildProject(data) is False
    dstSample.unlink()

    # Create a real zip file, and unpack it. The raw sample source isn't
    # shipped in packaged builds, only the pre-built asset, so fall back
    # to copying that instead.
    if srcSample.is_dir():
        with ZipFile(dstSample, "w") as zipObj:
            zipObj.write(srcSample / "UEProject.UEx", "UEProject.UEx")
            for docFile in (srcSample / "content").iterdir():
                zipObj.write(docFile, f"content/{docFile.name}")
    else:
        assert bldSample.is_file()
        copyfile(bldSample, dstSample)

    assert builder.buildProject(data) is True

    # Can't create to the same target again
    assert builder.buildProject(data) is False

    # Building without a name or author keeps the sample's own values
    dataNoNameAuthor = {"path": fncPath / "project2", "sample": True}
    assert builder.buildProject(dataNoNameAuthor) is True

    sampleProject = NWProject()
    sampleProject.openProject(fncPath / "project2")
    assert sampleProject.data.name != ""
    assert sampleProject.data.author != ""

    dstSample.unlink()


@pytest.mark.core
def testCoreTools_DocxImporter(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Import a Word document into a new project."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [
            ("My Novel", "Title"),
            ("Jane Doe", "Subtitle"),
            ("Chapter One", "Heading1"),
            ("The first paragraph of the chapter.", None),
            ("Scene One", "Heading2"),
            ("The first scene.", None),
            ("Chapter Two", "Heading1"),
            ("Another chapter.", None),
        ],
        title="My Novel",
        author="Jane Doe",
    )

    projPath = fncPath / "imported"
    importer = DocxImporter()
    assert importer.importFile(docxPath, projPath) is True
    assert importer.error == ""
    assert importer.projectPath == projPath

    # The project files must exist
    assert (projPath / nwFiles.PROJ_FILE).is_file()
    assert (projPath / "manifest.json").is_file()

    # The source document is kept for provenance
    assert (projPath / "import" / "source" / "original.docx").is_file()
    assert (projPath / "import" / "manifest.json").is_file()

    # Open the project and check its contents
    project = NWProject()
    assert project.openProject(projPath) is True
    assert project.data.name == "My Novel"
    assert project.data.author == "Jane Doe"

    roots = {node.item.itemName: node for node in project.tree._model.root.children}
    assert list(roots) == [
        "Novel",
        "Characters",
        "Locations",
        "Metadata",
        "Research",
        "Archive",
        "Trash",
    ]

    # The novel root has a document for each block of the Word document,
    # but the scenes are nested under their chapter
    novel = roots["Novel"]
    assert novel.childCount() == 3
    docs = [(node.item.itemName, node.item.mainHeading) for node in novel.children]
    assert docs == [
        ("My Novel", "H1"),
        ("Chapter One", "H2"),
        ("Chapter Two", "H2"),
    ]

    # The scene must be a child of the chapter it belongs to
    chapter = novel.children[1]
    assert chapter.childCount() == 1
    scene = chapter.children[0]
    assert scene.item.itemName == "Scene One"
    assert scene.item.mainHeading == "H3"
    assert scene.item.itemParent == chapter.item.itemHandle

    # The text of the documents must be preserved
    text = project.storage.getDocumentText(scene.item.itemHandle)
    assert "### Scene One" in text
    assert "The first scene." in text

    # The import issues document must be present in the research root
    research = roots["Research"]
    assert research.childCount() == 1
    issues = research.children[0]
    assert issues.item.itemName == "Import Issues"
    assert issues.item.getMainIconStyle() == "alert_error:issue"

    # There must be no orphaned files in the project
    assert project.tree.checkConsistency("Recovered") == (0, 0)

    project.closeProject()


@pytest.mark.core
def testCoreTools_DocxImporterCommentsAndImages(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Comments and images are handled as specified."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [
            ("Chapter One", "Heading1"),
            ("A paragraph with an image.", None),
            ("A commented paragraph.", None),
        ],
        comments=[(2, "1", "Check this")],
        images={1: "rId9"},
    )

    projPath = fncPath / "imported"
    importer = DocxImporter()
    assert importer.importFile(docxPath, projPath) is True

    project = NWProject()
    assert project.openProject(projPath) is True

    roots = {node.item.itemName: node for node in project.tree._model.root.children}
    novel = roots["Novel"]
    chapter = novel.children[0]

    # The chapter must have an images document as a child
    assert chapter.childCount() == 1
    images = chapter.children[0]
    assert images.item.itemName == "Images"
    assert images.item.getMainIconStyle() == "prj_document:image"

    # The images document must list the image
    imgText = project.storage.getDocumentText(images.item.itemHandle)
    assert "# Images" in imgText
    assert "img_" in imgText
    assert "rId9" in imgText

    # The image file must be saved in the project
    assert (projPath / "assets" / "img").is_dir()
    assert len(list((projPath / "assets" / "img").iterdir())) == 1

    # The text document must hold the image marker
    text = project.storage.getDocumentText(chapter.item.itemHandle)
    assert "%Image: img_" in text
    assert "paragraph=1" in text
    assert 'context="A paragraph with an image."' in text

    # The comment must be inserted in the text as a synopsis comment,
    # and must not be a document of its own
    assert "%Synopsis: Test Author: Check this" in text
    assert not any(node.item.itemName.startswith("Comment") for node in roots["Research"].children)

    project.closeProject()


@pytest.mark.core
def testCoreTools_DocxImporterNameOverride(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """The project name and author can be overridden."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [("Chapter One", "Heading1"), ("Some text.", None)],
        title="Doc Title",
        author="Doc Author",
    )

    projPath = fncPath / "imported"
    importer = DocxImporter()
    assert importer.importFile(docxPath, projPath, name="New Name", author="New Author") is True

    project = NWProject()
    assert project.openProject(projPath) is True
    assert project.data.name == "New Name"
    assert project.data.author == "New Author"
    project.closeProject()


@pytest.mark.core
def testCoreTools_DocxImporterErrors(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test the error handling of the Word document importer."""
    importer = DocxImporter()

    # A source file that does not exist
    assert importer.importFile(fncPath / "missing.docx", fncPath / "imported") is False
    assert importer.error != ""

    # A source file that is not a Word document
    badPath = fncPath / "bad.docx"
    badPath.write_text("Not a Word document", encoding="utf-8")
    assert importer.importFile(badPath, fncPath / "imported") is False
    assert importer.error != ""

    # A valid Word document is needed for the remaining path checks
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [("Chapter One", "Heading1"), ("Some text.", None)],
    )

    # An empty target path must not resolve to the current working directory
    assert importer.importFile(docxPath, "", overwrite=True) is False
    assert importer.error != ""

    # The home directory and filesystem root are not valid replacement targets
    assert importer.importFile(docxPath, Path.home(), overwrite=True) is False
    assert importer.error != ""
    assert importer.importFile(docxPath, Path.home().parent, overwrite=True) is False
    assert importer.error != ""
    assert importer.importFile(docxPath, Path(Path.home().anchor), overwrite=True) is False
    assert importer.error != ""

    # A target folder that is not empty
    target = fncPath / "notempty"
    target.mkdir(parents=True)
    (target / "stuff.txt").write_text("Stuff", encoding="utf-8")
    assert importer.importFile(docxPath, target) is False
    assert importer.error != ""
    assert not (target / nwFiles.PROJ_FILE).exists()

    # A Word document with no content
    emptyPath = makeDocx(fncPath / "empty.docx", [])
    assert importer.importFile(emptyPath, fncPath / "imported") is False
    assert importer.error != ""
    assert not (fncPath / "imported").exists()


@pytest.mark.core
def testCoreTools_ReplacePathRollback(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a failed replacement restores the original path."""
    source = fncPath / "replacement"
    source.mkdir()
    (source / "new.txt").write_text("New", encoding="utf-8")

    target = fncPath / "existing"
    target.mkdir()
    (target / "old.txt").write_text("Old", encoding="utf-8")

    originalRename = Path.rename

    def failReplacement(self: Path, path: str | Path) -> Path:
        if self == source:
            raise OSError("Replacement failed")
        return originalRename(self, path)

    monkeypatch.setattr(Path, "rename", failReplacement)
    with pytest.raises(OSError, match="Replacement failed"):
        replacePath(source, target)

    assert (target / "old.txt").read_text(encoding="utf-8") == "Old"
    assert not (target / "new.txt").exists()
    assert (source / "new.txt").is_file()


@pytest.mark.core
def testCoreTools_ReplacePathLocked(
    fncPath: Path,
):
    """Test that a locked project is not moved or replaced."""
    source = fncPath / "replacement"
    source.mkdir()
    (source / "new.txt").write_text("New", encoding="utf-8")

    target = fncPath / "existing"
    target.mkdir()
    (target / "old.txt").write_text("Old", encoding="utf-8")
    (target / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")

    with pytest.raises(RuntimeError, match="locked"):
        replacePath(source, target)

    assert (target / "old.txt").read_text(encoding="utf-8") == "Old"
    assert (source / "new.txt").is_file()


@pytest.mark.core
def testCoreTools_ReplacePathLockRace(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a lock appearing during replacement restores the target."""
    source = fncPath / "replacement"
    source.mkdir()
    (source / "new.txt").write_text("New", encoding="utf-8")

    target = fncPath / "existing"
    target.mkdir()
    (target / "old.txt").write_text("Old", encoding="utf-8")

    originalRename = Path.rename

    def addLock(self: Path, path: str | Path) -> Path:
        if self == source:
            for backup in target.parent.glob(f".{target.name}.umbraedit-backup-*"):
                (backup / nwFiles.PROJ_LOCK).write_text("late lock", encoding="utf-8")
        return originalRename(self, path)

    monkeypatch.setattr(Path, "rename", addLock)
    with pytest.raises(RuntimeError, match="locked"):
        replacePath(source, target)

    assert (target / "old.txt").read_text(encoding="utf-8") == "Old"
    assert not (target / "new.txt").exists()


@pytest.mark.core
def testCoreTools_ReplacePathTargetLockRace(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
):
    """Test that a lock written to the installed target restores the original."""
    source = fncPath / "replacement"
    source.mkdir()
    (source / "new.txt").write_text("New", encoding="utf-8")

    target = fncPath / "existing"
    target.mkdir()
    (target / "old.txt").write_text("Old", encoding="utf-8")

    originalRename = Path.rename

    def addLock(self: Path, path: str | Path) -> Path:
        result = originalRename(self, path)
        if self == source:
            (target / nwFiles.PROJ_LOCK).write_text("late lock", encoding="utf-8")
        return result

    monkeypatch.setattr(Path, "rename", addLock)
    with pytest.raises(RuntimeError, match="became locked"):
        replacePath(source, target)

    assert (target / "old.txt").read_text(encoding="utf-8") == "Old"
    assert not (target / "new.txt").exists()

    # The competing project and its lock are preserved, not deleted.
    failed = list(fncPath.glob(".existing.umbraedit-failed-*"))
    assert len(failed) == 1
    assert (failed[0] / nwFiles.PROJ_LOCK).is_file()


@pytest.mark.core
def testCoreTools_ReplacePathSourceLocked(fncPath: Path):
    """Test that a locked replacement is not installed."""
    source = fncPath / "replacement"
    source.mkdir()
    (source / "new.txt").write_text("New", encoding="utf-8")
    (source / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")

    target = fncPath / "existing"
    target.mkdir()
    (target / "old.txt").write_text("Old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="locked"):
        replacePath(source, target)

    assert (target / "old.txt").read_text(encoding="utf-8") == "Old"
    assert (source / "new.txt").is_file()


@pytest.mark.core
def testCoreTools_ReplacePathDescendantLocked(fncPath: Path):
    """Test that a container with a locked descendant is not replaced."""
    source = fncPath / "replacement"
    source.mkdir()
    (source / "new.txt").write_text("New", encoding="utf-8")

    target = fncPath / "existing"
    active = target / "Active Project"
    active.mkdir(parents=True)
    (active / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")

    with pytest.raises(RuntimeError, match="locked"):
        replacePath(source, target)

    assert (active / nwFiles.PROJ_LOCK).is_file()
    assert (source / "new.txt").is_file()


@pytest.mark.core
def testCoreTools_ProjectBuilderSaveFailure(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that a failed project save is reported as a build failure."""
    monkeypatch.setattr(NWProject, "saveProject", lambda *a, **k: False)
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(fncPath / "new"), "name": "New Project", "author": ""}) is False


@pytest.mark.core
def testCoreTools_ProjectBuilderStaleLock(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that a project with a stale lock is not accepted as built."""
    originalClose = NWProject.closeProject

    def leaveLock(project: NWProject) -> None:
        path = project.storage.storagePath
        originalClose(project)
        if path:
            (path / nwFiles.PROJ_LOCK).write_text("stale lock", encoding="utf-8")

    monkeypatch.setattr(NWProject, "closeProject", leaveLock)
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(fncPath / "new"), "name": "New Project", "author": ""}) is False
    assert (fncPath / "new" / nwFiles.PROJ_LOCK).is_file()


@pytest.mark.core
def testCoreTools_ResetProjectKeepsLock(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that a failed open does not remove another instance's lock."""
    source = fncPath / "source"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(source), "name": "Source", "author": ""})
    lockFile = source / nwFiles.PROJ_LOCK
    lockFile.write_text("locked", encoding="utf-8")

    builder = ProjectBuilder()
    assert builder._resetProject(source, {"name": "Copy", "author": ""}) is False
    assert lockFile.is_file()


@pytest.mark.core
def testCoreTools_DocxImporterOverwrite(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that an existing project can be replaced by an import."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [("Chapter One", "Heading1"), ("Some text.", None)],
        title="New Novel",
        author="Jane Doe",
    )

    # Create an existing project in the target folder
    target = fncPath / "existing"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Old Novel", "author": "John Doe"})
    oldFile = target / nwFiles.PROJ_FILE
    assert oldFile.is_file()

    # Without the overwrite flag, the import must fail
    importer = DocxImporter()
    assert importer.importFile(docxPath, target) is False
    assert importer.error != ""
    assert oldFile.is_file()

    # If building the replacement fails, the old project must be preserved
    importer = DocxImporter()
    monkeypatch.setattr(importer, "_buildProject", lambda *a: False)
    assert importer.importFile(docxPath, target, overwrite=True) is False
    assert oldFile.is_file()

    # With the overwrite flag, the project must be replaced
    importer = DocxImporter()
    assert importer.importFile(docxPath, target, overwrite=True) is True
    assert importer.error == ""
    assert importer.projectPath == target
    assert (target / nwFiles.PROJ_FILE).is_file()

    # The recent-project entry must point to the final path and contain the
    # new project's metadata, not the temporary build path.
    recentEntries = CONFIG.recentProjects.listEntries()
    assert str(target) in [entry[0] for entry in recentEntries]
    assert all(".umbraedit-import-" not in entry[0] for entry in recentEntries)
    targetEntry = next(entry for entry in recentEntries if entry[0] == str(target))
    assert targetEntry[1] == "New Novel"

    # The new project must have replaced the old one
    project = NWProject()
    assert project.openProject(target) is True
    assert project.data.name == "New Novel"
    assert project.data.author == "Jane Doe"
    project.closeProject()


@pytest.mark.core
def testCoreTools_DocxImporterOverwriteRollback(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that a failed import replacement preserves the old project."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [("Chapter One", "Heading1"), ("Some text.", None)],
        title="New Novel",
    )

    target = fncPath / "existing"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Old Novel", "author": ""})
    oldFile = target / nwFiles.PROJ_FILE
    assert oldFile.is_file()

    originalRename = Path.rename

    def failReplacement(self: Path, path: str | Path) -> Path:
        if self.name.startswith(".umbraedit-import-"):
            raise OSError("Replacement failed")
        return originalRename(self, path)

    monkeypatch.setattr(Path, "rename", failReplacement)
    importer = DocxImporter()
    assert importer.importFile(docxPath, target, overwrite=True) is False
    assert importer.error != ""
    assert oldFile.is_file()

    project = NWProject()
    assert project.openProject(target) is True
    assert project.data.name == "Old Novel"
    project.closeProject()


@pytest.mark.core
def testCoreTools_DocxImporterOverwriteSymlink(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that an import cannot replace the target of a symbolic link."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [("Chapter One", "Heading1"), ("Some text.", None)],
    )

    referent = fncPath / "referent"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(referent), "name": "Referent", "author": ""})
    referentFile = referent / nwFiles.PROJ_FILE

    link = fncPath / "link"
    try:
        link.symlink_to(referent, target_is_directory=True)
    except OSError:  # pragma: no cover
        pytest.skip("Symbolic links are not supported on this platform")

    importer = DocxImporter()
    assert importer.importFile(docxPath, link, overwrite=True) is False
    assert importer.error != ""
    assert referentFile.is_file()
    assert link.is_symlink()


@pytest.mark.core
def testCoreTools_DocxImporterOverwriteLocked(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test that a locked project cannot be replaced by an import."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [("Chapter One", "Heading1"), ("Some text.", None)],
    )

    target = fncPath / "existing"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Old Novel", "author": ""})
    oldFile = target / nwFiles.PROJ_FILE
    (target / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")

    importer = DocxImporter()
    assert importer.importFile(docxPath, target, overwrite=True) is False
    assert importer.error != ""
    assert oldFile.is_file()


@pytest.mark.core
def testCoreTools_ScanProjectFolder(
    fncPath: Path,
    mockGUI: MockGuiMain,
):
    """Test scanning a folder for UmbraEdit projects."""
    root = fncPath / "projects"
    root.mkdir()

    # A folder that does not exist has no projects
    assert scanProjectFolder(fncPath / "missing") == []

    # An empty path must not scan the current working directory
    assert scanProjectFolder("") == []
    assert scanProjectFolder(Path()) == []

    # An empty folder has no projects
    assert scanProjectFolder(root) == []

    # A folder with a project
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(root / "Project One"), "name": "Project One", "author": ""})
    assert builder.buildProject({"path": str(root / "Project Two"), "name": "Project Two", "author": ""})

    # A folder that is not a project is ignored
    (root / "Not A Project").mkdir()
    (root / "Not A Project" / "readme.txt").write_text("Nope", encoding="utf-8")

    # A file is ignored
    (root / "notes.txt").write_text("Nope", encoding="utf-8")

    # A symbolic link to a project is ignored
    outside = fncPath / "outside"
    assert builder.buildProject({"path": str(outside), "name": "Outside", "author": ""})
    try:
        (root / "Linked Project").symlink_to(outside, target_is_directory=True)
        linkedFile = root / "Linked File Project"
        linkedFile.mkdir()
        (linkedFile / nwFiles.PROJ_FILE).symlink_to(outside / nwFiles.PROJ_FILE)
    except OSError:  # pragma: no cover
        pytest.skip("Symbolic links are not supported on this platform")

    # A folder with only a symbolic link to a project file is ignored
    assert not isValidProjectFolder(root / "Linked File Project")

    projects = scanProjectFolder(root)
    assert len(projects) == 2
    assert [p.path.name for p in projects] == ["Project One", "Project Two"]
    assert [p.name for p in projects] == ["Project One", "Project Two"]
    assert all(p.time > 0 for p in projects)

    # The project name is read from the project file
    assert readProjectName(root / "Project One" / nwFiles.PROJ_FILE) == "Project One"

    # A file that is not a project file has no name
    assert readProjectName(root / "notes.txt") == ""
    assert readProjectName(root / "missing" / nwFiles.PROJ_FILE) == ""

    # A project with an unreadable project file falls back to the folder name
    brokenRoot = fncPath / "broken"
    brokenRoot.mkdir()
    broken = brokenRoot / "Broken Project"
    broken.mkdir()
    (broken / nwFiles.PROJ_FILE).write_text("Not a project file", encoding="utf-8")
    brokenProjects = scanProjectFolder(brokenRoot)
    assert len(brokenProjects) == 1
    assert brokenProjects[0].name == "Broken Project"


@pytest.mark.core
def testCoreTools_ProjectLockDetection(fncPath: Path):
    """Test that malformed and descendant locks are treated as locked."""
    target = fncPath / "target"
    target.mkdir()
    assert readProjectLock(target) is None
    assert containsProjectLock(target) is False

    # A lock path with the wrong type is malformed and must block replacement
    (target / nwFiles.PROJ_LOCK).mkdir()
    assert readProjectLock(target) is not None
    assert containsProjectLock(target) is True

    # A lock in a descendant project also blocks replacement of its parent
    nested = fncPath / "nested"
    nested.mkdir()
    child = nested / "child"
    child.mkdir()
    (child / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")
    assert containsProjectLock(nested) is True
