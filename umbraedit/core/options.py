"""
UmbraEdit - Project Options Cache
===================================

This file is a part of UmbraEdit.

Copyright (C) 2019 Veronica Berglyd Olsen and UmbraEdit contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import json
import logging
import os
import stat

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, TypeVar

from umbraedit import CONFIG, SHARED
from umbraedit.common import checkBool, checkFloat, checkInt, checkString, jsonEncode
from umbraedit.constants import nwFiles
from umbraedit.core.safeio import (
    FileIdentity,
    captureRegularFileIdentity,
    fileIdentity,
    isLinkLike,
    openRegularFile,
    verifyPathIdentity,
    writeFileAtomic,
)
from umbraedit.error import logException

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

_T_Enum = TypeVar("_T_Enum", bound=Enum)

VALID_MAP: dict[str, set[str]] = {
    "GuiWritingStats": {
        "winWidth",
        "winHeight",
        "widthCol0",
        "widthCol1",
        "widthCol2",
        "widthCol3",
        "sortCol",
        "sortOrder",
        "incNovel",
        "incNotes",
        "hideZeros",
        "hideNegative",
        "groupByDay",
        "showIdleTime",
        "histMax",
    },
    "GuiDocSplit": {
        "spLevel",
        "intoFolder",
        "docHierarchy",
    },
    "GuiProjectSettings": {
        "winWidth",
        "winHeight",
        "replaceColW",
        "statusColW",
        "importColW",
    },
    "GuiWordList": {
        "winWidth",
        "winHeight",
    },
    "GuiNovelView": {
        "lastCol",
        "lastColSize",
    },
    "GuiBuildSettings": {
        "winWidth",
        "winHeight",
        "treeWidth",
        "filterWidth",
        "autoPreview",
    },
    "GuiManuscript": {
        "winWidth",
        "winHeight",
        "optsWidth",
        "viewWidth",
        "listHeight",
        "detailsHeight",
        "detailsWidth",
        "detailsExpanded",
        "statsExpanded",
        "showNewPage",
    },
    "GuiManuscriptBuild": {
        "winWidth",
        "winHeight",
        "fmtWidth",
        "sumWidth",
    },
    "GuiDocViewerPanel": {
        "colWidths",
        "hideInactive",
    },
    "GuiProjectSearch": {
        "searchFilters",
    },
    "GuiStorySettings": {
        "winWidth",
        "winHeight",
    },
}


class OptionState:
    """Core: GUI Options Storage.

    A class for storing the state of the GUI. The data is stored per
    project. Settings that should be project-independent are stored in
    the Config instead.
    """

    def __init__(self, project: NWProject) -> None:
        self._project = project
        self._state = {}
        self._lastIdentity: Optional[FileIdentity] = None
        self._identityKnown = False

    @property
    def lastIdentity(self) -> Optional[FileIdentity]:
        """Return the identity of the last observed or published file."""
        return self._lastIdentity

    @property
    def lastIdentityKnown(self) -> bool:
        """Return whether the target's presence was observed."""
        return self._identityKnown

    def resetIdentity(self) -> None:
        """Start a new observation epoch for the options file."""
        self._lastIdentity = None
        self._identityKnown = False

    ##
    #  Load and Save Cache
    ##

    def loadSettings(self) -> bool:
        """Load the options dictionary from the project."""
        stateFile = self._project.storage.getMetaFile(nwFiles.OPTS_FILE)
        if not isinstance(stateFile, Path):
            return False

        logger.debug("Loading GUI options file")
        try:
            parentIdentity = self._getParentIdentity(stateFile, None)
            targetIdentity = captureRegularFileIdentity(stateFile)

            if self._identityKnown:
                if self._lastIdentity is None:
                    if targetIdentity is not None:
                        raise OSError("The options file appeared after it was observed to be absent")
                elif targetIdentity != self._lastIdentity:
                    raise OSError("The options file changed after it was observed")

            if targetIdentity is None:
                self._lastIdentity = None
                self._identityKnown = True
                data = {}
            else:
                with openRegularFile(
                    stateFile,
                    expectedParent=parentIdentity,
                    expectedIdentity=targetIdentity,
                ) as inFile:
                    data = json.load(inFile)
                self._lastIdentity = targetIdentity
                self._identityKnown = True
        except Exception:
            logger.error("Failed to load GUI options file")
            logException()
            return False

        # Filter out unused variables
        state = data.get("UmbraEdit.guiOptions", {})
        for aGroup in state:
            if aGroup in VALID_MAP:
                self._state[aGroup] = {}
                for anOpt in state[aGroup]:
                    if anOpt in VALID_MAP[aGroup]:
                        self._state[aGroup][anOpt] = state[aGroup][anOpt]

        return True

    def saveSettings(
        self,
        *,
        expectedParent: Optional[FileIdentity] = None,
        expectedTarget: Optional[FileIdentity] = None,
        replaceExisting: bool = True,
    ) -> bool:
        """Save the options dictionary to the project."""
        stateFile = self._project.storage.getMetaFile(nwFiles.OPTS_FILE)
        if not isinstance(stateFile, Path):
            return False

        logger.debug("Saving GUI options file")
        try:
            parentIdentity = self._getParentIdentity(stateFile, expectedParent)
            targetIdentity = expectedTarget
            replaceTarget = replaceExisting
            if targetIdentity is None and self._identityKnown:
                targetIdentity = self._lastIdentity
                if targetIdentity is None:
                    replaceTarget = False

            data = {"UmbraEdit.guiOptions": self._state}
            text = jsonEncode(data, nmax=4)
            lineEnding = CONFIG.lineEnding if isinstance(CONFIG.lineEnding, str) else os.linesep
            payload = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", lineEnding).encode("utf-8")
            publishedIdentity = writeFileAtomic(
                stateFile,
                payload,
                expectedParent=parentIdentity,
                expectedTarget=targetIdentity,
                replaceExisting=replaceTarget,
                quarantineParent=self._project.storage.runtimePath,
                expectedQuarantineParent=self._project.storage.rootIdentity,
            )
            self._lastIdentity = publishedIdentity
            self._identityKnown = True
        except Exception as exc:
            SHARED.appendErrorMessage(exc)
            logger.error("Failed to save GUI options file")
            logException()
            return False

        return True

    ##
    #  Internal Functions
    ##

    def _getParentIdentity(
        self,
        stateFile: Path,
        expectedParent: Optional[FileIdentity],
    ) -> FileIdentity:
        """Return and validate the identity of the project meta folder."""
        parentIdentity = expectedParent
        if parentIdentity is None:
            parentIdentity = self._project.storage.metaIdentity
        if parentIdentity is None:
            parentStat = os.lstat(stateFile.parent)
            if isLinkLike(stateFile.parent) or not stat.S_ISDIR(parentStat.st_mode):
                raise OSError("The project meta folder is not a real directory")
            parentIdentity = fileIdentity(parentStat, stateFile.parent)
        verifyPathIdentity(stateFile.parent, parentIdentity, requireDirectory=True)
        return parentIdentity

    ##
    #  Setters
    ##

    def setValue(self, group: str, name: str, value: Any) -> bool:
        """Save a value, with a given group and name."""
        if group not in VALID_MAP:
            logger.error("Unknown option group '%s'", group)
            return False

        if name not in VALID_MAP[group]:
            logger.error("Unknown option name '%s'", name)
            return False

        if group not in self._state:
            self._state[group] = {}

        if isinstance(value, Enum):
            self._state[group][name] = value.name
        else:
            self._state[group][name] = value

        return True

    ##
    #  Getters
    ##

    def getValue(self, group: str, name: str, default: Any) -> Any:
        """Return an arbitrary type value, if it exists. Otherwise,
        return the default value.
        """
        if group in self._state:
            return self._state[group].get(name, default)
        return default

    def getList(self, group: str, name: str, default: list[Any]) -> list[Any]:
        """Return the value as a list, if it exists. Otherwise, return
        the default value.
        """
        if group in self._state and isinstance(value := self._state[group].get(name, default), list):
            return value
        return default

    def getDict(self, group: str, name: str, default: dict[str, Any]) -> dict[str, Any]:
        """Return the value as a dict, if it exists. Otherwise, return
        the default value.
        """
        if group in self._state and isinstance(value := self._state[group].get(name, default), dict):
            return value
        return default

    def getString(self, group: str, name: str, default: str) -> str:
        """Return the value as a string, if it exists. Otherwise, return
        the default value.
        """
        if group in self._state:
            return checkString(self._state[group].get(name, default), default)
        return default

    def getInt(self, group: str, name: str, default: int) -> int:
        """Return the value as an int, if it exists. Otherwise, return
        the default value.
        """
        if group in self._state:
            return checkInt(self._state[group].get(name, default), default)
        return default

    def getFloat(self, group: str, name: str, default: float) -> float:
        """Return the value as a float, if it exists. Otherwise, return
        the default value.
        """
        if group in self._state:
            return checkFloat(self._state[group].get(name, default), default)
        return default

    def getBool(self, group: str, name: str, default: bool) -> bool:
        """Return the value as a bool, if it exists. Otherwise, return
        the default value.
        """
        if group in self._state:
            return checkBool(self._state[group].get(name, default), default)
        return default

    def getEnum(self, group: str, name: str, lookup: type, default: _T_Enum) -> _T_Enum:
        """Return the value mapped to an enum. Otherwise return the
        default value.
        """
        if issubclass(lookup, type(default)) and group in self._state and name in self._state[group]:
            value = self._state[group][name]
            if value in lookup.__members__:
                return lookup[value]
        return default
