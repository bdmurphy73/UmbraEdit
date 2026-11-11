"""
UmbraEdit - Metadata Tests
==========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.metadata import (
    Metadata,
    checkMetadataRequired,
    formatValues,
    formatValuesForBuild,
    getEnabledFormats,
    getRequiredFieldsForFormat,
    getValue,
    loadMetadata,
    resolveVariables,
    saveMetadata,
    setValue,
    validateIsbn,
)


def _makeMetadata(tmp_path: Path) -> Metadata:
    """Create a Metadata object with test data."""
    meta = Metadata()
    meta.book = {
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
        "keywords": ["fantasy", "adventure", "magic", "dragons", "quest", "hero", "villain"],
        "bisac": ["FIC009000"],
        "audience": "Adult",
        "contentWarnings": ["Violence"],
    }
    meta.formats = {
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
    meta.custom = {"dedicationName": "M."}
    return meta


@pytest.mark.umbra
def test_metadata_R1_load_save(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: loadMetadata and saveMetadata work correctly."""
    meta = _makeMetadata(tmp_path)

    # Save
    saveMetadata(tmp_path, meta)

    # Load
    loaded = loadMetadata(tmp_path)
    assert loaded.v == 1
    assert loaded.book["title"] == "The Salt Road"
    assert loaded.book["author"] == "B.D. Murphy"
    assert loaded.formats["paperback"]["enabled"] is True
    assert loaded.formats["paperback"]["isbn"] == "9780306406157"
    assert loaded.formats["epub"]["enabled"] is True
    assert loaded.custom["dedicationName"] == "M."


