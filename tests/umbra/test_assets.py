"""
UmbraEdit - Asset Store Tests
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json

from io import BytesIO
from pathlib import Path

import pytest

from PIL import Image

from umbraedit.umbra.assets import (
    ROLE_COVER,
    ROLE_FIGURE,
    ROLE_OTHER,
    AssetStore,
    _detectMime,
)


def _makePng(width: int = 100, height: int = 50, color: tuple = (200, 100, 50)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _makeJpeg(width: int = 100, height: int = 50) -> bytes:
    img = Image.new("RGB", (width, height), (50, 100, 200))
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def store(tmp_path: Path) -> AssetStore:
    return AssetStore(tmp_path)


@pytest.mark.umbra
def test_umbra_assets_A1_addAndDedup(store):
    """A1: Same bytes added twice gives one asset."""
    png = _makePng()
    id1 = store.addAsset(png, ROLE_FIGURE, name="test.png")
    id2 = store.addAsset(png, ROLE_FIGURE, name="test2.png")
    assert id1 == id2
    assert len(store.index) == 1


@pytest.mark.umbra
def test_umbra_assets_A1_mimeByContent(store):
    """A1: A renamed .jpg that is really PNG is typed image/png."""
    png = _makePng()
    assetId = store.addAsset(png, ROLE_FIGURE, name="renamed.jpg")
    entry = store.getAsset(assetId)
    assert entry["type"] == "image/png"


@pytest.mark.umbra
def test_umbra_assets_R1_addFromBytes(store):
    """R1: addAsset from bytes creates file."""
    png = _makePng()
    assetId = store.addAsset(png, ROLE_FIGURE, name="test.png")
    assert len(assetId) == 8
    assert store.assetPath(assetId).is_file()


@pytest.mark.umbra
def test_umbra_assets_R1_addFromFile(store, tmp_path):
    """R1: addAsset from a Path streams the file."""
    pngPath = tmp_path / "test.png"
    pngPath.write_bytes(_makePng())
    assetId = store.addAsset(pngPath, ROLE_FIGURE)
    assert store.assetPath(assetId).is_file()


@pytest.mark.umbra
def test_umbra_assets_R1_iterByRole(store):
    """R1: iterAssets filters by role."""
    png = _makePng()
    jpeg = _makeJpeg()
    store.addAsset(png, ROLE_FIGURE, name="fig.png")
    store.addAsset(jpeg, ROLE_COVER, name="cover.jpg")
    assert len(store.iterAssets(role=ROLE_FIGURE)) == 1
    assert len(store.iterAssets(role=ROLE_COVER)) == 1


@pytest.mark.umbra
def test_umbra_assets_R1_unused(store):
    """R1: unusedAssets returns unreferenced assets."""
    store.addAsset(_makePng(), ROLE_FIGURE, name="unused.png")
    assert len(store.unusedAssets()) == 1


@pytest.mark.umbra
def test_umbra_assets_R1_remove(store):
    """R1: removeAsset removes an unused asset."""
    assetId = store.addAsset(_makePng(), ROLE_FIGURE, name="rem.png")
    store.removeAsset(assetId)
    assert assetId not in store.index


@pytest.mark.umbra
def test_umbra_assets_A5_removeUsedRefused(store, tmp_path):
    """A5: Deleting a used asset is refused."""
    assetId = store.addAsset(_makePng(), ROLE_FIGURE, name="used.png")
    contentDir = tmp_path / "content"
    contentDir.mkdir(exist_ok=True)
    (contentDir / "doc001.md").write_text(f"[image:{assetId}|alt]\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="in use"):
        store.removeAsset(assetId)


@pytest.mark.umbra
def test_umbra_assets_A5_removeImmutableRefused(store):
    """A5: Deleting an immutable asset is refused."""
    assetId = store.addAsset(_makePng(), ROLE_OTHER, name="test.dat")
    entry = store.getAsset(assetId)
    entry["immutable"] = True
    store._index[assetId] = entry
    with pytest.raises(PermissionError, match="immutable"):
        store.removeAsset(assetId)


@pytest.mark.umbra
def test_umbra_assets_A5_replaceKeepsId(store):
    """A5: Replacing a figure keeps the id."""
    png1 = _makePng(color=(255, 0, 0))
    png2 = _makePng(color=(0, 0, 255))
    assetId = store.addAsset(png1, ROLE_FIGURE, name="test.png")
    store.replaceAsset(assetId, png2)
    assert assetId in store.index


@pytest.mark.umbra
def test_umbra_assets_A2_svgScriptRejected(store):
    """A2: SVG with script is rejected."""
    with pytest.raises(ValueError, match="script"):
        store.addAsset(b'<svg><script>alert("xss")</script></svg>', ROLE_FIGURE, name="evil.svg")


@pytest.mark.umbra
def test_umbra_assets_A2_svgOnAttrRejected(store):
    """A2: SVG with on* handler is rejected."""
    with pytest.raises(ValueError, match="handler"):
        store.addAsset(b'<svg><rect onload="alert(1)"/></svg>', ROLE_FIGURE, name="evil.svg")


@pytest.mark.umbra
def test_umbra_assets_A2_svgJsUrlRejected(store):
    """A2: SVG with javascript: URL is rejected."""
    with pytest.raises(ValueError, match="javascript"):
        store.addAsset(b'<svg><a href="javascript:alert(1)">click</a></svg>', ROLE_FIGURE, name="evil.svg")


@pytest.mark.umbra
def test_umbra_assets_A2_corruptDetected(store):
    """A2: Flipped byte in stored file is reported as assetCorrupt."""
    assetId = store.addAsset(_makePng(), ROLE_FIGURE, name="test.png")
    filePath = store.assetPath(assetId)
    data = bytearray(filePath.read_bytes())
    data[len(data) // 2] ^= 0xFF
    filePath.write_bytes(bytes(data))
    issues = store.verifyAssets()
    assert len(issues) == 1
    assert issues[0]["ruleId"] == "assetCorrupt"


@pytest.mark.umbra
def test_umbra_assets_R3_missingDetected(store):
    """R3: Missing file is reported as assetMissing."""
    assetId = store.addAsset(_makePng(), ROLE_FIGURE, name="test.png")
    store.assetPath(assetId).unlink()
    issues = store.verifyAssets()
    assert len(issues) == 1
    assert issues[0]["ruleId"] == "assetMissing"


@pytest.mark.umbra
def test_umbra_assets_R2_mimeByContent(store):
    """R2: MIME type detected by content, not extension."""
    assert _detectMime(_makePng(), "file.jpg") == "image/png"
    assert _detectMime(_makeJpeg(), "file.png") == "image/jpeg"


@pytest.mark.umbra
def test_umbra_assets_R6_indexAtomic(store):
    """R6: Index file written atomically with schema v1."""
    store.addAsset(_makePng(), ROLE_FIGURE, name="test.png")
    assert store._indexPath.is_file()
    data = json.loads(store._indexPath.read_text(encoding="utf-8"))
    assert data["v"] == 1
    assert len(data["assets"]) == 1
