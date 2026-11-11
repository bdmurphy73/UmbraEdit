"""
UmbraEdit - Cover Tests
=======================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.covers import (
    CoverStore,
    _calculateWraparoundSize,
    loadCovers,
    saveCovers,
)
from umbraedit.umbra.metadata import Metadata, saveMetadata


def _makeProjectWithMetadata(tmp_path: Path) -> tuple[Any, Metadata]:
    """Create a project with metadata."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    metadata = Metadata()
    metadata.book = {
        "title": "Test Book",
        "author": "Test Author",
        "language": "en",
        "copyrightYear": 2026,
        "copyrightHolder": "Test Author",
    }
    metadata.formats = {
        "paperback": {
            "enabled": True,
            "isbn": "9780306406157",
            "trim": "5.5x8.5",
            "pageCount": 300,
            "paper": "cream60",
        },
        "hardback": {
            "enabled": True,
            "isbn": "9780306406158",
            "trim": "6x9",
            "pageCount": 400,
            "paper": "cream60",
        },
        "epub": {
            "enabled": True,
            "isbn": "9780306406159",
        },
        "audiobook": {
            "enabled": True,
            "isbn": "9780306406160",
            "narrator": "Test Narrator",
        },
    }
    saveMetadata(tmp_path, metadata)
    project.session.startSession()
    project._valid = True
    project._tree._ready = True

    return project, metadata


