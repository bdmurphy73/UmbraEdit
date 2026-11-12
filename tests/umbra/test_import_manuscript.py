"""
UmbraEdit - Test Suite for Import Manuscript and Project Lifecycle

Tests cover:
1. ImportManuscriptCommand tr() crash fix (AttributeError fix)
2. Project creation (blank and from sample)
3. Document/chapter creation and editing
4. Metadata editing
5. Export to EPUB/HTML
6. Character/world sheet management
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QObject

from umbraedit import CONFIG, SHARED
from umbraedit.core.coretools import ProjectBuilder
from umbraedit.core.project import NWProject
from umbraedit.gui.importmanuscript import ImportManuscriptCommand, importManuscript
from umbraedit.enum import nwItemClass


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


class TestProjectLifecycle:
    """End-to-end tests for project creation, editing, and export."""

    def test_create_blank_project(self, projPath: Path) -> None:
        """Creating a blank project should succeed."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        assert project._ready
        assert project.data.name == ""

    def test_create_project_with_metadata(self, projPath: Path) -> None:
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

    def test_create_chapter_and_scene(self, projPath: Path) -> None:
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

    def test_edit_document_content(self, projPath: Path) -> None:
        """Writing and reading document content should work."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)

        doc = project.storage.getDocument(chHandle)
        doc.writeDocument("## Chapter 1\n\nThis is test content.\n")
        project.index.reIndexHandle(chHandle)

        # Read back
        doc2 = project.storage.getDocument(chHandle)
        content = doc2.getDocumentText()
        assert "Chapter 1" in content
        assert "This is test content" in content

    def test_edit_metadata(self, projPath: Path) -> None:
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

    def test_create_character_sheet(self, projPath: Path) -> None:
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

        # Read back
        doc2 = project.storage.getDocument(chHandle)
        content = doc2.getDocumentText()
        assert "Jane Smith" in content
        assert "@tag: Jane" in content

    def test_create_world_sheet(self, projPath: Path) -> None:
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

        # Read back
        doc2 = project.storage.getDocument(wHandle)
        content = doc2.getDocumentText()
        assert "Earth" in content
        assert "@tag: Earth" in content

    def test_epub_export(self, projPath: Path) -> None:
        """Exporting to EPUB should produce a valid file."""
        from umbraedit.formats.toepub import EpubWriter

        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        project.data.setName("Test Novel")
        project.data.setAuthor("Test Author")

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        scHandle = project.newFile("Scene 1", chHandle)

        doc = project.storage.getDocument(scHandle)
        doc.writeDocument("### Scene 1\n\nThis is scene content.\n")
        project.index.reIndexHandle(scHandle)

        project.saveProject()
        project.closeProject()

        # Re-open for export
        project2 = NWProject()
        project2.openProject(projPath)

        epubPath = projPath / "output.epub"
        writer = EpubWriter()
        result = writer.export(project2, epubPath)

        assert result is True or result is None  # May return None on success
        assert epubPath.exists()

    def test_html_export(self, projPath: Path) -> None:
        """Exporting to HTML should produce a valid file."""
        from umbraedit.formats.tohtml import HtmlWriter

        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        project.data.setName("Test Novel")
        project.data.setAuthor("Test Author")

        nrHandle = project.newRoot(nwItemClass.NOVEL)
        chHandle = project.newFile("Chapter 1", nrHandle)
        scHandle = project.newFile("Scene 1", chHandle)

        doc = project.storage.getDocument(scHandle)
        doc.writeDocument("### Scene 1\n\nThis is scene content.\n")
        project.index.reIndexHandle(scHandle)

        project.saveProject()
        project.closeProject()

        project2 = NWProject()
        project2.openProject(projPath)

        htmlPath = projPath / "output.html"
        writer = HtmlWriter()
        result = writer.export(project2, htmlPath)

        assert result is True or result is None
        assert htmlPath.exists()

    def test_document_text_formatting(self, projPath: Path) -> None:
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

        doc2 = project.storage.getDocument(scHandle)
        content = doc2.getDocumentText()
        assert "**bold**" in content
        assert "_italic_" in content
        assert "~~strike~~" in content
        assert "* item 1" in content

    def test_import_manuscript_no_crash(self, projPath: Path, monkeypatch: Any, mockGUI: Any) -> None:
        """ImportManuscriptCommand.execute() must not crash with AttributeError."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        # Mock QFileDialog to return no file (cancel)
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: ("", ""),
        )

        command = ImportManuscriptCommand(project, mockGUI)
        # This should not raise AttributeError about tr()
        command.execute()

    def test_import_manuscript_with_file(self, projPath: Path, monkeypatch: Any, mockGUI: Any) -> None:
        """ImportManuscriptCommand with a valid DOCX file path."""
        project = NWProject()
        project.storage.createNewProject(projPath)
        project.setDefaultStatusImport()

        # Create a fake DOCX file
        fakeDocx = projPath / "test.docx"
        fakeDocx.write_text("fake docx content")

        # Mock QFileDialog to return our fake file
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(fakeDocx), ""),
        )

        # Mock QMessageBox to avoid showing dialogs
        monkeypatch.setattr(
            "umbraedit.gui.importmanuscript.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.No,
        )

        command = ImportManuscriptCommand(project, mockGUI)
        command.execute()  # Should not crash

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
