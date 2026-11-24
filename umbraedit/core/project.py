"""
UmbraEdit - Project Wrapper
=============================

This file is a part of UmbraEdit.

Copyright (C) 2018 Veronica Berglyd Olsen and UmbraEdit contributors.

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
import tempfile
import uuid

from enum import Enum
from functools import partial
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Optional, Union

from PyQt6.QtCore import QCoreApplication

from umbraedit import CONFIG, SHARED, __hexversion__, __version__
from umbraedit.common import (
    checkStringNone,
    formatInt,
    formatTimeStamp,
    getFileSize,
    hexToInt,
    makeFileNameSafe,
    minmax,
    safeIsFile,
)
from umbraedit.constants import nwFiles, nwLabels, nwStyles, trConst
from umbraedit.core.index import Index
from umbraedit.core.options import OptionState
from umbraedit.core.projectdata import ProjectData
from umbraedit.core.projectxml import ProjectXMLReader, ProjectXMLWriter, XMLReadState
from umbraedit.core.safeio import (
    DirectorySnapshot,
    FileIdentity,
    copyRegularFile,
    directoryHasNonQuarantineEntries,
    ensureDirectory,
    fileIdentity,
    getDefaultDirectoryMode,
    isLinkLike,
    isPathWithin,
    openDirectory,
    openDirectoryAt,
    removeEmptyDirectoryIfOwned,
    removeTreeIfOwned,
    renameNoReplace,
    renameNoReplaceBetween,
    scanRegularFiles,
    supportsDirectoryDescriptors,
    unlinkIfSameFile,
)
from umbraedit.core.sessions import SessionLog
from umbraedit.core.storage import ProjectStorage, ProjectStorageCreate, ProjectStorageOpen
from umbraedit.core.tree import ProjectTree
from umbraedit.enum import nwItemClass, nwItemLayout, nwItemType, nwProjectKind
from umbraedit.error import logException

if TYPE_CHECKING:
    from umbraedit.core.status import T_StatusKind, T_UpdateEntry

logger = logging.getLogger(__name__)


def _sameDirectorySnapshot(left: DirectorySnapshot, right: DirectorySnapshot) -> bool:
    """Return whether two directory snapshots describe the same entries."""
    return (
        left.identity == right.identity
        and left.fileIdentities.keys() == right.fileIdentities.keys()
        and all(left.fileIdentities[name] == right.fileIdentities[name] for name in left.fileIdentities)
    )


class NWProjectState(Enum):
    """The state of the loaded project."""

    UNKNOWN = 0
    LOCKED = 1
    RECOVERY = 2
    READY = 3


class NWProject:
    """Core: UmbraEdit Project Class.

    This class is the parent class of the project, and holds instances
    of project data, the project tree, and the project index.
    """

    __slots__ = (
        "_changed",
        "_countsDirty",
        "_data",
        "_index",
        "_langData",
        "_options",
        "_session",
        "_sessionActive",
        "_state",
        "_storage",
        "_tree",
        "_updateRecent",
        "_valid",
        "tr",
    )

    def __init__(self) -> None:

        # Core Elements
        self._options = OptionState(self)  # Project-specific GUI options
        self._storage = ProjectStorage(self)  # The project storage handler
        self._data = ProjectData(self)  # The project settings
        self._tree = ProjectTree(self)  # The project tree
        self._index = Index(self)  # The project index
        self._session = SessionLog(self)  # The session record

        # Project Status
        self._langData = {}  # Localisation data
        self._changed = False  # The project has unsaved changes
        self._valid = False  # The project was successfully loaded
        self._state = NWProjectState.UNKNOWN
        self._countsDirty = False  # The word counts need to be recalculated
        self._sessionActive = False  # Project hooks are bound to this session
        self._updateRecent = True  # Track this session in the recent cache

        # Internal Mapping
        self.tr = partial(QCoreApplication.translate, "NWProject")

        logger.debug("Ready: NWProject")

    def __del__(self) -> None:  # pragma: no cover
        """Class destructor."""
        logger.debug("Delete: NWProject")

    def clear(self) -> None:
        """Clear the project."""
        self._tree.clear()
        self._index.clear()

    ##
    #  Properties
    ##

    @property
    def options(self) -> OptionState:
        return self._options

    @property
    def storage(self) -> ProjectStorage:
        return self._storage

    @property
    def data(self) -> ProjectData:
        return self._data

    @property
    def tree(self) -> ProjectTree:
        return self._tree

    @property
    def index(self) -> Index:
        return self._index

    @property
    def session(self) -> SessionLog:
        return self._session

    @property
    def projOpened(self) -> float:
        return self._session.start

    @property
    def projChanged(self) -> bool:
        return self._changed

    @property
    def isValid(self) -> bool:
        """Return True if a project is loaded."""
        return self._valid

    @property
    def state(self) -> NWProjectState:
        """Return the current project state."""
        return self._state

    @property
    def lockStatus(self) -> Optional[list]:
        """Return the project lock information."""
        return self._storage.lockStatus

    @property
    def currentTotalCount(self) -> int:
        """Return the current total word count from the tree."""
        return self._tree.model.root.count

    @property
    def countsDirty(self) -> bool:
        """Return whether the word counts need to be recalculated."""
        return self._countsDirty

    ##
    #  Item Methods
    ##

    def newRoot(self, itemClass: nwItemClass, pos: int = -1) -> str:
        """Add a new root folder to the project. If label is not set,
        use the class label.
        """
        label = trConst(nwLabels.CLASS_NAME[itemClass])
        return self._tree.create(label, None, nwItemType.ROOT, itemClass=itemClass, pos=pos)

    def newFolder(self, label: str, parent: str, pos: int = -1) -> Optional[str]:
        """Add a new folder with a given label and parent item."""
        return self._tree.create(label, parent, nwItemType.FOLDER, pos=pos)

    def newFile(self, label: str, parent: str, pos: int = -1) -> Optional[str]:
        """Add a new file with a given label and parent item."""
        return self._tree.create(label, parent, nwItemType.FILE, pos=pos)

    def removeItem(self, tHandle: str) -> bool:
        """Remove an item from the project. This will delete both the
        project entry and a document file if it exists.
        """
        if self._tree.checkType(tHandle, nwItemType.FILE):
            SHARED.closeDocument(tHandle)
            doc = self._storage.getDocument(tHandle)
            if not doc.deleteDocument():
                SHARED.error(self.tr("Could not delete document file."), info=doc.error)
                return False
        self._index.deleteHandle(tHandle)
        self._tree.remove(tHandle)
        return True

    def writeNewFile(
        self,
        tHandle: str,
        hLevel: int,
        isDocument: bool,
        text: str = "",
        *,
        addHeading: bool = True,
    ) -> bool:
        """Write content to a new document after it is created. This
        will not run if the file exists and is not empty.
        """
        if not ((tItem := self._tree[tHandle]) and tItem.isFileType()):
            return False

        if self._storage.getDocumentText(tHandle).strip():
            return False

        if addHeading:
            indent = "#" * minmax(hLevel, 1, 4)
            text = f"{indent} {tItem.itemName}\n\n{text}"

        if tItem.isNovelLike() and isDocument:
            tItem.setLayout(nwItemLayout.DOCUMENT)
        else:
            tItem.setLayout(nwItemLayout.NOTE)

        self._storage.getDocument(tHandle).writeDocument(text)
        self._index.scanText(tHandle, text)

        return True

    def copyFileContent(self, tHandle: str, sHandle: str, newTitle: Optional[str] = None) -> bool:
        """Copy content to a new document after it is created. This
        will not run if the file exists and is not empty.
        """
        if not ((tItem := self._tree[tHandle]) and tItem.isFileType()):
            return False

        if not ((sItem := self._tree[sHandle]) and sItem.isFileType()):
            return False

        if self._storage.getDocumentText(tHandle).strip():
            return False

        logger.debug("Populating '%s' with text from '%s'", tHandle, sHandle)
        text = self._storage.getDocumentText(sHandle)
        if newTitle and (lines := text.split("\n")) and lines and lines[0].startswith(nwStyles.H_MARKERS):
            prefix, _, _ = lines[0].partition(" ")
            lines[0] = f"{prefix} {newTitle}"
            text = "\n".join(lines)

        self._storage.getDocument(tHandle).writeDocument(text)
        sItem.setLayout(tItem.itemLayout)
        self._index.reIndexHandle(tHandle)

        return True

    def createNewNote(self, tag: str, itemClass: nwItemClass) -> None:
        """Create a new note. This function is used by the document
        editor to create note files for unknown tags.
        """
        if itemClass != nwItemClass.NO_CLASS:
            if not (rHandle := self._tree.findRoot(itemClass)):
                rHandle = self.newRoot(itemClass)
            if rHandle and (tHandle := self.newFile(tag.title(), rHandle)):
                self.writeNewFile(tHandle, 1, False, f"@tag: {tag}\n\n")
                self._tree.refreshItems([tHandle])

    ##
    #  Project Methods
    ##

    def openProject(
        self,
        projPath: str | Path,
        clearLock: bool = False,
        *,
        updateRecent: bool = True,
    ) -> bool:
        """Open the project file provided. If it doesn't exist, assume
        it is a folder and look for the file within it. If successful,
        parse the XML of the file and populate the project variables and
        build the tree of project items.

        The ``updateRecent`` flag is disabled by standalone tools that
        must not modify the user's recent-project cache.
        """
        logger.info("Opening project: %s", projPath)
        self._updateRecent = updateRecent

        # A previous session may have ended logically while its validated
        # lock cleanup was still pending. Never overwrite that ownership
        # state with a new project session.
        if not self._valid and self._storage.isOpen() and not self.releaseSession():
            SHARED.error(
                self.tr("Failed to release the previous project session."),
                info=self.tr("Path: {0}").format(str(projPath)),
            )
            return False

        status = self._storage.initProjectStorage(projPath, clearLock)
        if status != ProjectStorageOpen.READY:
            if not self._valid and self._storage.isOpen():
                self.releaseSession()
            if status == ProjectStorageOpen.UNKOWN:
                SHARED.error(
                    self.tr("Not a known project file format."),
                    info=self.tr("Path: {0}").format(str(projPath)),
                )
            elif status == ProjectStorageOpen.NOT_FOUND:
                SHARED.error(
                    self.tr("Project file not found."),
                    info=self.tr("Path: {0}").format(str(projPath)),
                )
            elif status == ProjectStorageOpen.FAILED:
                SHARED.error(
                    self.tr("Failed to open project."),
                    info=self.tr("Path: {0}").format(str(projPath)),
                    exc=self._storage.exc,
                )
            elif status == ProjectStorageOpen.LOCKED:
                self._state = NWProjectState.LOCKED
            else:  # pragma: no cover
                pass
            return False

        try:
            return self._openProjectSession(updateRecent)
        except Exception as exc:
            logger.error("Unexpected error while opening project", exc_info=exc)
            self.releaseSession()
            SHARED.error(
                self.tr("Failed to open project."),
                info=self.tr("Path: {0}").format(str(projPath)),
                exc=exc,
            )
            return False

    def _openProjectSession(self, updateRecent: bool) -> bool:
        """Open a project after its exclusive session lock was acquired."""
        # File identity receipts belong to a single project session. A
        # reused NWProject instance must re-observe the options and index
        # files when it opens a new session instead of comparing them
        # with identities retained from the previous session.
        self._options.resetIdentity()
        self._index.resetIdentity()

        # Read Project XML
        # ================

        xmlReader = self._storage.getXmlReader()
        if not isinstance(xmlReader, ProjectXMLReader):
            self.releaseSession()
            return False

        self._data = ProjectData(self)
        projContent = []
        xmlParsed = xmlReader.read(self._data, projContent)
        self._storage.recordXmlIdentity(xmlReader.lastIdentity)
        appVersion = xmlReader.appVersion or self.tr("Unknown")
        if not xmlParsed:
            if xmlReader.state == XMLReadState.NOT_NWX_FILE:
                SHARED.error(self.tr("Project file does not appear to be a UmbraEditXML file."))
            elif xmlReader.state == XMLReadState.UNKNOWN_VERSION:
                SHARED.error(
                    self.tr(
                        "Unknown or unsupported UmbraEdit project file format. "
                        "The project cannot be opened by this version of UmbraEdit. "
                        "The file was saved with UmbraEdit version {0}."
                    ).format(appVersion)
                )
            else:
                SHARED.error(self.tr("Failed to parse project xml."))
            self.releaseSession()
            return False

        # Check Legacy Upgrade
        # ====================

        if (xmlReader.state == XMLReadState.WAS_LEGACY or self._storage.hasBreakingChanges()) and not SHARED.question(
            self.tr(
                "The file format of your project is about to be updated. "
                "If you proceed, older versions of UmbraEdit will no "
                "longer be able to open this project. Continue?"
            ),
            default=True,
        ):
            self.releaseSession()
            return False

        # Check UmbraEdit Version
        # =========================

        if xmlReader.hexVersion > hexToInt(__hexversion__) and not SHARED.question(
            self.tr(
                "This project was saved by a newer version of "
                "UmbraEdit, version {0}. This is version {1}. If you "
                "continue to open the project, some attributes and "
                "settings may not be preserved, but the overall project "
                "should be fine. Continue opening the project?"
            ).format(appVersion, __version__),
            warn=True,
        ):
            self.releaseSession()
            return False

        # Post XML Loading
        if not self._storage.runPostXMLTasks():
            SHARED.error(self.tr("Failed to open project."), exc=self._storage.exc)
            self.releaseSession()
            return False

        # Extract Data
        # ============

        self._tree.unpack(projContent)
        if not self._options.loadSettings():
            SHARED.error(self.tr("Failed to open project."), exc=self._storage.exc)
            self.releaseSession()
            return False
        self._loadProjectLocalisation()

        # Check the project tree consistency
        # This also handles any orphaned files found
        orphans, recovered = self._tree.checkConsistency(self.tr("Recovered"))
        if orphans > 0:
            SHARED.warn(
                self.tr("Found {0} orphaned file(s) in the project. {1} file(s) were recovered.").format(
                    orphans, recovered
                )
            )

        # A missing, corrupt, or raced index cache is recoverable. The
        # index revision check in the GUI will trigger a rebuild without
        # preventing the project itself from opening.
        self._index.loadIndex()
        if xmlReader.state == XMLReadState.WAS_LEGACY:
            # Often, the index needs to be rebuilt when updating format
            self._index.rebuild()

        self.updateCounts()
        self._session.startSession()

        # The storage layer acquires the exclusive lock before any project
        # mutation. Verify that this session still owns it before exposing
        # the opened project to the rest of the application.
        if not self._storage.lockSession():
            self._valid = False
            self._state = NWProjectState.LOCKED
            self.releaseSession()
            SHARED.error(self.tr("The project is already open in another session."))
            return False

        from umbraedit.umbra import hooks as _umbraHooks

        _umbraHooks.call(_umbraHooks.PROJECT_OPENED, self)
        self._sessionActive = True
        self.setProjectChanged(False)

        # Check for copies and update recent projects
        if storePath := self._storage.storagePath:
            if self._storage.kind == nwProjectKind.BACKUP:
                stamp = self._storage.timeStamp
                if SHARED.question(
                    self.tr(
                        "This project is a backup copy. Do you want to make it a separate "
                        "project so UmbraEdit can tell it apart from the original?"
                    ),
                    info=self.tr("Backup from: {0}").format(CONFIG.localDateTime(stamp)) if stamp else "",
                ):
                    self._data.setUuid("")
                # The manifest must be saved as a regular project
                self.setProjectChanged(True)

            elif (other := CONFIG.recentProjects.findCopy(storePath, self._data.uuid)) and SHARED.question(
                self.tr(
                    "This project appears to be a copy of another project. "
                    "It was either copied outside of UmbraEdit, or is a backup copy. "
                    "Do you want to make it a separate project so UmbraEdit can tell them apart?"
                ),
                info=self.tr("Path: {0}").format(other),
            ):
                self._data.setUuid("")
                self.setProjectChanged(True)

            if updateRecent:
                CONFIG.recentProjects.update(storePath, self._data, time())

        self._valid = True
        self._state = NWProjectState.READY

        SHARED.newStatusMessage(self.tr("Opened Project: {0}").format(self._data.name))

        return True

    def saveProject(self, autoSave: bool = False) -> bool:
        """Save the project main XML file. The saving command itself
        uses a temporary filename, and the file is replaced afterwards
        to make sure if the save fails, we're not left with a truncated
        file.
        """
        if not self._storage.isOpen():
            SHARED.error(self.tr("There is no project open."))
            return False

        saveTime = time()

        logger.info("Saving project: %s", self._storage.storagePath)

        if autoSave:
            self._data.incAutoCount()
        else:
            self._data.incSaveCount()

        self.updateCounts()
        self.countStatus()

        xmlWriter = self._storage.getXmlWriter()
        if not isinstance(xmlWriter, ProjectXMLWriter):
            return False

        saveTime = time()
        SHARED.clearErrorCache()
        self._data.setIndexRevision(self._index.indexRevision)
        editTime = self._data.editTime + max(round(saveTime - self._session.start), 0)
        content = self._tree.pack()
        if not xmlWriter.write(
            self._data,
            content,
            saveTime,
            editTime,
            expectedParent=self._storage.rootIdentity,
            expectedTarget=self._storage.xmlIdentity,
            replaceExisting=self._storage.xmlIdentity is not None,
        ):
            self._reportErrors(self.tr("Issues encountered when saving project:"))
            return False
        self._storage.recordXmlIdentity(xmlWriter.lastIdentity)

        # Save other project data
        if not autoSave:
            if not self._options.saveSettings(
                expectedParent=self._storage.metaIdentity,
                expectedTarget=self._options.lastIdentity,
                replaceExisting=self._options.lastIdentity is not None,
            ):
                self._reportErrors(self.tr("Issues encountered when saving project:"))
                return False
            if not self._index.saveIndex(
                expectedParent=self._storage.metaIdentity,
                expectedTarget=self._index.lastIdentity,
                replaceExisting=self._index.lastIdentity is not None,
            ):
                self._reportErrors(self.tr("Issues encountered when saving project:"))
                return False

        if not self._storage.runPostSaveTasks(
            saveTime=saveTime,
            autoSave=autoSave,
            expectedParent=self._storage.rootIdentity,
            expectedTarget=self._storage.lastManifestIdentity,
            replaceExisting=self._storage.lastManifestIdentity is not None,
        ):
            self._reportErrors(self.tr("Issues encountered when saving project:"))
            return False

        # Update recent projects
        if self._updateRecent and (storagePath := self._storage.storagePath):
            CONFIG.recentProjects.update(storagePath, self._data, saveTime)

        self._reportErrors(self.tr("Issues encountered when saving project:"))

        SHARED.newStatusMessage(self.tr("Saved Project: {0}").format(self._data.name))
        self.setProjectChanged(False)

        # Notify listeners that the project (tree) was saved
        from umbraedit.umbra import hooks as _umbraHooks

        _umbraHooks.call(_umbraHooks.PROJECT_SAVED, self)

        return True

    def saveProjectAs(self, newPath: str | Path, newName: str) -> bool:
        """Save the current project to a new location with a new name.

        Creates a new project folder at the given path, copies all document,
        metadata, and asset files from the current project, and writes the
        project XML with the new name. The new location is added to the
        recent projects list as a separate entry from the original location.

        If any part of the new project fails to build, the original project
        remains active and the incomplete destination is removed.
        """
        if not self._storage.isOpen():
            SHARED.error(self.tr("There is no project open."))
            return False

        # Resolve the parent path, but preserve the final path component
        # so a symlinked destination can be rejected instead of silently
        # writing through it to another location.
        requestedPath = Path(newPath).expanduser().absolute()
        newPath = requestedPath.parent.resolve() / requestedPath.name
        if isLinkLike(newPath):
            SHARED.error(self.tr("The target project location cannot be a symbolic link."))
            return False

        oldRuntimePath = self._storage.runtimePath
        oldContentPath = self._storage.contentPath
        oldMetaPath = oldRuntimePath / "meta" if oldRuntimePath else None
        oldAssetPath = oldRuntimePath / "assets" / "img" if oldRuntimePath else None
        oldRootIdentity = self._storage.rootIdentity
        oldMetaIdentity = self._storage.metaIdentity
        oldContentIdentity = self._storage.contentIdentity
        contentSnapshot: Optional[DirectorySnapshot] = None
        metaSnapshot: Optional[DirectorySnapshot] = None
        assetSnapshot: Optional[DirectorySnapshot] = None
        useDirectoryDescriptors = supportsDirectoryDescriptors()

        def verifySourceRoot() -> None:
            """Verify that the source project root is still the same object."""
            if oldRuntimePath is None or oldRootIdentity is None:
                raise OSError("The source project identity is unavailable")
            rootStat = os.lstat(oldRuntimePath)
            if (
                isLinkLike(oldRuntimePath)
                or not stat.S_ISDIR(rootStat.st_mode)
                or fileIdentity(rootStat, oldRuntimePath) != oldRootIdentity
            ):
                raise OSError("The project folder changed before it could be copied")

        def verifySourceSnapshot(snapshot: Optional[DirectorySnapshot]) -> None:
            """Verify that a source directory still matches its snapshot."""
            if snapshot is None:
                return
            current = scanRegularFiles(snapshot.path, expectedPath=snapshot.path)
            if not _sameDirectorySnapshot(snapshot, current):
                raise OSError(f"The source folder changed before it could be copied: {snapshot.path}")

        if oldRuntimePath:
            try:
                targetInsideProject = isPathWithin(newPath.resolve(), oldRuntimePath.resolve())
            except OSError as exc:
                SHARED.error(self.tr("Failed to validate the target project location."), exc=exc)
                return False
            if targetInsideProject:
                SHARED.error(self.tr("The target project location cannot be inside the current project."))
                return False

        targetExisted = newPath.exists() or newPath.is_symlink()
        targetMode: Optional[int] = None
        targetIdentity: Optional[FileIdentity] = None
        if targetExisted:
            try:
                if isLinkLike(newPath) or not newPath.is_dir():
                    SHARED.error(self.tr("Failed to create project storage."))
                    return False
                targetStat = os.lstat(newPath)
                if not stat.S_ISDIR(targetStat.st_mode):
                    SHARED.error(self.tr("Failed to create project storage."))
                    return False
                if directoryHasNonQuarantineEntries(newPath):
                    SHARED.error(self.tr("The target folder is not empty. Please choose another folder."))
                    return False
                targetMode = stat.S_IMODE(targetStat.st_mode)
                targetIdentity = fileIdentity(targetStat, newPath)
            except OSError as exc:
                SHARED.error(self.tr("Failed to create project storage."), exc=exc)
                return False

        # Reject linked source files before saving any document. A normal
        # document save must never write through a malicious project link.
        if oldRuntimePath:
            try:
                rootStat = os.lstat(oldRuntimePath)
                if isLinkLike(oldRuntimePath) or not stat.S_ISDIR(rootStat.st_mode):
                    raise OSError("The project folder is not a real directory")
                if oldRootIdentity is not None and fileIdentity(rootStat, oldRuntimePath) != oldRootIdentity:
                    raise OSError("The project folder changed before Save As could begin")
            except OSError as exc:
                logger.error("Failed to validate the project folder before Save As", exc_info=exc)
                SHARED.error(self.tr("Failed to validate the target project location."), exc=exc)
                return False
        if oldContentPath and (oldContentPath.exists() or isLinkLike(oldContentPath)):
            try:
                contentSnapshot = scanRegularFiles(oldContentPath)
                if oldContentIdentity is not None and contentSnapshot.identity != oldContentIdentity:
                    raise OSError("The project content folder changed before Save As could begin")
            except OSError as exc:
                logger.error("Failed to validate project content before Save As", exc_info=exc)
                SHARED.error(
                    self.tr("Failed to copy document file: {0}").format(oldContentPath.name),
                    exc=exc,
                )
                return False
        if oldMetaPath:
            try:
                if not oldMetaPath.exists() and not isLinkLike(oldMetaPath):
                    if oldMetaIdentity is not None:
                        raise OSError("The project metadata folder is missing")
                else:
                    metaSnapshot = scanRegularFiles(oldMetaPath)
                    if oldMetaIdentity is not None and metaSnapshot.identity != oldMetaIdentity:
                        raise OSError("The project metadata folder changed before Save As could begin")
            except OSError as exc:
                logger.error("Failed to validate project metadata before Save As", exc_info=exc)
                SHARED.error(
                    self.tr("Failed to copy project metadata file: {0}").format(oldMetaPath.name),
                    exc=exc,
                )
                return False
        if oldAssetPath:
            try:
                if isLinkLike(oldAssetPath) or isLinkLike(oldAssetPath.parent):
                    raise OSError("The project image folder cannot be a link")
                if oldAssetPath.parent.exists() and not oldAssetPath.parent.is_dir():
                    raise OSError("The project asset folder is not a directory")
                if oldAssetPath.exists():
                    assetSnapshot = scanRegularFiles(oldAssetPath, expectedPath=oldAssetPath)
            except OSError as exc:
                logger.error("Failed to validate project images before Save As", exc_info=exc)
                SHARED.error(self.tr("Failed to copy project image file."), exc=exc)
                return False

        # Save the complete active state so that a failed copy can restore
        # the original project rather than leaving it pointed at a partial
        # destination.
        oldStorageState: dict[str, object] = {
            "_storagePath": self._storage._storagePath,
            "_runtimePath": self._storage._runtimePath,
            "_rootIdentity": self._storage._rootIdentity,
            "_metaIdentity": self._storage._metaIdentity,
            "_contentIdentity": self._storage._contentIdentity,
            "_xmlIdentity": self._storage._xmlIdentity,
            "_lockFilePath": self._storage._lockFilePath,
            "_lockFileIdentity": self._storage._lockFileIdentity,
            "_manifestPath": self._storage._manifestPath,
            "_lastManifestIdentity": self._storage._lastManifestIdentity,
            "_lockedBy": self._storage._lockedBy,
            "_openMode": self._storage._openMode,
            "_ready": self._storage._ready,
            "_exception": self._storage._exception,
            "_oldDocuments": self._storage._oldDocuments,
            "_kind": self._storage._kind,
            "_timeStamp": self._storage._timeStamp,
        }
        oldUuid = self._data.uuid
        oldName = self._data.name
        oldIndexRevision = self._data.indexRevision
        oldEditTime = self._data.editTime
        oldChanged = self._changed
        oldCountsDirty = self._countsDirty
        oldLockPath = self._storage._lockFilePath
        oldLockIdentity = self._storage._lockFileIdentity
        oldOptionsIdentity = self._options.lastIdentity
        oldOptionsIdentityKnown = self._options.lastIdentityKnown
        oldIndexIdentity = self._index.lastIdentity
        oldIndexIdentityKnown = self._index.lastIdentityKnown

        stagingPath: Optional[Path] = None
        stagingIdentity: Optional[FileIdentity] = None
        stagingParentIdentity: Optional[FileIdentity] = None
        stagedFileIdentities: dict[Path, FileIdentity] = {}
        stagedMetaIdentity: Optional[FileIdentity] = None
        targetBackupPath: Optional[Path] = None
        conflictPath: Optional[Path] = None

        def verifyStaging() -> None:
            """Verify that the application-owned staging tree is unchanged."""
            if stagingPath is None or stagingIdentity is None:
                raise OSError("The project staging directory is unavailable")
            if useDirectoryDescriptors:
                parentFd = openDirectory(newPath.parent)
                try:
                    if stagingParentIdentity is not None:
                        parentStat = os.fstat(parentFd)
                        if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                            raise OSError("The destination folder changed while saving")
                    stageStat = os.stat(
                        stagingPath.name,
                        dir_fd=parentFd,
                        follow_symlinks=False,
                    )
                    stageIdentity = fileIdentity(
                        stageStat,
                        Path(stagingPath.name),
                        dirFd=parentFd,
                    )
                    if not stat.S_ISDIR(stageStat.st_mode) or stageIdentity != stagingIdentity:
                        raise OSError("The project staging directory changed while saving")
                finally:
                    os.close(parentFd)
            else:
                if stagingParentIdentity is not None:
                    parentStat = os.lstat(newPath.parent)
                    if isLinkLike(newPath.parent) or fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                        raise OSError("The destination folder changed while saving")
                stageStat = os.lstat(stagingPath)
                if isLinkLike(stagingPath) or not stat.S_ISDIR(stageStat.st_mode):
                    raise OSError("The project staging directory changed while saving")
                if fileIdentity(stageStat, stagingPath) != stagingIdentity:
                    raise OSError("The project staging directory changed while saving")
            for stagedPath, expectedIdentity in stagedFileIdentities.items():
                stagedStat = os.lstat(stagedPath)
                if not stat.S_ISREG(stagedStat.st_mode) or fileIdentity(stagedStat, stagedPath) != expectedIdentity:
                    raise OSError("A staged project file changed while saving")

        def restoreState() -> None:
            """Restore the original project and storage state."""
            for key, value in oldStorageState.items():
                setattr(self._storage, key, value)
            self._data.setUuid(oldUuid)
            self._data.setName(oldName)
            self._options._lastIdentity = oldOptionsIdentity
            self._options._identityKnown = oldOptionsIdentityKnown
            self._index._lastIdentity = oldIndexIdentity
            self._index._identityKnown = oldIndexIdentityKnown
            self._data.setIndexRevision(oldIndexRevision)
            self._data.setEditTime(oldEditTime)
            self._countsDirty = oldCountsDirty
            self.setProjectChanged(oldChanged)

        def cleanStaging() -> bool:
            """Remove the application-owned staging directory."""
            if stagingPath is None or stagingIdentity is None:
                return True
            try:
                removeTreeIfOwned(
                    stagingPath,
                    stagingIdentity,
                    quarantineParent=newPath.parent,
                    expectedQuarantineParent=stagingParentIdentity,
                )
            except OSError:
                logger.error("Failed to remove project staging directory '%s'", stagingPath)
                logException()
                return False
            return True

        def restoreTargetBackup() -> bool:
            """Restore an empty target folder moved aside for publishing."""
            nonlocal conflictPath, targetBackupPath
            if targetBackupPath is None:
                return True
            try:
                if targetIdentity is None:
                    raise OSError("The previous target project folder identity is unknown")

                parentFd: Optional[int] = None
                if useDirectoryDescriptors:
                    parentFd = openDirectory(newPath.parent)
                    try:
                        if stagingParentIdentity is not None:
                            parentStat = os.fstat(parentFd)
                            if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                                raise OSError("The destination folder changed while saving")
                        backupStat = os.stat(
                            targetBackupPath.name,
                            dir_fd=parentFd,
                            follow_symlinks=False,
                        )
                        backupIdentity = fileIdentity(
                            backupStat,
                            Path(targetBackupPath.name),
                            dirFd=parentFd,
                        )
                        if (
                            stat.S_ISLNK(backupStat.st_mode)
                            or not stat.S_ISDIR(backupStat.st_mode)
                            or backupIdentity != targetIdentity
                        ):
                            raise OSError("The previous target project folder changed before it could be restored")
                        try:
                            os.stat(newPath.name, dir_fd=parentFd, follow_symlinks=False)
                        except FileNotFoundError:
                            pass
                        else:
                            logger.warning(
                                "Could not restore the target project folder; it is preserved at '%s'",
                                targetBackupPath,
                            )
                            return False
                        if not renameNoReplaceBetween(
                            Path(targetBackupPath.name),
                            Path(newPath.name),
                            sourceDirFd=parentFd,
                            targetDirFd=parentFd,
                        ):
                            raise OSError("Could not restore the target project folder")
                        restoredStat = os.stat(
                            newPath.name,
                            dir_fd=parentFd,
                            follow_symlinks=False,
                        )
                        restoredIdentity = fileIdentity(
                            restoredStat,
                            Path(newPath.name),
                            dirFd=parentFd,
                        )
                    finally:
                        os.close(parentFd)
                else:
                    if stagingParentIdentity is not None:
                        parentStat = os.lstat(newPath.parent)
                        if fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                            raise OSError("The destination folder changed while saving")
                    backupStat = os.lstat(targetBackupPath)
                    if (
                        stat.S_ISLNK(backupStat.st_mode)
                        or not stat.S_ISDIR(backupStat.st_mode)
                        or fileIdentity(backupStat, targetBackupPath) != targetIdentity
                    ):
                        raise OSError("The previous target project folder changed before it could be restored")
                    if newPath.exists() or newPath.is_symlink():
                        logger.warning(
                            "Could not restore the target project folder; it is preserved at '%s'", targetBackupPath
                        )
                        return False
                    if not renameNoReplace(targetBackupPath, newPath):
                        raise OSError("Could not restore the target project folder")
                    restoredStat = os.lstat(newPath)
                    restoredIdentity = fileIdentity(restoredStat, newPath)

                if not stat.S_ISDIR(restoredStat.st_mode) or restoredIdentity != targetIdentity:
                    conflictCandidate = newPath.parent / f".umbraedit-conflict-{uuid.uuid4().hex}"
                    try:
                        if useDirectoryDescriptors:
                            parentFd = openDirectory(newPath.parent)
                            try:
                                if stagingParentIdentity is not None:
                                    parentStat = os.fstat(parentFd)
                                    if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                                        raise OSError("The destination folder changed while saving")
                                if renameNoReplaceBetween(
                                    Path(newPath.name),
                                    Path(conflictCandidate.name),
                                    sourceDirFd=parentFd,
                                    targetDirFd=parentFd,
                                ):
                                    conflictPath = conflictCandidate
                                else:
                                    conflictPath = newPath
                            finally:
                                os.close(parentFd)
                        else:
                            if stagingParentIdentity is not None:
                                parentStat = os.lstat(newPath.parent)
                                if fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                                    raise OSError("The destination folder changed while saving")
                            if renameNoReplace(newPath, conflictCandidate):
                                conflictPath = conflictCandidate
                            else:
                                conflictPath = newPath
                    except OSError:
                        conflictPath = None
                    targetBackupPath = None
                    raise OSError("The restored target project folder does not match the original folder")
                targetBackupPath = None
                return True
            except Exception:
                logger.exception("Failed to restore the target project folder '%s'", newPath)
            if targetBackupPath is not None:
                logger.warning("The target project folder is preserved at '%s'", targetBackupPath)
            return False

        # First save all current documents to make sure everything is current
        saveTime = time()
        self.updateCounts()
        self.countStatus()

        for docHandle in self._tree.allDocs():
            doc = self._storage.getDocument(docHandle)
            if doc and doc.nwItem:
                text = doc.readDocument()
                if text is None:
                    SHARED.error(self.tr("Failed to read a project document before saving."))
                    return False
                if not doc.writeDocument(text):
                    SHARED.error(self.tr("Failed to save a project document before saving."))
                    return False

        # The document save legitimately replaces content files. Capture
        # their new identities, but keep the original directory identity so
        # a folder replacement during the save cannot be mixed into the copy.
        try:
            verifySourceRoot()
            if oldContentPath is not None:
                if contentSnapshot is None:
                    if oldContentPath.exists() or isLinkLike(oldContentPath):
                        raise OSError("The project content folder appeared before it could be copied")
                else:
                    currentContent = scanRegularFiles(oldContentPath)
                    if currentContent.identity != contentSnapshot.identity:
                        raise OSError("The project content folder changed while documents were being saved")
                    contentSnapshot = currentContent
            if oldMetaPath is not None:
                if metaSnapshot is None:
                    if oldMetaPath.exists() or isLinkLike(oldMetaPath):
                        raise OSError("The project metadata folder appeared before it could be copied")
                else:
                    currentMeta = scanRegularFiles(oldMetaPath)
                    if not _sameDirectorySnapshot(metaSnapshot, currentMeta):
                        raise OSError("The project metadata folder changed while documents were being saved")
            if oldAssetPath is not None:
                if assetSnapshot is None:
                    if oldAssetPath.exists() or isLinkLike(oldAssetPath):
                        raise OSError("The project image folder appeared before it could be copied")
                else:
                    currentAssets = scanRegularFiles(oldAssetPath, expectedPath=oldAssetPath)
                    if not _sameDirectorySnapshot(assetSnapshot, currentAssets):
                        raise OSError("The project image folder changed while documents were being saved")
        except OSError as exc:
            logger.error("Failed to validate the project source before Save As", exc_info=exc)
            SHARED.error(self.tr("Failed to validate the target project location."), exc=exc)
            return False

        # Build the new project in an application-owned staging directory.
        # The user-selected target is not modified until the complete copy
        # has been validated and is ready to publish.
        try:
            if useDirectoryDescriptors:
                parentFd = openDirectory(newPath.parent)
                try:
                    stagingParentStat = os.fstat(parentFd)
                    stagingParentIdentity = fileIdentity(
                        stagingParentStat,
                        fileDescriptor=parentFd,
                    )
                    for _ in range(10):
                        stagingName = f".umbraedit-stage-{uuid.uuid4().hex}"
                        try:
                            os.mkdir(stagingName, 0o700, dir_fd=parentFd)
                        except FileExistsError:
                            continue
                        stagingPath = newPath.parent / stagingName
                        stagingStat = os.stat(
                            stagingName,
                            dir_fd=parentFd,
                            follow_symlinks=False,
                        )
                        break
                    else:
                        raise OSError("Could not create a unique project staging directory")
                finally:
                    os.close(parentFd)
            else:
                stagingParentStat = os.lstat(newPath.parent)
                if isLinkLike(newPath.parent) or not stat.S_ISDIR(stagingParentStat.st_mode):
                    raise OSError("The destination folder is not a real directory")
                stagingParentIdentity = fileIdentity(stagingParentStat, newPath.parent)
                stagingPath = Path(
                    tempfile.mkdtemp(prefix=".umbraedit-stage-", dir=str(newPath.parent)),
                )
                stagingStat = os.lstat(stagingPath)
                currentParentStat = os.lstat(newPath.parent)
                if fileIdentity(currentParentStat, newPath.parent) != stagingParentIdentity:
                    raise OSError("The destination folder changed while saving")
            if isLinkLike(stagingPath) or not stat.S_ISDIR(stagingStat.st_mode):
                raise OSError("The project staging directory is not a real directory")
            stagingIdentity = fileIdentity(stagingStat, stagingPath)
            if targetMode is None:
                targetMode = getDefaultDirectoryMode(
                    newPath.parent,
                    expectedParent=stagingParentIdentity,
                    quarantineParent=stagingPath,
                    expectedQuarantineParent=stagingIdentity,
                )
        except OSError as exc:
            cleanStaging()
            restoreState()
            SHARED.error(self.tr("Failed to create project storage."), exc=exc)
            return False

        try:
            verifyStaging()
        except OSError:
            cleanStaging()
            restoreState()
            SHARED.error(self.tr("Failed to create project storage."))
            return False

        status = self._storage.createNewProject(stagingPath, resolvePath=False)
        if status != ProjectStorageCreate.READY:
            cleanStaging()
            restoreState()
            if status == ProjectStorageCreate.NOT_EMPTY:
                SHARED.error(self.tr("The target folder is not empty. Please choose another folder."))
            else:
                SHARED.error(self.tr("Failed to create project storage."))
            return False

        try:
            verifyStaging()
        except OSError as exc:
            cleanStaging()
            restoreState()
            SHARED.error(self.tr("Failed to create project storage."), exc=exc)
            return False

        errorMessage = self.tr("Failed to save project as a new project.")
        try:
            # Update project data: new UUID and name
            self._data.setUuid("")
            self._data.setName(newName)

            # Copy all document files from old content to new content.
            # Link-like entries are rejected rather than dereferenced.
            if oldContentPath and contentSnapshot is not None:
                try:
                    verifySourceRoot()
                    verifySourceSnapshot(contentSnapshot)
                    verifyStaging()
                    stageFd: Optional[int] = None
                    newContentFd: Optional[int] = None
                    newContentIdentity: Optional[FileIdentity] = None
                    try:
                        if useDirectoryDescriptors:
                            stageFd = openDirectory(stagingPath)
                            stageStat = os.fstat(stageFd)
                            if fileIdentity(stageStat, fileDescriptor=stageFd) != stagingIdentity:
                                raise OSError("The project staging directory changed while it was being copied")
                            newContentFd = openDirectoryAt(stageFd, "content")
                            newContentStat = os.fstat(newContentFd)
                            if not stat.S_ISDIR(newContentStat.st_mode):
                                raise OSError("The staged content folder is not a real directory")
                            newContentIdentity = fileIdentity(
                                newContentStat,
                                fileDescriptor=newContentFd,
                            )
                        else:
                            newContentPath = stagingPath / "content"
                            newContentStat = os.lstat(newContentPath)
                            if isLinkLike(newContentPath) or not stat.S_ISDIR(newContentStat.st_mode):
                                raise OSError("The staged content folder is not a real directory")
                            newContentIdentity = fileIdentity(newContentStat, newContentPath)
                        for mdFile in contentSnapshot.files:
                            if mdFile.suffix == ".md":
                                verifySourceRoot()
                                verifyStaging()
                                targetPath = stagingPath / "content" / mdFile.name
                                copiedIdentity = copyRegularFile(
                                    mdFile,
                                    targetPath,
                                    expectedParent=contentSnapshot.identity,
                                    expectedSourceIdentity=contentSnapshot.fileIdentities[mdFile.name],
                                    expectedTargetParent=newContentIdentity,
                                    targetDirFd=newContentFd,
                                    quarantineParent=stagingPath,
                                    expectedQuarantineParent=stagingIdentity,
                                )
                                stagedFileIdentities[targetPath] = copiedIdentity
                    finally:
                        if newContentFd is not None:
                            os.close(newContentFd)
                        if stageFd is not None:
                            os.close(stageFd)
                    verifySourceRoot()
                    verifySourceSnapshot(contentSnapshot)
                    verifyStaging()
                except Exception as exc:
                    errorMessage = self.tr("Failed to copy document file: {0}").format(oldContentPath.name)
                    logger.error("Failed to copy document file: %s", exc)
                    raise

            # Copy all meta files from old meta to new meta.
            if oldMetaPath and metaSnapshot is not None:
                try:
                    verifySourceRoot()
                    verifySourceSnapshot(metaSnapshot)
                    verifyStaging()
                    stageFd: Optional[int] = None
                    metaFd: Optional[int] = None
                    try:
                        if useDirectoryDescriptors:
                            stageFd = openDirectory(stagingPath)
                            stageStat = os.fstat(stageFd)
                            if fileIdentity(stageStat, fileDescriptor=stageFd) != stagingIdentity:
                                raise OSError("The project staging directory changed while it was being copied")
                            try:
                                metaFd = openDirectoryAt(stageFd, "meta")
                            except FileNotFoundError:
                                os.mkdir("meta", 0o700, dir_fd=stageFd)
                                metaFd = openDirectoryAt(stageFd, "meta")
                            newMetaStat = os.fstat(metaFd)
                            stagedMetaIdentity = fileIdentity(
                                newMetaStat,
                                fileDescriptor=metaFd,
                            )
                        else:
                            newMetaPath = stagingPath / "meta"
                            newMetaStat = os.lstat(newMetaPath)
                            if isLinkLike(newMetaPath) or not stat.S_ISDIR(newMetaStat.st_mode):
                                raise OSError("The staged metadata folder is not a real directory")
                            stagedMetaIdentity = fileIdentity(newMetaStat, newMetaPath)
                        for metaFile in metaSnapshot.files:
                            verifySourceRoot()
                            verifyStaging()
                            targetPath = stagingPath / "meta" / metaFile.name
                            copiedIdentity = copyRegularFile(
                                metaFile,
                                targetPath,
                                expectedParent=metaSnapshot.identity,
                                expectedSourceIdentity=metaSnapshot.fileIdentities[metaFile.name],
                                expectedTargetParent=stagedMetaIdentity,
                                targetDirFd=metaFd,
                                quarantineParent=stagingPath,
                                expectedQuarantineParent=stagingIdentity,
                            )
                            stagedFileIdentities[targetPath] = copiedIdentity
                    finally:
                        if metaFd is not None:
                            os.close(metaFd)
                        if stageFd is not None:
                            os.close(stageFd)
                    verifySourceRoot()
                    verifySourceSnapshot(metaSnapshot)
                    verifyStaging()
                except Exception as exc:
                    errorMessage = self.tr("Failed to copy project metadata file: {0}").format(oldMetaPath.name)
                    logger.error("Failed to copy meta file: %s", exc)
                    raise

            # Copy all project image assets. Link-like files and folders
            # are rejected rather than silently omitted, since a missing
            # image would break references in the copied project.
            if oldAssetPath and assetSnapshot is not None:
                try:
                    verifySourceRoot()
                    verifySourceSnapshot(assetSnapshot)
                    verifyStaging()
                    stageFd: Optional[int] = None
                    assetsFd: Optional[int] = None
                    imageFd: Optional[int] = None
                    newAssetIdentity: Optional[FileIdentity] = None
                    try:
                        if useDirectoryDescriptors:
                            stageFd = openDirectory(stagingPath)
                            stageStat = os.fstat(stageFd)
                            if fileIdentity(stageStat, fileDescriptor=stageFd) != stagingIdentity:
                                raise OSError("The project staging directory changed while it was being copied")
                            try:
                                assetsFd = openDirectoryAt(stageFd, "assets")
                            except FileNotFoundError:
                                os.mkdir("assets", 0o700, dir_fd=stageFd)
                                assetsFd = openDirectoryAt(stageFd, "assets")
                            try:
                                imageFd = openDirectoryAt(assetsFd, "img")
                            except FileNotFoundError:
                                os.mkdir("img", 0o700, dir_fd=assetsFd)
                                imageFd = openDirectoryAt(assetsFd, "img")
                            newAssetStat = os.fstat(imageFd)
                            newAssetIdentity = fileIdentity(
                                newAssetStat,
                                fileDescriptor=imageFd,
                            )
                        else:
                            assetsPath = stagingPath / "assets"
                            imagePath = assetsPath / "img"
                            ensureDirectory(assetsPath)
                            ensureDirectory(imagePath)
                            newAssetStat = os.lstat(imagePath)
                            if isLinkLike(imagePath) or not stat.S_ISDIR(newAssetStat.st_mode):
                                raise OSError("The staged image folder is not a real directory")
                            newAssetIdentity = fileIdentity(newAssetStat, imagePath)
                        for assetFile in assetSnapshot.files:
                            verifySourceRoot()
                            verifyStaging()
                            targetPath = stagingPath / "assets" / "img" / assetFile.name
                            copiedIdentity = copyRegularFile(
                                assetFile,
                                targetPath,
                                expectedParent=assetSnapshot.identity,
                                expectedSourceIdentity=assetSnapshot.fileIdentities[assetFile.name],
                                expectedTargetParent=newAssetIdentity,
                                targetDirFd=imageFd,
                                quarantineParent=stagingPath,
                                expectedQuarantineParent=stagingIdentity,
                            )
                            stagedFileIdentities[targetPath] = copiedIdentity
                    finally:
                        if imageFd is not None:
                            os.close(imageFd)
                        if assetsFd is not None:
                            os.close(assetsFd)
                        if stageFd is not None:
                            os.close(stageFd)
                    verifySourceRoot()
                    verifySourceSnapshot(assetSnapshot)
                    verifyStaging()
                except Exception as exc:
                    logger.error("Failed to copy project image file: %s", exc)
                    errorMessage = self.tr("Failed to copy project image file.")
                    raise

            # Write project XML
            verifySourceRoot()
            verifyStaging()
            if stagedMetaIdentity is None:
                if useDirectoryDescriptors:
                    stageFd = openDirectory(stagingPath)
                    try:
                        metaFd = openDirectoryAt(stageFd, "meta")
                        try:
                            stagedMetaIdentity = fileIdentity(
                                os.fstat(metaFd),
                                fileDescriptor=metaFd,
                            )
                        finally:
                            os.close(metaFd)
                    finally:
                        os.close(stageFd)
                else:
                    newMetaPath = stagingPath / "meta"
                    newMetaStat = os.lstat(newMetaPath)
                    if isLinkLike(newMetaPath) or not stat.S_ISDIR(newMetaStat.st_mode):
                        raise OSError("The staged metadata folder is not a real directory")
                    stagedMetaIdentity = fileIdentity(newMetaStat, newMetaPath)
            self._data.setIndexRevision(self._index.indexRevision)
            saveTime = time()
            editTime = self._data.editTime + max(round(saveTime - self._session.start), 0)
            content = self._tree.pack()
            xmlWriter = self._storage.getXmlWriter()
            if not isinstance(xmlWriter, ProjectXMLWriter):
                raise OSError("Could not create a project XML writer")

            if not xmlWriter.write(
                self._data,
                content,
                saveTime,
                editTime,
                expectedParent=stagingIdentity,
                expectedTarget=None,
                replaceExisting=False,
            ):
                self._reportErrors(self.tr("Issues encountered when saving project:"))
                raise OSError("Could not write the project XML")
            xmlPath = stagingPath / nwFiles.PROJ_FILE
            xmlIdentity = xmlWriter.lastIdentity
            if xmlIdentity is None:
                raise OSError("Could not write the project XML")
            stagedFileIdentities[xmlPath] = xmlIdentity
            verifyStaging()

            # Save other project data
            optionsPath = stagingPath / "meta" / nwFiles.OPTS_FILE
            optionsIdentity = stagedFileIdentities.get(optionsPath)
            if not self._options.saveSettings(
                expectedParent=stagedMetaIdentity,
                expectedTarget=optionsIdentity,
                replaceExisting=optionsIdentity is not None,
            ):
                raise OSError("Could not save the project options")
            optionsIdentity = self._options.lastIdentity
            if optionsIdentity is None:
                raise OSError("Could not save the project options")
            stagedFileIdentities[optionsPath] = optionsIdentity
            verifyStaging()

            indexPath = stagingPath / "meta" / nwFiles.INDEX_FILE
            indexIdentity = stagedFileIdentities.get(indexPath)
            if not self._index.saveIndex(
                expectedParent=stagedMetaIdentity,
                expectedTarget=indexIdentity,
                replaceExisting=indexIdentity is not None,
            ):
                raise OSError("Could not save the project index")
            indexIdentity = self._index.lastIdentity
            if indexIdentity is None:
                raise OSError("Could not save the project index")
            stagedFileIdentities[indexPath] = indexIdentity
            verifyStaging()

            if not self._storage.runPostSaveTasks(
                saveTime=saveTime,
                autoSave=False,
                expectedParent=stagingIdentity,
                expectedTarget=None,
                replaceExisting=False,
            ):
                raise OSError("Could not finalise the project storage")
            manifestPath = stagingPath / nwFiles.MANIFEST_FILE
            manifestIdentity = self._storage.lastManifestIdentity
            if manifestIdentity is None:
                raise OSError("Could not write the project manifest")
            stagedFileIdentities[manifestPath] = manifestIdentity
            verifyStaging()

            # Lock the staged project before publishing it. The lock file
            # is moved together with the rest of the project.
            assert stagingPath is not None
            if not self._storage.lockSession(expectedParent=stagingIdentity):
                raise OSError("Could not lock the staged project")
            verifyStaging()
            stagedLockPath = self._storage._lockFilePath
            if not stagedLockPath or not stagedLockPath.is_file():
                raise OSError("Could not lock the new project")
            stagedLockIdentity = self._storage._lockFileIdentity
            if stagedLockIdentity is None:
                raise OSError("Could not lock the new project")
            stagedFileIdentities[stagedLockPath] = stagedLockIdentity

            # Publish the complete staged project with atomic no-replace
            # semantics. An existing empty target is first moved aside,
            # and is restored if publishing fails.
            verifySourceRoot()
            if targetExisted:
                try:
                    currentStat = os.lstat(newPath)
                except OSError:
                    errorMessage = self.tr("The target project location changed while saving. Please try again.")
                    raise
                if (
                    stat.S_ISLNK(currentStat.st_mode)
                    or not stat.S_ISDIR(currentStat.st_mode)
                    or targetIdentity is None
                    or fileIdentity(currentStat, newPath) != targetIdentity
                ):
                    errorMessage = self.tr("The target project location changed while saving. Please try again.")
                    raise OSError("The target project location changed while saving")
                if directoryHasNonQuarantineEntries(newPath):
                    errorMessage = self.tr("The target project location changed while saving. Please try again.")
                    raise OSError("The target project location is no longer an empty folder")

                targetBackupCandidate = newPath.parent / f".umbraedit-saveas-{uuid.uuid4().hex}"
                if useDirectoryDescriptors:
                    parentFd = openDirectory(newPath.parent)
                    try:
                        if stagingParentIdentity is not None:
                            parentStat = os.fstat(parentFd)
                            if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                                raise OSError("The destination folder changed while saving")
                        moved = renameNoReplaceBetween(
                            Path(newPath.name),
                            Path(targetBackupCandidate.name),
                            sourceDirFd=parentFd,
                            targetDirFd=parentFd,
                        )
                    finally:
                        os.close(parentFd)
                else:
                    if stagingParentIdentity is not None:
                        parentStat = os.lstat(newPath.parent)
                        if fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                            raise OSError("The destination folder changed while saving")
                    moved = renameNoReplace(newPath, targetBackupCandidate)
                if not moved:
                    errorMessage = self.tr("The target project location changed while saving. Please try again.")
                    raise OSError("Could not move the existing target project folder aside")
                targetBackupPath = targetBackupCandidate
                backupStat = os.lstat(targetBackupPath)
                if (
                    stat.S_ISLNK(backupStat.st_mode)
                    or not stat.S_ISDIR(backupStat.st_mode)
                    or targetIdentity is None
                    or fileIdentity(backupStat, targetBackupPath) != targetIdentity
                ):
                    conflictPath = targetBackupPath
                    targetBackupPath = None
                    errorMessage = self.tr("The target project location changed while saving. Please try again.")
                    raise OSError("The target project location changed before it could be moved aside")
                if directoryHasNonQuarantineEntries(targetBackupPath):
                    restoreTargetBackup()
                    errorMessage = self.tr("The target project location changed while saving. Please try again.")
                    raise OSError("The target project location is no longer an empty folder")
            elif newPath.exists() or newPath.is_symlink():
                errorMessage = self.tr("The target project location changed while saving. Please try again.")
                raise OSError("The target project location already exists")

            # The staging directory remains private while it is being built.
            # Apply the intended final permissions immediately before the
            # atomic publication so a new target follows the process umask.
            assert targetMode is not None
            verifyStaging()
            if useDirectoryDescriptors:
                stagingFd = openDirectory(stagingPath)
                try:
                    os.fchmod(stagingFd, targetMode)
                finally:
                    os.close(stagingFd)
            else:
                os.chmod(stagingPath, targetMode)
            verifyStaging()
            try:
                if useDirectoryDescriptors:
                    parentFd = openDirectory(newPath.parent)
                    try:
                        if stagingParentIdentity is not None:
                            parentStat = os.fstat(parentFd)
                            if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                                raise OSError("The destination folder changed while saving")
                        stageStat = os.stat(
                            stagingPath.name,
                            dir_fd=parentFd,
                            follow_symlinks=False,
                        )
                        stageIdentity = fileIdentity(
                            stageStat,
                            Path(stagingPath.name),
                            dirFd=parentFd,
                        )
                        if stageIdentity != stagingIdentity:
                            raise OSError("The project staging directory changed before publication")
                        published = renameNoReplaceBetween(
                            Path(stagingPath.name),
                            Path(newPath.name),
                            sourceDirFd=parentFd,
                            targetDirFd=parentFd,
                        )
                    finally:
                        os.close(parentFd)
                else:
                    if stagingParentIdentity is not None:
                        parentStat = os.lstat(newPath.parent)
                        if fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                            raise OSError("The destination folder changed while saving")
                    stageStat = os.lstat(stagingPath)
                    if isLinkLike(stagingPath) or fileIdentity(stageStat, stagingPath) != stagingIdentity:
                        raise OSError("The project staging directory changed before publication")
                    published = renameNoReplace(stagingPath, newPath)
            except Exception:
                restoreTargetBackup()
                raise
            if not published:
                restoreTargetBackup()
                errorMessage = self.tr("The target project location changed while saving. Please try again.")
                raise OSError("The target project location already exists")
            stagingPath = None

            assert stagingIdentity is not None
            try:
                if useDirectoryDescriptors:
                    parentFd = openDirectory(newPath.parent)
                    try:
                        if stagingParentIdentity is not None:
                            parentStat = os.fstat(parentFd)
                            if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                                raise OSError("The destination folder changed while saving")
                        publishedStat = os.stat(
                            newPath.name,
                            dir_fd=parentFd,
                            follow_symlinks=False,
                        )
                        publishedIdentity = fileIdentity(
                            publishedStat,
                            Path(newPath.name),
                            dirFd=parentFd,
                        )
                        if not stat.S_ISDIR(publishedStat.st_mode) or publishedIdentity != stagingIdentity:
                            raise OSError("The published project folder does not match the staged project")
                    finally:
                        os.close(parentFd)
                else:
                    if stagingParentIdentity is not None:
                        parentStat = os.lstat(newPath.parent)
                        if fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                            raise OSError("The destination folder changed while saving")
                    publishedStat = os.lstat(newPath)
                    if isLinkLike(newPath) or not stat.S_ISDIR(publishedStat.st_mode):
                        raise OSError("The published project folder does not match the staged project")
                    if fileIdentity(publishedStat, newPath) != stagingIdentity:
                        raise OSError("The published project folder does not match the staged project")
            except OSError as exc:
                conflictCandidate = newPath.parent / f".umbraedit-conflict-{uuid.uuid4().hex}"
                try:
                    if useDirectoryDescriptors:
                        parentFd = openDirectory(newPath.parent)
                        try:
                            if stagingParentIdentity is not None:
                                parentStat = os.fstat(parentFd)
                                if fileIdentity(parentStat, fileDescriptor=parentFd) != stagingParentIdentity:
                                    raise OSError("The destination folder changed while saving")
                            if renameNoReplaceBetween(
                                Path(newPath.name),
                                Path(conflictCandidate.name),
                                sourceDirFd=parentFd,
                                targetDirFd=parentFd,
                            ):
                                conflictPath = conflictCandidate
                            else:
                                conflictPath = newPath
                        finally:
                            os.close(parentFd)
                    else:
                        if stagingParentIdentity is not None:
                            parentStat = os.lstat(newPath.parent)
                            if fileIdentity(parentStat, newPath.parent) != stagingParentIdentity:
                                raise OSError("The destination folder changed while saving")
                        if renameNoReplace(newPath, conflictCandidate):
                            conflictPath = conflictCandidate
                        else:
                            conflictPath = newPath
                except OSError:
                    # The destination path may now refer to an unrelated
                    # directory. Never move or remove that replacement.
                    conflictPath = None
                errorMessage = self.tr("The published project folder changed while saving. Please try again.")
                raise OSError("The published project folder does not match the staged project") from exc

            if targetBackupPath is not None:
                try:
                    if targetIdentity is None:
                        raise OSError("The previous target project folder identity is unknown")
                    removeEmptyDirectoryIfOwned(
                        targetBackupPath,
                        targetIdentity,
                        expectedParent=stagingParentIdentity,
                        quarantineParent=newPath.parent,
                        expectedQuarantineParent=stagingParentIdentity,
                    )
                    targetBackupPath = None
                except OSError:
                    logger.warning("Could not remove the previous target project folder '%s'", targetBackupPath)
                    SHARED.warn(
                        self.tr("The previous target project folder is preserved at: {0}").format(targetBackupPath)
                    )

            # The staged paths now refer to the published project.
            self._storage._storagePath = newPath
            self._storage._runtimePath = newPath
            self._storage._lockFilePath = newPath / nwFiles.PROJ_LOCK
            self._storage._manifestPath = newPath / nwFiles.MANIFEST_FILE
            # The identity map is keyed by the staging paths, which cease to
            # exist after publication. The published files are the same
            # filesystem objects, so retain the identities observed while
            # they were staged.
            self._storage._xmlIdentity = xmlIdentity
            self._storage._lastManifestIdentity = manifestIdentity

            if oldLockPath and oldLockIdentity is not None and oldLockPath != self._storage._lockFilePath:
                try:
                    unlinkIfSameFile(
                        oldLockPath,
                        oldLockIdentity,
                        quarantineParent=oldLockPath.parent if oldRootIdentity is not None else None,
                        expectedQuarantineParent=oldRootIdentity,
                    )
                except OSError as exc:
                    logger.warning("Failed to release the original project lock: %s", exc)
                    SHARED.warn(
                        self.tr(
                            "The new project was saved, but the original project lock could not be removed. "
                            "Please remove it manually if necessary."
                        )
                    )

        except Exception as exc:
            cleaned = cleanStaging()
            restored = restoreTargetBackup()
            restoreState()
            detailMessages = []
            if not cleaned:
                detailMessages.append(self.tr("The incomplete destination could not be removed."))
            if not restored and targetBackupPath is not None:
                detailMessages.append(
                    self.tr("The previous target project folder is preserved at: {0}").format(targetBackupPath)
                )
            if conflictPath is not None:
                detailMessages.append(
                    self.tr("An unexpected published project folder is preserved at: {0}").format(conflictPath)
                )
            details = "\n".join(detailMessages)
            logger.error("Failed to save project as a new project", exc_info=exc)
            SHARED.error(errorMessage, details=details, exc=exc)
            return False

        # Update recent projects with the new location (separate from original)
        if self._updateRecent:
            try:
                CONFIG.recentProjects.update(str(newPath), self._data, saveTime)
            except Exception as exc:
                logger.error("Failed to update the recent projects list", exc_info=exc)

        self._reportErrors(self.tr("Issues encountered when saving project:"))
        SHARED.newStatusMessage(self.tr("Saved Project As: {0}").format(newName))
        self.setProjectChanged(False)

        return True

    def releaseSession(self) -> bool:
        """Release the project session lock without writing project data.

        Standalone tools use this to leave the project in a consistent,
        unlocked state after a read-only or explicitly completed command.
        If lock cleanup fails, the validated ownership state is retained
        so the caller can retry the exact same cleanup.
        """
        released = True
        if self._storage.isOpen():
            try:
                released = self._storage.closeSession()
            except Exception as exc:
                released = False
                logger.error("Failed to close the project storage session", exc_info=exc)

        wasActive = self._sessionActive
        self._sessionActive = False
        self._valid = False
        self._state = NWProjectState.UNKNOWN

        if wasActive:
            from umbraedit.umbra import hooks as _umbraHooks

            _umbraHooks.call(_umbraHooks.PROJECT_RELEASED, self)

        if not released:
            logger.error("The project session lock could not be released")
        return released

    def closeProject(self, idleTime: float = 0.0) -> bool:
        """Close the project and release its exclusive session lock."""
        logger.info("Closing project")

        released = True
        try:
            SHARED.clearErrorCache()
            self._index.clear()  # Triggers clear signal, see #1718
            self._options.saveSettings(
                expectedParent=self._storage.metaIdentity,
                expectedTarget=self._options.lastIdentity,
                replaceExisting=self._options.lastIdentity is not None,
            )
            self._tree.writeToCFile()
            self._session.appendSession(idleTime)
        except Exception as exc:
            logger.error("Failed to write project data while closing", exc_info=exc)
            SHARED.error(self.tr("Issues encountered when closing project:"), exc=exc)
        finally:
            try:
                released = self._storage.closeSession()
            except Exception as exc:
                released = False
                logger.error("Failed to close the project storage session", exc_info=exc)

        wasActive = self._sessionActive
        self._sessionActive = False
        self._valid = False
        self._state = NWProjectState.UNKNOWN

        if wasActive:
            from umbraedit.umbra import hooks as _umbraHooks

            _umbraHooks.call(_umbraHooks.PROJECT_CLOSING, self)

        self._reportErrors(self.tr("Issues encountered when closing project:"))
        if not released:
            SHARED.error(self.tr("The project session lock could not be released."))
        return released

    def backupProject(self, doNotify: bool) -> bool:
        """Create a zip file of the entire project."""
        if not self._storage.isOpen():
            logger.error("No project open")
            return False

        logger.info("Backing up project")
        SHARED.newStatusMessage(self.tr("Backing up project ..."))

        if not self._data.name:
            SHARED.error(
                self.tr(
                    "Cannot backup project because no project name is set. "
                    "Please set a Project Name in Project Settings."
                )
            )
            return False

        cleanName = makeFileNameSafe(self._data.name)
        backupPath = CONFIG.backupPath()
        baseDir = backupPath / cleanName
        try:
            baseDir.mkdir(exist_ok=True, parents=True)
            if isLinkLike(baseDir) or not baseDir.is_dir():
                raise OSError("The backup folder cannot be a link")
        except Exception as exc:
            SHARED.error(self.tr("Could not create backup folder."), exc=exc)
            return False

        saveTime = time()
        _backupInterval = CONFIG.backupInterval
        if _backupInterval == "day":
            timeStamp = formatTimeStamp(saveTime, fileSafe=True, fmt="%Y-%m-%d")
        elif _backupInterval == "week":
            timeStamp = formatTimeStamp(saveTime, fileSafe=True, fmt="%G-W%V")
        elif _backupInterval == "month":
            timeStamp = formatTimeStamp(saveTime, fileSafe=True, fmt="%Y-%m")
        else:  # Option "session" falls through here
            timeStamp = formatTimeStamp(saveTime, fileSafe=True)

        archName = baseDir / f"{cleanName} {timeStamp}.zip"
        if archName.exists() or isLinkLike(archName):
            if isLinkLike(archName):
                SHARED.error(self.tr("The backup archive target cannot be a symbolic link."))
                return False
            for index in range(1, 1000):
                candidate = baseDir / f"{cleanName} {timeStamp} ({index}).zip"
                if not candidate.exists() and not isLinkLike(candidate):
                    archName = candidate
                    break
            else:
                SHARED.error(self.tr("Could not create a unique backup archive name."))
                return False
        if self._storage.zipIt(archName, saveTime, compression=2):
            if doNotify:
                size = formatInt(getFileSize(archName))
                SHARED.info(
                    self.tr("Created a backup of your project of size {0}B.").format(size),
                    info=self.tr("Path: {0}").format(str(backupPath)),
                )
        else:
            SHARED.error(self.tr("Could not write backup archive."))
            return False

        SHARED.newStatusMessage(self.tr("Project backed up to '{0}'").format(str(archName)))

        return True

    ##
    #  Setters
    ##

    def setDefaultStatusImport(self) -> None:
        """Set the default status and importance values."""
        self._data.itemStatus.add(None, self.tr("New"), "faded", "STAR", 0)
        self._data.itemStatus.add(None, self.tr("Note"), "red", "TRIANGLE", 0)
        self._data.itemStatus.add(None, self.tr("Draft"), "yellow", "CIRCLE_T", 0)
        self._data.itemStatus.add(None, self.tr("Finished"), "green", "STAR", 0)
        self._data.itemImport.add(None, self.tr("New"), "purple", "SQUARE", 0)
        self._data.itemImport.add(None, self.tr("Minor"), "purple", "BLOCK_2", 0)
        self._data.itemImport.add(None, self.tr("Major"), "purple", "BLOCK_3", 0)
        self._data.itemImport.add(None, self.tr("Main"), "purple", "BLOCK_4", 0)

    def setProjectLang(self, language: Optional[str], rtl: bool) -> None:
        """Set the project-specific language."""
        language = checkStringNone(language, None)
        reload = self._data.language != language
        self._data.setLanguage(language, rtl)
        if reload:
            self._loadProjectLocalisation()

    def setProjectChanged(self, status: bool) -> bool:
        """Toggle the project changed flag, and propagate the
        information to the GUI statusbar.
        """
        if isinstance(status, bool):
            self._changed = status
            SHARED.setGlobalProjectState(self._changed)
        return self._changed

    ##
    #  Class Methods
    ##

    def updateCounts(self) -> None:
        """Update the total word and character count values."""
        wNovel, wNotes, cNovel, cNotes, wSession, wTarget = self._tree.sumCounts()
        self._data.setCurrCounts(wNovel=wNovel, wNotes=wNotes, cNovel=cNovel, cNotes=cNotes)
        self._data.setDailyProgress(wSession, wTarget)
        self._countsDirty = False

    def markCountsDirty(self) -> None:
        """Flag that an item's goal eligibility has changed, so the word
        counts are stale and must be recalculated.
        """
        self._countsDirty = True

    def countStatus(self) -> None:
        """Count how many times the various status flags are used in the
        project tree. The counts themselves are kept in the ItemStatus
        objects. This is essentially a refresh.
        """
        self._data.itemStatus.resetCounts()
        self._data.itemImport.resetCounts()
        for nwItem in self._tree:
            if nwItem.isNovelLike():
                self._data.itemStatus.increment(nwItem.itemStatus)
            else:
                self._data.itemImport.increment(nwItem.itemImport)

    def updateStatus(self, kind: T_StatusKind, update: T_UpdateEntry) -> None:
        """Update status or import entries."""
        if kind == "s":
            self._data.itemStatus.update(update)
            SHARED.emitStatusLabelsChanged(self, kind)
            self._tree.refreshAllItems()
        elif kind == "i":
            self._data.itemImport.update(update)
            SHARED.emitStatusLabelsChanged(self, kind)
            self._tree.refreshAllItems()
        else:  # pragma: no cover
            pass

    def updateTheme(self) -> None:
        """Update theme elements."""
        logger.debug("Theme Update: NWProject")

        self._data.itemStatus.refreshIcons()
        self._data.itemImport.refreshIcons()

    def localLookup(self, word: str | int) -> str:
        """Look up a word or number in the translation map for the
        project and return it. The variable is cast to a string before
        lookup. If the word does not exist, it returns itself.
        """
        return self._langData.get(str(word), str(word))

    ##
    #  Internal Functions
    ##
    def _reportErrors(self, title: str) -> None:
        """Report any errors from the error cache."""
        if errors := SHARED.errorCache():
            SHARED.error(title, "<br><br>".join(errors))

    def _loadProjectLocalisation(self) -> bool:
        """Load the language data for the current project language."""
        if self._data.language is None or CONFIG.nwLangPath is None:
            self._langData = {}
            return False

        langFile = Path(CONFIG.nwLangPath) / f"project_{self._data.language}.json"
        if not safeIsFile(langFile):
            langFile = Path(CONFIG.nwLangPath) / "project_en_GB.json"

        try:
            with open(langFile, mode="r", encoding="utf-8") as inFile:
                self._langData = json.load(inFile)
            logger.debug("Loaded project language file: %s", langFile.name)
        except Exception:
            logger.error("Failed to load project language file")
            logException()
            return False

        return True
