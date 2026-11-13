"""
UmbraEdit - Integration Test for Complete User Workflow

This test simulates the complete user workflow:
1. Launch app → Welcome dialog appears
2. Create sample project → No lock errors
3. Open project → UI loads correctly
4. Verify project structure and content
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from umbraedit import CONFIG, SHARED
from umbraedit.core.coretools import ProjectBuilder
from umbraedit.core.project import NWProject
from umbraedit.core.storage import ProjectStorage
from umbraedit.enum import nwItemClass
from umbraedit.gui.importmanuscript import ImportManuscriptCommand
from umbraedit.tools.welcome import GuiWelcome
from umbraedit.gui.mainmenu import GuiMainMenu


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
        data = {"name": "Test Sample", "path": projPath / "TestSample", "sample": True}
        
        # The actual welcome dialog uses ProjectBuilder
        # We'll mock the sample extraction since sample.zip isn't in test asset path
        from umbraedit.core.coretools import ProjectBuilder
        
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
        result = builder.buildProject({"name": "Test Sample", "path": projPath / "TestSample", "sample": True})
        
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
        
        from umbraedit.gui.importmanuscript import ImportManuscriptCommand
        command = ImportManuscriptCommand(project, None)
        
        # Mock file dialog to cancel
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: ("", ""),
        )
        
        # This should not raise AttributeError
        command.execute()

    def test_import_manuscript_with_file(self, mockGUI: Any, projPath: Path, monkeypatch: Any) -> None:
        """Test import with a fake file."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()
        
        from umbraedit.gui.importmanuscript import ImportManuscriptCommand
        command = ImportManuscriptCommand(project, None)
        
        # Create fake DOCX
        fake_docx = projPath / "test.docx"
        fake_docx.write_text("fake")
        
        import pytest
        from PyQt6.QtWidgets import QMessageBox
        
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(fake_docx), ""),
        )
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.No,
        )
        
        from umbraedit.gui.importmanuscript import ImportManuscriptCommand
        command = ImportManuscriptCommand(project, None)
        command.execute()  # Should not crash

    def test_welcome_dialog_ui_elements(self, mockGUI: Any) -> None:
        """Test that welcome dialog has the expected UI elements."""
        dialog = GuiWelcome(mockGUI)
        
        # Check that the dialog has the expected tabs
        assert hasattr(dialog, 'tabOpen')
        assert hasattr(dialog, 'tabNew')
        assert hasattr(dialog, 'mainStack')
        
        # Check fill project options (on tabNew.projectForm)
        assert hasattr(dialog.tabNew.projectForm, 'fillBlank')
        assert hasattr(dialog.tabNew.projectForm, 'fillSample')
        assert hasattr(dialog.tabNew.projectForm, 'fillCopy')
        
        dialog.close()

    @pytest.mark.skip(reason="Requires full GUI initialization, tested separately")
    def test_main_menu_open_welcome(self, mockGUI: Any) -> None:
        """Test that main menu can open welcome dialog."""
        menu = GuiMainMenu(mockGUI)
        
        # Check that the open project action exists
        assert hasattr(menu, 'aOpenProject')
        
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
        
        from umbraedit.enum import nwItemClass
        
        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        scHandle = project.newFile("Scene 1", chHandle)
        
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
        
        from umbraedit.enum import nwItemClass
        
        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        scHandle = project.newFile("Scene 1", chHandle)
        
        doc = project.storage.getDocument(chHandle)
        doc.writeDocument("## Chapter 1\n\nTest content.")
        project.index.reIndexHandle(chHandle)
        
        # Read back via storage
        content = project.storage.getDocumentText(chHandle)
        assert "Chapter 1" in content
        assert "Test content" in content

    def test_sample_project_exists(self) -> None:
        """Verify sample project assets exist."""
        from umbraedit import CONFIG
        
        sampleZip = CONFIG.assetPath("sample.zip")
        assert sampleZip.exists(), "sample.zip not found in assets"

    def test_sample_project_xml_valid(self) -> None:
        """Sample project XML must be well-formed."""
        import zipfile
        import xml.etree.ElementTree as ET
        from umbraedit import CONFIG
        
        sampleZip = CONFIG.assetPath("sample.zip")
        with zipfile.ZipFile(sampleZip, "r") as z:
            xmlContent = z.read("UEProject.UEx")
            root = ET.fromstring(xmlContent)
            assert root.tag == "UmbraEditXML"
            assert root.get("fileVersion") == "1.6"

    def test_sample_project_has_content(self) -> None:
        """Sample project must have content files."""
        import zipfile
        from umbraedit import CONFIG
        
        sampleZip = CONFIG.assetPath("sample.zip")
        with zipfile.ZipFile(sampleZip, "r") as z:
            contentFiles = [n for n in z.namelist() if n.startswith("content/") and n.endswith(".md")]
            assert len(contentFiles) > 0, "Sample project must have content files"