"""
UmbraEdit - Project Document Tests
====================================

This file is a part of UmbraEdit.

Copyright (C) 2020 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import os

from pathlib import Path
from typing import Any

import pytest

from umbraedit.core import safeio
from umbraedit.core.document import MAX_META_LINES, DocumentMeta, ProjectDocument
from umbraedit.core.project import NWProject
from umbraedit.enum import nwItemClass, nwItemLayout
from umbraedit.formats.tomlparser import NTomlParser

from tests.helpers import MOCK_TIME, C, MockRnd, buildTestProject, readFile, writeFile
from tests.mocked import MockGuiMain, causeOSError


@pytest.mark.core
def testProjectDocument_LoadSave(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test loading and saving a document with the ProjectDocument class."""
    monkeypatch.setattr("umbraedit.core.document.time", lambda: MOCK_TIME)

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    # Read Document
    # =============

    # Not a valid handle
    doc = ProjectDocument(project, "stuff")
    assert bool(doc) is False
    assert doc.readDocument() is None
    assert doc.fileExists() is False
    assert doc.hashError is False
    assert doc.createdDate == "Unknown"
    assert doc.updatedDate == "Unknown"

    # Non-existent handle
    doc = ProjectDocument(project, C.hInvalid)
    assert doc.readDocument() is None
    assert doc._lastHash == ""
    assert doc.fileExists() is False

    # No content path
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.contentPath", property(lambda *a: None))
        doc = ProjectDocument(project, C.hSceneDoc)
        assert doc.readDocument() is None
        assert doc.fileExists() is False

    # Cause open() to fail while loading
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.document.openRegularFile", causeOSError)
        doc = ProjectDocument(project, C.hSceneDoc)
        assert doc.fileExists() is True
        assert doc.readDocument() is None
        assert doc.error == "OSError: Mock OSError"

    # Load the text
    doc = ProjectDocument(project, C.hSceneDoc)
    assert doc.fileExists() is True
    assert doc.readDocument() == "### New Scene\n\n"

    # Try to open a new (non-existent) file
    xHandle = project.newFile("New File", C.hNovelRoot)
    assert xHandle is not None
    doc = ProjectDocument(project, xHandle)
    assert bool(doc) is True
    assert repr(doc) == f"<ProjectDocument handle={xHandle}>"
    assert doc.readDocument() == ""

    # Write Document
    # ==============

    # No content path
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.contentPath", property(lambda *a: None))
        doc = ProjectDocument(project, xHandle)
        assert doc.writeDocument("") is False

    # Set handle and save
    text = "### Test File\n\nText ...\n\n"
    doc = ProjectDocument(project, xHandle)
    assert doc.writeDocument(text) is True

    # Save again to ensure temp file and previous file is handled
    assert doc.writeDocument(text) is True

    # Check file content
    docPath = fncPath / "content" / f"{xHandle}.md"
    assert readFile(docPath) == (
        "+++\n"
        'name = "New File"\n'
        f'parent = "{C.hNovelRoot}"\n'
        f'handle = "{xHandle}"\n'
        'class = "NOVEL"\n'
        'layout = "DOCUMENT"\n'
        'textHash = "b288c3ab03181027d9a16d7fd2291262f5de9ac8"\n'
        'createdDate = "2019-05-10 18:52:00"\n'
        'updatedDate = "2019-05-10 18:52:00"\n'
        "+++\n"
        "### Test File\n\n"
        "Text ...\n\n"
    )

    # Touch the document on disk without changing its content
    stat = docPath.stat()
    touched = stat.st_mtime_ns + 10_000_000_000
    os.utime(docPath, ns=(touched, touched))
    assert doc.writeDocument(text) is True

    # Alter the document on disk and save again
    writeFile(docPath, "blablabla")
    assert doc.writeDocument(text) is False

    # Force the overwrite
    assert doc.writeDocument(text, forceWrite=True) is True

    # Delete the document on disk and save again
    docPath.unlink()
    assert doc.writeDocument(text) is False

    # Force the overwrite to restore the file
    assert doc.writeDocument(text, forceWrite=True) is True

    # Force no meta data
    doc._item = None
    assert doc.writeDocument(text) is True
    assert readFile(docPath) == text

    # Cause open() to fail while saving
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.document.writeFileAtomic", causeOSError)
        assert doc.writeDocument(text) is False
        assert doc.error == "OSError: Mock OSError"

    doc._error = ""
    assert doc.error == ""

    # Cause publication to fail while saving
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.safeio.renameNoReplaceBetween", causeOSError)
        mp.setattr("umbraedit.core.safeio.renameNoReplace", causeOSError)
        assert doc.writeDocument(text) is False
        assert doc.error == "OSError: Mock OSError"

    doc._error = ""
    assert doc.error == ""

    # Saving with no handle
    doc._handle = None
    assert doc.writeDocument(text) is False

    # Cause stat() to fail right after a successful write
    origLstat = os.lstat
    published = False

    def markPublished(*args: Any, **kwargs: Any):
        nonlocal published
        result = safeio.writeFileAtomic(*args, **kwargs)
        published = True
        return result

    def failDocStat(path: Path, *a: Any, **kw: Any) -> os.stat_result:
        if published and path == docPath:
            raise OSError("Mock OSError")
        return origLstat(path, *a, **kw)

    doc = ProjectDocument(project, xHandle)
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.document.writeFileAtomic", markPublished)
        mp.setattr(os, "lstat", failDocStat)
        assert doc.writeDocument("Stat Failure") is True
        assert doc._lastStat is None

    # Trailing line break
    doc = ProjectDocument(project, xHandle)
    assert doc.writeDocument("") is True
    assert doc.readDocument() == ""
    assert doc.writeDocument("Stuff") is True
    assert doc.readDocument() == "Stuff\n"
    assert doc.writeDocument("Stuff\n") is True
    assert doc.readDocument() == "Stuff\n"
    assert doc.writeDocument("Stuff\n\n") is True
    assert doc.readDocument() == "Stuff\n\n"

    # Control characters are stripped on read. See #3038.
    assert doc.writeDocument("Some\x00text\x01with control chars") is True
    assert doc.readDocument() == "Sometextwith control chars\n"

    # Quick Read
    # ==========

    doc = ProjectDocument(project, xHandle)
    assert doc.writeDocument("### Test File\n\nText ...\n\n") is True

    contPath = fncPath / "content"
    assert ProjectDocument.quickReadText(contPath, xHandle) == ("### Test File\n\nText ...\n\n")

    # Check read text fallback
    assert ProjectDocument.quickReadText(contPath, "0000000000000") == ""
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.document.openRegularFile", causeOSError)
        assert ProjectDocument.quickReadText(contPath, xHandle) == ""

    # A missing closing +++ is treated as having no header at all
    noClose = '+++\nname = "Test"\n### Chapter 1\n\nSome real body text.\n'
    (contPath / f"{xHandle}.md").write_text(noClose, encoding="utf-8")
    assert ProjectDocument.quickReadText(contPath, xHandle) == noClose

    doc = ProjectDocument(project, xHandle)
    assert doc.readDocument() == noClose

    # Same, but exceeding the max meta lines first
    noCloseLong = "+++\n" + "".join(f"meta{i} = 1\n" for i in range(MAX_META_LINES + 5))
    (contPath / f"{xHandle}.md").write_text(noCloseLong, encoding="utf-8")
    assert ProjectDocument.quickReadText(contPath, xHandle) == noCloseLong

    # Malformed meta values are parsed defensively and otherwise ignored
    doc._meta = DocumentMeta()
    parser = NTomlParser(flat=True)
    parser.readString('parent = "notahandle"\nhandle = "alsonotahandle"\nclass = "BADCLASS"\nlayout = "BADLAYOUT"\n')
    doc._applyMeta(parser)
    assert doc._meta == DocumentMeta()

    # Delete Document
    # ===============

    # Delete a non-existing document
    doc = ProjectDocument(project, "stuff")
    assert doc.deleteDocument() is False
    assert docPath.exists()

    # No content path
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.storage.ProjectStorage.contentPath", property(lambda *a: None))
        doc = ProjectDocument(project, xHandle)
        assert doc.deleteDocument() is False

    # Cause the delete to fail
    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.core.document.unlinkIfSameFile", causeOSError)
        doc = ProjectDocument(project, xHandle)
        assert doc.deleteDocument() is False
        assert doc.error == "OSError: Mock OSError"

    # Make the delete pass
    doc = ProjectDocument(project, xHandle)
    assert doc.deleteDocument() is True
    assert not docPath.exists()


