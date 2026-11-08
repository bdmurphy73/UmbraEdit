"""
UmbraEdit - JSON I/O Tests
===========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json
import os

from pathlib import Path

import pytest

from umbraedit.umbra.jsonio import UmbraSchemaNewerError, readJson, writeJson


@pytest.mark.umbra
def test_umbra_jsonio_R2_writeReadRoundtrip(tmp_path: Path):
    """R2: Write then read returns the same data."""
    filePath = tmp_path / "test.json"
    data = {"key": "value", "count": 42, "flag": True}
    writeJson(filePath, data)
    result = readJson(filePath)
    assert result == data


@pytest.mark.umbra
def test_umbra_jsonio_R2_canonicalBytes(tmp_path: Path):
    """R2: Same data always produces the same bytes (canonical form)."""
    filePath1 = tmp_path / "test1.json"
    filePath2 = tmp_path / "test2.json"
    data = {"b": 2, "a": 1}
    writeJson(filePath1, data)
    writeJson(filePath2, data)
    assert filePath1.read_bytes() == filePath2.read_bytes()


@pytest.mark.umbra
def test_umbra_jsonio_R2_sortedKeys(tmp_path: Path):
    """R2: Keys are sorted in output."""
    filePath = tmp_path / "sorted.json"
    writeJson(filePath, {"zebra": 1, "apple": 2, "mango": 3})
    content = filePath.read_text(encoding="utf-8")
    assert content.index('"apple"') < content.index('"mango"') < content.index('"zebra"')


@pytest.mark.umbra
def test_umbra_jsonio_R2_trailingNewline(tmp_path: Path):
    """R2: File has a trailing newline."""
    filePath = tmp_path / "newline.json"
    writeJson(filePath, {"key": "val"})
    assert filePath.read_bytes().endswith(b"\n")


@pytest.mark.umbra
def test_umbra_jsonio_R2_missingFileDefault(tmp_path: Path):
    """R2: Missing file returns the default value."""
    filePath = tmp_path / "missing.json"
    result = readJson(filePath, default={"default": True})
    assert result == {"default": True}


@pytest.mark.umbra
def test_umbra_jsonio_R2_missingFileEmptyDict(tmp_path: Path):
    """R2: Missing file returns empty dict by default."""
    filePath = tmp_path / "missing.json"
    assert readJson(filePath) == {}


@pytest.mark.umbra
def test_umbra_jsonio_A4_atomicWrite(tmp_path: Path):
    """A4: Write is atomic (no partial file on crash)."""
    filePath = tmp_path / "atomic.json"

    class FakeCrash(Exception):
        pass

    # Write successfully first
    writeJson(filePath, {"key": "value"})
    original = filePath.read_bytes()

    # Simulate crash during write by patching os.rename
    originalRename = os.rename
    with pytest.raises(FakeCrash):
        def crashRename(src: str, dst: str) -> None:
            raise FakeCrash("Simulated crash between temp write and rename")

        os.rename = crashRename
        try:
            writeJson(filePath, {"key": "changed"})
        finally:
            os.rename = originalRename

    # Original file should be intact
    assert filePath.read_bytes() == original


@pytest.mark.umbra
def test_umbra_jsonio_A4_sameBytesForSameData(tmp_path: Path):
    """A4: Same data produces the same bytes."""
    filePath = tmp_path / "same.json"
    data = {"items": [1, 2, 3], "name": "test"}
    writeJson(filePath, data)
    bytes1 = filePath.read_bytes()
    writeJson(filePath, data)
    bytes2 = filePath.read_bytes()
    assert bytes1 == bytes2


@pytest.mark.umbra
def test_umbra_jsonio_A5_schemaNewerError(tmp_path: Path):
    """A5: File with schema version > supported raises UmbraSchemaNewerError."""
    filePath = tmp_path / "newer.json"
    filePath.write_text(
        json.dumps({"v": 999, "key": "value"}),
        encoding="utf-8",
    )
    with pytest.raises(UmbraSchemaNewerError):
        readJson(filePath)


@pytest.mark.umbra
def test_umbra_jsonio_R2_unicodeNFC(tmp_path: Path):
    """R2: Unicode data is written as NFC UTF-8."""
    filePath = tmp_path / "unicode.json"
    data = {"title": "Caf\u00e9", "text": "\u201cCurly quotes\u201d"}
    writeJson(filePath, data)
    content = filePath.read_text(encoding="utf-8")
    assert "Caf\u00e9" in content
    assert "\u201cCurly quotes\u201d" in content


@pytest.mark.umbra
def test_umbra_jsonio_R2_emptyDict(tmp_path: Path):
    """R2: Empty dict roundtrips correctly."""
    filePath = tmp_path / "empty.json"
    writeJson(filePath, {})
    result = readJson(filePath)
    assert result == {}
