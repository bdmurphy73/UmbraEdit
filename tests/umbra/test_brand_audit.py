"""
UmbraEdit - Brand Audit Tests
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from utils.umbra_brand_audit import checkHashes


@pytest.mark.umbra
def test_umbra_brand_audit_A6_noHashMatch() -> None:
    """A6: No image file hash matches an upstream brand graphic."""
    failures = checkHashes()
    assert failures == [], f"Hash audit failures: {failures}"


@pytest.mark.umbra
def test_umbra_brand_audit_A6_desktopFileClean() -> None:
    """A6: Desktop file does not contain old product name."""
    desktopFile = Path("setup/data/umbraedit.desktop")
    assert desktopFile.is_file()
    content = desktopFile.read_text(encoding="utf-8")
    assert "novelwriter" not in content.lower()


@pytest.mark.umbra
def test_umbra_brand_audit_A6_mimeFileClean() -> None:
    """A6: MIME type file does not contain old product name."""
    mimeFile = Path("setup/data/x-umbraedit-project.xml")
    assert mimeFile.is_file()
    content = mimeFile.read_text(encoding="utf-8")
    assert "novelwriter" not in content.lower()


@pytest.mark.umbra
def test_umbra_brand_A9_brandPyExists() -> None:
    """A9: brand.py exists with APP_NAME."""
    from umbraedit.umbra.brand import APP_NAME

    assert APP_NAME == "UmbraEdit"
