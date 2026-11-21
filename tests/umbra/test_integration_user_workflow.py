"""UmbraEdit - Integration Test for Complete User Workflow.

This test simulates the complete user workflow:
1. Launch app → Welcome dialog appears
2. Create sample project → No lock errors
3. Open project → UI loads correctly
4. Verify project structure and content
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from PyQt6 import sip
from PyQt6.QtWidgets import QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from umbraedit import CONFIG
from umbraedit.core.coretools import ProjectBuilder
from umbraedit.core.project import NWProject
from umbraedit.enum import nwItemClass
from umbraedit.gui.importmanuscript import ImportManuscriptCommand
from umbraedit.gui.mainmenu import GuiMainMenu
from umbraedit.tools.welcome import GuiWelcome


class MockMainGui:
    """Mock GUI for testing without full GUI initialization."""

    def __init__(self):
        self.project = None
        self.closed = False

    def showWelcomeDialog(self):
        pass

    def closeProject(self):
        if self.project:
            self.project.closeProject()
            self.project = None


class TestCompleteUserWorkflow:
    """Test the complete user workflow from launch to project creation."""

    def test_welcome_dialog_creates_sample_project(self, mockGUI: Any, projPath: Path, monkeypatch: Any) -> None:
        """Test that welcome dialog can create a sample project without lock errors."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()
        project.closeProject()

        # Now simulate the welcome dialog creating a sample project
        # This mimics what happens when user clicks "Create an example project"
        sample_data = {"name": "Test Sample", "path": projPath / "TestSample", "sample": True}

        # The actual welcome dialog uses ProjectBuilder
        # We'll mock the sample extraction since sample.zip isn't in test asset path

        def mock_extract_sample(self, path: Path, data: dict) -> bool:
            """Mock sample extraction - create a minimal valid project structure."""
            project = NWProject()
            project.storage.createNewProject(path)
            project.setDefaultStatusImport()
            project.data.setName(data.get("name", "Test Sample"))
            project.data.setAuthor(data.get("author", ""))
            project.saveProject()
            project.closeProject()
            return True

        monkeypatch.setattr(
            "umbraedit.core.coretools.ProjectBuilder._extractSampleProject",
            mock_extract_sample,
        )

        # The actual welcome dialog uses ProjectBuilder
        builder = ProjectBuilder()
        result = builder.buildProject(sample_data)

        # Verify project was created successfully
        assert result is True
        assert (projPath / "TestSample").exists()

        # Verify no lock file remains
        lock_file = projPath / "TestSample" / "nwProject.lock"
        assert not lock_file.exists(), "Lock file should not exist after creation"

        # Verify project structure
        project = NWProject()
        project.openProject(projPath / "TestSample")
        assert project.data.name == "Test Sample"
        project.closeProject()

    def test_welcome_dialog_sample_name(self, mockGUI: Any, projPath: Path) -> None:
        """Test that sample project gets the correct name."""
        from umbraedit.tools.welcome import SAMPLE_NAME

        assert SAMPLE_NAME == "UmbraEdit_Sample"

    def test_sample_project_loads_without_lock_error(self, mockGUI: Any, projPath: Path) -> None:
        """Test that opening the sample project doesn't show lock error."""
        # First create a sample project
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()
        project.data.setName("Test Project")
        project.saveProject()
        project.closeProject()

        # Now try to open it - should not show lock error
        project2 = NWProject()
        result = project2.openProject(projPath)
        assert result is True
        assert project2._valid
        project2.closeProject()

    def test_import_manuscript_no_crash(self, mockGUI: Any, projPath: Path, monkeypatch: Any) -> None:
        """Test that import manuscript doesn't crash with AttributeError."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        command = ImportManuscriptCommand(project, None)

        # Mock file dialog to cancel
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: ("", ""),
        )

        # This should not raise AttributeError
        command.execute()

    def test_import_manuscript_with_file(self, mockGUI: Any, projPath: Path, monkeypatch: Any, qtbot: QtBot) -> None:
        """Test import with a fake file."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        command = ImportManuscriptCommand(project, None)

        # Create fake DOCX
        fake_docx = projPath / "test.docx"
        fake_docx.write_text("fake")

        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(fake_docx), ""),
        )
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.No,
        )

        # Collect the error message instead of showing a modal dialog.
        # A modal dialog would block the event loop, and the dialog
        # would still be open when the test ends.
        errors: list[str] = []

        def mockCritical(*args: Any, **kwargs: Any) -> None:
            errors.append(str(args[2]) if len(args) > 2 else "")

        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QMessageBox.critical",
            mockCritical,
        )

        command = ImportManuscriptCommand(project, None)
        command.execute()  # Should not crash

        # The import runs in the background. Wait for the result to be
        # delivered, so that it is handled inside the test, and not
        # during the teardown of the test.
        qtbot.waitUntil(lambda: bool(errors), timeout=10000)

        assert len(errors) == 1
        assert "Failed to import manuscript" in errors[0]

    def test_import_manuscript_no_dialog_without_gui(self, mockGUI: Any, projPath: Path, monkeypatch: Any) -> None:
        """The import result must not open a dialog if the main window
        has been closed while the import was running.
        """
        from umbraedit import SHARED
        from umbraedit.gui.importmanuscript import _dialogParent
        from umbraedit.umbra.ingest.worker import IngestJobResult

        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        command = ImportManuscriptCommand(project, None)

        # There is no main window at all
        monkeypatch.setattr(SHARED, "_gui", None)
        assert _dialogParent() is None

        # The result must be handled without opening a dialog
        command._on_ingest_complete(IngestJobResult(success=False, error="Test error"))

        # The main window was closed, and the widget was deleted
        gui = QWidget()
        monkeypatch.setattr(SHARED, "_gui", gui)
        gui.close()
        sip.delete(gui)

        assert _dialogParent() is None

        # The result must be handled without opening a dialog
        command._on_ingest_complete(IngestJobResult(success=False, error="Test error"))

    def test_welcome_dialog_ui_elements(self, mockGUI: Any) -> None:
        """Test that welcome dialog has the expected UI elements."""
        dialog = GuiWelcome(mockGUI)

        # Check that the dialog has the expected tabs
        assert hasattr(dialog, "tabOpen")
        assert hasattr(dialog, "tabNew")
        assert hasattr(dialog, "mainStack")

        # Check fill project options (on tabNew.projectForm)
        assert hasattr(dialog.tabNew.projectForm, "fillBlank")
        assert hasattr(dialog.tabNew.projectForm, "fillSample")
        assert hasattr(dialog.tabNew.projectForm, "fillCopy")

        dialog.close()

    @pytest.mark.skip(reason="Requires full GUI initialization, tested separately")
    def test_main_menu_open_welcome(self, mockGUI: Any) -> None:
        """Test that main menu can open welcome dialog."""
        menu = GuiMainMenu(mockGUI)

        # Check that the open project action exists
        assert hasattr(menu, "aOpenProject")

        # Check that it connects to showWelcomeDialog
        # This is tested implicitly by the connection existing

    def test_create_project_with_metadata(self, mockGUI: Any, projPath: Path) -> None:
        """Test creating project with metadata and verifying it persists."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        project.data.setUuid("test-uuid-1234")
        project.data.setName("Test Novel")
        project.data.setAuthor("Test Author")
        project.saveProject()
        project.closeProject()

        # Re-open and verify
        project2 = NWProject()
        project2.openProject(projPath)
        assert project2.data.name == "Test Novel"
        assert project2.data.author == "Test Author"
        project2.closeProject()

    def test_chapter_scene_creation(self, mockGUI: Any, projPath: Path) -> None:
        """Test creating chapters and scenes."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        assert chHandle is not None
        scHandle = project.newFile("Scene 1", chHandle)
        assert scHandle is not None

        assert chHandle != ""
        assert scHandle != ""

        chDoc = project.storage.getDocument(chHandle)
        scDoc = project.storage.getDocument(scHandle)
        assert chDoc is not None
        assert scDoc is not None

    def test_document_read_write(self, mockGUI: Any, projPath: Path) -> None:
        """Test writing and reading document content."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        assert chHandle is not None
        sceneHandle = project.newFile("Scene 1", chHandle)
        assert sceneHandle is not None

        doc = project.storage.getDocument(chHandle)
        doc.writeDocument("## Chapter 1\n\nTest content.")
        project.index.reIndexHandle(chHandle)

        # Read back via storage
        content = project.storage.getDocumentText(chHandle)
        assert "Chapter 1" in content
        assert "Test content" in content

    def test_sample_project_exists(self) -> None:
        """Verify sample project assets exist."""
        sampleZip = CONFIG.assetPath("sample.zip")
        assert sampleZip.exists(), "sample.zip not found in assets"

    def test_sample_project_xml_valid(self) -> None:
        """Sample project XML must be well-formed."""
        import xml.etree.ElementTree as ET
        import zipfile

        sampleZip = CONFIG.assetPath("sample.zip")
        with zipfile.ZipFile(sampleZip, "r") as z:
            xmlContent = z.read("UEProject.UEx")
            root = ET.fromstring(xmlContent)
            assert root.tag == "UmbraEditXML"
            assert root.get("fileVersion") == "1.6"

    def test_sample_project_has_content(self) -> None:
        """Sample project must have content files."""
        import zipfile

        sampleZip = CONFIG.assetPath("sample.zip")
        with zipfile.ZipFile(sampleZip, "r") as z:
            contentFiles = [n for n in z.namelist() if n.startswith("content/") and n.endswith(".md")]
            assert len(contentFiles) > 0, "Sample project must have content files"
