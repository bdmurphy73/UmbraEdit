"""
UmbraEdit - Umbra Settings
==========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Provides app-level and project-level typed settings with a registry
of declared keys so a settings page can list them. Keys use the
format `<feature>.<name>`.
"""  # noqa

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import settingsFile

SettingType = Literal["bool", "str", "int"]


@dataclass
class DeclaredSetting:
    """A declared setting key with its type, default, and label."""

    key: str
    type: SettingType
    default: Any
    label: str


class UmbraSettings:
    """Typed settings registry with app-level and project-level storage."""

    def __init__(self) -> None:
        self._declared: dict[str, DeclaredSetting] = {}
        self._appValues: dict[str, Any] = {}
        self._projValues: dict[str, Any] = {}
        self._projectPath: Path | None = None

    ##
    #  Registry
    ##

    def declare(self, key: str, sType: SettingType, default: Any, label: str) -> None:
        """Declare a setting key with its type, default value, and label."""
        self._declared[key] = DeclaredSetting(key=key, type=sType, default=default, label=label)
        if key not in self._appValues:
            self._appValues[key] = default

    ##
    #  Typed Getters
    ##

    def getBool(self, key: str, default: bool = False) -> bool:
        """Get a boolean setting value."""
        value = self._getValue(key)
        if isinstance(value, bool):
            return value
        return default

    def getStr(self, key: str, default: str = "") -> str:
        """Get a string setting value."""
        value = self._getValue(key)
        if isinstance(value, str):
            return value
        return default

    def getInt(self, key: str, default: int = 0) -> int:
        """Get an integer setting value."""
        value = self._getValue(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return default

    def _getValue(self, key: str) -> Any:
        """Get the raw value for a key, checking project first, then app."""
        if self._projectPath is not None and key in self._projValues:
            return self._projValues[key]
        return self._appValues.get(key, self._declared.get(key).default if key in self._declared else None)

    ##
    #  Setters
    ##

    def setApp(self, key: str, value: Any) -> None:
        """Set an app-level setting value."""
        self._appValues[key] = value

    def setProject(self, key: str, value: Any) -> None:
        """Set a project-level setting value."""
        self._projValues[key] = value

    ##
    #  Persistence
    ##

    def loadProject(self, projectPath: Path) -> None:
        """Load project-level settings from `<project>/umbra/settings.json`."""
        self._projectPath = projectPath
        filePath = settingsFile(projectPath)
        if filePath.is_file():
            data = readJson(filePath)
            if isinstance(data, dict):
                self._projValues = {k: v for k, v in data.items() if k != "v"}

    def saveProject(self) -> None:
        """Save project-level settings to `<project>/umbra/settings.json`."""
        if self._projectPath is not None:
            writeJson(settingsFile(self._projectPath), self._projValues)
            from umbraedit.umbra import hooks as _umbraHooks
            _umbraHooks.call(_umbraHooks.SIDECAR_WRITTEN, settingsFile(self._projectPath))

    ##
    #  Listing (for Preferences page)
    ##

    def declaredSettings(self) -> list[DeclaredSetting]:
        """Return all declared settings, sorted by key."""
        return sorted(self._declared.values(), key=lambda s: s.key)

    def settingsByFeature(self) -> dict[str, list[DeclaredSetting]]:
        """Group declared settings by their feature prefix."""
        groups: dict[str, list[DeclaredSetting]] = {}
        for setting in self.declaredSettings():
            prefix = setting.key.split(".")[0] if "." in setting.key else "general"
            groups.setdefault(prefix, []).append(setting)
        return groups


# Global singleton
umbraSettings = UmbraSettings()


# Declare sync settings (P17)
def _declareSyncSettings() -> None:
    """Declare sync-related settings."""
    umbraSettings.declare("sync.store", "str", "", "UmbraStore server URL")
    umbraSettings.declare("sync.token", "str", "", "Authentication token")
    umbraSettings.declare("sync.projectId", "str", "", "Linked project ID")
    umbraSettings.declare("sync.blockBuildsOnConflict", "bool", True, "Block builds when conflicts are open")
    umbraSettings.declare("sync.staleMinutes", "int", 60, "Minutes after which a stale pull warning is shown")


# Declare token settings (P18)
def _declareTokenSettings() -> None:
    """Declare token-related settings."""
    umbraSettings.declare("tokens.createAutomatically", "bool", True, "Automatically create character notes for unresolved slots")


# Declare analysis settings (P23)
def _declareAnalysisSettings() -> None:
    """Declare analysis-related settings."""
    umbraSettings.declare("analysis.endpoint", "str", "http://127.0.0.1:11434", "Local model endpoint (Ollama/LM Studio)")
    umbraSettings.declare("analysis.model", "str", "", "Model name for analysis")
    umbraSettings.declare("analysis.temperature", "str", "0.2", "Temperature for generation")
    umbraSettings.declare("analysis.contextTokens", "int", 8192, "Context token budget")
    umbraSettings.declare("analysis.timeoutSeconds", "int", 300, "Request timeout in seconds")


_declareSyncSettings()
_declareTokenSettings()
_declareAnalysisSettings()
