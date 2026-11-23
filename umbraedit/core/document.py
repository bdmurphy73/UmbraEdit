"""
UmbraEdit - Project Document
==============================

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

import hashlib
import io
import logging
import os
import stat

from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Optional, TextIO, Union

from umbraedit import CONFIG
from umbraedit.common import formatTimeStamp, isHandle, stripUnsafe
from umbraedit.core.safeio import (
    FileIdentity,
    fileIdentity,
    isLinkLike,
    openDirectory,
    openRegularFile,
    unlinkIfSameFile,
    writeFileAtomic,
)
from umbraedit.enum import nwItemClass, nwItemLayout
from umbraedit.error import formatException, logException
from umbraedit.formats.tomlparser import NTomlParser

if TYPE_CHECKING:
    from umbraedit.core.item import ProjectItem
    from umbraedit.core.project import NWProject
    from umbraedit.formats.tomlparser import T_TomlObject

logger = logging.getLogger(__name__)

MAX_META_LINES = 20


@dataclass
class DocumentMeta:
    """A dataclass representing the meta data of a document."""

    name: str = ""
    parent: Optional[str] = None
    handle: Optional[str] = None
    itemClass: nwItemClass = nwItemClass.NOVEL
    itemLayout: nwItemLayout = nwItemLayout.NOTE
    textHash: str = ""
    createdDate: str = "Unknown"
    updatedDate: str = "Unknown"


class ProjectDocument:
    """Core: Project Document Class.

    A Class wrapping a single UmbraEdit document file. It represents
    a project item of nwItemType FILE. The file is not guaranteed to
    exist, even if the item does. In the case it doesn't exist, reading
    it returns a None rather than an empty or non-empty string.
    """

    def __init__(self, project: NWProject, tHandle: Optional[str]) -> None:

        self._project = project

        self._item = None  # The currently open item
        self._handle = None  # The handle of the currently open item
        self._fileLoc = None  # The file location of the currently open item
        self._meta = DocumentMeta()  # The meta data of the currently open item
        self._error = ""  # The latest encountered IO error

        self._lastHash = ""  # The last known SHA hash
        self._lastStat = None  # The (mtime_ns, size) of the file at last read/write
        self._lastIdentity: Optional[FileIdentity] = None  # Identity observed at the last read/write
        self._identityKnown = False  # Whether the target's presence was observed
        self._hashError = False  # Hash mismatch on last write attempt

        if isHandle(tHandle):
            self._handle = tHandle

        if self._handle is not None:
            self._item = self._project.tree[tHandle]

    def __repr__(self) -> str:
        """Return a string representation of the document."""
        return f"<ProjectDocument handle={self._handle}>"

    def __bool__(self) -> bool:
        """Return True if the document has a valid handle and item."""
        return self._handle is not None and self._item is not None

    ##
    #  Properties
    ##

    @property
    def hashError(self) -> bool:
        """Check if the file hash has changed outside of UmbraEdit."""
        return self._hashError

    @property
    def fileLocation(self) -> str:
        """Return the file location of the current document."""
        return str(self._fileLoc)

    @property
    def meta(self) -> DocumentMeta:
        """Return the meta data of the current document."""
        return self._meta

    @property
    def error(self) -> str:
        """Return the last recorded error."""
        return self._error

    @property
    def createdDate(self) -> str:
        """Return the document creation date."""
        return self._meta.createdDate

    @property
    def updatedDate(self) -> str:
        """Return the document creation date."""
        return self._meta.updatedDate

    @property
    def nwItem(self) -> Optional[ProjectItem]:
        """Return a pointer to the currently open ProjectItem."""
        return self._item

    ##
    #  Static Methods
    ##

    @staticmethod
    def quickReadText(
        content: Path,
        tHandle: str,
        expectedParent: Optional[FileIdentity] = None,
    ) -> str:
        """Return the text of a document without following links."""
        try:
            contentStat = os.lstat(content)
            if isLinkLike(content) or not stat.S_ISDIR(contentStat.st_mode):
                raise OSError("The content folder is not a real directory")
            parentIdentity = expectedParent if expectedParent is not None else fileIdentity(contentStat)
            if fileIdentity(contentStat) != parentIdentity:
                raise OSError("The content folder changed since the project was opened")
            path = content / f"{tHandle}.md"
            try:
                targetStat = os.lstat(path)
            except FileNotFoundError:
                return ""
            if isLinkLike(path) or not stat.S_ISREG(targetStat.st_mode):
                raise OSError("The document file is not a regular file")
            targetIdentity = fileIdentity(targetStat)
            with (
                openRegularFile(
                    path,
                    expectedParent=parentIdentity,
                    expectedIdentity=targetIdentity,
                ) as binaryFile,
                io.TextIOWrapper(binaryFile, encoding="utf-8", newline="") as inFile,
            ):
                _, text = ProjectDocument._splitHeader(inFile)
                return text
        except Exception:
            logger.error("Cannot read document with handle '%s'", tHandle)
            logException()
        return ""

    ##
    #  Methods
    ##

    def fileExists(self) -> bool:
        """Check if the document file exists."""
        if self._handle is None:
            return False

        contentPath = self._project.storage.contentPath
        if not isinstance(contentPath, Path):
            logger.error("No content path set")
            return False

        path = contentPath / f"{self._handle}.md"
        try:
            pathStat = os.lstat(path)
        except OSError:
            return False
        return stat.S_ISREG(pathStat.st_mode) and not isLinkLike(path)

    def readDocument(self, isOrphan: bool = False) -> Optional[str]:
        """Read the document specified by the handle set in the
        constructor, capturing potential file system errors and parse
        meta data. If the document doesn't exist on disk, return an
        empty string. If something went wrong, return None.
        """
        self._error = ""
        if not isinstance(self._handle, str):
            logger.error("No document handle set")
            return None

        if self._item is None and not isOrphan:
            logger.error("Unknown UmbraEdit document")
            return None

        contentPath = self._project.storage.contentPath
        if not isinstance(contentPath, Path):
            logger.error("No content path set")
            return None
        try:
            contentIdentity = self._getContentIdentity(contentPath)
        except OSError as exc:
            self._error = formatException(exc)
            return None

        docFile = f"{self._handle}.md"
        logger.debug("Opening document: %s", docFile)

        docPath = contentPath / docFile
        self._fileLoc = docPath

        text = ""
        self._meta = DocumentMeta()
        self._lastHash = ""
        self._lastStat = None
        self._lastIdentity = None
        self._identityKnown = False

        try:
            targetStat = os.lstat(docPath)
        except FileNotFoundError:
            targetStat = None
        except OSError as exc:
            self._error = formatException(exc)
            return None

        if targetStat is not None:
            try:
                if isLinkLike(docPath) or not stat.S_ISREG(targetStat.st_mode):
                    raise OSError("The document file is not a regular file")
                targetIdentity = fileIdentity(targetStat)
                with (
                    openRegularFile(
                        docPath,
                        expectedParent=contentIdentity,
                        expectedIdentity=targetIdentity,
                    ) as binaryFile,
                    io.TextIOWrapper(binaryFile, encoding="utf-8", newline="") as inFile,
                ):
                    metaLines, text = self._splitHeader(inFile)
                    if metaLines:
                        parser = NTomlParser(flat=True)
                        parser.readString("".join(metaLines))
                        self._applyMeta(parser)

                    # Record the file's identity and stat so future saves
                    # can detect a concurrent replacement without relying
                    # only on timestamps and file size.
                    fileStat = os.fstat(inFile.fileno())
                    self._lastIdentity = fileIdentity(fileStat)
                    self._identityKnown = True
                    self._lastStat = (fileStat.st_mtime_ns, fileStat.st_size)

            except Exception as exc:
                self._error = formatException(exc)
                return None

        else:
            # The document file does not exist, so we assume it's a new
            # document and return an empty text string.
            self._identityKnown = True
            logger.debug("The requested document does not exist")

        self._lastHash = hashlib.sha1(text.encode()).hexdigest()

        from umbraedit.umbra import hooks as _umbraHooks

        _umbraHooks.call(_umbraHooks.DOCUMENT_LOADING, self._handle, text)
        return stripUnsafe(text)

    def writeDocument(self, text: str, forceWrite: bool = False) -> bool:
        """Write the document specified by the handle attribute. Handle
        any IO errors in the process  Returns True if successful, False
        if not.
        """
        self._error = ""
        if not isinstance(self._handle, str):
            logger.error("No document handle set")
            return False

        contentPath = self._project.storage.contentPath
        if not isinstance(contentPath, Path):
            logger.error("No content path set")
            return False
        try:
            contentStat = os.lstat(contentPath)
            if isLinkLike(contentPath) or not stat.S_ISDIR(contentStat.st_mode):
                raise OSError("The content folder is not a real directory")
            contentIdentity = fileIdentity(contentStat)
        except OSError as exc:
            self._error = formatException(exc)
            return False

        docFile = f"{self._handle}.md"
        logger.debug("Saving document: %s", docFile)

        docPath = contentPath / docFile
        expectedTarget: Optional[FileIdentity] = None
        replaceExisting = False
        try:
            targetStat = os.lstat(docPath)
        except FileNotFoundError:
            targetStat = None
        except OSError as exc:
            self._error = formatException(exc)
            return False

        currentIdentity: Optional[FileIdentity] = None
        if targetStat is not None:
            if isLinkLike(docPath) or not stat.S_ISREG(targetStat.st_mode):
                self._error = "The document file is not a regular file"
                return False
            currentIdentity = fileIdentity(targetStat)

        if self._identityKnown:
            if self._lastIdentity != currentIdentity:
                if not forceWrite:
                    logger.error("The document file was replaced since it was opened")
                    self._hashError = True
                    return False
                if self.readDocument() is None:
                    return False
            expectedTarget = self._lastIdentity
            replaceExisting = expectedTarget is not None
        else:
            # This document was not loaded through this wrapper. Capture
            # the target once at the start of the write decision so a
            # replacement installed later cannot be adopted implicitly.
            expectedTarget = currentIdentity
            replaceExisting = currentIdentity is not None

        # Check if the document has changed in place on disk.
        prevHash = self._lastHash
        if prevHash:
            try:
                currentStat = os.lstat(docPath)
                if isLinkLike(docPath) or not stat.S_ISREG(currentStat.st_mode):
                    raise OSError("The document file is not a regular file")
                statSig = (currentStat.st_mtime_ns, currentStat.st_size)
            except OSError:
                statSig = None

            if statSig != self._lastStat:
                # Verify by checking the hash
                self.readDocument()
                if self._lastHash != prevHash and not forceWrite:
                    logger.error("File has been altered on disk since opened")
                    self._hashError = True
                    return False

        if text and not text.endswith("\n"):
            text += "\n"

        currTime = formatTimeStamp(time())
        writeHash = hashlib.sha1(text.encode(encoding="utf-8")).hexdigest()
        createdDate = self._meta.createdDate
        updatedDate = self._meta.updatedDate
        if writeHash != self._lastHash:
            updatedDate = currTime
        if targetStat is None:
            createdDate = currTime
            updatedDate = currTime

        # DocMeta Header
        docMeta = ""
        if self._item:
            meta: T_TomlObject = {
                "name": self._item.itemName,
                "parent": self._item.itemParent or "",
                "handle": self._item.itemHandle or "",
                "class": self._item.itemClass.name,
                "layout": self._item.itemLayout.name,
                "textHash": writeHash,
                "createdDate": createdDate,
                "updatedDate": updatedDate,
            }
            toml = NTomlParser(flat=True).writeString(meta).strip()
            docMeta = f"+++\n{toml}\n+++\n"

        # If we're here, the file was successfully prepared, so we can
        # notify listeners before it is published.
        from umbraedit.umbra import hooks as _umbraHooks

        _umbraHooks.call(_umbraHooks.DOCUMENT_PRE_SAVE, self._handle, str(docPath))

        try:
            payloadText = (docMeta + text).replace("\r\n", "\n").replace("\r", "\n")
            lineEnding = CONFIG.lineEnding if isinstance(CONFIG.lineEnding, str) else os.linesep
            payload = payloadText.replace("\n", lineEnding).encode("utf-8")
            publishedIdentity = writeFileAtomic(
                docPath,
                payload,
                expectedParent=contentIdentity,
                expectedTarget=expectedTarget,
                replaceExisting=replaceExisting,
            )
        except Exception as exc:
            self._error = formatException(exc)
            logger.error("Failed to write document '%s'", self._handle, exc_info=exc)
            return False

        self._lastHash = writeHash
        self._lastIdentity = publishedIdentity
        self._identityKnown = True
        self._meta.textHash = writeHash
        self._meta.createdDate = createdDate
        self._meta.updatedDate = updatedDate
        try:
            currentStat = os.lstat(docPath)
            if isLinkLike(docPath) or not stat.S_ISREG(currentStat.st_mode):
                raise OSError("The document file is not a regular file")
            self._lastStat = (currentStat.st_mtime_ns, currentStat.st_size)
        except OSError:
            self._lastStat = None
        self._hashError = False

        _umbraHooks.call(_umbraHooks.DOCUMENT_SAVED, self._handle, text)

        return True

    def deleteDocument(self) -> bool:
        """Permanently delete a document source file and related files
        from the project data folder.
        """
        self._error = ""
        if not isinstance(self._handle, str):
            logger.error("No document handle set")
            return False

        contentPath = self._project.storage.contentPath
        if not isinstance(contentPath, Path):
            logger.error("No content path set")
            return False

        docPath = contentPath / f"{self._handle}.md"
        docTemp = docPath.with_suffix(".tmp")

        try:
            contentIdentity = self._getContentIdentity(contentPath)
            parentFd: Optional[int] = None
            if os.name != "nt" and os.open in os.supports_dir_fd:
                parentFd = openDirectory(contentPath)
                if fileIdentity(os.fstat(parentFd)) != contentIdentity:
                    raise OSError("The content folder changed before the document could be removed")
            try:
                for targetPath in (docPath, docTemp):
                    try:
                        if parentFd is not None and os.stat in os.supports_dir_fd:
                            targetStat = os.stat(targetPath.name, dir_fd=parentFd, follow_symlinks=False)
                        else:
                            targetStat = os.lstat(targetPath)
                    except FileNotFoundError:
                        continue
                    if isLinkLike(targetPath) or not stat.S_ISREG(targetStat.st_mode):
                        raise OSError("The document file is not a regular file")
                    unlinkIfSameFile(targetPath, fileIdentity(targetStat), dirFd=parentFd)
            finally:
                if parentFd is not None:
                    os.close(parentFd)
        except Exception as exc:
            self._error = formatException(exc)
            return False

        return True

    ##
    #  Internal Functions
    ##

    def _getContentIdentity(self, contentPath: Path) -> FileIdentity:
        """Return the validated identity of the project content folder."""
        contentStat = os.lstat(contentPath)
        if isLinkLike(contentPath) or not stat.S_ISDIR(contentStat.st_mode):
            raise OSError("The content folder is not a real directory")
        contentIdentity = fileIdentity(contentStat)
        expectedIdentity = self._project.storage.contentIdentity
        if expectedIdentity is not None and contentIdentity != expectedIdentity:
            raise OSError("The content folder changed since the project was opened")
        return contentIdentity

    def _applyMeta(self, parser: NTomlParser) -> None:
        """Populate the document meta data from a parsed TOML header."""
        parent = parser.getStr(None, "parent", "")
        handle = parser.getStr(None, "handle", "")

        self._meta = DocumentMeta(
            name=parser.getStr(None, "name", ""),
            parent=parent if isHandle(parent) else None,
            handle=handle if isHandle(handle) else None,
            itemClass=parser.getEnum(None, "class", nwItemClass.NOVEL),
            itemLayout=parser.getEnum(None, "layout", nwItemLayout.NOTE),
            textHash=parser.getStr(None, "textHash", ""),
            createdDate=parser.getStr(None, "createdDate", "Unknown"),
            updatedDate=parser.getStr(None, "updatedDate", "Unknown"),
        )

    @staticmethod
    def _splitHeader(stream: TextIO) -> tuple[list[str], str]:
        """Split an open document file into TOML header and text."""
        first = stream.readline()
        if first.strip() == "+++":
            meta = []
            for _ in range(MAX_META_LINES):
                line = stream.readline()
                if not line:
                    break
                if line.strip() == "+++":
                    return meta, stream.read()
                meta.append(line)
            stream.seek(0)
            return [], stream.read()
        return [], first + stream.read()