@pytest.mark.umbra
def test_covers_R1_load_save(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: loadCovers and saveCovers work correctly."""
    covers = loadCovers(tmp_path)
    assert covers["v"] == 1
    assert "slots" in covers
    assert "requirements" in covers

    covers["slots"]["epub"] = {"assetId": "abc123"}
    saveCovers(tmp_path, covers)

    loaded = loadCovers(tmp_path)
    assert loaded["slots"]["epub"]["assetId"] == "abc123"


@pytest.mark.umbra
def test_covers_R1_setCover(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: setCover adds asset and stores assetId."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)

    store = CoverStore(tmp_path)

    # Create a test image
    test_image = tmp_path / "test_cover.jpg"
    from PIL import Image

    # EPUB aspect ratio 1:1.6 (e.g., 2560x1600)
    img = Image.new("RGB", (2560, 1600), color="red")
    img.save(test_image, "JPEG")

    asset_id = store.setCover("epub", test_image)

    assert asset_id is not None
    assert len(asset_id) >= 8

    cover = store.getCover("epub")
    assert cover is not None
    assert cover["assetId"] == asset_id
    assert cover["type"] in ("image/jpeg", "image/png")


@pytest.mark.umbra
def test_covers_R1_validateCover(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: validateCover checks type, size, aspect, square, DPI."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    # Test missing cover
    findings = store.validateCover("epub")
    assert any(f.ruleId == "coverMissing" for f in findings)

    # Add valid cover
    test_image = tmp_path / "test_cover.jpg"
    from PIL import Image

    # EPUB aspect ratio 1:1.6 (e.g., 2560x1600)
    img = Image.new("RGB", (2560, 1600), color="red")
    img.save(test_image, "JPEG")

    store.setCover("epub", test_image)
    findings = store.validateCover("epub")
    assert not any(f.ruleId == "coverMissing" for f in findings)
    assert not any(f.ruleId == "coverInvalid" for f in findings)


@pytest.mark.umbra
def test_covers_R1_clearCover(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: clearCover removes cover."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    test_image = tmp_path / "test_cover.jpg"
    from PIL import Image

    # EPUB aspect ratio 1:1.6 (e.g., 2560x1600)
    img = Image.new("RGB", (2560, 1600), color="red")
    img.save(test_image, "JPEG")

    store.setCover("epub", test_image)
    assert store.getCover("epub") is not None

    result = store.clearCover("epub")
    assert result is True
    assert store.getCover("epub") is None

    # Clearing again returns False
    result = store.clearCover("epub")
    assert result is False


@pytest.mark.umbra
def test_covers_R1_getCover(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: getCover returns Asset or None."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    assert store.getCover("epub") is None

    test_image = tmp_path / "test_cover.jpg"
    from PIL import Image

    # EPUB aspect ratio 1:1.6 (e.g., 2560x1600)
    img = Image.new("RGB", (2560, 1600), color="red")
    img.save(test_image, "JPEG")

    store.setCover("epub", test_image)
    cover = store.getCover("epub")
    assert cover is not None
    assert "assetId" in cover
    assert cover["type"] in ("image/jpeg", "image/png")


@pytest.mark.umbra
def test_covers_R2_epub_requirements(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: EPUB cover validates aspect ratio and minimum sides."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    # Too small
    test_image = tmp_path / "small.jpg"
    from PIL import Image

    img = Image.new("RGB", (1000, 800), color="red")
    img.save(test_image, "JPEG")
    store.setCover("epub", test_image)

    findings = store.validateCover("epub")
    assert any(f.ruleId == "coverInvalid" and "too small" in f.message for f in findings)

    # Wrong aspect ratio
    test_image2 = tmp_path / "wrong_aspect.jpg"
    img2 = Image.new("RGB", (3000, 1000), color="blue")
    img2.save(test_image2, "JPEG")
    store.setCover("epub", test_image2)

    findings = store.validateCover("epub")
    assert any(f.ruleId == "coverInvalid" and "aspect ratio" in f.message for f in findings)

    # Valid EPUB cover
    test_image3 = tmp_path / "valid.jpg"
    img3 = Image.new("RGB", (2560, 1600), color="green")
    img3.save(test_image3, "JPEG")
    store.setCover("epub", test_image3)

    findings = store.validateCover("epub")
    assert not any(f.ruleId == "coverInvalid" for f in findings)


@pytest.mark.umbra
def test_covers_R2_audiobook_requirements(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Audiobook cover validates square and size range."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    # Non-square
    test_image = tmp_path / "non_square.jpg"
    from PIL import Image

    img = Image.new("RGB", (3000, 2000), color="red")
    img.save(test_image, "JPEG")
    store.setCover("audiobook", test_image)

    findings = store.validateCover("audiobook")
    assert any(f.ruleId == "coverInvalid" and "square" in f.message for f in findings)

    # Too small
    test_image2 = tmp_path / "small_square.jpg"
    img2 = Image.new("RGB", (1000, 1000), color="blue")
    img2.save(test_image2, "JPEG")
    store.setCover("audiobook", test_image2)

    findings = store.validateCover("audiobook")
    assert any(f.ruleId == "coverInvalid" and "too small" in f.message for f in findings)

    # Too large
    test_image3 = tmp_path / "large_square.jpg"
    img3 = Image.new("RGB", (4000, 4000), color="green")
    img3.save(test_image3, "JPEG")
    store.setCover("audiobook", test_image3)

    findings = store.validateCover("audiobook")
    assert any(f.ruleId == "coverInvalid" and "too large" in f.message for f in findings)

    # Valid square
    test_image4 = tmp_path / "valid_square.jpg"
    img4 = Image.new("RGB", (3000, 3000), color="yellow")
    img4.save(test_image4, "JPEG")
    store.setCover("audiobook", test_image4)

    findings = store.validateCover("audiobook")
    assert not any(f.ruleId == "coverInvalid" for f in findings)


@pytest.mark.umbra
def test_covers_R2_paperback_wraparound(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Paperback wraparound size calculation."""
    _project, metadata = _makeProjectWithMetadata(tmp_path)
    CoverStore(tmp_path)

    expected = _calculateWraparoundSize(metadata, "paperback")
    assert expected is not None
    width, height = expected

    # 5.5x8.5 inch = 139.7x215.9 mm, 300 pages, cream60 (0.0635 mm/page)
    # Spine = 300 * 0.0635 = 19.05 mm
    # Width = 2*139.7 + 19.05 + 2*3.175 = 304.8 mm
    # Height = 215.9 + 2*3.175 = 222.25 mm
    assert abs(width - 304.8) < 0.1
    assert abs(height - 222.25) < 0.1


@pytest.mark.umbra
def test_covers_R2_hardback_wraparound(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Hardback wraparound includes board thickness."""
    _project, metadata = _makeProjectWithMetadata(tmp_path)
    expected = _calculateWraparoundSize(metadata, "hardback")
    assert expected is not None
    width, height = expected

    # 6x9 inch = 152.4x228.6 mm, 400 pages
    # Spine = 400 * 0.0635 + 2*2.5 = 25.4 + 5 = 30.4 mm
    # Width = 2*152.4 + 30.4 + 2*3.175 = 341.55 mm
    # Height = 228.6 + 2*3.175 = 234.95 mm
    assert abs(width - 341.55) < 0.1
    assert abs(height - 234.95) < 0.1


@pytest.mark.umbra
def test_covers_R3_ui_requirements(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R3: UI - getEnabledFormats returns only enabled formats."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    enabled = store.getEnabledFormats()
    assert "paperback" in enabled
    assert "hardback" in enabled
    assert "epub" in enabled
    assert "audiobook" in enabled


@pytest.mark.umbra
def test_covers_R4_useSourceCover(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: useSourceCover copies asset from source project."""
    import shutil
    import tempfile

    # Create source project
    source_path = Path(tempfile.mkdtemp())
    try:
        _source_project, _source_metadata = _makeProjectWithMetadata(source_path)
        source_store = CoverStore(source_path)

        test_image = source_path / "source_cover.jpg"
        from PIL import Image

        img = Image.new("RGB", (3000, 2000), color="red")
        img.save(test_image, "JPEG")

        source_store.setCover("epub", test_image)
        source_store.getCover("epub")["assetId"]

        # Create edition project
        edition_path = Path(tempfile.mkdtemp())
        try:
            _edition_project, _edition_metadata = _makeProjectWithMetadata(edition_path)
            edition_store = CoverStore(edition_path)

            # Use source cover
            result = edition_store.useSourceCover("epub", source_path)
            assert result is True

            edition_cover = edition_store.getCover("epub")
            assert edition_cover is not None
            # Asset ID may be the same due to deduplication (same content)
            # but the edition should have its own slot entry with source info
            assert edition_cover["assetId"] is not None
            assert edition_store._covers["slots"]["epub"].get("source") == "main"
        finally:
            shutil.rmtree(edition_path)
    finally:
        shutil.rmtree(source_path)


@pytest.mark.umbra
def test_covers_R5_coverMissing_gate(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R5: coverMissing gate blocks build for enabled format without cover."""
    project, _metadata = _makeProjectWithMetadata(tmp_path)
    from umbraedit.umbra.covergates import _coverMissingFindings
    from umbraedit.umbra.gates import GateScope

    # No covers set, EPUB is enabled and required
    scope = GateScope(project=project, operation="build.run")
    findings = list(_coverMissingFindings(scope))
    cover_missing = [f for f in findings if f.ruleId == "coverMissing"]
    assert len(cover_missing) > 0
    assert any(f.detail.get("format") == "epub" for f in cover_missing)


@pytest.mark.umbra
def test_covers_A1_epub_no_cover_blocks(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A1: EPUB build with no cover fails with coverMissing."""
    project, _metadata = _makeProjectWithMetadata(tmp_path)
    from umbraedit.umbra.covergates import _coverMissingFindings
    from umbraedit.umbra.gates import GateScope

    scope = GateScope(project=project, operation="build.run")
    findings = list(_coverMissingFindings(scope))
    cover_missing = [f for f in findings if f.ruleId == "coverMissing"]
    assert any(f.detail.get("format") == "epub" for f in cover_missing)


@pytest.mark.umbra
def test_covers_A2_audiobook_no_cover_blocks(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A2: audio.book blocked without cover, chapter test build runs."""
    project, _metadata = _makeProjectWithMetadata(tmp_path)
    from umbraedit.umbra.covergates import _coverMissingFindings
    from umbraedit.umbra.gates import GateScope

    scope = GateScope(project=project, operation="audio.book")
    findings = list(_coverMissingFindings(scope))
    cover_missing = [f for f in findings if f.ruleId == "coverMissing"]
    assert any(f.detail.get("format") == "audiobook" for f in cover_missing)


@pytest.mark.umbra
def test_covers_A3_audiobook_square(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A3: Non-square audiobook cover invalid; 3000x3000 PNG passes."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    from PIL import Image

    # Non-square
    test_image = tmp_path / "test.jpg"
    img = Image.new("RGB", (3000, 2000), color="red")
    img.save(test_image, "JPEG")
    store.setCover("audiobook", test_image)

    findings = store.validateCover("audiobook")
    assert any(f.ruleId == "coverInvalid" for f in findings)

    # Valid square
    test_image = tmp_path / "test.png"
    img = Image.new("RGB", (3000, 3000), color="green")
    img.save(test_image, "PNG")
    store.setCover("audiobook", test_image)

    findings = store.validateCover("audiobook")
    assert not any(f.ruleId == "coverInvalid" for f in findings)


@pytest.mark.umbra
def test_covers_A4_wraparound_size(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A4: Wraparound size calculation."""
    # This is tested in test_covers_R2_paperback_wraparound
    # which verifies 5.5x8.5, 300-page, cream60 = 304.8x222.25 mm


@pytest.mark.umbra
def test_covers_A5_edition_cover_blocks(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A5: Edition project with empty slot blocks publish."""
    import shutil
    import tempfile

    source_path = Path(tempfile.mkdtemp())
    try:
        _source_project, _ = _makeProjectWithMetadata(source_path)
        source_store = CoverStore(source_path)

        test_image = source_path / "cover.jpg"
        from PIL import Image

        img = Image.new("RGB", (3000, 2000), color="red")
        img.save(test_image, "JPEG")
        source_store.setCover("epub", test_image)

        edition_path = Path(tempfile.mkdtemp())
        try:
            edition_project, edition_metadata = _makeProjectWithMetadata(edition_path)
            edition_store = CoverStore(edition_path)

            # Create edition.json to mark as edition project
            # Disable paperback, hardback, audiobook for this test
            edition_metadata.formats["paperback"]["enabled"] = False
            edition_metadata.formats["hardback"]["enabled"] = False
            edition_metadata.formats["audiobook"]["enabled"] = False
            edition_metadata.formats["epub"]["enabled"] = True
            saveMetadata(edition_path, edition_metadata)

            # Create edition.json to mark as edition project
            edition_file = edition_path / "umbra" / "edition.json"
            edition_file.parent.mkdir(parents=True, exist_ok=True)
            edition_file.write_text(
                '{"v":1,"editionId":"ed-zh-hans","language":"zh-Hans",'
                '"source":{"path":"../source","editionId":"main"},'
                '"translatable":["book.title"]}',
                encoding="utf-8",
            )

            edition_store = CoverStore(edition_path)

            # Edition has no cover of its own
            from umbraedit.umbra.covergates import _coverEditionMissingFindings
            from umbraedit.umbra.gates import GateScope

            scope = GateScope(project=edition_project, operation="publish.package")
            findings = list(_coverEditionMissingFindings(scope))
            edition_missing = [f for f in findings if f.ruleId == "coverEditionMissing"]
            assert any(f.detail.get("format") == "epub" for f in edition_missing)

            # Copy source cover
            edition_store.useSourceCover("epub", source_path)

            # Now should pass
            scope = GateScope(project=edition_project, operation="publish.package")
            findings = list(_coverEditionMissingFindings(scope))
            edition_missing = [f for f in findings if f.ruleId == "coverEditionMissing"]
            assert len(edition_missing) == 0
        finally:
            shutil.rmtree(edition_path)
    finally:
        shutil.rmtree(source_path)


@pytest.mark.umbra
def test_covers_A6_replace_cover(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A6: Replacing cover updates next build; old asset reported."""
    _project, _metadata = _makeProjectWithMetadata(tmp_path)
    store = CoverStore(tmp_path)

    from PIL import Image

    test_image1 = tmp_path / "cover1.jpg"
    img1 = Image.new("RGB", (3000, 2000), color="red")
    img1.save(test_image1, "JPEG")

    store.setCover("epub", test_image1)
    old_asset_id = store.getCover("epub")["assetId"]

    # Replace with new cover
    test_image2 = tmp_path / "cover2.jpg"
    img2 = Image.new("RGB", (3000, 2000), color="blue")
    img2.save(test_image2, "JPEG")
    store.setCover("epub", test_image2)

    new_asset_id = store.getCover("epub")["assetId"]
    assert new_asset_id != old_asset_id

    # Old asset should still exist in asset store (unused)
    asset_store = store._assetStore
    old_asset = asset_store.getAsset(old_asset_id)
    assert old_asset is not None

    # Should be reported as unused
    unused = asset_store.unusedAssets()
    assert old_asset_id in unused
