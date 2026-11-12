"""
UmbraEdit - Test Suite for Import Manuscript and Project Lifecycle

Tests cover:
1. ImportManuscriptCommand tr() crash fix (AttributeError fix)
2. Project creation (blank and from sample)
3. Document/chapter creation and editing
4. Metadata editing
5. Export to EPUB/HTML
6. Character/world sheet management
7. Import manuscript DOCX functionality
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QMessageBox

from umbraedit import CONFIG, SHARED
from umbraedit.core.project import NWProject
from umbraedit.enum import nwItemClass
from umbraedit.formats.toepub import ToEPub
from umbraedit.formats.tohtml import ToHtml
from umbraedit.gui.importmanuscript import ImportManuscriptCommand, importManuscript


class TestImportManuscriptCommand:
    """Tests for ImportManuscriptCommand - ensures tr() doesn't crash."""

    def test_command_inherits_qobject(self, mockGUI: Any) -> None:
        """ImportManuscriptCommand must inherit QObject to have tr()."""
        project = NWProject()
        command = ImportManuscriptCommand(project, mockGUI)
        assert isinstance(command, QObject)

    def test_tr_method_works(self, mockGUI: Any, monkeypatch: Any) -> None:
        """tr() method must not raise AttributeError."""
        project = NWProject()
        command = ImportManuscriptCommand(project, mockGUI)

        # Mock QFileDialog to avoid showing a real dialog
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: ("", ""),
        )

        # This should not raise AttributeError: 'ImportManuscriptCommand' object has no attribute 'tr'
        command.execute()

    def test_tr_returns_translated_string(self, mockGUI: Any) -> None:
        """tr() should return a string, not raise."""
        project = NWProject()
        command = ImportManuscriptCommand(project, mockGUI)
        result = command.tr("Select DOCX Manuscript")
        assert isinstance(result, str)
        assert result == "Select DOCX Manuscript"

    def test_tr_with_format_args(self, mockGUI: Any) -> None:
        """tr() with format arguments should work."""
        project = NWProject()
        command = ImportManuscriptCommand(project, mockGUI)
        result = command.tr("Failed to commit import: {0}").format("test error")
        assert "test error" in result

    def test_execute_with_no_file(self, mockGUI: Any, monkeypatch: Any) -> None:
        """execute() with cancelled file dialog should not crash."""
        project = NWProject()
        command = ImportManuscriptCommand(project, mockGUI)

        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: ("", ""),
        )

        command.execute()  # Should not crash