@pytest.mark.core
def testProjectDocument_NormalisesLineEndings(
    monkeypatch: pytest.MonkeyPatch,
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that project documents use LF line endings on every platform."""
    # The legacy preference must not change the canonical on-disk format
    # of project documents.
    monkeypatch.setattr("umbraedit.CONFIG.forceUnixLineEndings", False)
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    docPath = fncPath / "content" / f"{C.hSceneDoc}.md"
    docPath.write_bytes(b"First line\r\nSecond line\rThird line")

    doc = ProjectDocument(project, C.hSceneDoc)
    assert doc.readDocument() == "First line\nSecond line\nThird line"
    assert ProjectDocument.quickReadText(fncPath / "content", C.hSceneDoc) == ("First line\nSecond line\nThird line")

    assert doc.writeDocument("First line\nSecond line\n") is True
    payload = docPath.read_bytes()
    assert b"\r\n" not in payload
    assert b"\r" not in payload
    assert payload.endswith(b"First line\nSecond line\n")


@pytest.mark.core
def testProjectDocument_RejectsSymlinkedFile(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that document reads and writes never follow a linked file."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    docPath = fncPath / "content" / f"{C.hSceneDoc}.md"
    outside = fncPath / "outside-document.md"
    outside.write_text("outside data", encoding="utf-8")
    docPath.unlink()
    try:
        os.symlink(outside, docPath)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    doc = ProjectDocument(project, C.hSceneDoc)
    assert doc.readDocument() is None
    assert doc.writeDocument("replacement") is False
    assert outside.read_text(encoding="utf-8") == "outside data"
    assert docPath.is_symlink()


@pytest.mark.core
def testProjectDocument_RejectsConcurrentReplacement(
    mockGUI: MockGuiMain,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a document replacement is preserved between read and write."""
    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    docPath = fncPath / "content" / f"{C.hSceneDoc}.md"
    originalStat = docPath.stat()
    originalBytes = docPath.read_bytes()
    doc = ProjectDocument(project, C.hSceneDoc)
    assert doc.readDocument() == "### New Scene\n\n"

    replacement = fncPath / "replacement.md"
    replacement.write_bytes(originalBytes)
    os.utime(replacement, ns=(originalStat.st_atime_ns, originalStat.st_mtime_ns))
    docPath.unlink()
    replacement.replace(docPath)

    assert doc.writeDocument("replacement text") is False
    assert docPath.read_bytes() == originalBytes


@pytest.mark.core
def testProjectDocument_Methods(monkeypatch: pytest.MonkeyPatch, mockGUI: MockGuiMain, fncPath: Path, mockRnd: MockRnd):
    """Test other methods of the ProjectDocument class."""
    monkeypatch.setattr("umbraedit.core.document.time", lambda: MOCK_TIME)

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    doc = ProjectDocument(project, C.hSceneDoc)
    docPath = fncPath / "content" / f"{C.hSceneDoc}.md"

    assert doc.readDocument() == "### New Scene\n\n"

    # Check location
    assert doc.fileLocation == str(docPath)

    # Check the item
    assert doc.nwItem is not None
    assert doc.nwItem.itemHandle == C.hSceneDoc  # type: ignore

    # Check the meta
    assert doc.meta.name == "New Scene"
    assert doc.meta.parent == C.hChapterDir
    assert doc.meta.itemClass == nwItemClass.NOVEL
    assert doc.meta.itemLayout == nwItemLayout.DOCUMENT

    # Old-style meta lines in the body are preserved verbatim
    assert doc.writeDocument("%%~ stuff\n### Test File\n\nText ...\n\n")
    assert readFile(docPath) == (
        "+++\n"
        'name = "New Scene"\n'
        f'parent = "{C.hChapterDir}"\n'
        f'handle = "{C.hSceneDoc}"\n'
        'class = "NOVEL"\n'
        'layout = "DOCUMENT"\n'
        'textHash = "dd350c602de803554b2a7c17f191ae25dea1df63"\n'
        'createdDate = "2019-05-10 18:52:00"\n'
        'updatedDate = "2019-05-10 18:52:00"\n'
        "+++\n"
        "%%~ stuff\n"
        "### Test File\n\n"
        "Text ...\n\n"
    )

    assert doc.readDocument() == "%%~ stuff\n### Test File\n\nText ...\n\n"
