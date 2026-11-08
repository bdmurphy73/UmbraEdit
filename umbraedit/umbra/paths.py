"""
UmbraEdit - Umbra Sidecar Paths
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Provides path management for the `<project>/umbra/` sidecar folder.
This folder stores UmbraEdit-specific metadata that is separate from
the novelWriter project format. It is created lazily on first write.
"""  # noqa

from __future__ import annotations

from pathlib import Path

UMBRA_DIR_NAME = "umbra"

# Sub-folders
CACHE_DIR = "cache"
HISTORY_DIR = "history"
OUTBOX_DIR = "outbox"
JOBS_DIR = "jobs"
ASSETS_DIR = "assets"

# Project-level file names
SETTINGS_JSON = "settings.json"
VOICES_JSON = "voices.json"
TONES_JSON = "tones.json"
SHEET_JSON = "sheet.json"
METADATA_JSON = "metadata.json"
COVERS_JSON = "covers.json"
EDITION_JSON = "edition.json"
SERIES_JSON = "series.json"
PAGES_JSON = "pages.json"
JOURNAL_JSONL = "journal.jsonl"
DEVICE_JSON = "device.json"

# Sub-folder names for later prompts
PROMPTS_DIR = "prompts"
ALIGN_DIR = "align"
PROPOSALS_DIR = "proposals"


def umbraDir(projectPath: Path) -> Path:
    """Return the `<project>/umbra/` directory, creating it if needed."""
    path = projectPath / UMBRA_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cacheDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/cache/`, creating it if needed."""
    path = umbraDir(projectPath) / CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def historyDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/history/`, creating it if needed."""
    path = umbraDir(projectPath) / HISTORY_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def outboxDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/outbox/`, creating it if needed."""
    path = umbraDir(projectPath) / OUTBOX_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def jobsDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/jobs/`, creating it if needed."""
    path = umbraDir(projectPath) / JOBS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def assetsDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/assets/`, creating it if needed."""
    path = umbraDir(projectPath) / ASSETS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def settingsFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/settings.json`."""
    return umbraDir(projectPath) / SETTINGS_JSON


def voicesFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/voices.json`."""
    return umbraDir(projectPath) / VOICES_JSON


def tonesFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/tones.json`."""
    return umbraDir(projectPath) / TONES_JSON


def sheetFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/sheet.json`."""
    return umbraDir(projectPath) / SHEET_JSON


def metadataFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/metadata.json`."""
    return umbraDir(projectPath) / METADATA_JSON


def pronSeenFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/cache/pron-seen.json`."""
    return cacheDir(projectPath) / "pron-seen.json"


def coversFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/covers.json`."""
    return umbraDir(projectPath) / COVERS_JSON


def editionFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/edition.json`."""
    return umbraDir(projectPath) / EDITION_JSON


def seriesFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/series.json`."""
    return umbraDir(projectPath) / SERIES_JSON


def pagesFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/pages.json`."""
    return umbraDir(projectPath) / PAGES_JSON


def journalFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/journal.jsonl`."""
    return umbraDir(projectPath) / JOURNAL_JSONL


def deviceFile(projectPath: Path) -> Path:
    """Return `<project>/umbra/device.json`."""
    return umbraDir(projectPath) / DEVICE_JSON


def promptsDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/prompts/`."""
    path = umbraDir(projectPath) / PROMPTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def alignDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/align/`."""
    path = umbraDir(projectPath) / ALIGN_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def proposalsDir(projectPath: Path) -> Path:
    """Return `<project>/umbra/proposals/`."""
    path = umbraDir(projectPath) / PROPOSALS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path