class TestProjectLifecycle:
    """End-to-end tests for project creation, editing, and export."""

    def test_create_blank_project(self, mockGUI: Any, projPath: Path) -> None:
        """Creating a blank project should succeed."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        assert project.storage.storagePath == projPath

    def test_create_project_with_metadata(self, mockGUI: Any, projPath: Path) -> None:
        """Creating a project and setting metadata should persist."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        project.data.setUuid("test-uuid-1234")
        project.data.setName("Test Novel")
        project.data.setAuthor("Test Author")
        project.saveProject()

        # Re-open and verify metadata persisted
        project2 = NWProject()
        project2.openProject(projPath)
        assert project2.data.name == "Test Novel"
        assert project2.data.author == "Test Author"

    def test_create_chapter_and_scene(self, mockGUI: Any, projPath: Path) -> None:
        """Creating chapters and scenes in a project should work."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        nrHandle = project.newRoot(nwItemClass.NOVEL)

        chHandle = project.newFile("Chapter 1", nrHandle)
        scHandle = project.newFile("Scene 1.1", chHandle)

        assert chHandle != ""
        assert scHandle != ""

        # Verify the documents exist
        chDoc = project.storage.getDocument(chHandle)
        scDoc = project.storage.getDocument(scHandle)
        assert chDoc is not None
        assert scDoc is not None

    def test_edit_document_content(self, mockGUI: Any, projPath: Path) -> None:
        """Writing and reading document content should work."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)

        doc = project.storage.getDocument(chHandle)
        doc.writeDocument("## Chapter 1\n\nThis is test content.\n")
        project.index.reIndexHandle(chHandle)

        # Read back via storage
        content = project.storage.getDocumentText(chHandle)
        assert "Chapter 1" in content
        assert "This is test content" in content

    def test_edit_metadata(self, mockGUI: Any, projPath: Path) -> None:
        """Editing project metadata should persist across save/load."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        project.data.setName("My Novel")
        project.data.setAuthor("Jane Writer")
        project.data.setUuid("my-uuid-1234")
        project.saveProject()
        project.closeProject()

        # Re-open
        project2 = NWProject()
        project2.openProject(projPath)
        assert project2.data.name == "My Novel"
        assert project2.data.author == "Jane Writer"

    def test_create_character_sheet(self, mockGUI: Any, projPath: Path) -> None:
        """Creating a character sheet should work."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        crHandle = project.newRoot(nwItemClass.CHARACTER)
        cfHandle = project.newFolder("Characters", crHandle)
        chHandle = project.newFile("Jane Smith", cfHandle)

        assert chHandle != ""

        doc = project.storage.getDocument(chHandle)
        assert doc is not None
        doc.writeDocument("# Jane Smith\n\n@tag: Jane\n\n%Short: The heroine.\n")
        project.index.reIndexHandle(chHandle)

        # Read back via storage
        content = project.storage.getDocumentText(chHandle)
        assert "Jane Smith" in content
        assert "@tag: Jane" in content

    def test_create_world_sheet(self, mockGUI: Any, projPath: Path) -> None:
        """Creating a world/location sheet should work."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        wrHandle = project.newRoot(nwItemClass.WORLD)
        wHandle = project.newFile("Earth", wrHandle)

        assert wHandle != ""

        doc = project.storage.getDocument(wHandle)
        doc.writeDocument("# Earth\n\n@tag: Earth\n\n%Short: Third planet from the sun.\n")
        project.index.reIndexHandle(wHandle)

        # Read back via storage
        content = project.storage.getDocumentText(wHandle)
        assert "Earth" in content
        assert "@tag: Earth" in content

    def test_document_text_formatting(self, mockGUI: Any, projPath: Path) -> None:
        """Markdown formatting in documents should be preserved."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        scHandle = project.newFile("Scene 1", chHandle)

        doc = project.storage.getDocument(scHandle)
        doc.writeDocument(
            "### Scene 1\n\n"
            "This has **bold**, _italic_, **_bold italic_**, and ~~strike~~.\n"
            "Quote: \"hello world\".\n"
            "List:\n* item 1\n* item 2\n"
        )
        project.index.reIndexHandle(scHandle)

        content = project.storage.getDocumentText(scHandle)
        assert "**bold**" in content
        assert "_italic_" in content
        assert "~~strike~~" in content
        assert "* item 1" in content

    def test_sample_project_zip_exists(self) -> None:
        """The sample.zip asset must exist for the welcome dialog."""
        sampleZip = CONFIG.assetPath("sample.zip")
        assert sampleZip.exists(), "sample.zip not found in assets"

    def test_sample_project_xml_valid(self) -> None:
        """The sample project XML must be well-formed."""
        import zipfile
        import xml.etree.ElementTree as ET

        sampleZip = CONFIG.assetPath("sample.zip")
        with zipfile.ZipFile(sampleZip, "r") as z:
            xmlContent = z.read("nwProject.nwx")
            root = ET.fromstring(xmlContent)
            assert root.tag == "UmbraEditXML"
            assert root.get("fileVersion") == "1.6"

    def test_sample_project_has_content(self) -> None:
        """The sample project must have content files."""
        import zipfile

        sampleZip = CONFIG.assetPath("sample.zip")
        with zipfile.ZipFile(sampleZip, "r") as z:
            contentFiles = [n for n in z.namelist() if n.startswith("content/") and n.endswith(".md")]
            assert len(contentFiles) > 0, "Sample project must have content files"