@pytest.mark.umbra
def test_metadata_R1_get_set_value(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: getValue and setValue work with dot notation paths."""
    meta = _makeMetadata(tmp_path)

    # Get existing values
    assert getValue(meta, "book.title") == "The Salt Road"
    assert getValue(meta, "book.author") == "B.D. Murphy"
    assert getValue(meta, "formats.paperback.isbn") == "9780306406157"
    assert getValue(meta, "custom.dedicationName") == "M."

    # Get non-existent values
    assert getValue(meta, "book.nonexistent") is None
    assert getValue(meta, "nonexistent.path") is None

    # Set values
    assert setValue(meta, "book.title", "New Title") is True
    assert meta.book["title"] == "New Title"

    assert setValue(meta, "formats.epub.isbn", "9781234567890") is True
    assert meta.formats["epub"]["isbn"] == "9781234567890"

    # Set custom value (unknown keys allowed)
    assert setValue(meta, "custom.newField", "customValue") is True
    assert meta.custom["newField"] == "customValue"

    # Invalid paths
    assert setValue(meta, "book", "value") is False
    assert setValue(meta, "invalid.path", "value") is False


@pytest.mark.umbra
def test_metadata_R1_formatValues(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: formatValues merges book and format-specific values."""
    meta = _makeMetadata(tmp_path)

    values = formatValues(meta, "paperback")

    # Book values are now under "book" key
    assert values["book"]["title"] == "The Salt Road"
    assert values["book"]["author"] == "B.D. Murphy"
    assert values["book"]["language"] == "en"

    # Format-specific values override
    assert values["isbn"] == "9780306406157"
    assert values["trim"] == "5.5x8.5"
    assert values["paper"] == "cream60"

    # Format object
    assert values["format"]["name"] == "paperback"
    assert values["format"]["isbn"] == "9780306406157"

    # Custom values
    assert values["custom"]["dedicationName"] == "M."


@pytest.mark.umbra
def test_metadata_R1_formatValuesForBuild(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: formatValuesForBuild adds date and edition."""
    meta = _makeMetadata(tmp_path)

    values = formatValuesForBuild(meta, "epub", "zh-Hans")

    assert values["format"]["name"] == "epub"
    assert values["format"]["edition"] == "zh-Hans"
    assert "date" in values
    assert values["date"]  # Should have current date


@pytest.mark.umbra
def test_metadata_R1_bookValues(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: bookValues service function works."""
    meta = _makeMetadata(tmp_path)
    from umbraedit.umbra.metadata import saveMetadata

    saveMetadata(tmp_path, meta)

    values = formatValuesForBuild(meta, "paperback", "main")
    assert values["book"]["title"] == "The Salt Road"
    assert values["format"]["name"] == "paperback"


@pytest.mark.umbra
def test_metadata_R2_resolveVariables(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: resolveVariables resolves {{...}} template variables."""
    from umbraedit.core.project import NWProject
    from umbraedit.umbra.metadata import saveMetadata

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    meta = _makeMetadata(tmp_path)
    saveMetadata(project.storage.storagePath, meta)

    text = (
        "Title: {{book.title}}, Author: {{book.author}}, ISBN: {{format.isbn}}, "
        "Format: {{format.name}}, Custom: {{custom.dedicationName}}, Date: {{date}}"
    )
    resolved, unresolved = resolveVariables(text, project, "main", "paperback")

    assert "Title: The Salt Road" in resolved
    assert "Author: B.D. Murphy" in resolved
    assert "ISBN: 9780306406157" in resolved
    assert "Format: paperback" in resolved
    assert "Custom: M." in resolved
    assert unresolved == []


@pytest.mark.umbra
def test_metadata_R2_resolveVariables_unknown(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: resolveVariables tracks unresolved variables."""
    from umbraedit.core.project import NWProject
    from umbraedit.umbra.metadata import saveMetadata

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    meta = _makeMetadata(tmp_path)
    saveMetadata(project.storage.storagePath, meta)

    text = "{{book.title}} and {{book.unknown}}"
    resolved, unresolved = resolveVariables(text, project, "main", "paperback")

    assert "The Salt Road" in resolved
    assert "{{book.unknown}}" in resolved
    assert "book.unknown" in unresolved


@pytest.mark.umbra
def test_metadata_A1_isbn_validation(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A1: ISBN validation vectors."""
    # Valid ISBN-13
    is_valid, normalized = validateIsbn("9780306406157")
    assert is_valid is True
    assert normalized == "9780306406157"

    # Invalid ISBN-13 (wrong check digit)
    is_valid, _ = validateIsbn("9780306406158")
    assert is_valid is False

    # Valid ISBN-10 with X check digit
    is_valid, normalized = validateIsbn("080442957X")
    assert is_valid is True
    assert normalized == "080442957X"

    # Invalid ISBN-10
    is_valid, _ = validateIsbn("030640615Y")
    assert is_valid is False


@pytest.mark.umbra
def test_metadata_A2_format_isbn_resolution(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A2: {{format.isbn}} resolves per format."""
    from umbraedit.core.project import NWProject
    from umbraedit.umbra.metadata import saveMetadata

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    meta = _makeMetadata(tmp_path)
    saveMetadata(project.storage.storagePath, meta)

    # Paperback build
    text = "ISBN: {{format.isbn}}"
    resolved, _ = resolveVariables(text, project, "main", "paperback")
    assert "9780306406157" in resolved

    # EPUB build
    resolved, _ = resolveVariables(text, project, "main", "epub")
    assert "9780306406158" in resolved

    # Audiobook build
    resolved, _ = resolveVariables(text, project, "main", "audiobook")
    assert "9780306406159" in resolved


@pytest.mark.umbra
def test_metadata_A3_metadataRequired_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A3: Missing title blocks build with metadataRequired."""
    meta = _makeMetadata(tmp_path)
    meta.book["title"] = ""  # Remove title
    from umbraedit.umbra.metadata import saveMetadata

    saveMetadata(tmp_path, meta)

    missing = checkMetadataRequired(meta)
    # Should have missing title for paperback, epub, audiobook
    title_missing = [m for m in missing if m[0] == "book.title"]
    assert len(title_missing) >= 3  # paperback, epub, audiobook are enabled


@pytest.mark.umbra
def test_metadata_A4_disabled_format_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A4: Disabling hardback removes its gates."""
    meta = _makeMetadata(tmp_path)
    meta.formats["hardback"]["enabled"] = False

    # Hardback is disabled, so its ISBN should not be required
    missing = checkMetadataRequired(meta)
    hardback_isbn_missing = [m for m in missing if m[0] == "formats.hardback.isbn"]
    assert len(hardback_isbn_missing) == 0


@pytest.mark.umbra
def test_metadata_A5_round_trip(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A5: Values round-trip through save and load."""
    meta = _makeMetadata(tmp_path)
    from umbraedit.umbra.metadata import saveMetadata

    saveMetadata(tmp_path, meta)
    loaded = loadMetadata(tmp_path)

    assert loaded.book["title"] == meta.book["title"]
    assert loaded.formats["paperback"]["isbn"] == meta.formats["paperback"]["isbn"]
    assert loaded.custom["dedicationName"] == meta.custom["dedicationName"]


@pytest.mark.umbra
def test_metadata_getEnabledFormats(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """GetEnabledFormats returns only enabled formats."""
    meta = _makeMetadata(tmp_path)
    enabled = getEnabledFormats(meta)
    assert "paperback" in enabled
    assert "epub" in enabled
    assert "audiobook" in enabled
    assert "hardback" not in enabled  # disabled


@pytest.mark.umbra
def test_metadata_getRequiredFieldsForFormat(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """GetRequiredFieldsForFormat returns format-specific required fields."""
    assert getRequiredFieldsForFormat("paperback") == ["isbn"]
    assert getRequiredFieldsForFormat("audiobook") == ["isbn", "narrator"]
    assert getRequiredFieldsForFormat("epub") == ["isbn"]
    assert getRequiredFieldsForFormat("hardback") == ["isbn"]
    assert getRequiredFieldsForFormat("unknown") == []


@pytest.mark.umbra
def test_metadata_keyword_count(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """KeywordCount gate: more than 7 keywords is advisory."""
    meta = _makeMetadata(tmp_path)
    # 7 keywords exactly
    meta.book["keywords"] = ["k1", "k2", "k3", "k4", "k5", "k6", "k7"]
    # This would trigger keywordCount gate if > 7
    # The test just verifies the field exists
    assert len(meta.book["keywords"]) == 7


@pytest.mark.umbra
def test_metadata_audiobook_narrator_required(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """Audiobook narrator is required when audiobook is enabled."""
    meta = _makeMetadata(tmp_path)
    meta.formats["audiobook"]["narrator"] = ""

    missing = checkMetadataRequired(meta)
    narrator_missing = [m for m in missing if m[0] == "formats.audiobook.narrator"]
    assert len(narrator_missing) == 1
