"""
UmbraEdit - Image Insert Tests
==============================

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

from pathlib import Path

import PIL.Image
import pytest

from PyQt6.QtGui import QAction, QTextCursor
from PyQt6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from umbraedit import CONFIG, SHARED
from umbraedit.constants import nwKeyWords
from umbraedit.core.imageimport import ImageImportError, ImageImportReason
from umbraedit.core.project import NWProject
from umbraedit.guimain import GuiMain
from umbraedit.types import QtKeepAnchor, QtMoveAnchor

from tests.helpers import C, MockRnd, buildTestProject


def _writeImage(path: Path, imageFormat: str = "PNG") -> None:
    """Write a small valid test image."""
    path.parent.mkdir(parents=True, exist_ok=True)
    PIL.Image.new("RGB", (4, 4), (20, 40, 60)).save(path, format=imageFormat)


@pytest.mark.gui
def testImageInsert_MenuStructure(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    mockRnd: MockRnd,
):
    """Test that the Images submenu exposes Cover and Icon actions."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True

    assert nwKeyWords.ICON_KEY in nwKeyWords.VALID_KEYS
    assert nwKeyWords.ICON_KEY in nwKeyWords.META_KEYS
    assert nwKeyWords.ICON_KEY not in nwKeyWords.ALL_KEYS

    menu = nwGUI.mainMenu
    assert menu.mInsImages.title() == "Images"
    assert [action.text() for action in menu.mInsImages.actions()] == ["Cover", "Icon"]
    assert "Icon" not in [action.text() for action in menu.mInsKeywords.actions()]

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))

    with qtbot.waitSignal(menu.requestImageInsert, timeout=1000) as signal:
        menu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert signal.args == [nwKeyWords.COVER_KEY]

    with qtbot.waitSignal(menu.requestImageInsert, timeout=1000) as signal:
        menu.aInsIcon.activate(QAction.ActionEvent.Trigger)
    assert signal.args == [nwKeyWords.ICON_KEY]


