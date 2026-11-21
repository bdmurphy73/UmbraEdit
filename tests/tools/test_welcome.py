"""
UmbraEdit - Welcome Dialog Tests
==================================

This file is a part of UmbraEdit.

Copyright (C) 2023 Veronica Berglyd Olsen and UmbraEdit contributors.

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

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMenu
from pytestqt.qtbot import QtBot

from umbraedit import CONFIG, SHARED
from umbraedit.constants import nwFiles
from umbraedit.core.coretools import ProjectBuilder
from umbraedit.core.project import NWProject
from umbraedit.core.projectdata import ProjectData
from umbraedit.dialogs.projectconflict import GuiProjectConflict, ProjectConflictAction
from umbraedit.enum import nwItemClass
from umbraedit.guimain import GuiMain
from umbraedit.shared import _GuiAlert
from umbraedit.tools.welcome import SAMPLE_KEY, SAMPLE_NAME, GuiWelcome, _ProjectListEntry
from umbraedit.types import (
    QtAccessibleTextRole,
    QtDecorationRole,
    QtDisplayRole,
    QtFontRole,
    QtKeyDown,
    QtKeyLeft,
    QtKeyRight,
    QtKeyUp,
    QtMouseLeft,
    QtTextAlignmentRole,
    QtToolTipRole,
    QtUserRole,
)

from tests.helpers import makeDocx


@pytest.mark.gui
def testGuiWelcome_Main(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, nwGUI: GuiMain, fncPath: Path):
    """Test the main Welcome window."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        # This ensures the paint event is executed
        welcome.show()

    # By default, the project list is shown
    assert welcome.mainStack.currentIndex() == 0

    # Show the new project form
    welcome.btnNew.click()
    assert welcome.mainStack.currentIndex() == 1

    # Revert to project list
    welcome.btnList.click()
    assert welcome.mainStack.currentIndex() == 0

    # Cancelling the browse dialog does nothing
    with monkeypatch.context() as mp:
        mp.setattr(SHARED, "getProjectFolder", lambda *a, **k: None)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnBrowse.click()

    # Open a project
    with monkeypatch.context() as mp:
        mp.setattr(SHARED, "getProjectFolder", lambda *a, **k: fncPath)
        with qtbot.waitSignal(welcome.openProjectRequest) as signal:
            welcome.btnBrowse.click()
        assert signal.args
        assert signal.args[0] == fncPath

    # Opening the selected item only applies while on the Open tab
    welcome.btnNew.click()
    assert welcome.mainStack.currentIndex() == 1
    with monkeypatch.context() as mp:
        openMock = MagicMock()
        mp.setattr(welcome.tabOpen, "openSelectedItem", openMock)
        welcome._openSelectedItem()
        assert openMock.called is False
    welcome.btnList.click()
    assert welcome.mainStack.currentIndex() == 0

    # A non-Path value emits nothing, but still closes the dialog
    with monkeypatch.context() as mp:
        mp.setattr(welcome, "close", lambda *a: None)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome._openProjectPath(None)  # type: ignore

    # Create sample project when list is empty
    assert welcome.tabOpen.listModel.rowCount() == 1
    selected = welcome.tabOpen.listModel.index(0, 0).data()
    assert selected[0] == SAMPLE_NAME
    assert selected[1] == SAMPLE_KEY
    welcome.tabOpen._selectFirstItem()

    # A folder must be selected
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: None)
        welcome.tabOpen._processOpenProjectRequest(SAMPLE_KEY)

    assert SHARED.lastAlert[0] == "You must select a location for the example project."

    # Successful
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: fncPath)
        welcome.tabOpen._processOpenProjectRequest(SAMPLE_KEY)

    assert (fncPath / SAMPLE_NAME).is_dir()

    # But can't create a duplicate
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: fncPath)
        welcome.tabOpen._processOpenProjectRequest(SAMPLE_KEY)

    assert SHARED.lastAlert[0] == "The target folder already exists. Please choose another folder."

    # qtbot.stop()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_Open(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, nwGUI: GuiMain):
    """Test the open tab in the Welcome window."""
    monkeypatch.setattr(QMenu, "exec", lambda *a: None)
    monkeypatch.setattr(QMenu, "setParent", lambda *a: None)

    data1 = ProjectData(SHARED.project)
    data2 = ProjectData(SHARED.project)

    data1.setUuid(None)
    data2.setUuid(None)
    data1.setName("Project One")
    data2.setName("Project Two")
    data1.setCurrCounts(12345, 0)
    data2.setCurrCounts(54321, 0)

    CONFIG.recentProjects.update("/stuff/project_one", data1, 1690000000)
    CONFIG.recentProjects.update("/stuff/project_two", data2, 1700000000)
    dateOne = CONFIG.localDate(datetime.fromtimestamp(1700000000))
    dateTwo = CONFIG.localDate(datetime.fromtimestamp(1690000000))

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    assert welcome.mainStack.currentIndex() == 0
    tabOpen = welcome.tabOpen
    listModel = tabOpen.listModel
    vPort = tabOpen.listWidget.viewport()

    posOne = tabOpen.listWidget.rectForIndex(listModel.createIndex(0, 0)).center()
    posTwo = tabOpen.listWidget.rectForIndex(listModel.createIndex(1, 0)).center()

    # Check items, which should be in opposite order
    entry = listModel.data(listModel.createIndex(0, 0), QtDisplayRole)
    assert isinstance(entry, _ProjectListEntry)
    assert entry.title == "Project Two"
    assert entry.path == "/stuff/project_two"
    assert entry.details == f"Last Opened: {dateOne}, Word Count: 54.3\u2009k"
    assert entry.accessible == f"Project Two, Last Opened {dateOne}, Word Count 54.3\u2009k"
    assert listModel.data(listModel.createIndex(0, 0), QtAccessibleTextRole) == entry.accessible

    entry = listModel.data(listModel.createIndex(1, 0), QtDisplayRole)
    assert isinstance(entry, _ProjectListEntry)
    assert entry.title == "Project One"
    assert entry.path == "/stuff/project_one"
    assert entry.details == f"Last Opened: {dateTwo}, Word Count: 12.3\u2009k"
    assert entry.accessible == f"Project One, Last Opened {dateTwo}, Word Count 12.3\u2009k"
    assert listModel.data(listModel.createIndex(1, 0), QtAccessibleTextRole) == entry.accessible

    # Check other model data roles
    assert listModel.data(listModel.createIndex(0, 0), QtDecorationRole) is None
    assert listModel.data(listModel.createIndex(0, 0), QtFontRole) is None
    assert listModel.data(listModel.createIndex(0, 0), QtTextAlignmentRole) is None
    assert listModel.data(listModel.createIndex(0, 0), QtToolTipRole) is None
    assert listModel.data(listModel.createIndex(0, 0), QtUserRole) is None

    # Check out of range index
    assert listModel.data(listModel.createIndex(2, 0), QtDisplayRole) is None

    # Change selection with arrow keys
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_two"
    qtbot.keyClick(tabOpen, QtKeyLeft)  # Does nothing
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_two"
    qtbot.keyClick(tabOpen, QtKeyRight)  # Does nothing
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_two"
    qtbot.keyClick(tabOpen, QtKeyDown)  # Selects lower
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_one"
    qtbot.keyClick(tabOpen, QtKeyDown)  # Does nothing (already on last)
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_one"
    qtbot.keyClick(tabOpen, QtKeyUp)  # Selects upper
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_two"
    qtbot.keyClick(tabOpen, QtKeyUp)  # Does nothing (already on first)
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_two"

    # Single click item
    qtbot.mouseClick(vPort, QtMouseLeft, pos=posOne, delay=10)
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_two"
    qtbot.mouseClick(vPort, QtMouseLeft, pos=posTwo, delay=10)
    assert tabOpen.selectedPath.text() == "Path: /stuff/project_one"

    # Double click item
    qtbot.mouseClick(vPort, QtMouseLeft, pos=posTwo, delay=10)
    with monkeypatch.context() as mp:
        mp.setattr(welcome, "close", lambda *a: None)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            qtbot.mouseDClick(vPort, QtMouseLeft, pos=posTwo, delay=10)
        assert signal.args
        assert signal.args[0] == Path("/stuff/project_one")

    # Press open button
    qtbot.mouseClick(vPort, QtMouseLeft, pos=posTwo, delay=10)
    with monkeypatch.context() as mp:
        mp.setattr(welcome, "close", lambda *a: None)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnOpen.click()
        assert signal.args
        assert signal.args[0] == Path("/stuff/project_one")

    # Context Menu
    def getMenuForPos(pos: QPoint) -> QMenu | None:
        tabOpen._openContextMenu(pos)
        for obj in tabOpen.children():
            if isinstance(obj, QMenu) and obj.objectName() == "ContextMenu":
                return obj
        return None

    qtbot.mouseClick(vPort, QtMouseLeft, pos=posOne, delay=10)
    ctxMenu = getMenuForPos(posOne)
    assert isinstance(ctxMenu, QMenu)
    assert ctxMenu.actions()[0].text() == "Open Project"
    assert ctxMenu.actions()[1].text() == "Remove Project"

    # Open item from context menu
    with monkeypatch.context() as mp:
        mp.setattr(welcome, "close", lambda *a: None)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            ctxMenu.actions()[0].activate(QAction.ActionEvent.Trigger)
        assert signal.args
        assert signal.args[0] == Path("/stuff/project_two")

    ctxMenu.setObjectName("")
    ctxMenu.deleteLater()

    # Delete item from context menu
    ctxMenu = getMenuForPos(posOne)
    assert isinstance(ctxMenu, QMenu)
    ctxMenu.actions()[1].activate(QAction.ActionEvent.Trigger)
    assert len(CONFIG.recentProjects.listEntries()) == 1

    ctxMenu.setObjectName("")
    ctxMenu.deleteLater()

    # Check removing entry error handling
    assert listModel.data(listModel.createIndex(1, 0), QtDisplayRole) is None
    assert listModel.removeEntry(listModel.createIndex(1, 0)) is False

    # With nothing selected, opening or deleting the selection does nothing
    tabOpen.listWidget.clearSelection()
    tabOpen.listWidget.selectionModel().clearCurrentIndex()  # type: ignore
    with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
        tabOpen.openSelectedItem()

    countBefore = len(CONFIG.recentProjects.listEntries())
    tabOpen._deleteSelectedItem()
    assert len(CONFIG.recentProjects.listEntries()) == countBefore

    # Double-clicking an invalid index does nothing
    with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
        tabOpen._projectDoubleClicked(listModel.createIndex(99, 0))

    # Declining the delete confirmation leaves the entry in place
    qtbot.mouseClick(vPort, QtMouseLeft, pos=posOne, delay=10)
    with monkeypatch.context() as mp:
        mp.setattr(_GuiAlert, "finalState", False)
        countBefore = len(CONFIG.recentProjects.listEntries())
        tabOpen._deleteSelectedItem()
        assert len(CONFIG.recentProjects.listEntries()) == countBefore

    # qtbot.stop()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_New(
    qtbot: QtBot,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test the new project tab in the Welcome window."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    assert welcome.mainStack.currentIndex() == 1
    tabNew = welcome.tabNew
    newForm = tabNew.projectForm

    # Cancelling the browse dialog leaves the path unchanged
    pathBefore = newForm.projPath.text()
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
        newForm.browsePath.click()
        assert newForm.projPath.text() == pathBefore

    # Populate the path
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: fncPath)
        newForm.browsePath.click()
        assert newForm.projPath.text() == str(fncPath)

    # Turning off root folders should disable notes switch
    newForm.addNotes.setChecked(True)
    newForm.addPlot.setChecked(False)
    newForm.addChar.setChecked(False)
    newForm.addWorld.setChecked(False)
    newForm._syncSwitches()
    assert newForm.addNotes.isChecked() is False

    # With at least one root folder enabled, the notes switch is untouched
    newForm.addNotes.setChecked(True)
    newForm.addPlot.setChecked(True)
    newForm._syncSwitches()
    assert newForm.addNotes.isChecked() is True
    newForm.addPlot.setChecked(False)

    # Change fill info to sample
    newForm.fillSample.trigger()
    assert newForm._fillMode == newForm.FILL_SAMPLE
    assert newForm.projFill.text() == "Example Project"
    assert newForm.extraWidget.isVisible() is False

    # Cancelling the template picker leaves the fill mode unchanged
    fillModeBefore = newForm._fillMode
    with monkeypatch.context() as mp:
        mp.setattr(SHARED, "getProjectPath", lambda *a, **k: None)
        newForm.fillCopy.trigger()
        assert newForm._fillMode == fillModeBefore

    # Change fill info to template
    with monkeypatch.context() as mp:
        mp.setattr(SHARED, "getProjectPath", lambda *a, **k: fncPath)
        newForm.fillCopy.trigger()
        assert newForm._fillMode == newForm.FILL_COPY
        assert newForm.projFill.text() == f"Template: {fncPath}"
        assert newForm.extraWidget.isVisible() is False

    # Change back to fill blank using the menu
    newForm.fillMenu.actions()[0].activate(QAction.ActionEvent.Trigger)
    assert newForm._fillMode == newForm.FILL_BLANK
    assert newForm.projFill.text() == "Fresh Project"
    assert newForm.extraWidget.isVisible() is True

    # Creating a project without a name, pops an error
    caplog.clear()
    welcome.btnCreate.click()
    assert "A project name is required." in caplog.text

    # Set some more values, and extract data
    projPath = fncPath / "Test Project"
    newForm.projName.setText("Test Project")
    newForm.projAuthor.setText("Jane Smith")
    newForm.addPlot.setChecked(True)
    newForm.addChar.setChecked(True)
    newForm.addWorld.setChecked(True)
    newForm.addNotes.setChecked(True)
    newForm.numChapters.setValue(10)
    newForm.numScenes.setValue(6)
    assert newForm.getProjectData() == {
        "name": "Test Project",
        "author": "Jane Smith",
        "path": str(projPath),
        "blank": True,
        "sample": False,
        "template": None,
        "import": None,
        "chapters": 10,
        "scenes": 6,
        "roots": [nwItemClass.PLOT, nwItemClass.CHARACTER, nwItemClass.WORLD],
        "notes": True,
    }

    # A failed build does not request opening the project
    with monkeypatch.context() as mp:
        mp.setattr(ProjectBuilder, "buildProject", lambda *a, **k: False)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()
    assert not (projPath / nwFiles.PROJ_FILE).exists()

    # Create a project with these values
    with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
        welcome.btnCreate.click()
    assert signal.args
    assert signal.args[0] == projPath
    assert (projPath / nwFiles.PROJ_FILE).exists()

    # qtbot.stop()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_NewImport(
    qtbot: QtBot,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test importing a Word document from the new project tab."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    assert welcome.mainStack.currentIndex() == 1
    tabNew = welcome.tabNew
    newForm = tabNew.projectForm

    docxPath = makeDocx(
        fncPath / "novel.docx",
        [
            ("My Novel", "Title"),
            ("Jane Doe", "Subtitle"),
            ("Chapter One", "Heading1"),
            ("The first paragraph of the chapter.", None),
        ],
        title="My Novel",
        author="Jane Doe",
    )

    # Cancelling the file dialog leaves the fill mode unchanged
    fillModeBefore = newForm._fillMode
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
        newForm.fillImport.trigger()
        assert newForm._fillMode == fillModeBefore

    # Selecting a Word document sets the fill mode and fills in details
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(docxPath), ""))
        newForm.fillImport.trigger()
    assert newForm._fillMode == newForm.FILL_IMPORT
    assert newForm.projName.text() == "My Novel"
    assert newForm.projAuthor.text() == "Jane Doe"
    assert "novel.docx" in newForm.projFill.text()
    assert newForm.extraWidget.isVisible() is False

    # Set the target folder
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(fncPath))
        newForm.browsePath.click()
    assert newForm.projPath.text() == str(fncPath / "My Novel")

    # Creating the project must open it
    received: list[Path] = []
    welcome.openProjectRequest.connect(received.append)
    welcome.btnCreate.click()
    assert len(received) == 1
    assert Path(received[0]) == fncPath / "My Novel"
    assert (fncPath / "My Novel" / nwFiles.PROJ_FILE).is_file()

    # The imported project must have the documents from the Word file
    project = NWProject()
    assert project.openProject(fncPath / "My Novel") is True
    assert project.data.name == "My Novel"
    assert project.data.author == "Jane Doe"
    roots = {node.item.itemName: node for node in project.tree._model.root.children}
    assert roots["Novel"].childCount() == 2
    project.closeProject()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_NewImportError(
    qtbot: QtBot,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a failed Word document import is handled."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    tabNew = welcome.tabNew
    newForm = tabNew.projectForm

    # A file that is not a Word document cannot be read
    badPath = fncPath / "bad.docx"
    badPath.write_text("Not a Word document", encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(badPath), ""))
        newForm.fillImport.trigger()
    assert newForm._fillMode == newForm.FILL_BLANK
    welcome.close()

    # A Word document with no content cannot be imported
    emptyPath = makeDocx(fncPath / "empty.docx", [])
    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(emptyPath), ""))
        newForm.fillImport.trigger()
    assert newForm._fillMode == newForm.FILL_BLANK
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ProjectFolder(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that projects in the project folder are listed."""
    projRoot = fncPath / "projects"
    projRoot.mkdir()

    # Create two projects in the project folder
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(projRoot / "Project One"), "name": "Project One", "author": ""})
    assert builder.buildProject({"path": str(projRoot / "Project Two"), "name": "Project Two", "author": ""})

    # A folder that is not a project is ignored
    (projRoot / "Not A Project").mkdir()
    (projRoot / "Not A Project" / "readme.txt").write_text("Nope", encoding="utf-8")

    CONFIG.setProjectFolder(projRoot)
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    listModel = welcome.tabOpen.listModel
    assert listModel.rowCount() == 2

    entries = [listModel.data(listModel.index(i, 0), QtDisplayRole) for i in range(2)]
    assert all(isinstance(e, _ProjectListEntry) for e in entries)
    assert {e.title for e in entries} == {"Project One", "Project Two"}  # type: ignore[union-attr]
    assert {e.path for e in entries} == {  # type: ignore[union-attr]
        str(projRoot / "Project One"),
        str(projRoot / "Project Two"),
    }

    # The projects were just created, so they are also in the recent list
    assert all(e.recent is True for e in entries)  # type: ignore[union-attr]
    assert all("Word Count" in e.details for e in entries)  # type: ignore[union-attr]

    # Open a project from the list must work
    welcome.tabOpen.listWidget.setCurrentIndex(listModel.index(0, 0))
    with monkeypatch.context() as mp:
        mp.setattr(welcome, "close", lambda *a: None)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnOpen.click()
        assert signal.args
        assert Path(signal.args[0]).parent == projRoot

    # Remove the projects from the recent list, and check the list again
    CONFIG.recentProjects.remove(str(projRoot / "Project One"))
    CONFIG.recentProjects.remove(str(projRoot / "Project Two"))

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    listModel = welcome.tabOpen.listModel
    assert listModel.rowCount() == 2

    entries = [listModel.data(listModel.index(i, 0), QtDisplayRole) for i in range(2)]
    assert all(isinstance(e, _ProjectListEntry) for e in entries)

    # They are not in the recent list, so they cannot be removed from it
    assert all(e.recent is False for e in entries)  # type: ignore[union-attr]

    # The details must show when the project was last modified
    assert all("Last Modified" in e.details for e in entries)  # type: ignore[union-attr]

    # The context menu has no remove option for these entries
    with monkeypatch.context() as mp:
        mp.setattr(QMenu, "exec", lambda *a: None)
        mp.setattr(QMenu, "setParent", lambda *a: None)
        welcome.tabOpen._openContextMenu(QPoint(0, 0))
        for obj in welcome.children():
            if isinstance(obj, QMenu) and obj.objectName() == "ContextMenu":
                assert [a.text() for a in obj.actions()] == ["Open Project"]
                obj.setObjectName("")
                obj.deleteLater()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_RemoveMergedRecent(
    qtbot: QtBot,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that removing a recent project keeps it in the folder list."""
    projRoot = fncPath / "projects"
    projRoot.mkdir()
    target = projRoot / "Project"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Project", "author": ""})
    CONFIG.setProjectFolder(projRoot)

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    listModel = welcome.tabOpen.listModel
    assert listModel.rowCount() == 1
    entry = listModel.entry(listModel.index(0, 0))
    assert entry is not None
    assert entry.recent is True
    assert entry.scanned is True

    assert listModel.removeEntry(listModel.index(0, 0)) is True
    assert listModel.rowCount() == 1
    entry = listModel.entry(listModel.index(0, 0))
    assert entry is not None
    assert entry.recent is False
    assert entry.scanned is True
    assert "Last Modified" in entry.details
    assert all(Path(path) != target for path, _, _, _ in CONFIG.recentProjects.listEntries())

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_NewProjectFolder(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that the project folder is created when it doesn't exist."""
    projRoot = fncPath / "projects" / "nested"
    assert not projRoot.exists()

    CONFIG.setProjectFolder(projRoot)

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    # The new project page must default to the project folder
    assert newForm.projPath.text() == str(projRoot)

    newForm.projName.setText("A Project")
    assert newForm.projPath.text() == str(projRoot / "A Project")

    with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
        welcome.btnCreate.click()
    assert signal.args
    assert signal.args[0] == projRoot / "A Project"

    # The project folder must have been created
    assert projRoot.is_dir()
    assert (projRoot / "A Project" / nwFiles.PROJ_FILE).is_file()

    # The default author must remain empty
    project = NWProject()
    assert project.openProject(projRoot / "A Project") is True
    assert project.data.author == ""
    project.closeProject()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictCancel(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a project conflict can be cancelled."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    # Create a project that blocks the target path
    target = fncPath / "Blocked"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Blocked", "author": ""})

    newForm.projName.setText("Blocked")
    newForm._basePath = fncPath
    newForm._updateProjPath()
    assert newForm.projPath.text() == str(target)

    # Cancelling the dialog stops the operation
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.CANCEL)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    # The existing project must still be there
    assert (target / nwFiles.PROJ_FILE).is_file()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictSafety(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a project conflict cannot erase an unsafe path."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    # A project name that resolves to the parent folder must be rejected
    protected = fncPath / "keep.txt"
    protected.write_text("Keep me", encoding="utf-8")
    newForm._basePath = fncPath / "projects"
    newForm._basePath.mkdir()
    newForm.projName.setText("..")

    with monkeypatch.context() as mp:
        mp.setattr(
            GuiProjectConflict,
            "ask",
            lambda *a, **k: pytest.fail("The conflict dialog must not be opened for an unsafe path"),
        )
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert protected.is_file()
    assert newForm.isSafeProjectPath(fncPath / "projects" / "Safe Project") is True
    assert newForm.isSafeProjectPath(fncPath / "projects" / "..") is False
    newForm._basePath = Path.home().parent
    assert newForm.isSafeProjectPath(Path.home()) is False
    newForm._basePath = Path.home() / "UE_Projects"
    assert newForm.isSafeProjectPath(Path.home() / "UE_Projects" / "Project") is True
    assert (fncPath / "projects").is_dir()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictOpenProject(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that the currently open project cannot be erased."""
    target = fncPath / "Open Project"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Open Project", "author": ""})
    assert SHARED.project.openProject(target) is True

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm
    newForm._basePath = fncPath
    newForm.projName.setText("Open Project")
    newForm._updateProjPath()

    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert (target / nwFiles.PROJ_FILE).is_file()
    assert SHARED.project.storage.storagePath == target

    SHARED.project.closeProject()
    welcome.close()


@pytest.mark.gui
@pytest.mark.parametrize("fillMode", ["blank", "copy"])
def testGuiWelcome_ConflictBuildFailure(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
    fillMode: str,
):
    """Test that a failed replacement build preserves the old project."""
    target = fncPath / "Target"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Old Project", "author": ""})
    oldFile = target / nwFiles.PROJ_FILE
    assert oldFile.is_file()

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm
    newForm._basePath = fncPath
    newForm.projName.setText("Target")
    newForm._updateProjPath()

    if fillMode == "copy":
        source = fncPath / "Source"
        assert builder.buildProject({"path": str(source), "name": "Source", "author": ""})
        newForm._copyPath = source / nwFiles.PROJ_FILE
        newForm._fillMode = newForm.FILL_COPY

    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        mp.setattr(ProjectBuilder, "buildProject", lambda *a, **k: False)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert oldFile.is_file()
    project = NWProject()
    assert project.openProject(target) is True
    assert project.data.name == "Old Project"
    project.closeProject()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictLockedProject(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a project with a lock file cannot be replaced."""
    target = fncPath / "Target"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Old Project", "author": ""})
    oldFile = target / nwFiles.PROJ_FILE
    (target / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm
    newForm._basePath = fncPath
    newForm.projName.setText("Target")
    newForm._updateProjPath()

    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        mp.setattr(SHARED, "question", lambda *a, **k: False)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert oldFile.is_file()
    assert (target / nwFiles.PROJ_LOCK).is_file()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictNestedLockedProject(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a container with a locked project cannot be replaced."""
    target = fncPath / "Target"
    target.mkdir()
    active = target / "Active Project"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(active), "name": "Active Project", "author": ""})
    (active / nwFiles.PROJ_LOCK).write_text("locked", encoding="utf-8")

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm
    newForm._basePath = fncPath
    newForm.projName.setText("Target")
    newForm._updateProjPath()

    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert (active / nwFiles.PROJ_LOCK).is_file()
    welcome.close()


@pytest.mark.gui
@pytest.mark.parametrize("targetType", ["folder", "file"])
def testGuiWelcome_ConflictExistingPath(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
    targetType: str,
):
    """Test that an empty folder or file can be replaced by a project."""
    target = fncPath / "Target"
    if targetType == "folder":
        target.mkdir()
    else:
        target.write_text("Existing file", encoding="utf-8")

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm
    newForm._basePath = fncPath
    newForm.projName.setText("Target")
    newForm._updateProjPath()

    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnCreate.click()
        assert signal.args
        assert signal.args[0] == target

    assert (target / nwFiles.PROJ_FILE).is_file()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictErase(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a project conflict can be resolved by erasing the folder."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    # Create a project that blocks the target path
    target = fncPath / "Blocked"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Blocked", "author": ""})
    oldFile = target / nwFiles.PROJ_FILE
    assert oldFile.is_file()

    newForm.projName.setText("Blocked")
    newForm._basePath = fncPath
    newForm._updateProjPath()

    # Erasing the folder replaces the project
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnCreate.click()
        assert signal.args
        assert signal.args[0] == target

    # The project must have been replaced
    assert (target / nwFiles.PROJ_FILE).is_file()

    project = NWProject()
    assert project.openProject(target) is True
    assert project.data.name == "Blocked"
    project.closeProject()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictCopy(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a copied project can replace an existing project."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    # Create a source project and an existing target project
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(fncPath / "Source"), "name": "Source", "author": ""})
    assert builder.buildProject({"path": str(fncPath / "Target"), "name": "Target", "author": ""})

    newForm._copyPath = fncPath / "Source" / nwFiles.PROJ_FILE
    newForm._fillMode = newForm.FILL_COPY
    newForm._basePath = fncPath
    newForm.projName.setText("Target")
    newForm._updateProjPath()

    # Erasing the target lets the copy replace the project
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnCreate.click()
        assert signal.args
        assert signal.args[0] == fncPath / "Target"

    project = NWProject()
    assert project.openProject(fncPath / "Target") is True
    assert project.data.name == "Target"
    project.closeProject()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictCopySelf(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a project cannot be replaced by a copy of itself."""
    target = fncPath / "Source"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Source", "author": ""})
    oldFile = target / nwFiles.PROJ_FILE

    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm
    newForm._copyPath = target / nwFiles.PROJ_FILE
    newForm._fillMode = newForm.FILL_COPY
    newForm._basePath = fncPath
    newForm.projName.setText("Source")
    newForm._updateProjPath()

    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert oldFile.is_file()
    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ConflictRename(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a project conflict can be resolved by changing the name."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    # Create a project that blocks the target path
    target = fncPath / "Blocked"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Blocked", "author": ""})

    newForm.projName.setText("Blocked")
    newForm._basePath = fncPath
    newForm._updateProjPath()

    # Cancelling the name prompt stops the operation
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.RENAME)
        mp.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()

    assert (target / nwFiles.PROJ_FILE).is_file()

    # Changing the name creates the project in a new folder
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.RENAME)
        mp.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed Project", True))
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnCreate.click()
        assert signal.args
        assert signal.args[0] == fncPath / "Renamed Project"

    # The new project must exist, and the old one must be untouched
    assert (fncPath / "Renamed Project" / nwFiles.PROJ_FILE).is_file()
    assert (target / nwFiles.PROJ_FILE).is_file()

    welcome.close()


@pytest.mark.gui
def testGuiWelcome_ImportConflict(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    nwGUI: GuiMain,
    fncPath: Path,
):
    """Test that a Word document import can replace an existing project."""
    welcome = GuiWelcome(nwGUI)
    with qtbot.waitExposed(welcome):
        welcome.show()

    welcome.btnNew.click()
    newForm = welcome.tabNew.projectForm

    docxPath = makeDocx(
        fncPath / "novel.docx",
        [
            ("Chapter One", "Heading1"),
            ("The first paragraph of the chapter.", None),
        ],
        title="My Novel",
        author="Jane Doe",
    )

    with monkeypatch.context() as mp:
        mp.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(docxPath), ""))
        newForm.fillImport.trigger()

    newForm.projName.setText("My Novel")
    newForm._basePath = fncPath
    newForm._updateProjPath()

    # Create an existing project with the same name
    target = fncPath / "My Novel"
    builder = ProjectBuilder()
    assert builder.buildProject({"path": str(target), "name": "Old Novel", "author": "John Doe"})
    oldFile = target / nwFiles.PROJ_FILE
    assert oldFile.is_file()

    # The import must fail when the folder is in use
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.CANCEL)
        with qtbot.assertNotEmitted(welcome.openProjectRequest, wait=100):
            welcome.btnCreate.click()
    assert oldFile.is_file()

    # Erasing the folder lets the import replace the project
    with monkeypatch.context() as mp:
        mp.setattr(GuiProjectConflict, "ask", lambda *a, **k: ProjectConflictAction.ERASE)
        with qtbot.waitSignal(welcome.openProjectRequest, timeout=5000) as signal:
            welcome.btnCreate.click()
        assert signal.args
        assert signal.args[0] == target

    # The staged import must not leave a transient recent-project entry
    recentEntries = CONFIG.recentProjects.listEntries()
    assert all(".umbraedit-import-" not in entry[0] for entry in recentEntries)
    targetEntry = next(entry for entry in recentEntries if entry[0] == str(target))
    assert targetEntry[1] == "My Novel"

    project = NWProject()
    assert project.openProject(target) is True
    assert project.data.name == "My Novel"
    assert project.data.author == "Jane Doe"
    project.closeProject()

    welcome.close()
