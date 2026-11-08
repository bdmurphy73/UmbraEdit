"""
UmbraEdit - Settings Tests
==========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json

import pytest

from umbraedit.umbra.settings import UmbraSettings


@pytest.fixture
def settings():
    """Return a fresh UmbraSettings instance."""
    return UmbraSettings()


@pytest.mark.umbra
def test_umbra_settings_R5_declareAndGetType(settings):
    """R5: Declare and get a typed setting."""
    settings.declare("test.enabled", "bool", True, "Enable test feature")
    assert settings.getBool("test.enabled") is True
    settings.setApp("test.enabled", False)
    assert settings.getBool("test.enabled") is False


@pytest.mark.umbra
def test_umbra_settings_R5_getStr(settings):
    """R5: getStr returns a string setting."""
    settings.declare("test.name", "str", "default", "Test name")
    assert settings.getStr("test.name") == "default"
    settings.setApp("test.name", "custom")
    assert settings.getStr("test.name") == "custom"


@pytest.mark.umbra
def test_umbra_settings_R5_getInt(settings):
    """R5: getInt returns an integer setting."""
    settings.declare("test.count", "int", 5, "Test count")
    assert settings.getInt("test.count") == 5
    settings.setApp("test.count", 10)
    assert settings.getInt("test.count") == 10


@pytest.mark.umbra
def test_umbra_settings_R5_undeclaredKey(settings):
    """R5: Undeclared key returns the provided default."""
    assert settings.getBool("undeclared.key", True) is True
    assert settings.getStr("undeclared.key", "fallback") == "fallback"
    assert settings.getInt("undeclared.key", 99) == 99


@pytest.mark.umbra
def test_umbra_settings_R5_declaredSettings(settings):
    """R5: declaredSettings returns all declared keys sorted."""
    settings.declare("b.key", "str", "b", "B Key")
    settings.declare("a.key", "str", "a", "A Key")
    declared = settings.declaredSettings()
    assert len(declared) == 2
    assert declared[0].key == "a.key"
    assert declared[1].key == "b.key"


@pytest.mark.umbra
def test_umbra_settings_R5_settingsByFeature(settings):
    """R5: Settings are grouped by feature prefix."""
    settings.declare("feature1.enabled", "bool", True, "F1 Enabled")
    settings.declare("feature1.count", "int", 0, "F1 Count")
    settings.declare("feature2.name", "str", "", "F2 Name")
    groups = settings.settingsByFeature()
    assert "feature1" in groups
    assert "feature2" in groups
    assert len(groups["feature1"]) == 2
    assert len(groups["feature2"]) == 1


@pytest.mark.umbra
def test_umbra_settings_R5_projectPersistence(tmp_path, settings):
    """R5: Project-level settings persist to settings.json."""
    settings.declare("proj.value", "str", "default", "Project value")
    settings.loadProject(tmp_path)
    settings.setProject("proj.value", "saved")
    settings.saveProject()

    from umbraedit.umbra.paths import settingsFile
    assert settingsFile(tmp_path).is_file()

    fresh = UmbraSettings()
    fresh.declare("proj.value", "str", "default", "Project value")
    fresh.loadProject(tmp_path)
    assert fresh.getStr("proj.value") == "saved"


@pytest.mark.umbra
def test_umbra_settings_A6_persistsValue(tmp_path, settings):
    """A6: A declared setting persists its value across save/load."""
    settings.declare("persist.test", "bool", False, "Persist test")
    settings.loadProject(tmp_path)
    settings.setProject("persist.test", True)
    settings.saveProject()

    from umbraedit.umbra.paths import settingsFile
    data = json.loads(settingsFile(tmp_path).read_text(encoding="utf-8"))
    assert data.get("persist.test") is True
