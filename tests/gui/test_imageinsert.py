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
from zipfile import ZipFile

import PIL.Image
import pytest

from PyQt6.QtGui import QAction, QTextCursor
from PyQt6.QtWidgets import QFileDialog, QInputDialog
from pytestqt.qtbot import QtBot

from umbraedit import CONFIG, SHARED
from umbraedit.constants import nwKeyWords
from umbraedit.core.imageimport import ImageImportError, ImageImportReason, importProjectImage
from umbraedit.core.imagemeta import MAX_IMAGE_DIMENSION
from umbraedit.core.project import NWProject
from umbraedit.guimain import GuiMain
from umbraedit.types import QtKeepAnchor, QtMoveAnchor

from tests.helpers import C, MockRnd, buildTestProject


def _writeImage(
    path: Path,
    imageFormat: str = "PNG",
    size: tuple[int, int] = (4, 4),
) -> None:
    """Write a small valid test image."""
    path.parent.mkdir(parents=True, exist_ok=True)
    PIL.Image.new("RGB", size, (20, 40, 60)).save(path, format=imageFormat)


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
    assert nwKeyWords.IMAGE_KEY in nwKeyWords.VALID_KEYS
    assert nwKeyWords.IMAGE_KEY in nwKeyWords.META_KEYS
    assert nwKeyWords.IMAGE_KEY not in nwKeyWords.ALL_KEYS

    menu = nwGUI.mainMenu
    assert menu.aImageAssets.text() == "Image Assets"
    assert menu.aImageAssets in menu.viewMenu.actions()
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
    assert nwGUI.imageAssets.imageList.count() == 1
    coverItem = nwGUI.imageAssets.imageList.currentItem()
    assert coverItem is not None
    assert coverItem.text() == "cover.png"

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
    assert nwGUI.imageAssets.imageList.count() == 2
    iconItem = nwGUI.imageAssets.imageList.currentItem()
    assert iconItem is not None
    assert iconItem.text() == "cover_1.png"


