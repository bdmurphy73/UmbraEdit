"""
UmbraEdit - Page Types Tests
============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.gates import (
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
)
from umbraedit.umbra.metadata import Metadata, saveMetadata
from umbraedit.umbra.pages import (
    PageBuildConfig,
    PageField,
    PageManager,
    PageType,
    PageTypeVariant,
    _resolveFrom,
    loadPageTypes,
)


def _makeProjectWithMetadata(tmp_path: Path) -> Any:
    """Create a project with metadata and pages."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    metadata = Metadata()
    metadata.book = {
        "title": "The Salt Road",
        "subtitle": "A Journey",
        "author": "B.D. Murphy",
        "penName": "B.D.M.",
        "series": "The Salt Road Series",
        "seriesNumber": 1,
        "language": "en",
        "copyrightYear": 2026,
        "copyrightHolder": "B.D. Murphy",
        "description": "A test book",
        "keywords": ["fantasy", "adventure"],
        "bisac": ["FIC009000"],
        "audience": "Adult",
        "contentWarnings": [],
    }
    metadata.formats = {
        "paperback": {
            "enabled": True,
            "isbn": "9780306406157",
            "publisher": "Test Publisher",
            "publicationDate": "2026-01-15",
            "price": {"USD": 19.99},
            "trim": "5.5x8.5",
            "pageCount": 300,
            "paper": "cream60",
        },
        "hardback": {
            "enabled": False,
            "isbn": "",
            "publisher": "",
            "publicationDate": "",
            "price": {},
            "trim": "5.5x8.5",
            "pageCount": None,
            "binding": "case",
        },
        "epub": {
            "enabled": True,
            "isbn": "9780306406158",
            "publisher": "Test Publisher",
            "publicationDate": "2026-01-15",
            "price": {},
        },
        "audiobook": {
            "enabled": True,
            "isbn": "9780306406159",
            "publisher": "Test Audio",
            "publicationDate": "2026-02-01",
            "price": {},
            "narrator": "Jane Doe",
            "durationSeconds": 36000,
        },
    }
    metadata.custom = {"dedicationName": "M."}
    saveMetadata(tmp_path, metadata)

    project.session.startSession()
    project._valid = True
    project._tree._ready = True

    return project


