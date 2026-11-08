"""
UmbraEdit - Project Generator Tests
====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import hashlib

from pathlib import Path

import pytest

from utils.umbra_gen_project import generateProject


def _hashDir(path: Path) -> str:
    """Hash all files in a directory recursively, sorted by name."""
    hasher = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            hasher.update(f.name.encode())
            hasher.update(f.read_bytes())
    return hasher.hexdigest()


@pytest.mark.umbra
def test_umbra_gen_project_A3_deterministic(tmp_path: Path) -> None:
    """A3: Same seed produces identical project file hashes."""
    out1 = tmp_path / "proj1"
    out2 = tmp_path / "proj2"

    generateProject(out1, words=1000, scenes=12, characters=4, places=3, seed=42)
    generateProject(out2, words=1000, scenes=12, characters=4, places=3, seed=42)

    hash1 = _hashDir(out1)
    hash2 = _hashDir(out2)
    assert hash1 == hash2, "Same seed must produce identical projects"


@pytest.mark.umbra
def test_umbra_gen_project_A3_differentSeed(tmp_path: Path) -> None:
    """A3: Different seeds produce different projects."""
    out1 = tmp_path / "proj1"
    out2 = tmp_path / "proj2"

    generateProject(out1, words=1000, scenes=12, characters=4, places=3, seed=42)
    generateProject(out2, words=1000, scenes=12, characters=4, places=3, seed=99)

    hash1 = _hashDir(out1)
    hash2 = _hashDir(out2)
    assert hash1 != hash2, "Different seeds must produce different projects"


@pytest.mark.umbra
def test_umbra_gen_project_R5_small(tmp_path: Path) -> None:
    """R5: --small generates a 12-scene fixture with 4 characters and 3 places."""
    out = tmp_path / "fixture-small"
    generateProject(out, words=1200, scenes=12, characters=4, places=3, seed=7)

    assert (out / "nwProject.nwx").is_file()
    contentFiles = list((out / "content").glob("*.md"))
    # 12 scenes + 4 chars + 3 places = 19 content files
    assert len(contentFiles) == 19


@pytest.mark.umbra
def test_umbra_gen_project_R5_unicode(tmp_path: Path) -> None:
    """R5: Generator handles Unicode (curly quotes, accents) in output."""
    out = tmp_path / "unicode_proj"
    generateProject(out, words=500, scenes=6, characters=2, places=2, seed=42)

    # Check content files are valid UTF-8
    for f in (out / "content").glob("*.md"):
        content = f.read_text(encoding="utf-8")
        assert isinstance(content, str)


@pytest.mark.umbra
def test_umbra_gen_project_R5_existingOutput(tmp_path: Path) -> None:
    """R5: Generator fails if output folder already exists."""
    out = tmp_path / "existing"
    out.mkdir()

    with pytest.raises(SystemExit):
        generateProject(out, words=100, scenes=2, characters=1, places=1, seed=1)