@pytest.mark.gui
def testImageInsert_BackupIncludesUnsavedMetadataAndAsset(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a manual backup flushes image metadata before archiving."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(4)

    source = fncPath / "cover.png"
    _writeImage(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert editor.docChanged is True

    backupPath = fncPath / "backups"
    backupPath.mkdir(parents=True)
    CONFIG.setBackupPath(backupPath)
    assert nwGUI.backupProject() is True

    archives = list(backupPath.rglob("*.zip"))
    assert len(archives) == 1
    with ZipFile(archives[0]) as archive:
        names = set(archive.namelist())
        assert "assets/img/cover.png" in names
        document = archive.read(f"content/{C.hSceneDoc}.md").decode("utf-8")
    assert "@Cover: assets/img/cover.png" in document


@pytest.mark.gui
def testImageInsert_SaveAsIncludesUnsavedMetadataAndAsset(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that Save As flushes image metadata before copying the project."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(4)

    source = fncPath / "cover.png"
    _writeImage(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert editor.docChanged is True

    target = fncPath / "image-project-copy"
    monkeypatch.setattr(SHARED, "getProjectFolder", lambda *args: str(target))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Image Copy", True))
    nwGUI.saveProjectAs()

    assert target.is_dir()
    assert (target / "assets" / "img" / "cover.png").is_file()
    document = (target / "content" / f"{C.hSceneDoc}.md").read_text(encoding="utf-8")
    assert "@Cover: assets/img/cover.png" in document


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
    monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 10)
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

    def failCleanup(*args, **kwargs):
        raise OSError("Cleanup failed")

    with monkeypatch.context() as mp:
        mp.setattr("umbraedit.editor.docpanes.removeImportedProjectImage", failCleanup)
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
def testImageInsert_ReplacementAfterImportAbortsInsertion(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a replaced imported image is not referenced in the document."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Text")
    editor.setCursorPosition(4)

    source = fncPath / "cover.png"
    _writeImage(source)

    def importThenReplace(project, path):
        imported = importProjectImage(project, path)
        imported.path.unlink()
        imported.path.write_bytes(b"replacement")
        return imported

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    monkeypatch.setattr("umbraedit.editor.docpanes.importProjectImage", importThenReplace)
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    assert editor.getText() == "Text"
    assert editor.getCursorPosition() == 4
    assert SHARED.lastAlert[0] == (
        "The active project or document changed while importing the image. Please try again."
    )
    assert (projPath / "assets" / "img" / "cover.png").read_bytes() == b"replacement"


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
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that image imports require a project and fall back to a document."""
    source = fncPath / "cover.png"
    _writeImage(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)
    assert SHARED.lastAlert[0] == "Please open a project before importing an image."

    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    nwGUI.docPanes.closeDocument()
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    assert nwGUI.docEditor.docHandle is not None
    assert nwGUI.docEditor.getText().endswith("@Cover: assets/img/cover.png")
    assert (projPath / "assets" / "img" / "cover.png").is_file()


@pytest.mark.gui
def testImageAssets_AddAndSelect(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that Add stores an asset and Select inserts it at the cursor."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("beforeafter")
    editor.setCursorPosition(6)

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    assert manager.isHidden() is True
    nwGUI.mainMenu.aImageAssets.activate(QAction.ActionEvent.Trigger)
    assert manager.isVisible() is True
    assert nwGUI.mainMenu.aImageAssets.isChecked() is True

    manager.addButton.click()
    assert manager.imageList.count() == 1
    assert manager.imageList.currentRow() == 0
    listItem = manager.imageList.item(0)
    assert listItem is not None
    assert listItem.text() == "landscape.png"
    assert listItem.icon().isNull() is False
    assert (projPath / "assets" / "img" / "landscape.png").is_file()
    assert editor.getText() == "beforeafter"

    manager.widthSpin.setValue(80)
    assert manager.heightSpin.value() == 40
    manager.positionCombo.setCurrentIndex(manager.positionCombo.findData("right"))
    manager.selectButton.click()

    assert editor.getText() == (
        "before\n@Image: assets/img/landscape.png | width=80 | height=40 | position=right\nafter"
    )
    editor.undo()
    assert editor.getText() == "beforeafter"


@pytest.mark.gui
def testImageInsert_CancelWithoutDocumentDoesNotOpenOne(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    mockRnd: MockRnd,
):
    """Test that cancelling an image import does not open a fallback document."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    nwGUI.docPanes.closeDocument()
    assert nwGUI.docEditor.docHandle is None

    lastAlert = SHARED.lastAlert
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    nwGUI.mainMenu.aInsCover.activate(QAction.ActionEvent.Trigger)

    assert nwGUI.docEditor.docHandle is None
    assert not (projPath / "assets" / "img").exists()
    assert SHARED.lastAlert == lastAlert


@pytest.mark.gui
def testImageAssets_SizeLimitPreservesAspectRatio(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that linked dimensions remain bounded without being distorted."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True

    source = fncPath / "tall.png"
    _writeImage(source, size=(100, 10000))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()
    manager.widthSpin.setValue(MAX_IMAGE_DIMENSION)

    # A 100 x 10000 image can use at most 1000 x 100000 pixels while
    # retaining its aspect ratio and staying within the shared bounds.
    assert manager.widthSpin.value() == 1000
    assert manager.heightSpin.value() == MAX_IMAGE_DIMENSION


@pytest.mark.gui
def testImageAssets_RefreshRecalculatesChangedAspectRatio(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that changed image contents keep the saved width and aspect ratio."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()
    manager.widthSpin.setValue(80)
    assert manager.heightSpin.value() == 40

    assetPath = projPath / "assets" / "img" / "landscape.png"
    PIL.Image.new("RGB", (20, 40), (20, 40, 60)).save(assetPath, format="PNG")
    manager.refreshAssets()

    assert manager.widthSpin.value() == 80
    assert manager.heightSpin.value() == 160


@pytest.mark.gui
def testImageAssets_AddCancellationIsDocumentNeutral(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    mockRnd: MockRnd,
):
    """Test that cancelling Add leaves both the project and document unchanged."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("Unchanged document")
    editor.setCursorPosition(4)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()

    assert manager.imageList.count() == 0
    assert editor.getText() == "Unchanged document"
    assert editor.getCursorPosition() == 4
    assert not (projPath / "assets" / "img").exists()


@pytest.mark.gui
def testImageAssets_DeleteChecksDocumentReferences(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that referenced assets cannot be deleted from the manager."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()
    manager.selectButton.click()
    assetPath = projPath / "assets" / "img" / "landscape.png"
    assert "@Image: assets/img/landscape.png" in nwGUI.docEditor.getText()

    manager.deleteButton.click()
    assert SHARED.lastAlert[0] == "The selected image is referenced by a document and cannot be deleted."
    assert assetPath.is_file()

    nwGUI.docEditor.setPlainText("No image reference")
    manager.deleteButton.click()
    assert assetPath.exists() is False
    assert manager.imageList.count() == 0


@pytest.mark.gui
def testImageAssets_DeleteProtectsCaseEquivalentReference(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a case-equivalent path protects an asset on case-insensitive systems."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()
    assetPath = projPath / "assets" / "img" / "landscape.png"
    upperPath = assetPath.with_name("LANDSCAPE.png")
    if not upperPath.exists():
        pytest.skip("The file system is case-sensitive")

    nwGUI.docEditor.setPlainText("@Image: assets/img/LANDSCAPE.png | width=40 | height=20 | position=center")
    manager.deleteButton.click()

    assert SHARED.lastAlert[0] == "The selected image is referenced by a document and cannot be deleted."
    assert assetPath.is_file()


@pytest.mark.gui
def testImageAssets_DeleteFindsNewNonNovelDocumentReference(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that deletion checks documents added after the tree cache was built."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    # Populate the cached novel document list before adding a document
    # below a non-novel root.
    assert C.hSceneDoc in SHARED.project.tree.allDocs()
    newHandle = SHARED.project.newFile("Character Notes", C.hCharRoot)
    assert isinstance(newHandle, str)
    newDocument = SHARED.project.storage.getDocument(newHandle)
    assert (
        newDocument.writeDocument("@Image: assets/img/landscape.png | width=40 | height=20 | position=center\n") is True
    )

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()
    manager.deleteButton.click()

    assert SHARED.lastAlert[0] == "The selected image is referenced by a document and cannot be deleted."
    assert (projPath / "assets" / "img" / "landscape.png").is_file()


@pytest.mark.gui
def testImageAssets_DeleteRechecksReferencesAfterConfirmation(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that a reference added during confirmation prevents deletion."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    manager = nwGUI.imageAssets
    manager.addButton.click()

    def confirmDelete(*args, **kwargs):
        nwGUI.docEditor.setPlainText("@Image: assets/img/landscape.png | width=40 | height=20 | position=center")
        return True

    monkeypatch.setattr(SHARED, "question", confirmDelete)
    manager.deleteButton.click()

    assert SHARED.lastAlert[0] == "The selected image is referenced by a document and cannot be deleted."
    assert (projPath / "assets" / "img" / "landscape.png").is_file()


@pytest.mark.gui
def testImageAssets_SelectFallsBackToDocumentBottom(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that selecting without an active document inserts at the bottom."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))

    nwGUI.imageAssets.addButton.click()
    nwGUI.docPanes.closeDocument()
    nwGUI.imageAssets.selectButton.click()

    assert nwGUI.docEditor.docHandle is not None
    assert nwGUI.docEditor.getText().endswith(
        "@Image: assets/img/landscape.png | width=40 | height=20 | position=center"
    )


@pytest.mark.gui
def testImageAssets_FocusModeRestoresVisibility(
    nwGUI: GuiMain,
    projPath: Path,
    mockRnd: MockRnd,
):
    """Test that Focus Mode hides the manager and restores its visibility."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    nwGUI.mainMenu.aImageAssets.activate(QAction.ActionEvent.Trigger)
    assert nwGUI.imageAssets.isVisible() is True

    nwGUI.toggleFocusMode()
    assert nwGUI.imageAssets.isVisible() is False
    assert nwGUI.mainMenu.aImageAssets.isChecked() is False

    SHARED.setFocusMode(False)
    assert nwGUI.imageAssets.isVisible() is True
    assert nwGUI.mainMenu.aImageAssets.isChecked() is True


@pytest.mark.gui
def testImageInsert_FormattedViewShowsCurrentDocument(
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
):
    """Test that the editor header opens the current document in the viewer."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    source = fncPath / "landscape.png"
    _writeImage(source, size=(40, 20))
    imported = importProjectImage(SHARED.project, source)

    editor = nwGUI.docEditor
    editor.setPlainText(
        f"### Scene\n\nFormatted text\n@Image: {imported.relativePath} | width=80 | height=40 | position=center"
    )
    header = editor.docHeader
    assert header.outerBox.indexOf(header.minmaxButton) < header.outerBox.indexOf(header.formattedButton)
    assert header.outerBox.indexOf(header.formattedButton) < header.outerBox.indexOf(header.closeButton)

    # Point the viewer at another document first. The formatted action
    # must still save and show the current editor document.
    nwGUI.docPanes.viewDocument(C.hChapterDoc)
    assert nwGUI.docViewer.docHandle == C.hChapterDoc

    header.formattedButton.click()
    assert nwGUI.docViewer.docHandle == C.hSceneDoc
    assert nwGUI.docPanes.splitView.isVisible() is True
    assert "Formatted text" in nwGUI.docViewer.toPlainText()

    imageFound = False
    viewerDocument = nwGUI.docViewer.document()
    assert viewerDocument is not None
    block = viewerDocument.firstBlock()
    while block.isValid():
        cursor = QTextCursor(block)
        cursor.setPosition(block.position())
        if cursor.charFormat().isImageFormat():
            imageFound = True
            imageFormat = cursor.charFormat().toImageFormat()
            assert (round(imageFormat.width()), round(imageFormat.height())) == (80, 40)
            break
        block = block.next()
    assert imageFound is True


@pytest.mark.gui
@pytest.mark.parametrize(
    ("actionName", "metadata"),
    [
        ("aInsCover", "@Cover: assets/img/cover.png"),
        ("aInsIcon", "@icon: assets/img/cover.png"),
    ],
)
def testImageInsert_BookImagesAreNotInsertedAboveHeading(
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    projPath: Path,
    fncPath: Path,
    mockRnd: MockRnd,
    actionName: str,
    metadata: str,
):
    """Test that Cover and Icon metadata are placed below the first heading."""
    buildTestProject(NWProject(), projPath)
    assert nwGUI.openProject(projPath) is True
    assert nwGUI.docPanes.openDocument(C.hSceneDoc) is True

    editor = nwGUI.docEditor
    editor.setPlainText("### Scene\nText")
    editor.setCursorPosition(0)

    source = fncPath / "cover.png"
    _writeImage(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    action = getattr(nwGUI.mainMenu, actionName)
    action.activate(QAction.ActionEvent.Trigger)

    assert editor.getText() == f"### Scene\n{metadata}\nText"