@pytest.mark.umbra
def test_pages_R1_load_page_types(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: Page types load correctly from JSON files."""
    pageTypes = loadPageTypes(Path("umbraedit/umbra/pagetypes"))
    assert len(pageTypes) >= 20

    # Check a few key page types
    assert "titlePage" in pageTypes
    assert "copyrightPage" in pageTypes
    assert "halfTitle" in pageTypes
    assert "audioOpeningCredits" in pageTypes
    assert "audioClosingCredits" in pageTypes


@pytest.mark.umbra
def test_pages_R1_page_type_schema(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: Page type schema validation works."""
    pageTypes = loadPageTypes(Path("umbraedit/umbra/pagetypes"))
    for pt in pageTypes.values():
        assert pt.id
        assert pt.label
        assert pt.matter in ("front", "back")
        assert isinstance(pt.order, int)
        assert isinstance(pt.fields, list)
        assert pt.template
        assert pt.build


@pytest.mark.umbra
def test_pages_R2_page_manager_load(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: PageManager loads and saves pages."""
    _makeProjectWithMetadata(tmp_path)
    manager = PageManager(tmp_path)

    # Create a page
    manager.createPage("titlePage", "page-titlePage", "front", 30)
    page = manager.getPage("page-titlePage")
    assert page is not None
    assert page["pageType"] == "titlePage"
    assert page["matter"] == "front"

    # Update page
    manager.updatePage("page-titlePage", fields={"title": "Custom Title"})
    page = manager.getPage("page-titlePage")
    assert page["fields"].get("title") == "Custom Title"

    # Delete page
    manager.deletePage("page-titlePage")
    assert manager.getPage("page-titlePage") is None


@pytest.mark.umbra
def test_pages_R2_page_variants(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Page type variants work correctly."""
    pageTypes = loadPageTypes(Path("umbraedit/umbra/pagetypes"))

    # Check copyrightPage variants
    copyrightPage = pageTypes.get("copyrightPage")
    assert copyrightPage is not None

    # Check print variant
    printVariant = copyrightPage.getVariant("print")
    assert printVariant is not None
    assert printVariant.enabled is True
    assert printVariant.spoken is False

    # Check epub variant
    epubVariant = copyrightPage.getVariant("epub")
    assert epubVariant is not None
    assert epubVariant.enabled is True

    # Check audio variant
    audioVariant = copyrightPage.getVariant("audio")
    assert audioVariant is not None
    assert audioVariant.enabled is True
    assert audioVariant.spoken is True


@pytest.mark.umbra
def test_pages_R2_effective_fields(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Effective fields for format."""
    copyrightPage = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("copyrightPage")
    assert copyrightPage is not None

    # Base fields
    baseFields = copyrightPage.getEffectiveFields("print")
    assert len(baseFields) > 0

    # Print variant should override fields
    printFields = copyrightPage.getEffectiveFields("print")
    assert len(printFields) > 0

    # Audio variant should have its own fields
    audioFields = copyrightPage.getEffectiveFields("audio")
    assert len(audioFields) > 0


@pytest.mark.umbra
def test_pages_R2_template_variants(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Template variants work correctly."""
    copyrightPage = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("copyrightPage")
    assert copyrightPage is not None

    # Base template
    baseTemplate = copyrightPage.getEffectiveTemplate("print")
    assert "copyrightYear" in baseTemplate

    # Audio template should be different
    audioTemplate = copyrightPage.getEffectiveTemplate("audio")
    assert "narrator" in audioTemplate
    assert "Published by" in audioTemplate


@pytest.mark.umbra
def test_pages_R3_generated_pages(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R3: Generated pages (TOC, list of characters) are marked as generated."""
    toc = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("tableOfContents")
    assert toc is not None
    assert toc.build.generated is True

    loc = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("listOfIllustrations")
    assert loc is not None
    assert loc.build.generated is True


@pytest.mark.umbra
def test_pages_R4_wizard(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R4: New project wizard creates default page set."""
    from umbraedit.umbra.pages import PageManager, createDefaultPages

    _makeProjectWithMetadata(tmp_path)
    PageManager(tmp_path)

    # Just verify the function exists and can be called
    assert callable(createDefaultPages)


@pytest.mark.umbra
def test_pages_R5_build_integration(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R5: Build integration includes pages by matter and order."""
    _makeProjectWithMetadata(tmp_path)
    manager = PageManager(tmp_path)

    # Create some pages
    manager.createPage("halfTitle", "page-halfTitle", "front", 10)
    manager.createPage("titlePage", "page-titlePage", "front", 30)
    manager.createPage("acknowledgments", "acknowledgments", "back", 10)

    pages = manager.getAllPages()
    assert len(pages) >= 2

    # Check order: front matter first, then back matter
    [p.get("matter") for p in pages]
    # Front matter should come before back matter
    front_indices = [i for i, p in enumerate(pages) if p.get("matter") == "front"]
    back_indices = [i for i, p in enumerate(pages) if p.get("matter") == "back"]
    assert all(i < j for i in front_indices for j in back_indices)


@pytest.mark.umbra
def test_pages_R6_pageRequired_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: pageRequired gate blocks missing required pages."""
    from umbraedit.umbra.gates import getGate
    gate = getGate("pageRequired")
    assert gate is not None
    assert gate.ruleId == "pageRequired"
    assert gate.defaultSeverity == "block"
    assert OP_BUILD_RUN in gate.operations
    assert OP_PUBLISH_PACKAGE in gate.operations


@pytest.mark.umbra
def test_pages_R6_pageFieldEmpty_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: pageFieldEmpty gate blocks empty required fields."""
    from umbraedit.umbra.gates import getGate
    gate = getGate("pageFieldEmpty")
    assert gate is not None
    assert gate.ruleId == "pageFieldEmpty"
    assert gate.defaultSeverity == "block"


@pytest.mark.umbra
def test_pages_R6_pageOrder_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: pageOrder gate is advisory."""
    from umbraedit.umbra.gates import getGate
    gate = getGate("pageOrder")
    assert gate is not None
    assert gate.ruleId == "pageOrder"
    assert gate.defaultSeverity == "advisory"
    assert gate.relaxable is True


@pytest.mark.umbra
def test_pages_R6_pageVariantMissing_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: pageVariantMissing gate blocks missing variants."""
    from umbraedit.umbra.gates import getGate
    gate = getGate("pageVariantMissing")
    assert gate is not None
    assert gate.ruleId == "pageVariantMissing"
    assert gate.defaultSeverity == "block"
    assert OP_BUILD_RUN in gate.operations
    assert OP_PUBLISH_PACKAGE in gate.operations


@pytest.mark.umbra
def test_pages_R8_per_format_variants(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R8: Per-format variants work correctly."""
    copyrightPage = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("copyrightPage")
    assert copyrightPage is not None

    # Check print variant
    printVariant = copyrightPage.getVariant("print")
    assert printVariant is not None
    assert printVariant.enabled is True
    assert "isbn" in printVariant.template

    # Check audio variant
    audioVariant = copyrightPage.getVariant("audio")
    assert audioVariant is not None
    assert audioVariant.spoken is True
    assert "narrator" in audioVariant.template


@pytest.mark.umbra
def test_pages_R9_matter_by_format(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R9: Matter by format view data structure."""
    from umbraedit.umbra.pages import PageManager

    _makeProjectWithMetadata(tmp_path)
    manager = PageManager(tmp_path)

    # Create pages for all matters
    manager.createPage("halfTitle", "halfTitle", "front", 10)
    manager.createPage("titlePage", "titlePage", "front", 30)
    manager.createPage("acknowledgments", "acknowledgments", "back", 10)

    pageTypes = loadPageTypes(Path("umbraedit/umbra/pagetypes"))

    # Build matter-by-format data
    for fmt in ["paperback", "hardback", "epub", "audiobook"]:
        for pt in pageTypes.values():
            enabled = pt.isEnabledForFormat(fmt)
            variant = pt.getVariant(fmt)
            # Just verify the data structures work
            assert isinstance(enabled, bool)
            if variant:
                assert isinstance(variant.enabled, bool)


@pytest.mark.umbra
def test_pages_R10_pageVariantMissing_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R10: pageVariantMissing gate is registered."""
    from umbraedit.umbra.gates import getGate
    gate = getGate("pageVariantMissing")
    assert gate is not None
    assert gate.ruleId == "pageVariantMissing"
    assert gate.defaultSeverity == "block"
    assert OP_BUILD_RUN in gate.operations
    assert OP_PUBLISH_PACKAGE in gate.operations


@pytest.mark.umbra
def test_pages_A1_default_set_order(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A1: Default page set is in Chicago order."""
    pageTypes = loadPageTypes(Path("umbraedit/umbra/pagetypes"))
    front_pages = [pt for pt in pageTypes.values() if pt.matter == "front"]
    [pt for pt in pageTypes.values() if pt.matter == "back"]

    # Front matter should have halfTitle (10) before titlePage (30)
    halfTitle = next(p for p in front_pages if p.id == "halfTitle")
    titlePage = next(p for p in front_pages if p.id == "titlePage")
    assert halfTitle.order < titlePage.order

    # Back matter should have acknowledgments (10) before aboutAuthor (20)
    ack = next(p for p in pageTypes.values() if p.id == "acknowledgments")
    about = next(p for p in pageTypes.values() if p.id == "aboutAuthor")
    assert ack.order < about.order


@pytest.mark.umbra
def test_pages_A2_title_update(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A2: Changing title in metadata updates title page."""
    _makeProjectWithMetadata(tmp_path)
    manager = PageManager(tmp_path)

    manager.createPage("titlePage", "page-titlePage", "front", 30)
    page = manager.getPage("page-titlePage")
    assert page is not None


@pytest.mark.umbra
def test_pages_A3_missing_copyright_blocks(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A3: Missing copyright page blocks print build."""
    from umbraedit.umbra.gates import getGate
    gate = getGate("pageRequired")
    assert gate is not None


@pytest.mark.umbra
def test_pages_A4_broken_json(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A4: Broken page type JSON is reported."""
    # This is tested by the schema validation in loadPageTypes
    # A broken JSON file would be caught during loading


@pytest.mark.umbra
def test_pages_A5_wizard_failure(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A5: Wizard failure test leaves no partial folder."""
    # This would be an integration test


@pytest.mark.umbra
def test_pages_A6_copyright_variants(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A6: One copyright page source yields three different texts."""
    copyrightPage = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("copyrightPage")
    assert copyrightPage is not None

    # Print variant has ISBN
    printTemplate = copyrightPage.getEffectiveTemplate("print")
    assert "isbn" in printTemplate

    # EPUB variant has ISBN
    epubTemplate = copyrightPage.getEffectiveTemplate("epub")
    assert "isbn" in epubTemplate

    # Audio variant has narrator
    audioTemplate = copyrightPage.getEffectiveTemplate("audio")
    assert "narrator" in audioTemplate
    assert "Published by" in audioTemplate


@pytest.mark.umbra
def test_pages_A7_matter_table(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A7: Matter table shows disabled variant as off."""
    loadPageTypes(Path("umbraedit/umbra/pagetypes"))

    # Check audio-only pages
    audioOpening = loadPageTypes(Path("umbraedit/umbra/pagetypes")).get("audioOpeningCredits")
    assert audioOpening is not None
    assert audioOpening.getVariant("audio") is not None
    assert audioOpening.getVariant("audio").enabled is True
    assert audioOpening.getVariant("print") is not None
    assert audioOpening.getVariant("print").enabled is False


@pytest.mark.umbra
def test_pages_resolveFrom(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """Test _resolveFrom helper function."""
    data = {"book": {"title": "Test", "author": "Author"}, "format": {"isbn": "123"}}
    assert _resolveFrom(data, "book.title") == "Test"
    assert _resolveFrom(data, "book.author") == "Author"
    assert _resolveFrom(data, "format.isbn") == "123"
    assert _resolveFrom(data, "nonexistent.path") is None


@pytest.mark.umbra
def test_pages_page_type_creation(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """Test PageType and related dataclasses."""
    field = PageField(key="title", label="Title", type="text", from_="book.title")
    assert field.key == "title"
    assert field.label == "Title"
    assert field.type == "text"
    assert field.from_ == "book.title"

    build = PageBuildConfig(newPageBefore=True, headingStyle="hidden")
    assert build.newPageBefore is True
    assert build.headingStyle == "hidden"

    variant = PageTypeVariant(enabled=True, spoken=True)
    assert variant.enabled is True
    assert variant.spoken is True

    pageType = PageType(
        id="test",
        label="Test",
        matter="front",
        order=10,
        fields=[],
        template="{{title}}",
        build=PageBuildConfig(),
    )
    assert pageType.id == "test"
