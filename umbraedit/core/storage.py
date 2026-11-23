"""
UmbraEdit - Project Storage
=============================

This file is a part of UmbraEdit.

Copyright (C) 2022 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import errno
import json
import logging
import os
import shutil
import stat
import uuid

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Optional, Sequence, Union
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from umbraedit import CONFIG, __hexversion__, __version__
from umbraedit.common import (
    formatTimeStamp,
    isHandle,
    minmax,
    safeExists,
    safeIsDir,
    safeIsFile,
    safeIterDir,
    simplified,
)
from umbraedit.constants import nwFiles
from umbraedit.core.document import ProjectDocument
from umbraedit.core.projectxml import FILE_REVISION, FILE_VERSION, ProjectXMLReader, ProjectXMLWriter
from umbraedit.core.safeio import (
    FileIdentity,
    ensureDirectory,
    fileIdentity,
    isLinkLike,
    openDirectory,
    openDirectoryAt,
    openExclusiveFile,
    openRegularFile,
    publishRegularFileNoReplace,
    removeEmptyDirectoryIfOwned,
    renameNoReplaceBetween,
    renameNoReplaceIfSameFile,
    scanRegularFiles,
    supportsDirectoryDescriptors,
    unlinkEntryIfSameFile,
    unlinkIfSameFile,
    verifyPathIdentity,
    writeFileAtomic,
)
from umbraedit.enum import nwItemClass, nwItemLayout, nwProjectKind
from umbraedit.error import logException
from umbraedit.formats.tomlparser import NTomlParser

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject
    from umbraedit.formats.tomlparser import T_TomlObject

logger = logging.getLogger(__name__)

MANIFEST_VERSION = "1.0"


@dataclass(frozen=True)
class LegacyDocument:
    """A verified legacy document awaiting conversion."""

    path: Path
    identity: FileIdentity
    parentIdentity: FileIdentity


def _addFileToZip(
    zipObj: ZipFile,
    source: Path,
    archivePath: str,
    expectedParent: Optional[FileIdentity] = None,
    expectedSourceIdentity: Optional[FileIdentity] = None,
) -> None:
    """Add a regular file to a zip archive without following links."""
    with (
        openRegularFile(
            source,
            expectedParent=expectedParent,
            expectedIdentity=expectedSourceIdentity,
        ) as inFile,
        zipObj.open(archivePath, mode="w", force_zip64=True) as outFile,
    ):
        shutil.copyfileobj(inFile, outFile, length=1024 * 1024)


class ProjectStorageOpen(Enum):
    """The status of a storage location."""

    UNKOWN = 0
    NOT_FOUND = 1
    LOCKED = 2
    FAILED = 3
    READY = 4


class ProjectStorageCreate(Enum):
    """The status of a new storage location."""

    NOT_EMPTY = 0
    OS_ERROR = 1
    READY = 2


class ProjectStorage:
    """Core: Project Storage Class.

    The class that handles all paths related to the project storage.
    """

    MODE_INACTIVE = 0
    MODE_INPLACE = 1
    MODE_ARCHIVE = 2

    def __init__(self, project: NWProject) -> None:
        self._project = project
        self._storagePath = None
        self._runtimePath = None
        self._rootIdentity: Optional[FileIdentity] = None
        self._metaIdentity: Optional[FileIdentity] = None
        self._contentIdentity: Optional[FileIdentity] = None
        self._xmlIdentity: Optional[FileIdentity] = None
        self._lockFilePath = None
        self._lockFileIdentity: Optional[FileIdentity] = None
        self._manifestPath = None
        self._lastManifestIdentity: Optional[FileIdentity] = None
        self._lockedBy = None
        self._openMode = self.MODE_INACTIVE
        self._ready = False
        self._exception = None
        self._oldDocuments = []
        self._kind = nwProjectKind.PROJECT
        self._timeStamp = None

    def clear(self) -> None:
        """Reset internal variables."""
        self._storagePath = None
        self._runtimePath = None
        self._rootIdentity = None
        self._metaIdentity = None
        self._contentIdentity = None
        self._xmlIdentity = None
        self._lockFilePath = None
        self._lockFileIdentity: Optional[FileIdentity] = None
        self._manifestPath = None
        self._lastManifestIdentity = None
        self._openMode = self.MODE_INACTIVE
        self._ready = False
        self._oldDocuments = []
        self._kind = nwProjectKind.PROJECT
        self._timeStamp = None

    ##
    #  Properties
    ##

    @property
    def storagePath(self) -> Optional[Path]:
        """Return the path where the project is stored."""
        return self._storagePath

    @property
    def runtimePath(self) -> Optional[Path]:
        """Return the path where the project is stored at runtime."""
        return self._runtimePath

    @property
    def rootIdentity(self) -> Optional[FileIdentity]:
        """Return the identity of the validated project root directory."""
        return self._rootIdentity

    @property
    def metaIdentity(self) -> Optional[FileIdentity]:
        """Return the identity of the validated project metadata folder."""
        return self._metaIdentity

    @property
    def contentIdentity(self) -> Optional[FileIdentity]:
        """Return the identity of the validated project content folder."""
        return self._contentIdentity

    @property
    def xmlIdentity(self) -> Optional[FileIdentity]:
        """Return the identity of the last observed project XML file."""
        return self._xmlIdentity

    def recordXmlIdentity(self, identity: Optional[FileIdentity]) -> None:
        """Record the identity of the project XML file last observed."""
        self._xmlIdentity = identity

    @property
    def lastManifestIdentity(self) -> Optional[FileIdentity]:
        """Return the identity of the most recently published manifest."""
        return self._lastManifestIdentity

    @property
    def kind(self) -> nwProjectKind:
        """Return the project kind recorded in the manifest."""
        return self._kind

    @property
    def timeStamp(self) -> Optional[datetime]:
        """Return the time stamp recorded in the manifest."""
        return self._timeStamp

    @property
    def contentPath(self) -> Optional[Path]:
        """Return the path used for project content. The folder must
        already exist and must not be a link.
        """
        if isinstance(self._runtimePath, Path):
            contentPath = self._runtimePath / "content"
            try:
                contentStat = os.lstat(contentPath)
            except OSError:
                contentStat = None
            if contentStat is not None and stat.S_ISDIR(contentStat.st_mode) and not isLinkLike(contentPath):
                return contentPath
        logger.error("Content path cannot be resolved")
        return None

    @property
    def lockStatus(self) -> Optional[list]:
        """Return the project lock information."""
        if isinstance(self._lockedBy, list) and len(self._lockedBy) == 4:
            return self._lockedBy
        return None

    @property
    def exc(self) -> Optional[Exception]:
        """Return the latest exception of the storage instance."""
        return self._exception

    ##
    #  Core Methods
    ##

    def isOpen(self) -> bool:
        """Check if the storage location is open."""
        return self._ready and self._runtimePath is not None

    def hasBreakingChanges(self) -> bool:
        """Check if the project has breaking changes that need to be
        converted before it can be opened.
        """
        return len(self._oldDocuments) > 0

    def createNewProject(self, path: str | Path, resolvePath: bool = True) -> ProjectStorageCreate:
        """Create a new project at the given location.

        ``resolvePath`` can be disabled for application-owned staging
        directories so a link introduced at the path is not followed.
        """
        inPath = Path(path).expanduser().absolute() if not resolvePath else Path(path).resolve()
        if safeIsDir(inPath) and len(list(safeIterDir(inPath))) > 0:
            logger.error("Folder is not empty: %s", inPath)
            return ProjectStorageCreate.NOT_EMPTY

        self._storagePath = inPath
        self._runtimePath = inPath
        self._rootIdentity = None
        self._metaIdentity = None
        self._contentIdentity = None
        self._xmlIdentity = None
        self._lockFilePath = inPath / nwFiles.PROJ_LOCK
        self._lockFileIdentity = None
        self._manifestPath = inPath / nwFiles.MANIFEST_FILE
        self._lastManifestIdentity = None
        self._openMode = self.MODE_INPLACE

        basePath = self._runtimePath
        metaPath = basePath / "meta"
        contPath = basePath / "content"
        try:
            if not resolvePath and supportsDirectoryDescriptors():
                rootFd = openDirectory(basePath)
                try:
                    rootStat = os.fstat(rootFd)
                    for childName in ("meta", "content"):
                        with suppress(FileExistsError):
                            os.mkdir(childName, 0o700, dir_fd=rootFd)
                        childFd = openDirectoryAt(rootFd, childName)
                        try:
                            childStat = os.fstat(childFd)
                            if not stat.S_ISDIR(childStat.st_mode):
                                raise OSError("The project folder is not a real directory")
                        finally:
                            os.close(childFd)
                    currentRootStat = os.lstat(basePath)
                    if not os.path.samestat(rootStat, currentRootStat):
                        raise OSError("The project folder changed while it was being created")
                finally:
                    os.close(rootFd)
            else:
                ensureDirectory(basePath)
                ensureDirectory(metaPath)
                ensureDirectory(contPath)
        except Exception as exc:
            self._exception = exc
            logger.error("Failed to create project folders", exc_info=exc)
            self.clear()
            return ProjectStorageCreate.OS_ERROR

        try:
            rootStat = os.lstat(basePath)
            if isLinkLike(basePath) or not stat.S_ISDIR(rootStat.st_mode):
                raise OSError("The project folder is not a real directory")
            self._rootIdentity = fileIdentity(rootStat)
            metaStat = os.lstat(metaPath)
            contentStat = os.lstat(contPath)
            if (
                isLinkLike(metaPath)
                or isLinkLike(contPath)
                or not stat.S_ISDIR(metaStat.st_mode)
                or not stat.S_ISDIR(contentStat.st_mode)
            ):
                raise OSError("The project folders are not real directories")
            self._metaIdentity = fileIdentity(metaStat)
            self._contentIdentity = fileIdentity(contentStat)
        except Exception as exc:
            self._exception = exc
            logger.error("Failed to validate the project folder", exc_info=exc)
            self.clear()
            return ProjectStorageCreate.OS_ERROR

        self._ready = True

        return ProjectStorageCreate.READY

    def initProjectStorage(self, path: str | Path, clearLock: bool = False) -> ProjectStorageOpen:
        """Initialise a UmbraEdit project location."""
        inPath = Path(path).resolve()

        # Initialise Storage Instance
        # ===========================

        # Check what we're opening. Only two options are allowed:
        # 1. A folder with an nwProject.nwx file in it (not home)
        # 2. A full path to an nwProject.nwx file
        if safeIsDir(inPath, alert=True) and inPath != Path.home().resolve():
            nwxFile = inPath / nwFiles.PROJ_FILE
        elif safeIsFile(inPath, alert=True):
            if inPath.name == nwFiles.PROJ_FILE:
                nwxFile = inPath
            else:
                logger.error("Not a UmbraEdit project")
                return ProjectStorageOpen.UNKOWN
        else:
            logger.error("Not found: %s", inPath)
            return ProjectStorageOpen.NOT_FOUND

        if not safeExists(nwxFile, alert=True):
            # The .nwx file must exist to continue
            logger.error("Not found: %s", nwxFile)
            return ProjectStorageOpen.NOT_FOUND

        nwxPath = nwxFile.parent
        try:
            rootStat = os.lstat(nwxPath)
            if isLinkLike(nwxPath) or not stat.S_ISDIR(rootStat.st_mode):
                raise OSError("The project folder is not a real directory")
            rootIdentity = fileIdentity(rootStat)
        except OSError as exc:
            self._exception = exc
            logger.error("Failed to validate the project folder", exc_info=exc)
            return ProjectStorageOpen.FAILED

        self._storagePath = nwxPath
        self._runtimePath = nwxPath
        self._rootIdentity = rootIdentity
        self._lockFilePath = nwxPath / nwFiles.PROJ_LOCK
        self._manifestPath = nwxPath / nwFiles.MANIFEST_FILE
        self._openMode = self.MODE_INPLACE

        # Check Project Lock
        # ==================

        if clearLock:
            self._clearLockFile(force=True)

        self._readLockFile()
        if self._lockedBy:
            logger.error("Project is locked, so not opening")
            return ProjectStorageOpen.LOCKED
        else:
            logger.debug("Project is not locked")

        # Acquire the exclusive lock before creating folders or running
        # any legacy conversion. A second session must not be able to
        # mutate the project while this session validates and opens it.
        self._ready = True
        if not self.lockSession(expectedParent=rootIdentity):
            self._readLockFile()
            self.clear()
            logger.error("Project lock could not be acquired")
            return ProjectStorageOpen.LOCKED

        if not self._readManifest():
            self._clearLockFile()
            self.clear()
            return ProjectStorageOpen.FAILED

        # Prepare Folder
        # ==============

        basePath = self._runtimePath
        metaPath = basePath / "meta"
        contPath = basePath / "content"
        try:
            if supportsDirectoryDescriptors():
                rootFd = openDirectory(basePath)
                try:
                    if fileIdentity(os.fstat(rootFd)) != rootIdentity:
                        raise OSError("The project folder changed while it was being opened")
                    for childName in ("meta", "content"):
                        with suppress(FileExistsError):
                            os.mkdir(childName, 0o700, dir_fd=rootFd)
                        childFd = openDirectoryAt(rootFd, childName)
                        try:
                            childStat = os.fstat(childFd)
                            if not stat.S_ISDIR(childStat.st_mode):
                                raise OSError("The project folders are not real directories")
                            if childName == "meta":
                                self._metaIdentity = fileIdentity(childStat)
                            else:
                                self._contentIdentity = fileIdentity(childStat)
                        finally:
                            os.close(childFd)
                    currentRootStat = os.lstat(basePath)
                    if fileIdentity(currentRootStat) != rootIdentity:
                        raise OSError("The project folder changed while it was being opened")
                finally:
                    os.close(rootFd)
            else:
                currentRootStat = os.lstat(basePath)
                if isLinkLike(basePath) or fileIdentity(currentRootStat) != rootIdentity:
                    raise OSError("The project folder changed while it was being opened")
                ensureDirectory(metaPath)
                currentRootStat = os.lstat(basePath)
                if fileIdentity(currentRootStat) != rootIdentity:
                    raise OSError("The project folder changed while it was being opened")
                ensureDirectory(contPath)
                currentRootStat = os.lstat(basePath)
                if fileIdentity(currentRootStat) != rootIdentity:
                    raise OSError("The project folder changed while it was being opened")
                metaStat = os.lstat(metaPath)
                contentStat = os.lstat(contPath)
                if (
                    isLinkLike(metaPath)
                    or isLinkLike(contPath)
                    or not stat.S_ISDIR(metaStat.st_mode)
                    or not stat.S_ISDIR(contentStat.st_mode)
                ):
                    raise OSError("The project folders are not real directories")
                self._metaIdentity = fileIdentity(metaStat)
                self._contentIdentity = fileIdentity(contentStat)
        except Exception as exc:
            logger.error("Failed to create project folders", exc_info=exc)
            self._clearLockFile()
            self.clear()
            return ProjectStorageOpen.FAILED

        # Check for legacy data folders
        try:
            legacy = _LegacyStorage(self._project)
            legacy.deprecatedFiles(
                basePath,
                expectedRoot=rootIdentity,
                expectedMeta=self._metaIdentity,
            )
            if supportsDirectoryDescriptors():
                rootFd = openDirectory(basePath)
                try:
                    if fileIdentity(os.fstat(rootFd)) != rootIdentity:
                        raise OSError("The project folder changed before legacy data could be scanned")
                    with os.scandir(rootFd) as entries:
                        for entry in entries:
                            if not entry.name.startswith("data_"):
                                continue
                            entryStat = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(entryStat.st_mode) or isLinkLike(basePath / entry.name):
                                raise OSError("Legacy project folders cannot be links")
                            if stat.S_ISDIR(entryStat.st_mode):
                                legacy.legacyDataFolder(
                                    basePath,
                                    basePath / entry.name,
                                    expectedRoot=rootIdentity,
                                    expectedContent=self._contentIdentity,
                                )
                finally:
                    os.close(rootFd)
            else:
                currentRootStat = os.lstat(basePath)
                if isLinkLike(basePath) or fileIdentity(currentRootStat) != rootIdentity:
                    raise OSError("The project folder changed before legacy data could be scanned")
                with os.scandir(basePath) as entries:
                    for entry in entries:
                        if not entry.name.startswith("data_"):
                            continue
                        entryStat = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(entryStat.st_mode) or isLinkLike(basePath / entry.name):
                            raise OSError("Legacy project folders cannot be links")
                        if stat.S_ISDIR(entryStat.st_mode):
                            legacy.legacyDataFolder(
                                basePath,
                                basePath / entry.name,
                                expectedRoot=rootIdentity,
                                expectedContent=self._contentIdentity,
                            )
                currentRootStat = os.lstat(basePath)
                if fileIdentity(currentRootStat) != rootIdentity:
                    raise OSError("The project folder changed while legacy data was being scanned")
            self._oldDocuments = legacy.findOldDocuments(
                contPath,
                expectedParent=self._contentIdentity,
            )
        except Exception as exc:
            logger.error("Failed to scan project folder content", exc_info=exc)
            self._clearLockFile()
            self.clear()
            return ProjectStorageOpen.FAILED

        return ProjectStorageOpen.READY

    def runPostXMLTasks(self) -> bool:
        """Run tasks after the project XML has been loaded."""
        if self._oldDocuments:
            try:
                legacy = _LegacyDocuments(self._project)
                legacy.convertDocuments(self._oldDocuments)
            except Exception as exc:
                self._exception = exc
                return False
        return True

    def runPostSaveTasks(
        self,
        saveTime: float,
        autoSave: bool = False,
        *,
        expectedParent: Optional[FileIdentity] = None,
        expectedTarget: Optional[FileIdentity] = None,
        replaceExisting: bool = True,
    ) -> bool:
        """Run tasks after the project has been saved."""
        if self._openMode == self.MODE_INPLACE:
            self._kind = nwProjectKind.PROJECT
            if expectedParent is None and expectedTarget is None:
                manifestParent = self._rootIdentity
                manifestTarget = self._lastManifestIdentity
                manifestReplace = manifestTarget is not None
            else:
                manifestParent = expectedParent
                manifestTarget = expectedTarget
                manifestReplace = replaceExisting
            return self._writeManifest(
                nwProjectKind.PROJECT,
                saveTime,
                expectedParent=manifestParent,
                expectedTarget=manifestTarget,
                replaceExisting=manifestReplace,
            )
        return True

    def lockSession(self, *, expectedParent: Optional[FileIdentity] = None) -> bool:
        """Lock the session when the project is successfully opened.

        Lock creation is exclusive. A lock that appeared after the
        initial project inspection is never replaced, and the caller is
        told when acquisition failed. If this storage instance already
        owns the lock, acquisition is idempotent.
        """
        if not self._ready:
            return False
        if self._lockFileIdentity is not None:
            if not isinstance(self._lockFilePath, Path):
                return False
            try:
                if self._rootIdentity is not None:
                    parentStat = os.lstat(self._lockFilePath.parent)
                    if fileIdentity(parentStat) != self._rootIdentity:
                        return False
                currentStat = os.lstat(self._lockFilePath)
            except OSError:
                currentStat = None
            return bool(
                currentStat is not None
                and stat.S_ISREG(currentStat.st_mode)
                and fileIdentity(currentStat) == self._lockFileIdentity
            )
        parentIdentity = expectedParent if expectedParent is not None else self._rootIdentity
        if parentIdentity is None:
            return False
        return self._writeLockFile(expectedParent=parentIdentity)

    def closeSession(self) -> None:
        """Run tasks related to closing the session."""
        self._clearLockFile()
        self.clear()

    ##
    #  Content Access Methods
    ##

    def getXmlReader(self) -> Optional[ProjectXMLReader]:
        """Return a properly configured ProjectXMLReader instance."""
        if isinstance(self._runtimePath, Path) and self._ready:
            return ProjectXMLReader(
                self._runtimePath / nwFiles.PROJ_FILE,
                expectedParent=self._rootIdentity,
            )
        return None

    def getXmlWriter(self) -> Optional[ProjectXMLWriter]:
        """Return a properly configured ProjectXMLWriter instance."""
        if isinstance(self._runtimePath, Path) and self._ready:
            return ProjectXMLWriter(self._runtimePath / nwFiles.PROJ_FILE)
        return None

    def getDocument(self, tHandle: Optional[str]) -> ProjectDocument:
        """Return a document wrapper object."""
        if isinstance(self._runtimePath, Path) and self._ready:
            return ProjectDocument(self._project, tHandle)
        return ProjectDocument(self._project, None)

    def getMetaFile(self, fileName: str) -> Optional[Path]:
        """Return the path to a file in the project meta folder."""
        if isinstance(self._runtimePath, Path) and self._ready:
            return self._runtimePath / "meta" / fileName
        return None

    def getDocumentText(self, tHandle: str) -> str:
        """Return the text of a document in a fast and efficient way."""
        if isinstance(self._runtimePath, Path):
            return ProjectDocument.quickReadText(
                self._runtimePath / "content",
                tHandle,
                expectedParent=self._contentIdentity,
            )
        return ""

    def scanContent(self) -> list[str]:
        """Scan the content folder and return the handle of all files
        found in it. Files that do not match the pattern are ignored.
        """
        contentPath = self.contentPath
        if not contentPath:
            return []
        contentStat = os.lstat(contentPath)
        if isLinkLike(contentPath) or not stat.S_ISDIR(contentStat.st_mode):
            return []
        contentIdentity = fileIdentity(contentStat)
        if self._contentIdentity is not None and contentIdentity != self._contentIdentity:
            logger.error("The content folder changed while it was being scanned")
            return []
        handles: list[str] = []
        with os.scandir(contentPath) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and entry.name.endswith(".md"):
                    handle = entry.name[:-3]
                    if isHandle(handle):
                        handles.append(handle)
        currentStat = os.lstat(contentPath)
        if not os.path.samestat(contentStat, currentStat):
            logger.error("The content folder changed while it was being scanned")
            return []
        return handles

    def zipIt(self, target: str | Path, saveTime: float, compression: Optional[int] = None) -> bool:
        """Zip the content of the project at its runtime location into a
        zip file. This process will only grab files that are supposed to
        be in the project. All non-project files will be left out.
        """
        basePath = self._runtimePath
        if not isinstance(basePath, Path):
            logger.error("No path set")
            return False

        targetPath = Path(target)
        stagePath: Optional[Path] = None
        stageIdentity: Optional[FileIdentity] = None
        targetParentFd: Optional[int] = None
        try:
            if isLinkLike(targetPath):
                raise OSError("The archive target cannot be a link")
            if isLinkLike(targetPath.parent):
                raise OSError("The archive folder cannot be a link")
            targetParentStat = os.lstat(targetPath.parent)
            if not stat.S_ISDIR(targetParentStat.st_mode):
                raise OSError("The archive folder is not a directory")
            targetParentIdentity = fileIdentity(targetParentStat)
            if os.name != "nt" and os.open in os.supports_dir_fd:
                targetParentFd = openDirectory(targetPath.parent)
                if fileIdentity(os.fstat(targetParentFd)) != targetParentIdentity:
                    raise OSError("The archive folder changed while it was being opened")
            if targetPath.exists():
                targetStat = os.lstat(targetPath)
                if not stat.S_ISREG(targetStat.st_mode):
                    raise OSError("The archive target is not a regular file")

            baseMeta = basePath / "meta"
            baseCont = basePath / "content"
            baseAssets = basePath / "assets"
            baseImages = baseAssets / "img"

            rootStat = os.lstat(basePath)
            if isLinkLike(basePath) or not stat.S_ISDIR(rootStat.st_mode):
                raise OSError("The project folder is not a real directory")
            rootIdentity = fileIdentity(rootStat)
            if self._rootIdentity is not None and rootIdentity != self._rootIdentity:
                raise OSError("The project folder changed before the backup could be created")

            files: list[tuple[Path, str, FileIdentity, FileIdentity]] = []
            projectFile = basePath / nwFiles.PROJ_FILE
            if isLinkLike(projectFile):
                raise OSError("The project file cannot be a link")
            if projectFile.exists():
                if not projectFile.is_file():
                    raise OSError("The project file is not a regular file")
                files.append((
                    projectFile,
                    nwFiles.PROJ_FILE,
                    rootIdentity,
                    fileIdentity(os.lstat(projectFile)),
                ))

            if baseMeta.exists() or isLinkLike(baseMeta):
                metaSnapshot = scanRegularFiles(baseMeta)
                if self._metaIdentity is not None and metaSnapshot.identity != self._metaIdentity:
                    raise OSError("The project metadata folder changed before the backup could be created")
                metaFiles = {item.name for item in metaSnapshot.files}
                for fileName in (
                    nwFiles.BUILDS_FILE,
                    nwFiles.INDEX_FILE,
                    nwFiles.OPTS_FILE,
                    nwFiles.DICT_FILE,
                    nwFiles.SESS_FILE,
                ):
                    metaFile = baseMeta / fileName
                    if metaFile.name in metaFiles:
                        files.append((
                            metaFile,
                            f"meta/{metaFile.name}",
                            metaSnapshot.identity,
                            metaSnapshot.fileIdentities[metaFile.name],
                        ))
                    elif metaFile.exists():
                        raise OSError(f"The project metadata file is not a regular file: {metaFile.name}")

            if baseCont.exists() or isLinkLike(baseCont):
                contentSnapshot = scanRegularFiles(baseCont)
                if self._contentIdentity is not None and contentSnapshot.identity != self._contentIdentity:
                    raise OSError("The project content folder changed before the backup could be created")
                files.extend(
                    (
                        contentFile,
                        f"content/{contentFile.name}",
                        contentSnapshot.identity,
                        contentSnapshot.fileIdentities[contentFile.name],
                    )
                    for contentFile in contentSnapshot.files
                    if contentFile.suffix == ".md" and isHandle(contentFile.stem)
                )

            if baseAssets.exists() or isLinkLike(baseAssets):
                if isLinkLike(baseAssets) or isLinkLike(baseImages):
                    raise OSError("The project image folder cannot be a link")
                if not baseAssets.is_dir():
                    raise OSError("The project asset folder is not a directory")
                if baseImages.exists():
                    if not baseImages.is_dir():
                        raise OSError("The project image folder is not a directory")
                    assetSnapshot = scanRegularFiles(baseImages, expectedPath=baseImages)
                    files.extend(
                        (
                            assetFile,
                            f"assets/img/{assetFile.name}",
                            assetSnapshot.identity,
                            assetSnapshot.fileIdentities[assetFile.name],
                        )
                        for assetFile in assetSnapshot.files
                    )

            comp = ZIP_STORED if compression is None else ZIP_DEFLATED
            level = minmax(compression, 0, 9) if isinstance(compression, int) else None
            stageName = f".umbraedit-backup-{uuid.uuid4().hex}.tmp"
            stagePath = targetPath.parent / stageName
            if targetParentFd is not None:
                stageFd = openExclusiveFile(Path(stageName), targetParentFd, mode=0o600)
            else:
                stageFd = openExclusiveFile(stagePath, mode=0o600)
            stageIdentity = fileIdentity(os.fstat(stageFd))
            with os.fdopen(stageFd, mode="wb") as stageFile:
                with ZipFile(stageFile, mode="w", compression=comp, compresslevel=level) as zipObj:
                    logger.info("Creating archive: %s", targetPath)
                    zipObj.writestr(
                        nwFiles.MANIFEST_FILE,
                        self._generateManifest(nwProjectKind.BACKUP, saveTime),
                    )
                    for srcPath, zipPath, parentIdentity, sourceIdentity in files:
                        _addFileToZip(
                            zipObj,
                            srcPath,
                            zipPath,
                            parentIdentity,
                            sourceIdentity,
                        )
                        logger.debug("Added: %s", zipPath)
                stageFile.flush()
                os.fsync(stageFile.fileno())

            if targetParentFd is not None:
                currentStageStat = os.stat(
                    stageName,
                    dir_fd=targetParentFd,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(currentStageStat.st_mode) or fileIdentity(currentStageStat) != stageIdentity:
                    raise OSError("The staged archive changed before it could be published")
                if not renameNoReplaceBetween(
                    Path(stageName),
                    Path(targetPath.name),
                    sourceDirFd=targetParentFd,
                    targetDirFd=targetParentFd,
                ):
                    raise FileExistsError(errno.EEXIST, "The archive target already exists", str(targetPath))
                publishedStat = os.stat(
                    targetPath.name,
                    dir_fd=targetParentFd,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(publishedStat.st_mode) or fileIdentity(publishedStat) != stageIdentity:
                    raise OSError("The published archive does not match the staged archive")
                currentParentStat = os.lstat(targetPath.parent)
                if not os.path.samestat(os.fstat(targetParentFd), currentParentStat):
                    with suppress(OSError):
                        unlinkEntryIfSameFile(targetPath, stageIdentity, dirFd=targetParentFd)
                    raise OSError("The archive folder changed while the archive was being published")
            else:
                currentStageStat = os.lstat(stagePath)
                if not stat.S_ISREG(currentStageStat.st_mode) or fileIdentity(currentStageStat) != stageIdentity:
                    raise OSError("The staged archive changed before it could be published")
                publishRegularFileNoReplace(
                    stagePath,
                    targetPath,
                    stageIdentity,
                    expectedSourceParent=targetParentIdentity,
                    expectedTargetParent=targetParentIdentity,
                )
            stagePath = None

        except Exception:
            logger.error("Failed to create archive")
            logException()
            if stagePath is not None and stageIdentity is not None:
                with suppress(OSError):
                    if targetParentFd is not None:
                        unlinkEntryIfSameFile(
                            Path(stagePath.name),
                            stageIdentity,
                            dirFd=targetParentFd,
                        )
                    else:
                        unlinkEntryIfSameFile(stagePath, stageIdentity)
            return False
        finally:
            if targetParentFd is not None:
                os.close(targetParentFd)

        return True

    ##
    #  Internal Functions
    ##

    def _readLockFile(self) -> None:
        """Read the project lock file without following links."""
        self._lockedBy = None
        path = self._lockFilePath
        if not isinstance(path, Path):
            return
        try:
            pathStat = os.lstat(path)
        except FileNotFoundError:
            return
        except OSError:
            logger.error("Failed to inspect project lockfile")
            logException()
            self._lockedBy = ["ERROR", "ERROR", "ERROR", "ERROR"]
            return

        if not stat.S_ISREG(pathStat.st_mode) or isLinkLike(path):
            logger.error("The project lockfile is not a regular file")
            self._lockedBy = ["ERROR", "ERROR", "ERROR", "ERROR"]
            return

        try:
            with openRegularFile(path, expectedParent=self._rootIdentity) as inFile:
                lockData = inFile.read(4097)
            if len(lockData) > 4096:
                raise ValueError("The project lockfile is too large")
            self._lockedBy = lockData.decode("utf-8").strip().split(";")
        except Exception:
            logger.error("Failed to read project lockfile")
            logException()
            self._lockedBy = ["ERROR", "ERROR", "ERROR", "ERROR"]

    def _writeLockFile(self, *, expectedParent: Optional[FileIdentity] = None) -> bool:
        """Create the project lock file exclusively without following links."""
        path = self._lockFilePath
        if not isinstance(path, Path):
            return False
        try:
            parentStat = os.lstat(path.parent)
            if not stat.S_ISDIR(parentStat.st_mode):
                raise OSError("The project folder is not a directory")
            parentIdentity = fileIdentity(parentStat)
            if expectedParent is not None and parentIdentity != expectedParent:
                raise OSError("The project folder changed before the lockfile could be created")
            if isLinkLike(path):
                raise OSError("The project lockfile cannot be a link")
            try:
                os.lstat(path)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(errno.EEXIST, "The project lockfile already exists", str(path))

            lockData = f"{CONFIG.hostName};{CONFIG.osType};{CONFIG.kernelVer};{int(time())}"
            self._lockFileIdentity = writeFileAtomic(
                path,
                lockData.encode("utf-8"),
                expectedParent=parentIdentity,
                expectedTarget=None,
            )
            return True
        except Exception:
            self._lockFileIdentity = None
            logger.error("Failed to write project lockfile")
            logException()
            return False

    def _clearLockFile(self, force: bool = False) -> None:
        """Remove the lock file only when it is owned by this session.

        ``force`` is reserved for the explicit "clear lock" recovery
        action. Normal session shutdown never removes a lock that was
        installed by another process.
        """
        path = self._lockFilePath
        if not isinstance(path, Path):
            return
        try:
            pathStat = os.lstat(path)
        except FileNotFoundError:
            self._lockedBy = None
            self._lockFileIdentity = None
            return
        except OSError:
            logger.error("Failed to remove project lockfile")
            logException()
            return

        if not stat.S_ISREG(pathStat.st_mode) or isLinkLike(path):
            logger.error("The project lockfile is not a regular file")
            return
        currentIdentity = fileIdentity(pathStat)
        if not force:
            if self._lockFileIdentity is None:
                logger.warning("The project lockfile is not owned by this session")
                return
            if currentIdentity != self._lockFileIdentity:
                logger.warning("The project lockfile changed and was preserved")
                return
        try:
            if self._rootIdentity is not None:
                parentStat = os.lstat(path.parent)
                if fileIdentity(parentStat) != self._rootIdentity:
                    raise OSError("The project folder changed before the lockfile could be removed")
            if os.name != "nt" and os.open in os.supports_dir_fd:
                parentFd = openDirectory(path.parent)
                try:
                    if self._rootIdentity is not None and fileIdentity(os.fstat(parentFd)) != self._rootIdentity:
                        raise OSError("The project folder changed before the lockfile could be removed")
                    entryStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
                    if not stat.S_ISREG(entryStat.st_mode) or fileIdentity(entryStat) != currentIdentity:
                        raise OSError("The project lockfile changed before it could be removed")
                    unlinkEntryIfSameFile(path, currentIdentity, dirFd=parentFd)
                finally:
                    os.close(parentFd)
            else:
                unlinkIfSameFile(path, currentIdentity)
        except Exception:
            logger.error("Failed to remove project lockfile")
            logException()
            return
        self._lockFileIdentity = None
        self._lockedBy = None

    def _generateManifest(self, kind: nwProjectKind, saveTime: float) -> str:
        """Generate the manifest JSON content."""
        return json.dumps(
            {
                "format": "UmbraEdit Project",
                "formatVersion": MANIFEST_VERSION,
                "projectVersion": f"{FILE_VERSION}-{FILE_REVISION}",
                "kind": kind,
                "timeStamp": formatTimeStamp(saveTime),
                "appVersion": __version__,
                "hexVersion": __hexversion__,
            },
            indent=2,
        )

    def _readManifest(self) -> bool:
        """Read the manifest file without following links."""
        self._kind = nwProjectKind.PROJECT
        self._timeStamp = None
        self._lastManifestIdentity = None
        path = self._manifestPath
        if not isinstance(path, Path):
            return True
        try:
            pathStat = os.lstat(path)
        except FileNotFoundError:
            if self._rootIdentity is not None:
                parentStat = os.lstat(path.parent)
                if isLinkLike(path.parent) or fileIdentity(parentStat) != self._rootIdentity:
                    self._exception = OSError("The project folder changed before the manifest could be read")
                    return False
            return True
        except OSError as exc:
            self._exception = exc
            logger.error("Failed to inspect manifest", exc_info=exc)
            return False
        if not stat.S_ISREG(pathStat.st_mode) or isLinkLike(path):
            self._exception = OSError("The project manifest is not a regular file")
            logger.error("The project manifest is not a regular file")
            return False
        try:
            with openRegularFile(path, expectedParent=self._rootIdentity) as inFile:
                manifestIdentity = fileIdentity(os.fstat(inFile.fileno()))
                data = json.loads(inFile.read().decode("utf-8"))
            self._lastManifestIdentity = manifestIdentity
            self._kind = nwProjectKind(data.get("kind"))
            self._timeStamp = datetime.fromisoformat(data.get("timeStamp"))
        except Exception:
            logger.error("Failed to read manifest")
            logException()
        return True

    def _writeManifest(
        self,
        kind: nwProjectKind,
        saveTime: float,
        *,
        expectedParent: Optional[FileIdentity] = None,
        expectedTarget: Optional[FileIdentity] = None,
        replaceExisting: bool = True,
    ) -> bool:
        """Write the manifest file."""
        if self._manifestPath is None:
            return False
        try:
            text = self._generateManifest(kind, saveTime)
            lineEnding = CONFIG.lineEnding if isinstance(CONFIG.lineEnding, str) else os.linesep
            payload = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", lineEnding).encode("utf-8")
            self._lastManifestIdentity = writeFileAtomic(
                self._manifestPath,
                payload,
                expectedParent=expectedParent,
                expectedTarget=expectedTarget,
                replaceExisting=replaceExisting,
            )
        except Exception:
            logger.error("Failed to write manifest")
            logException()
            return False
        return True


class _LegacyStorage:
    """Core: Legacy Storage Converter Utils.

    A class with various functions to convert old file formats and
    file/folder layouts to the current project format.
    """

    def __init__(self, project: NWProject) -> None:
        self._project = project

    def legacyDataFolder(
        self,
        path: Path,
        child: Path,
        *,
        expectedRoot: Optional[FileIdentity] = None,
        expectedContent: Optional[FileIdentity] = None,
    ) -> None:
        """Handle the content of a legacy data folder from a version 1.0
        project. This format had 16 data folders where there now is only
        one content folder.
        """
        logger.info("Processing legacy data folder: %s", path)

        first = child.name[-1]
        if first not in "0123456789abcdef":
            return

        try:
            rootStat = os.lstat(path)
            if isLinkLike(path) or not stat.S_ISDIR(rootStat.st_mode):
                raise OSError("The project folder is not a real directory")
            rootIdentity = fileIdentity(rootStat)
            if expectedRoot is not None and rootIdentity != expectedRoot:
                raise OSError("The project folder changed before the legacy folder could be processed")
            childStat = os.lstat(child)
            if isLinkLike(child) or not stat.S_ISDIR(childStat.st_mode):
                raise OSError("The legacy data folder is not a real directory")
            childIdentity = fileIdentity(childStat)
            contentPath = path / "content"
            contentStat = os.lstat(contentPath)
            if isLinkLike(contentPath) or not stat.S_ISDIR(contentStat.st_mode):
                raise OSError("The project content folder is not a real directory")
            contentIdentity = fileIdentity(contentStat)
            if expectedContent is not None and contentIdentity != expectedContent:
                raise OSError("The project content folder changed before the legacy folder could be processed")
        except OSError as exc:
            logger.error("Failed to validate legacy data folder: %s", child, exc_info=exc)
            return

        childFd: Optional[int] = None
        contentFd: Optional[int] = None
        rootFd: Optional[int] = None
        try:
            if supportsDirectoryDescriptors():
                rootFd = openDirectory(path)
                if fileIdentity(os.fstat(rootFd)) != rootIdentity:
                    raise OSError("The project folder changed while the legacy folder was opened")
                childFd = openDirectoryAt(rootFd, child.name)
                if fileIdentity(os.fstat(childFd)) != childIdentity:
                    raise OSError("The legacy data folder changed while it was being opened")
                contentFd = openDirectoryAt(rootFd, "content")
                if fileIdentity(os.fstat(contentFd)) != contentIdentity:
                    raise OSError("The project content folder changed while it was being opened")
            else:
                currentChildStat = os.lstat(child)
                if isLinkLike(child) or fileIdentity(currentChildStat) != childIdentity:
                    raise OSError("The legacy data folder changed before it could be processed")
                currentContentStat = os.lstat(contentPath)
                if isLinkLike(contentPath) or fileIdentity(currentContentStat) != contentIdentity:
                    raise OSError("The project content folder changed before it could be processed")
                childFd = None
                contentFd = None

            entries = os.scandir(childFd) if childFd is not None else os.scandir(child)
            with entries as scandirEntries:
                for entry in scandirEntries:
                    entryStat = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(entryStat.st_mode) or getattr(entryStat, "st_file_attributes", 0) & 0x400:
                        raise OSError("Legacy project files cannot be links")
                    if not stat.S_ISREG(entryStat.st_mode):
                        continue
                    name = entry.name
                    itemIdentity = fileIdentity(entryStat)
                    itemPath = Path(name) if childFd is not None else child / name
                    if len(name) == 21 and name.endswith("_main.nwd"):
                        newName = f"{first}{name[:12]}.nwd"
                        newPath = path / "content" / newName
                        try:
                            moved = renameNoReplaceIfSameFile(
                                itemPath,
                                newPath,
                                itemIdentity,
                                sourceDirFd=childFd,
                                targetDirFd=contentFd,
                            )
                            if moved:
                                logger.info("Moved file: %s", newPath)
                            else:
                                logger.warning("Could not move file because the target exists: %s", newPath)
                        except Exception as exc:
                            logger.warning("Failed to move: %s", itemPath, exc_info=exc)
                    elif len(name) == 21 and name.endswith("_main.bak"):
                        try:
                            unlinkEntryIfSameFile(itemPath, itemIdentity, dirFd=childFd)
                            logger.info("Deleted file: %s", itemPath)
                        except Exception as exc:
                            logger.warning("Failed to delete: %s", itemPath, exc_info=exc)
        except Exception as exc:
            logger.error("Failed to process legacy data folder: %s", child, exc_info=exc)
        finally:
            if contentFd is not None:
                os.close(contentFd)
            if childFd is not None:
                os.close(childFd)
            if rootFd is not None:
                os.close(rootFd)

        # Remove Data Folder only if both directories still refer to the
        # objects that were validated before conversion began.
        try:
            currentChildStat = os.lstat(child)
            currentContentStat = os.lstat(contentPath)
            if (
                isLinkLike(child)
                or isLinkLike(contentPath)
                or fileIdentity(currentChildStat) != childIdentity
                or fileIdentity(currentContentStat) != contentIdentity
            ):
                raise OSError("The legacy or content folder changed before cleanup")
            if removeEmptyDirectoryIfOwned(child, childIdentity, expectedParent=rootIdentity):
                logger.info("Deleted folder: %s", child)
        except Exception as exc:
            logger.warning("Failed to delete: %s", child, exc_info=exc)

    def deprecatedFiles(
        self,
        path: Path,
        *,
        expectedRoot: Optional[FileIdentity] = None,
        expectedMeta: Optional[FileIdentity] = None,
    ) -> None:
        """Handle files that are no longer used by UmbraEdit."""
        if expectedRoot is not None:
            rootStat = os.lstat(path)
            if isLinkLike(path) or fileIdentity(rootStat) != expectedRoot:
                logger.error("The project folder changed before deprecated files could be processed")
                return
        self._convertOldWordList(  # Changed in 2.1 Beta 1
            path / "meta" / "wordlist.txt",
            path / "meta" / nwFiles.DICT_FILE,
            expectedParent=expectedMeta,
        )
        self._convertOldLogFile(  # Changed in 2.1 Beta 1
            path / "meta" / "sessionStats.log",
            path / "meta" / nwFiles.SESS_FILE,
            expectedParent=expectedMeta,
        )

        # Delete removed files
        remove = [
            (path / "meta" / "tagsIndex.json", expectedMeta),  # Renamed in 2.1 Beta 1
            (path / "meta" / "mainOptions.json", expectedMeta),  # Replaced in 0.5
            (path / "meta" / "exportOptions.json", expectedMeta),  # Replaced in 0.5
            (path / "meta" / "outlineOptions.json", expectedMeta),  # Replaced in 0.5
            (path / "meta" / "timelineOptions.json", expectedMeta),  # Replaced in 0.5
            (path / "meta" / "docMergeOptions.json", expectedMeta),  # Replaced in 0.5
            (path / "meta" / "sessionLogOptions.json", expectedMeta),  # Replaced in 0.5
            (path / "cache" / "prevBuild.json", expectedRoot),  # Dropped in 2.1 Beta 1
            (path / "cache", expectedRoot),  # Dropped in 2.1 Beta 1
            (path / "ToC.json", expectedRoot),  # Dropped in 1.0 RC 1
            (path / "nwProject.bak", expectedRoot),  # Dropped in 2.3 Beta 1
        ]
        for item, expectedParent in remove:
            try:
                self._removeDeprecatedEntry(item, expectedParent=expectedParent)
                if not os.path.lexists(item):
                    logger.info("Deleted: %s", item)
            except Exception as exc:  # noqa: PERF203
                logger.warning("Failed to delete: %s", item, exc_info=exc)

    def findOldDocuments(
        self,
        content: Path,
        *,
        expectedParent: Optional[FileIdentity] = None,
    ) -> list[LegacyDocument]:
        """Return verified legacy documents without following links."""
        contentStat = os.lstat(content)
        if isLinkLike(content) or not stat.S_ISDIR(contentStat.st_mode):
            raise OSError("The content folder is not a real directory")
        parentIdentity = fileIdentity(contentStat)
        if expectedParent is not None and parentIdentity != expectedParent:
            raise OSError("The content folder changed before it could be scanned")
        snapshot = scanRegularFiles(content)
        if snapshot.identity != parentIdentity:
            raise OSError("The content folder changed while it was being scanned")
        documents: list[LegacyDocument] = [
            LegacyDocument(
                path=documentPath,
                identity=snapshot.fileIdentities[documentPath.name],
                parentIdentity=snapshot.identity,
            )
            for documentPath in snapshot.files
            if documentPath.suffix == ".nwd" and not os.path.lexists(documentPath.with_suffix(".md"))
        ]
        return documents

    ##
    #  Internal Functions
    ##

    def _removeDeprecatedEntry(
        self,
        path: Path,
        *,
        expectedParent: Optional[FileIdentity] = None,
    ) -> None:
        """Remove one deprecated entry without following links."""
        try:
            pathStat = os.lstat(path)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(pathStat.st_mode) or isLinkLike(path):
            raise OSError("The deprecated entry cannot be a link")
        identity = fileIdentity(pathStat)
        parentStat = os.lstat(path.parent)
        if isLinkLike(path.parent) or not stat.S_ISDIR(parentStat.st_mode):
            raise OSError("The deprecated entry parent is not a real directory")
        parentIdentity = fileIdentity(parentStat)
        if expectedParent is not None and parentIdentity != expectedParent:
            raise OSError("The deprecated entry parent changed")
        if stat.S_ISDIR(pathStat.st_mode):
            removeEmptyDirectoryIfOwned(path, identity, expectedParent=parentIdentity)
            return
        if os.name != "nt" and os.open in os.supports_dir_fd:
            parentFd = openDirectory(path.parent)
            try:
                if fileIdentity(os.fstat(parentFd)) != parentIdentity:
                    raise OSError("The deprecated entry parent changed")
                entryStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
                if not stat.S_ISREG(entryStat.st_mode) or fileIdentity(entryStat) != identity:
                    raise OSError("The deprecated entry changed before it could be removed")
                unlinkEntryIfSameFile(Path(path.name), identity, dirFd=parentFd)
            finally:
                os.close(parentFd)
        else:
            unlinkIfSameFile(path, identity)

    def _unlinkExpectedFile(
        self,
        path: Path,
        expectedIdentity: FileIdentity,
        expectedParent: FileIdentity,
    ) -> None:
        """Remove a source file only if it is still the observed object."""
        parentStat = os.lstat(path.parent)
        if isLinkLike(path.parent) or not stat.S_ISDIR(parentStat.st_mode):
            raise OSError("The source parent is not a real directory")
        if fileIdentity(parentStat) != expectedParent:
            raise OSError("The source parent changed before cleanup")
        if os.name != "nt" and os.open in os.supports_dir_fd:
            parentFd = openDirectory(path.parent)
            try:
                if fileIdentity(os.fstat(parentFd)) != expectedParent:
                    raise OSError("The source parent changed before cleanup")
                entryStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
                if not stat.S_ISREG(entryStat.st_mode) or fileIdentity(entryStat) != expectedIdentity:
                    raise OSError("The source changed before cleanup")
                unlinkEntryIfSameFile(Path(path.name), expectedIdentity, dirFd=parentFd)
            finally:
                os.close(parentFd)
        else:
            unlinkIfSameFile(path, expectedIdentity)

    def _convertOldWordList(
        self,
        wordList: Path,
        wordJson: Path,
        *,
        expectedParent: Optional[FileIdentity] = None,
    ) -> None:
        """Convert the old word list plain text file to new format."""
        try:
            outputStat = os.lstat(wordJson)
        except FileNotFoundError:
            outputStat = None
        except OSError:
            return
        if outputStat is not None:
            # If the new file already exists, we won't overwrite it.
            return

        try:
            sourceStat = os.lstat(wordList)
        except FileNotFoundError:
            return
        except OSError:
            raise

        try:
            if stat.S_ISLNK(sourceStat.st_mode) or isLinkLike(wordList) or not stat.S_ISREG(sourceStat.st_mode):
                raise OSError("The old word list is not a regular file")
            parentStat = os.lstat(wordList.parent)
            if isLinkLike(wordList.parent) or not stat.S_ISDIR(parentStat.st_mode):
                raise OSError("The word list parent is not a real directory")
            parentIdentity = fileIdentity(parentStat)
            if expectedParent is not None and parentIdentity != expectedParent:
                raise OSError("The word list parent changed before conversion")
            sourceIdentity = fileIdentity(sourceStat)

            logger.info("Converting: %s", wordList)
            words: list[str] = []
            with openRegularFile(
                wordList,
                expectedParent=parentIdentity,
                expectedIdentity=sourceIdentity,
            ) as inFile:
                words.extend(word for line in inFile.read().decode("utf-8").splitlines() if (word := line.strip()))

            data = {"UmbraEdit.userDict": list(dict.fromkeys(words))}
            payload = json.dumps(data, indent=2).encode("utf-8")
            writeFileAtomic(
                wordJson,
                payload,
                expectedParent=parentIdentity,
                expectedTarget=None,
                replaceExisting=False,
            )
            self._unlinkExpectedFile(wordList, sourceIdentity, parentIdentity)
        except Exception:
            logger.error("Failed to convert old word list file")
            logException()

    def _convertOldLogFile(
        self,
        sessLog: Path,
        sessJson: Path,
        *,
        expectedParent: Optional[FileIdentity] = None,
    ) -> None:
        """Convert the old text log file format to JSON Lines."""
        try:
            outputStat = os.lstat(sessJson)
        except FileNotFoundError:
            outputStat = None
        except OSError:
            return
        if outputStat is not None:
            # If the new file already exists, we won't overwrite it.
            return

        try:
            sourceStat = os.lstat(sessLog)
        except FileNotFoundError:
            return
        except OSError:
            raise

        try:
            if stat.S_ISLNK(sourceStat.st_mode) or isLinkLike(sessLog) or not stat.S_ISREG(sourceStat.st_mode):
                raise OSError("The old session log is not a regular file")
            parentStat = os.lstat(sessLog.parent)
            if isLinkLike(sessLog.parent) or not stat.S_ISDIR(parentStat.st_mode):
                raise OSError("The session log parent is not a real directory")
            parentIdentity = fileIdentity(parentStat)
            if expectedParent is not None and parentIdentity != expectedParent:
                raise OSError("The session log parent changed before conversion")
            sourceIdentity = fileIdentity(sourceStat)

            data = []
            offset = 0
            session = self._project.session
            logger.info("Converting: %s", sessLog)
            with openRegularFile(
                sessLog,
                expectedParent=parentIdentity,
                expectedIdentity=sourceIdentity,
            ) as inFile:
                records = inFile.read().decode("utf-8").splitlines()
            for record in records:
                bits = record.split()
                nBits = len(bits)
                if record.startswith("# Offset") and nBits == 3:
                    offset = int(bits[2])
                elif not record.startswith("#") and nBits > 5:
                    data.append(
                        session.createRecord(
                            start=f"{bits[0]} {bits[1]}",
                            end=f"{bits[2]} {bits[3]}",
                            novel=int(bits[4]),
                            notes=int(bits[5]),
                            idle=int(bits[6]) if nBits > 6 else 0,
                        )
                    )

            payload = (session.createInitial(offset) + "".join(data)).encode("utf-8")
            writeFileAtomic(
                sessJson,
                payload,
                expectedParent=parentIdentity,
                expectedTarget=None,
                replaceExisting=False,
            )
            self._unlinkExpectedFile(sessLog, sourceIdentity, parentIdentity)
        except Exception:
            logger.error("Failed to convert old stats file")
            logException()


class _LegacyDocuments:
    """Core: Legacy Document Format Converter."""

    def __init__(self, project: NWProject) -> None:
        self._project = project

    def convertDocuments(self, documents: Sequence[LegacyDocument | Path]) -> None:
        """Convert verified .nwd documents to the current .md format."""
        for document in documents:
            if isinstance(document, LegacyDocument):
                item = document.path
                sourceIdentity = document.identity
                parentIdentity = document.parentIdentity
            else:
                item = document
                try:
                    sourceStat = os.lstat(item)
                    parentStat = os.lstat(item.parent)
                except OSError:
                    continue
                if (
                    stat.S_ISLNK(sourceStat.st_mode)
                    or isLinkLike(item)
                    or not stat.S_ISREG(sourceStat.st_mode)
                    or isLinkLike(item.parent)
                    or not stat.S_ISDIR(parentStat.st_mode)
                    or item.suffix != ".nwd"
                ):
                    continue
                sourceIdentity = fileIdentity(sourceStat)
                parentIdentity = fileIdentity(parentStat)

            output = item.with_suffix(".md")
            if os.path.lexists(output):
                logger.warning(
                    "The converted document already exists; preserving the legacy source: %s",
                    item.name,
                )
                continue

            try:
                with openRegularFile(
                    item,
                    expectedParent=parentIdentity,
                    expectedIdentity=sourceIdentity,
                ) as inFile:
                    rawText = inFile.read().decode("utf-8")
                lines = rawText.splitlines(keepends=True)
                meta: list[str] = []
                bodyStart = 0
                for index, line in enumerate(lines[:10]):
                    if line.startswith(r"%%~"):
                        meta.append(line)
                        bodyStart = index + 1
                    else:
                        bodyStart = index
                        break
                text = "".join(lines[bodyStart:])

                parser = NTomlParser(flat=True)
                toml = parser.writeString(self._parseOldDocumentMeta(meta)).strip()
                lineEnding = CONFIG.lineEnding if isinstance(CONFIG.lineEnding, str) else os.linesep
                payloadText = f"+++\n{toml}\n+++\n{text}".replace("\r\n", "\n").replace("\r", "\n")
                payload = payloadText.replace("\n", lineEnding).encode("utf-8")
                publishedIdentity = writeFileAtomic(
                    output,
                    payload,
                    expectedParent=parentIdentity,
                    expectedTarget=None,
                    replaceExisting=False,
                )
            except FileExistsError:
                # The target may have appeared after the initial check. It
                # is never overwritten, and the legacy source is preserved.
                logger.warning(
                    "The converted document already exists; preserving the legacy source: %s",
                    item.name,
                )
                continue
            except Exception:
                logger.error("Failed to convert: %s", item.name)
                self._preserveUnconvertedSource(item, output, sourceIdentity, parentIdentity)
                continue

            logger.info("Converted file: %s -> %s", item.name, output.name)
            try:
                outputStat = verifyPathIdentity(
                    output,
                    publishedIdentity,
                    expectedParent=parentIdentity,
                )
                if not stat.S_ISREG(outputStat.st_mode):
                    raise OSError("The converted document is not a regular file")
                self._removeConvertedSource(item, sourceIdentity, parentIdentity)
            except Exception:
                # Publication and source cleanup are separate operations.
                # A cleanup failure must not turn a successful conversion
                # into a failed project open, and the source is retained.
                logger.warning(
                    "The converted document was published, but the legacy source could not be removed; "
                    "preserving the source: %s",
                    item.name,
                    exc_info=True,
                )

    ##
    #  Internal Functions
    ##

    def _preserveUnconvertedSource(
        self,
        source: Path,
        target: Path,
        sourceIdentity: FileIdentity,
        parentIdentity: FileIdentity,
    ) -> None:
        """Preserve a legacy source when conversion cannot be published."""
        parentFd: Optional[int] = None
        try:
            if os.name != "nt" and os.open in os.supports_dir_fd:
                parentFd = openDirectory(source.parent)
                if fileIdentity(os.fstat(parentFd)) != parentIdentity:
                    raise OSError("The legacy document parent changed before it could be preserved")
                moved = renameNoReplaceIfSameFile(
                    Path(source.name),
                    Path(target.name),
                    sourceIdentity,
                    sourceDirFd=parentFd,
                    targetDirFd=parentFd,
                )
            else:
                moved = renameNoReplaceIfSameFile(
                    source,
                    target,
                    sourceIdentity,
                )
            if moved:
                logger.info("Renamed unconverted file: %s -> %s", source.name, target.name)
                return
            if os.path.lexists(target):
                logger.warning(
                    "The converted document already exists; preserving the legacy source: %s",
                    source.name,
                )
                return
            raise OSError(errno.EEXIST, "The converted document could not be preserved", str(target))
        except Exception:
            if os.path.lexists(target):
                logger.warning(
                    "The converted document already exists; preserving the legacy source: %s",
                    source.name,
                )
                return
            logger.exception("Failed to preserve legacy document: %s", source.name)
            raise
        finally:
            if parentFd is not None:
                os.close(parentFd)

    def _removeConvertedSource(
        self,
        path: Path,
        expectedIdentity: FileIdentity,
        expectedParent: FileIdentity,
    ) -> None:
        """Remove a converted source only if it is still the same file."""
        parentStat = os.lstat(path.parent)
        if isLinkLike(path.parent) or not stat.S_ISDIR(parentStat.st_mode):
            raise OSError("The legacy document parent is not a real directory")
        if fileIdentity(parentStat) != expectedParent:
            raise OSError("The legacy document parent changed before cleanup")
        if os.name != "nt" and os.open in os.supports_dir_fd:
            parentFd = openDirectory(path.parent)
            try:
                if fileIdentity(os.fstat(parentFd)) != expectedParent:
                    raise OSError("The legacy document parent changed before cleanup")
                entryStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
                if not stat.S_ISREG(entryStat.st_mode) or fileIdentity(entryStat) != expectedIdentity:
                    raise OSError("The legacy document changed before cleanup")
                unlinkEntryIfSameFile(Path(path.name), expectedIdentity, dirFd=parentFd)
            finally:
                os.close(parentFd)
        else:
            unlinkIfSameFile(path, expectedIdentity)

    def _parseOldDocumentMeta(self, lines: list[str]) -> T_TomlObject:
        """Parse a line from the document starting with the characters
        %%~ that may contain meta data.
        """
        meta: T_TomlObject = {}
        for line in lines:
            if line.startswith("%%~name:"):
                meta["name"] = simplified(line[8:])

            elif line.startswith("%%~path:"):
                metaVal = line[8:].strip()
                metaBits = metaVal.split("/")
                if len(metaBits) == 2:
                    if isHandle(metaBits[0]):
                        meta["parent"] = metaBits[0]
                    if isHandle(metaBits[1]):
                        meta["handle"] = metaBits[1]

            elif line.startswith("%%~kind:"):
                metaVal = line[8:].strip()
                metaBits = metaVal.split("/")
                if len(metaBits) == 2:
                    if metaBits[0] in nwItemClass.__members__:
                        meta["class"] = nwItemClass[metaBits[0]]
                    if metaBits[1] in nwItemLayout.__members__:
                        meta["layout"] = nwItemLayout[metaBits[1]]

            elif line.startswith("%%~hash:"):
                meta["textHash"] = line[8:].strip()

            elif line.startswith("%%~date:"):
                metaVal = line[8:].strip()
                metaBits = metaVal.split("/")
                if len(metaBits) == 2:
                    meta["createdDate"] = metaBits[0].strip()
                    meta["updatedDate"] = metaBits[1].strip()

            else:
                logger.debug("Unknown meta data: '%s'", line.strip())

        return meta
