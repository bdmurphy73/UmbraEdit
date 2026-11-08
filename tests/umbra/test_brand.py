"""
UmbraEdit - Brand Module Tests
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import pytest

from umbraedit.umbra.brand import APP_ID, APP_NAME, APP_URL


@pytest.mark.umbra
def test_umbra_brand_R2_appName():
    """R2: APP_NAME is set and is a string."""
    assert isinstance(APP_NAME, str)
    assert len(APP_NAME) > 0
    assert APP_NAME == "UmbraEdit"


@pytest.mark.umbra
def test_umbra_brand_R2_appId():
    """R2: APP_ID is set and is a lower-case identifier."""
    assert isinstance(APP_ID, str)
    assert APP_ID.lower() == APP_ID
    assert APP_ID == "umbraedit"


@pytest.mark.umbra
def test_umbra_brand_R2_appUrl():
    """R2: APP_URL is set or empty."""
    assert isinstance(APP_URL, str)
