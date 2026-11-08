"""
UmbraEdit - Path Tests
=======================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra import paths as uPaths


@pytest.mark.umbra
def test_umbra_paths_R1_umbraDirCreated(tmp_path: Path):
    """R1: umbraDir creates <project>/umbra/ lazily."""
    assert not (tmp_path / "umbra").exists()
    result = uPaths.umbraDir(tmp_path)
    assert result == tmp_path / "umbra"
    assert result.is_dir()


@pytest.mark.umbra
def test_umbra_paths_R1_subdirsCreated(tmp_path: Path):
    """R1: Sub-folders are created lazily."""
    for fn in [uPaths.cacheDir, uPaths.historyDir, uPaths.outboxDir, uPaths.jobsDir, uPaths.assetsDir]:
        result = fn(tmp_path)
        assert result.is_dir()


@pytest.mark.umbra
def test_umbra_paths_R7_settingsFile(tmp_path: Path):
    """R7: settingsFile returns correct path."""
    result = uPaths.settingsFile(tmp_path)
    assert result == tmp_path / "umbra" / "settings.json"


@pytest.mark.umbra
def test_umbra_paths_R7_allFileConstants(tmp_path: Path):
    """R7: All file name constants are defined."""
    assert uPaths.SETTINGS_JSON == "settings.json"
    assert uPaths.VOICES_JSON == "voices.json"
    assert uPaths.TONES_JSON == "tones.json"
    assert uPaths.SHEET_JSON == "sheet.json"
    assert uPaths.METADATA_JSON == "metadata.json"
    assert uPaths.COVERS_JSON == "covers.json"
    assert uPaths.EDITION_JSON == "edition.json"
    assert uPaths.SERIES_JSON == "series.json"
    assert uPaths.PAGES_JSON == "pages.json"
    assert uPaths.JOURNAL_JSONL == "journal.jsonl"
    assert uPaths.DEVICE_JSON == "device.json"


@pytest.mark.umbra
def test_umbra_paths_R7_allFolderConstants(tmp_path: Path):
    """R7: All folder constants are defined."""
    assert uPaths.PROMPTS_DIR == "prompts"
    assert uPaths.ALIGN_DIR == "align"
    assert uPaths.PROPOSALS_DIR == "proposals"


@pytest.mark.umbra
def test_umbra_paths_A3_lazyCreation(tmp_path: Path):
    """A3: umbra/ is created lazily (only when a function is called)."""
    projPath = tmp_path / "proj"
    projPath.mkdir()
    assert not (projPath / "umbra").exists()
    uPaths.umbraDir(projPath)
    assert (projPath / "umbra").exists()