@pytest.mark.gui
def testImageInsert_ImportCoverAndIcon(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test importing images and inserting undoable metadata tags."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(4)

    source = fncPath / "cover.png"
    _writeImage(source)
    filters = []

    def selectImage(*args, **kwargs):
        filters.append(kwargs.get("filter", ""))
        return str(source), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", selectImage)

    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert editor.getText() == "Text\n@Cover: assets/img/cover.png"
    assert (projPath / "assets" / "img" / "cover.png").is_file()
    assert editor.textCursor().position() == len(editor.getText())
    assert filters == ["JPEG images (*.jpg);;PNG images (*.png)"]

    # The image tag is one undoable edit block.
    editor.undo()
    assert editor.getText() == "Text"
    assert (projPath / "assets" / "img" / "cover.png").is_file()

    editor.redo()
    assert editor.getText() == "Text\n@Cover: assets/img/cover.png"
    assert (projPath / "assets" / "img" / "cover.png").is_file()
    editor.undo()

    nwGUI.mainMenu.aInsIcon.activate(QAction.ActionEvent.Trigger)
    assert editor.getText() == "Text\n@icon: assets/img/cover_1.png"
    assert (projPath / "assets" / "img" / "cover_1.png").is_file()


@pytest.mark.gui
def testImageInsert_ExactCursor(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that an image tag is inserted at the captured cursor position."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("beforeafter")
    editor.setCursorPosition(6)

    source = fncPath / "cover.png"
    _writeImage(source)

    def selectImage(*args, **kwargs):
        # Simulate the editor losing its cursor position while the
        # modal file chooser is open.
        editor.setCursorPosition(0)
        return str(source), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", selectImage)
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    assert editor.getText() == "before\n@Cover: assets/img/cover.png\nafter"
    assert editor.textCursor().blockNumber() == 1
    assert editor.textCursor().block().text() == "@Cover: assets/img/cover.png"

    editor.undo()
    assert editor.getText() == "beforeafter"
    assert (projPath / "assets" / "img" / "cover.png").is_file()


@pytest.mark.gui
def testImageInsert_ExactCursorWithAstralCharacter(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that cursor offsets are handled correctly for non-BMP text."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("A😀B")
    editor.setCursorPosition(3)

    source = fncPath / "cover.png"
    _writeImage(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    assert editor.getText() == "A😀\n@Cover: assets/img/cover.png\nB"


@pytest.mark.gui
@pytest.mark.parametrize(("anchor", "position"), [(1, 3), (3, 1)])
def testImageInsert_CancelPreservesSelection(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    anchor: int,
    position: int,
    mockRnd: MockRnd,
):
    """Test that cancellation restores forward and backward selections."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    cursor = QTextCursor(editor.textCursor())
    cursor.setPosition(anchor, QtMoveAnchor)
    cursor.setPosition(position, QtKeepAnchor)
    editor.setTextCursor(cursor)

    def cancelImage(*args, **kwargs):
        editor.setCursorPosition(0)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", cancelImage)
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    restored = editor.textCursor()
    assert restored.anchor() == anchor
    assert restored.position() == position
    assert restored.selectedText() == "ex"
    assert editor.getText() == "Text"


@pytest.mark.gui
def testImageInsert_CancelAndInvalidImage(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test cancellation and invalid image feedback."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(2)
    lastAlert = SHARED.lastAlert

    def cancelImage(*args, **kwargs):
        editor.setCursorPosition(0)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", cancelImage)
    with qtbot.waitSignal(SHARED.projectStatusMessage, timeout=1000) as signal:
        nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert signal.args is not None
    assert signal.args[0] == "Image import cancelled. No changes were made."
    assert SHARED.lastAlert is lastAlert
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2

    invalid = fncPath / "invalid.png"
    invalid.write_bytes(b"not an image")

    def selectInvalid(*args, **kwargs):
        editor.setCursorPosition(0)
        return str(invalid), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", selectInvalid)
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "The selected file is not a valid JPG or PNG image."
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert not (projPath / "assets" / "img").exists()

    mismatch = fncPath / "mismatch.jpg"
    _writeImage(mismatch, "PNG")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(mismatch), ""))
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "The selected image format does not match its file extension."
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert not (projPath / "assets" / "img").exists()


@pytest.mark.gui
def testImageInsert_RejectsOversizedImage(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that oversized images are rejected with specific feedback."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(2)
    source = fncPath / "large.png"
    _writeImage(source)
    monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 1)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "The selected image is too large to import safely."
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert not (projPath / "assets" / "img").exists()


@pytest.mark.gui
def testImageInsert_CopyAndInsertionFailures(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that copy and insertion failures leave the document unchanged."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(2)

    source = fncPath / "cover.png"
    _writeImage(source)
    lastImagePath = CONFIG.lastPath("image")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    def failImport(*args, **kwargs):
        raise ImageImportError(ImageImportReason.WRITE_FAILED, "Copy failed")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.editor.docpanes.importProjectImage", failImport)
        nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "Could not copy the image into the project."
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert CONFIG.lastPath("image") == lastImagePath

    with monkeypatch.context() as mp:
        mp.setattr(editor, "insertMetaValue", lambda *args, **kwargs: False)
        nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "Could not insert the image reference into the document."
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert CONFIG.lastPath("image") == lastImagePath
    assert not (projPath / "assets" / "img" / "cover.png").exists()

    def raiseInsert(*args, **kwargs):
        raise RuntimeError("Insert failed")

    with monkeypatch.context() as mp:
        mp.setattr(editor, "insertMetaValue", raiseInsert)
        nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "Could not insert the image reference into the document."
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert CONFIG.lastPath("image") == lastImagePath
    assert not (projPath / "assets" / "img" / "cover.png").exists()

    targetPath = projPath / "assets" / "img" / "cover.png"
    realUnlink = Path.unlink

    def failUnlink(path, *args, **kwargs):
        if path == targetPath:
            raise OSError("Cleanup failed")
        return realUnlink(path, *args, **kwargs)

    with monkeypatch.context() as mp:
        mp.setattr("pathlib.Path.unlink", failUnlink)
        mp.setattr(editor, "insertMetaValue", lambda *args, **kwargs: False)
        nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == (
        "Could not insert the image reference into the document. The imported image could not be removed."
    )
    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 2
    assert CONFIG.lastPath("image") == lastImagePath
    assert targetPath.is_file()
    targetPath.unlink()


@pytest.mark.gui
def testImageInsert_ContextChangeAbortsImport(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a document change during the chooser aborts the import."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    source = fncPath / "cover.png"
    _writeImage(source)

    def changeDocument(*args, **kwargs):
        nwGUI.docPanes.closeDocument()
        return str(source), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", changeDocument)
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    assert SHARED.lastAlert[0] == ("The active project or document changed while selecting an image. Please try again.")
    assert not (projPath / "assets" / "img").exists()


@pytest.mark.gui
def testImageInsert_RequiresProjectAndDocument(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    mockRnd: MockRnd,
):
    """Test that image imports require an open project and document."""
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: pytest.fail("Dialog shown"))

    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "Please open a project before importing an image."

    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    nwGUI.docPanes.closeDocument()
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "Please open a document to import the image into."
