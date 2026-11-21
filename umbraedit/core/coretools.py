"""
UmbraEdit - Project Document Tools
====================================

This file is a part of UmbraEdit.

Copyright (C) 2022 Veronica Berglyd Olsen, B.D. Murphy and novelWriter contributors.

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
import logging
import os
import shutil
import stat
import tempfile
import time as time_module
import uuid
import xml.etree.ElementTree as ET

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Optional, Union
from zipfile import ZipFile, is_zipfile

from PyQt6.QtCore import QCoreApplication

from umbraedit import CONFIG, SHARED
from umbraedit.common import (
    isHandle,
    jsonEncode,
    minmax,
    safeExists,
    safeIsDir,
    safeIsFile,
    safeIterDir,
    simplified,
    writeTextFile,
)
from umbraedit.constants import nwFiles, nwItemClass, nwItemLayout, nwStats
from umbraedit.core.bookmeta import BookMetaBuilder
from umbraedit.core.project import NWProject
from umbraedit.core.storage import ProjectStorageCreate
from umbraedit.formats.fromdocx import (
    FromDocxDocument,
    ImportImage,
    ImportNote,
    ImportResult,
    ImportScene,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


logger = logging.getLogger(__name__)


class ScannedProject(NamedTuple):
    """A project found in the project folder."""

    path: Path
    name: str
    time: float


def scanProjectFolder(root: str | Path) -> list[ScannedProject]:
    """Scan a folder for UmbraEdit projects.

    All direct sub-folders of the given folder that contain a project file
    are returned. The name of the project is read from the project file when
    possible, and the folder name is used as a fallback. The time stamp
    is the time the project file was last modified.

    Args:
        root: The folder to scan.

    Returns:
        A list of the projects found in the folder.

    """
    result: list[ScannedProject] = []
    try:
        base = Path(root).expanduser()
    except (TypeError, ValueError):  # pragma: no cover
        return result
    if not base.parts or not safeIsDir(base):
        return result

    for item in sorted(safeIterDir(base)):
        try:
            if (
                item.name.startswith((".umbraedit-import-", ".umbraedit-project-"))
                or ".umbraedit-backup-" in item.name
                or ".umbraedit-failed-" in item.name
                or item.is_symlink()
                or not safeIsDir(item)
            ):
                continue
        except OSError:  # pragma: no cover
            continue
        projFile = item / nwFiles.PROJ_FILE
        try:
            if projFile.is_symlink() or not safeIsFile(projFile):
                continue
        except OSError:  # pragma: no cover
            continue
        try:
            stamp = projFile.stat().st_mtime
        except OSError:  # pragma: no cover
            stamp = 0.0
        result.append(ScannedProject(path=item, name=readProjectName(projFile) or item.name, time=stamp))

    return result


def readProjectName(projFile: str | Path) -> str:
    """Read the name of a project from its project file.

    Args:
        projFile: The path to the project file.

    Returns:
        The name of the project, or an empty string if it cannot be read.

    """
    try:
        with open(projFile, mode="rb") as inFile:
            for _, elem in ET.iterparse(inFile, events=("end",)):
                if elem.tag == "project":
                    for item in elem:
                        if item.tag == "name":
                            return simplified(item.text or "")
                    break
    except Exception:
        logger.debug("Could not read project name from %s", projFile)
    return ""


def isValidProjectFolder(path: str | Path) -> bool:
    """Check that a folder contains a valid UmbraEdit project file.

    Args:
        path: The project folder to validate.

    Returns:
        True if the project XML can be parsed and contains project data.

    """
    projFile = Path(path) / nwFiles.PROJ_FILE
    try:
        if projFile.is_symlink() or not safeIsFile(projFile):
            return False
    except OSError:  # pragma: no cover
        return False
    try:
        root = ET.parse(projFile).getroot()
    except (ET.ParseError, OSError):
        logger.debug("Could not validate project file: %s", projFile)
        return False
    return root.tag == "UmbraEditXML" and root.find("project") is not None


def readProjectLock(path: str | Path) -> Optional[str]:
    """Read the lock token for a project folder.

    Args:
        path: The project folder to inspect.

    Returns:
        The lock token, or None if the project is not locked. An invalid or
        unreadable lock file is returned as a non-empty placeholder so it
        is still treated as locked.

    """
    lockFile = Path(path) / nwFiles.PROJ_LOCK
    try:
        lockStat = os.lstat(lockFile)
    except FileNotFoundError:
        return None
    except NotADirectoryError:
        # The target itself is a file, so it cannot contain a lock file.
        return None
    except OSError:
        logger.error("Failed to inspect project lockfile: %s", lockFile)
        return "<unreadable>"

    if not stat.S_ISREG(lockStat.st_mode):
        logger.error("Invalid project lockfile: %s", lockFile)
        return "<invalid>"

    try:
        return lockFile.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        logger.error("Failed to read project lockfile: %s", lockFile)
        return "<unreadable>"


def containsProjectLock(path: str | Path) -> bool:
    """Check a path for project locks.

    The path itself and all of its descendant folders are checked. Symlinked
    folders are not followed, since replacing the containing path does not
    delete the contents of the link target. An unreadable folder is treated
    as locked so that an unknown state cannot lead to data loss.

    Args:
        path: The path to inspect.

    Returns:
        True if the path contains a project lock, otherwise False.

    """
    target = Path(path)
    if readProjectLock(target) is not None:
        return True

    try:
        if target.is_symlink() or not target.is_dir():
            return False
    except OSError:  # pragma: no cover
        return True

    folders = [target]
    while folders:
        folder = folders.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name == nwFiles.PROJ_LOCK:
                        return True
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            folders.append(Path(entry.path))
                    except OSError:  # pragma: no cover
                        return True
        except OSError:
            logger.error("Failed to inspect project folder for locks: %s", folder)
            return True

    return False


def replacePath(source: Path, target: Path) -> None:
    """Replace a path with a prepared path, with rollback on failure.

    The existing target is first moved to a uniquely named sibling backup.
    The prepared path is then moved into place. If that fails, the backup is
    restored so the original target is not lost. Project locks are checked
    before and after the move, and a lock appearing during the replacement
    aborts the operation.

    Args:
        source: The prepared path to move into place.
        target: The path to replace.

    Raises:
        OSError: If the paths could not be moved.
        RuntimeError: If the replacement failed and the original could not
            be restored automatically.

    """
    backup: Optional[Path] = None

    def removePath(path: Path) -> None:
        """Remove a path, whether it is a file, folder, or link."""
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def restoreBackup() -> None:
        """Restore the backup, preserving it if the target is occupied."""
        if backup is None:
            return
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"Could not install the replacement, and the original is preserved at: {backup}")
        try:
            backup.rename(target)
        except Exception as rollbackExc:
            raise RuntimeError(
                f"Could not install the replacement, and the original could not be restored: {backup}"
            ) from rollbackExc

    def preserveLockedTarget() -> None:
        """Preserve a locked replacement and restore the original target."""
        if backup is None:  # pragma: no cover
            raise RuntimeError("The project became locked and cannot be replaced.")

        failed = target.parent / f".{target.name}.umbraedit-failed-{uuid.uuid4().hex}"
        try:
            target.rename(failed)
            restoreBackup()
        except Exception as rollbackExc:
            raise RuntimeError(
                f"The project became locked, and the original could not be restored: {backup}"
            ) from rollbackExc
        raise RuntimeError(
            f"The project became locked. The original was restored, and the replacement was preserved at: {failed}"
        )

    # A prepared project must not carry a lock into its final location.
    # This also catches a lock that could not be removed when a staged copy
    # was closed.
    if containsProjectLock(source):
        raise RuntimeError("The replacement project is locked and cannot be installed.")

    if target.exists() or target.is_symlink():
        # Check the lock before moving anything. This avoids needlessly
        # making an active project disappear while the replacement is being
        # prepared. Descendant projects are checked as well, since replacing
        # a containing folder would otherwise delete them.
        if containsProjectLock(target):
            raise RuntimeError("The project is locked and cannot be replaced.")

        backup = target.parent / f".{target.name}.umbraedit-backup-{uuid.uuid4().hex}"
        target.rename(backup)

        # Check the moved target as well. A lock may have been written while
        # the target was being moved, and it must not be silently discarded.
        if containsProjectLock(backup):
            try:
                backup.rename(target)
            except Exception as rollbackExc:
                raise RuntimeError(
                    f"The project is locked, and the original could not be restored: {backup}"
                ) from rollbackExc
            raise RuntimeError("The project is locked and cannot be replaced.")

    try:
        source.rename(target)
    except Exception:
        if backup is not None:
            restoreBackup()
        raise

    # A concurrent opener can write its lock after the source has been
    # installed. Check the installed target, not the backup, before the old
    # project is discarded.
    if containsProjectLock(target):
        if backup is None:
            raise RuntimeError("The project became locked and cannot be replaced.")
        preserveLockedTarget()

    if backup is not None:
        # A lock can also appear in the moved target while the replacement
        # is being installed. In that case, remove the unlocked replacement
        # and restore the original.
        if containsProjectLock(backup):
            if containsProjectLock(target):
                preserveLockedTarget()
            try:
                removePath(target)
                restoreBackup()
            except Exception as rollbackExc:
                raise RuntimeError(
                    f"The project became locked, and the original could not be restored: {backup}"
                ) from rollbackExc
            raise RuntimeError("The project became locked and cannot be replaced.")

        # Check the installed target once more immediately before the old
        # project is discarded. This narrows the window in which a competing
        # opener could claim the replacement.
        if containsProjectLock(target):
            preserveLockedTarget()

        try:
            removePath(backup)
        except OSError:
            logger.warning("Could not remove the project backup: %s", backup)


class DocMerger:
    """Tool: Merge Documents.

    Document tool for merging a set of documents into a single new
    document. The parameters are defined by the user using the
    GuiDocMerge dialog.
    """

    def __init__(self, project: NWProject) -> None:
        self._project = project
        self._error = ""
        self._target = None
        self._text = []

    @property
    def targetHandle(self) -> Optional[str]:
        """Get the handle of the target document."""
        if self._target:
            return self._target.itemHandle
        return None

    ##
    #  Methods
    ##

    def getError(self) -> str:
        """Return any collected errors."""
        return self._error

    def setTargetDoc(self, tHandle: str) -> None:
        """Set the target document for the merging. Calling this
        function resets the class.
        """
        self._target = self._project.tree[tHandle]
        self._text = []

    def newTargetDoc(self, sHandle: str, label: str) -> None:
        """Create a brand new target document based on a source handle
        and a new doc label. Calling this function resets the class.
        """
        sItem = self._project.tree[sHandle]
        if sItem and sItem.itemParent:
            tHandle = self._project.newFile(label, sItem.itemParent)
            if nwItem := self._project.tree[tHandle]:  # pragma: no branch
                nwItem.setLayout(sItem.itemLayout)
                nwItem.setStatus(sItem.itemStatus)
                nwItem.setImport(sItem.itemImport)
                nwItem.notifyToRefresh()
                self._target = nwItem
                self._text = []

    def appendText(self, sHandle: str, addComment: bool, cmtPrefix: str) -> None:
        """Append text from an existing document to the text buffer."""
        if item := self._project.tree[sHandle]:
            text = self._project.storage.getDocumentText(sHandle).rstrip("\n")
            if addComment:
                info = item.describeMe()
                status, _ = item.getImportStatus()
                text = f"% {cmtPrefix} {info}: {item.itemName} [{status}]\n\n{text}"
            self._text.append(text)

    def writeTargetDoc(self) -> bool:
        """Write the accumulated text into the designated target
        document, appending any existing text.
        """
        if self._target:
            outDoc = self._project.storage.getDocument(self._target.itemHandle)
            if text := (outDoc.readDocument() or "").rstrip("\n"):
                self._text.insert(0, text)

            status = outDoc.writeDocument("\n\n".join(self._text) + "\n\n")
            if not status:
                self._error = outDoc.error

            self._project.index.reIndexHandle(self._target.itemHandle)
            self._target.notifyToRefresh()

            return status

        return False


class DocSplitter:
    """Document tool for splitting a document into a set of new
    documents. The parameters are defined by the user using the
    GuiDocSplit dialog.
    """

    def __init__(self, project: NWProject, sHandle: str) -> None:

        self._project = project

        self._error = ""
        self._parHandle = None
        self._srcHandle = None
        self._srcItem = None

        self._inFolder = False
        self._rawData = []

        srcItem = self._project.tree[sHandle]
        if srcItem is not None and srcItem.isFileType():
            self._srcHandle = sHandle
            self._srcItem = srcItem

    def __len__(self) -> int:
        """Return the number of raw data entries."""
        return len(self._rawData)

    ##
    #  Methods
    ##

    def getError(self) -> str:
        """Return any collected errors."""
        return self._error

    def setParentItem(self, pHandle: str) -> None:
        """Set the item that will be the top level parent item for the
        new documents.
        """
        self._parHandle = pHandle
        self._inFolder = False

    def newParentFolder(self, pHandle: str, folderLabel: str) -> None:
        """Create a new folder that will be the top level parent item
        for the new documents.
        """
        if self._srcItem:
            nHandle = self._project.newFolder(folderLabel, pHandle)
            if nwItem := self._project.tree[nHandle]:
                nwItem.setStatus(self._srcItem.itemStatus)
                nwItem.setImport(self._srcItem.itemImport)
                nwItem.notifyToRefresh()
            self._parHandle = nHandle
            self._inFolder = True

    def splitDocument(self, splitData: list, splitText: list[str]) -> None:
        """Loop through the split data record and perform the split job
        on a list of text lines.
        """
        self._rawData = []
        buffer = splitText.copy()
        for lineNo, hLevel, hLabel in reversed(splitData):
            chunk = buffer[lineNo:]
            buffer = buffer[:lineNo]
            self._rawData.insert(0, (chunk, hLevel, hLabel))

    def writeDocuments(self, docHierarchy: bool) -> Iterable[bool]:
        """Write each document in the buffer and yield if successful."""
        if self._srcHandle and self._srcItem and self._parHandle:
            pHandle = self._parHandle
            hHandle = [self._parHandle, "", "", "", ""]
            pLevel = 0
            for docText, hLevel, docLabel in self._rawData:
                hLevel = minmax(hLevel, 1, 4)
                if pLevel == 0:
                    pLevel = hLevel

                if docHierarchy:
                    if hLevel == 1:
                        pHandle = self._parHandle
                    elif hLevel == 2:
                        pHandle = hHandle[1] or hHandle[0]
                    elif hLevel == 3:
                        pHandle = hHandle[2] or hHandle[1] or hHandle[0]
                    elif hLevel == 4:
                        pHandle = hHandle[3] or hHandle[2] or hHandle[1] or hHandle[0]
                    else:  # pragma: no cover
                        pass

                if (dHandle := self._project.newFile(docLabel, pHandle)) and (nwItem := self._project.tree[dHandle]):
                    hHandle[hLevel] = dHandle
                    nwItem.setStatus(self._srcItem.itemStatus)
                    nwItem.setImport(self._srcItem.itemImport)

                    outDoc = self._project.storage.getDocument(dHandle)
                    status = outDoc.writeDocument("\n".join(docText))
                    if not status:
                        self._error = outDoc.error

                    self._project.index.reIndexHandle(dHandle)
                    nwItem.notifyToRefresh()

                    yield status

                    hHandle[hLevel] = dHandle
                    pLevel = hLevel
        return


class DocDuplicator:
    """A class that will duplicate all documents and folders starting
    from a given handle.
    """

    def __init__(self, project: NWProject) -> None:
        self._project = project

    ##
    #  Methods
    ##

    def duplicate(self, items: list[str]) -> list[str]:
        """Run through a list of items, duplicate them, and copy the
        text content if they are documents.
        """
        result = []
        after = True
        if items:
            hMap: dict[str, Optional[str]] = dict.fromkeys(items)
            SHARED.initMainProgress(len(items))
            for tHandle in items:
                SHARED.incMainProgress()
                if oldItem := self._project.tree[tHandle]:
                    pHandle = hMap.get(oldItem.itemParent or "") or oldItem.itemParent
                    if newItem := self._project.tree.duplicate(tHandle, pHandle, after):
                        hMap[tHandle] = newItem.itemHandle
                        if newItem.isFileType():
                            self._project.copyFileContent(newItem.itemHandle, tHandle)
                        newItem.notifyToRefresh()
                        result.append(newItem.itemHandle)
                    after = False
                else:
                    break
            SHARED.clearMainProgress()
        return result


class ProjectBuilder:
    """A class to build a new project from a set of user-defined
    parameter provided by the New Project Wizard.
    """

    def __init__(self) -> None:
        self._path = None
        self.tr = partial(QCoreApplication.translate, "ProjectBuilder")

    @property
    def projPath(self) -> Optional[Path]:
        """The path of the newly created project."""
        return self._path

    ##
    #  Methods
    ##

    def buildProject(self, data: dict) -> bool:
        """Build or copy a project from a data dictionary."""
        if isinstance(data, dict):
            path = data.get("path") or None
            if author := data.get("author"):
                CONFIG.setLastAuthor(author)
            if isinstance(path, (str, Path)):
                self._path = Path(path).resolve()
                if data.get("sample"):
                    built = self._extractSampleProject(self._path, data)
                elif data.get("template"):
                    built = self._copyProject(self._path, data)
                else:
                    built = self._buildAndPopulate(self._path, data)
                if built and not isValidProjectFolder(self._path):
                    SHARED.error(self.tr("The new project could not be validated."))
                    return False
                if built and containsProjectLock(self._path):
                    SHARED.error(self.tr("The new project could not be closed cleanly."))
                    return False
                return built
            SHARED.error("A project path is required.")
        return False

    ##
    #  Internal Functions
    ##

    def _buildAndPopulate(self, path: Path, data: dict) -> bool:
        """Build a blank project from a data dictionary."""
        project = NWProject()
        status = project.storage.createNewProject(path)
        if status == ProjectStorageCreate.NOT_EMPTY:
            SHARED.error(self.tr("The target folder is not empty. Please choose another folder."))
            return False
        elif status == ProjectStorageCreate.OS_ERROR:
            SHARED.error(
                self.tr("An error occurred while trying to create the project."),
                exc=project.storage.exc,
            )
            return False

        self._path = project.storage.storagePath

        trName = self.tr("New Project")
        trAuthor = self.tr("Author Name")
        trTitlePage = self.tr("Title Page")

        # Settings
        project.data.setUuid(None)
        project.data.setName(data.get("name", trName))
        project.data.setAuthor(data.get("author", trAuthor))
        project.data.setLanguage(CONFIG.guiLocale, CONFIG.rtlMode)
        project.setDefaultStatusImport()
        project.session.startSession()

        # Add Root Folders
        hNovelRoot = project.newRoot(nwItemClass.NOVEL)
        hTitlePage = project.newFile(trTitlePage, hNovelRoot)

        # Add the book metadata, which is common to all output formats
        BookMetaBuilder(project).build(project.data.name or "", project.data.author or "")

        # Generate Title Page
        aDoc = project.storage.getDocument(hTitlePage)
        aDoc.writeDocument(
            (
                "{author}[br]\n"
                "{address} 1[br]\n"
                "{address} 2 <<\n"
                "\n"
                "[vspace:5]\n"
                "\n"
                "#! {title}\n"
                "\n"
                ">> **{by} {author}** <<\n"
                "\n"
                ">> {count}: [field:{field}] <<\n"
            ).format(
                author=project.data.author or trAuthor,
                address=self.tr("Address Line"),
                title=project.data.name or trName,
                by=self.tr("By"),
                count=self.tr("Word Count"),
                field=nwStats.WORDS_TEXT,
            )
        )

        # Create chapters and scenes
        numChapters = data.get("chapters", 0)
        numScenes = data.get("scenes", 0)

        trChSynop = self.tr("Summary of the chapter.")
        trScSynop = self.tr("Summary of the scene.")
        trNoteDesc = self.tr("A short description.")

        # Create chapters
        if numChapters > 0:
            for ch in range(numChapters):
                chTitle = self.tr("Chapter {0}").format(f"{ch + 1:d}")
                cHandle = project.newFile(chTitle, hNovelRoot)
                aDoc = project.storage.getDocument(cHandle)
                aDoc.writeDocument(f"## {chTitle}\n\n%Synopsis: {trChSynop}\n\n")

                # Create chapter scenes
                if numScenes > 0 and cHandle:
                    for sc in range(numScenes):
                        scTitle = self.tr("Scene {0}").format(f"{ch + 1:d}.{sc + 1:d}")
                        sHandle = project.newFile(scTitle, cHandle)
                        aDoc = project.storage.getDocument(sHandle)
                        aDoc.writeDocument(f"### {scTitle}\n\n%Synopsis: {trScSynop}\n\n")

        # Create scenes (no chapters)
        elif numScenes > 0:
            for sc in range(numScenes):
                scTitle = self.tr("Scene {0}").format(f"{sc + 1:d}")
                sHandle = project.newFile(scTitle, hNovelRoot)
                aDoc = project.storage.getDocument(sHandle)
                aDoc.writeDocument(f"### {scTitle}\n\n%Synopsis: {trScSynop}\n\n")

        # Create notes folders
        noteTitles = {
            nwItemClass.PLOT: self.tr("Main Plot"),
            nwItemClass.CHARACTER: self.tr("Protagonist"),
            nwItemClass.WORLD: self.tr("Main Location"),
        }

        addNotes = data.get("notes", False)
        for newRoot in data.get("roots", []):
            if isinstance(newRoot, nwItemClass):
                rHandle = project.newRoot(newRoot)
                if addNotes:
                    aHandle = project.newFile(noteTitles[newRoot], rHandle)
                    ntTag = simplified(noteTitles[newRoot]).replace(" ", "")
                    aDoc = project.storage.getDocument(aHandle)
                    aDoc.writeDocument(f"# {noteTitles[newRoot]}\n\n@tag: {ntTag}\n\n%Short: {trNoteDesc}\n\n")

        # Also add the archive and trash folders
        project.newRoot(nwItemClass.ARCHIVE)
        _ = project.tree.trash  # Triggers the creation of Trash

        project.index.rebuild()
        if not project.saveProject():
            SHARED.error(self.tr("The new project could not be saved."))
            project.closeProject()
            return False
        project.closeProject()

        return True

    def _copyProject(self, path: Path, data: dict) -> bool:
        """Copy an existing project content, but not the meta data, and
        update new settings.
        """
        source = data.get("template")
        if not (
            isinstance(source, Path) and safeIsFile(source) and (source.name == nwFiles.PROJ_FILE or is_zipfile(source))
        ):
            logger.error("Could not access source project: %s", source)
            return False

        logger.info("Copying project: %s", source)
        if safeExists(path):
            SHARED.error(self.tr("The target folder already exists. Please choose another folder."))
            return False

        # Begin copying
        srcPath = source.parent
        dstPath = path.resolve()
        srcCont = srcPath / "content"
        dstCont = dstPath / "content"
        try:
            dstPath.mkdir(exist_ok=True)
            dstCont.mkdir(exist_ok=True)
            if is_zipfile(source):
                with ZipFile(source) as zipObj:
                    for member in zipObj.namelist():
                        if member == nwFiles.PROJ_FILE or (member.startswith("content") and member.endswith(".md")):
                            zipObj.extract(member, dstPath)
            else:
                shutil.copy2(srcPath / nwFiles.PROJ_FILE, dstPath)
                for item in srcCont.iterdir():
                    if item.is_file() and item.suffix == ".md" and isHandle(item.stem):
                        shutil.copy2(item, dstCont)
        except Exception as exc:
            SHARED.error(self.tr("Could not copy project files."), exc=exc)
            return False

        # Open the copied project and update settings
        return self._resetProject(dstPath, data)

    def _extractSampleProject(self, path: Path, data: dict) -> bool:
        """Make a copy of the sample project by extracting the
        sample.zip file to the new path.
        """
        if safeExists(path):
            SHARED.error(self.tr("The target folder already exists. Please choose another folder."))
            return False

        if safeIsFile(sample := CONFIG.assetPath("sample.zip")):
            try:
                # The sample.zip contains files at the root level (UEProject.UEx and content/).
                # Extract to a temporary location and move contents to the target path.
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmpdir_path = Path(tmpdir)
                    shutil.unpack_archive(sample, tmpdir_path)
                    # The zip contains files at root level; move them to the target path.
                    src = tmpdir_path
                    # Ensure target directory exists
                    path.mkdir(parents=True, exist_ok=True)
                    for item in src.iterdir():
                        shutil.move(str(item), str(path / item.name))
                if not self._resetProject(path, data):
                    return False
            except Exception as exc:
                SHARED.error(self.tr("Failed to create a new example project."), exc=exc)
                return False
        else:
            SHARED.error(
                self.tr(
                    "Failed to create a new example project. "
                    "Could not find the necessary files. "
                    "They seem to be missing from this installation."
                )
            )
            return False

        return True

    def _resetProject(self, path: Path, data: dict) -> bool:
        """Open a project and reset/update its settings."""
        project = NWProject()
        opened = False
        try:
            if not project.openProject(path):
                SHARED.error(self.tr("The copied project could not be opened."))
                return False
            opened = True

            isSample = project.data.uuid == "e2be99af-f9bf-4403-857a-c3d1ac25abea"

            # Project Data
            project.data.setUuid("")  # Creates a fresh uuid
            if name := data.get("name", ""):
                project.data.setName(name)
            if author := data.get("author", ""):
                project.data.setAuthor(author)
            if isSample:
                project.data.setLastHandle("974e400180a99", "editor")
                project.data.setLastHandle("53b69b83cdafc", "viewer")

            # Reset Items
            for item in project.tree:
                item.setCursorPos(0)
                item.setExpanded(True)

            # Settings
            project.data.setSpellCheck(True)
            project.data.setSpellLang(None)
            project.data.setDoBackup(True)
            project.data.setSaveCount(0)
            project.data.setAutoCount(0)
            project.data.setEditTime(0)

            project.index.rebuild()
            if not project.saveProject():
                SHARED.error(self.tr("The copied project could not be saved."))
                return False
        finally:
            if opened:
                project.closeProject()

        return True


class DocxImporter:
    """Tool: Import a Word DOCX/DOCM file into a new UmbraEdit project.

    The Word document is parsed, and the content is written to a new
    project where each chapter and scene becomes a project document.
    Scenes are nested under the chapter they belong to, so that the
    project tree reflects the structure of the novel.

    Comments from the Word document are inserted into the text of the
    document they were anchored to, as synopsis comments. Images are
    recorded in a separate "Images" document for each text document
    that contains them.

    Items that cannot be translated, like headers, footers and
    footnotes, are captured as note documents.

    The project is built in a temporary folder next to the target
    location, and moved into place when it is complete. If anything
    fails along the way, no project is created.
    """

    def __init__(self) -> None:
        self._error = ""
        self._projectPath: Optional[Path] = None
        self.tr = partial(QCoreApplication.translate, "DocxImporter")

    ##
    #  Properties
    ##

    @property
    def error(self) -> str:
        """Return any collected error message."""
        return self._error

    @property
    def projectPath(self) -> Optional[Path]:
        """Return the path of the project created by the last import."""
        return self._projectPath

    ##
    #  Public API
    ##

    def importFile(
        self,
        file_path: str | Path,
        project_path: str | Path,
        name: Optional[str] = None,
        author: Optional[str] = None,
        overwrite: bool = False,
    ) -> bool:
        """Import a Word DOCX/DOCM file into a new UmbraEdit project.

        Args:
            file_path: Path to the .docm or .docx file to import.
            project_path: Path where the new project folder will be created.
            name: Optional project name, overriding the document title.
            author: Optional author name, overriding the document author.
            overwrite: If True, an existing project folder at the target
                location is replaced by the imported project. The old
                project is only removed after the new project has been
                built successfully.

        Returns:
            True if the import was successful, False otherwise.

        """
        self._error = ""
        self._projectPath = None

        try:
            inPath = Path(file_path).expanduser().resolve()
            rawOutPath = Path(project_path).expanduser()
            if not rawOutPath.parts:
                raise ValueError("A project path is required")
            outPath = Path(os.path.abspath(rawOutPath))
        except Exception as exc:
            self._error = self.tr("Invalid path: {0}").format(str(exc))
            logger.error(self._error)
            return False

        if not safeIsFile(inPath):
            self._error = self.tr("The Word document could not be found.")
            logger.error(self._error)
            return False

        home = Path.home().resolve()
        if outPath == Path(outPath.anchor) or outPath == home or outPath in home.parents:
            self._error = self.tr("The target path is not a valid project location.")
            logger.error(self._error)
            return False

        if outPath.is_symlink():
            self._error = self.tr("The target path cannot be a symbolic link.")
            logger.error(self._error)
            return False

        if overwrite and containsProjectLock(outPath):
            self._error = self.tr("The project is open and cannot be replaced.")
            logger.error(self._error)
            return False

        if not overwrite and safeExists(outPath) and (not safeIsDir(outPath) or len(list(safeIterDir(outPath))) > 0):
            # The target folder must be empty, or not exist at all
            self._error = self.tr("The target folder is not empty.")
            logger.error(self._error)
            return False

        # Parse the Word document
        try:
            result = FromDocxDocument(inPath).parse()
        except Exception as exc:
            self._error = self.tr("Failed to parse the Word document: {0}").format(str(exc))
            logger.error(self._error, exc_info=exc)
            return False

        if not result.scenes:
            self._error = self.tr("No content was found in the Word document.")
            logger.error(self._error)
            return False

        # Build the project in a temporary folder next to the target, and
        # move it into place when it is complete
        tmpPath = None
        try:
            outPath.parent.mkdir(parents=True, exist_ok=True)
            tmpPath = Path(tempfile.mkdtemp(prefix=".umbraedit-import-", dir=str(outPath.parent)))
            if not self._buildProject(result, inPath, tmpPath, name, author):
                return False
            if not isValidProjectFolder(tmpPath):
                self._error = self.tr("The imported project could not be validated.")
                logger.error(self._error)
                return False
            if overwrite and containsProjectLock(outPath):
                self._error = self.tr("The project is open and cannot be replaced.")
                logger.error(self._error)
                return False
            replacePath(tmpPath, outPath)
            # Move the staged project's recent-project metadata to its
            # final path. This also replaces any stale metadata for the
            # project that was overwritten.
            resolvedOut = outPath.resolve()
            if str(outPath) != str(resolvedOut):
                CONFIG.recentProjects.remove(outPath)
            if not CONFIG.recentProjects.move(tmpPath.resolve(), resolvedOut):
                CONFIG.recentProjects.remove(resolvedOut)
        except Exception as exc:
            self._error = self.tr("Failed to create the project: {0}").format(str(exc))
            logger.error(self._error, exc_info=exc)
            return False
        finally:
            if tmpPath is not None:
                # Saving a staged project adds its temporary path to the
                # recent-project cache. Remove that transient entry.
                CONFIG.recentProjects.remove(tmpPath.resolve())
                if tmpPath.exists():
                    shutil.rmtree(tmpPath, ignore_errors=True)

        try:
            outPath.chmod(0o755)
        except OSError:  # pragma: no cover
            logger.warning("Could not set permissions on %s", outPath)

        self._projectPath = outPath
        logger.info(
            "Import completed: %d scenes, %d notes, %d images, %d comments",
            len(result.scenes),
            len(result.notes),
            len(result.images),
            len(result.comments),
        )
        return True

    ##
    #  Internal Functions
    ##

    def _buildProject(
        self,
        result: ImportResult,
        inPath: Path,
        path: Path,
        name: Optional[str] = None,
        author: Optional[str] = None,
    ) -> bool:
        """Build the project in the given folder."""
        project = NWProject()
        status = project.storage.createNewProject(path)
        if status != ProjectStorageCreate.READY:
            if status == ProjectStorageCreate.NOT_EMPTY:
                self._error = self.tr("The target folder is not empty.")
            else:
                self._error = self.tr("Failed to create the project folder.")
            logger.error(self._error)
            return False

        try:
            # Project meta data
            project.data.setUuid(None)
            project.data.setName(name or result.title or inPath.stem)
            project.data.setAuthor(author if author is not None else (result.author or ""))
            project.data.setLanguage(CONFIG.guiLocale, CONFIG.rtlMode)
            project.setDefaultStatusImport()
            project.session.startSession()

            # Root folders
            novelRoot = project.newRoot(nwItemClass.NOVEL)
            project.newRoot(nwItemClass.CHARACTER)
            project.newRoot(nwItemClass.WORLD)

            # The book metadata, which is common to all output formats
            BookMetaBuilder(project).build(project.data.name or "", project.data.author or "")

            researchRoot = project.newRoot(nwItemClass.CUSTOM)
            if item := project.tree[researchRoot]:
                item.setName("Research")
            project.newRoot(nwItemClass.ARCHIVE)
            _ = project.tree.trash  # Triggers the creation of Trash

            # Documents
            self._addScenes(project, novelRoot, result.scenes)

            # The image files referenced by the image documents
            self._writeImages(path, result.images)

            # The notes that could not be translated, and the issues
            # document and the source provenance
            for note in result.notes:
                self._addNote(project, researchRoot, note)
            self._addIssues(project, researchRoot, result, inPath)
            self._writeProvenance(path, inPath)

            project.index.rebuild()
            if not project.saveProject():
                self._error = self.tr("The imported project could not be saved.")
                logger.error(self._error)
                return False
        except Exception as exc:
            self._error = self.tr("Failed to build the project: {0}").format(str(exc))
            logger.error(self._error, exc_info=exc)
            return False
        finally:
            project.closeProject()

        return True

    def _addScenes(self, project: NWProject, novelRoot: str, scenes: list[ImportScene]) -> None:
        """Add the chapter and scene documents to the project.

        Scenes are added as children of the chapter they belong to, so
        that the project tree is indented like the novel structure.
        """
        chapterHandle: Optional[str] = None
        for scene in scenes:
            if scene.is_front:
                parent = novelRoot
                marker = "#"
                level = "H1"
                heading = scene.heading or self.tr("Front Matter")
            elif scene.is_chapter:
                parent = novelRoot
                marker = "##"
                level = "H2"
                heading = scene.heading
            else:
                parent = chapterHandle or novelRoot
                marker = "###"
                level = "H3"
                heading = scene.heading

            tHandle = project.newFile(heading, parent)
            if not tHandle:
                logger.error("Could not create document '%s'", heading)
                continue

            tItem = project.tree[tHandle]
            if tItem is None:  # pragma: no cover
                continue

            tItem.setLayout(nwItemLayout.DOCUMENT)
            tItem.setMainHeading(level)

            if scene.is_chapter:
                chapterHandle = tHandle

            parts = []
            if scene.preamble:
                parts.append("\n".join(scene.preamble).strip("\n"))
            parts.append(f"{marker} {heading}")
            if scene.text:
                parts.append(scene.text)

            text = "\n\n".join(parts) + "\n"
            aDoc = project.storage.getDocument(tHandle)
            aDoc.writeDocument(text)

            if scene.images:
                self._addImages(project, tHandle, scene.images)

    def _addImages(self, project: NWProject, parent: str, images: list[ImportImage]) -> None:
        """Add an images document for a text document.

        The document lists the images that were found in the text, with
        the ID used to reference them from the text itself.
        """
        tHandle = project.newFile("Images", parent)
        if not tHandle:
            logger.error("Could not create images document")
            return

        tItem = project.tree[tHandle]
        if tItem is None:  # pragma: no cover
            return

        tItem.setLayout(nwItemLayout.NOTE)
        tItem.setIconStyle("prj_document:image")

        lines = [
            "# Images",
            "",
            "The following images were found in this document. Each image is",
            "referenced from the text with an image marker holding the ID of",
            "the image.",
            "",
        ]
        for image in images:
            lines.append(f"## {image.img_id}")
            lines.append("")
            lines.append(f"- Source: {image.filename}")
            lines.append(f"- Type: {image.mime}")
            lines.append(f"- Size: {len(image.data)} bytes")
            lines.append(f"- Position: paragraph {image.paragraph}, offset {image.offset}")
            if image.context:
                lines.append(f"- Context: {image.context}")
            lines.append(f"- File: assets/img/{image.img_id}{Path(image.filename).suffix.lower()}")
            lines.append("")

        text = "\n".join(lines).strip() + "\n"
        aDoc = project.storage.getDocument(tHandle)
        aDoc.writeDocument(text)

    def _writeImages(self, path: Path, images: list[ImportImage]) -> None:
        """Write the image files to the assets folder of the project."""
        if not images:
            return
        try:
            imgDir = path / "assets" / "img"
            imgDir.mkdir(parents=True, exist_ok=True)
            for image in images:
                suffix = Path(image.filename).suffix.lower()
                target = imgDir / f"{image.img_id}{suffix}"
                target.write_bytes(image.data)
        except Exception as exc:
            logger.error("Failed to write the imported images", exc_info=exc)

    def _addNote(self, project: NWProject, notesRoot: str, note: ImportNote) -> None:
        """Add a note document for a non-translatable item."""
        label = f"{note.note_type.title()}: {note.source[:50]}"
        tHandle = project.newFile(label, notesRoot)
        if not tHandle:
            logger.error("Could not create note '%s'", label)
            return

        tItem = project.tree[tHandle]
        if tItem is None:  # pragma: no cover
            return

        tItem.setLayout(nwItemLayout.NOTE)

        lines = [
            f"# {note.note_type.title()}",
            "",
            f"Source: {note.source}",
            f"Type: {note.note_type}",
            "",
            note.text,
        ]
        if note.data:
            lines.append("")
            lines.append(f"Image data: {len(note.data)} bytes ({note.mime or 'unknown type'})")

        text = "\n".join(lines).strip() + "\n"
        aDoc = project.storage.getDocument(tHandle)
        aDoc.writeDocument(text)

    def _addIssues(self, project: NWProject, notesRoot: str, result: ImportResult, inPath: Path) -> None:
        """Add a document listing the items that could not be translated."""
        tHandle = project.newFile("Import Issues", notesRoot)
        if not tHandle:
            return

        tItem = project.tree[tHandle]
        if tItem is None:  # pragma: no cover
            return

        tItem.setLayout(nwItemLayout.NOTE)
        tItem.setIconStyle("alert_error:issue")

        counts: dict[str, int] = {}
        for note in result.notes:
            counts[note.note_type] = counts.get(note.note_type, 0) + 1

        loose = [c for c in result.comments if c.paragraph < 0]

        lines = [
            "# Import Issues",
            "",
            "The items listed below were found in the source document, but could not",
            "be translated directly into the project. They are recorded here so that",
            "they can be reviewed and corrected by hand.",
            "",
            f"Source file: {inPath.name}",
            f"Documents created: {len(result.scenes)}",
            "",
        ]

        if counts or loose:
            if counts:
                lines.append("## Summary")
                lines.append("")
                lines.extend(f"- {key.title()}: {counts[key]}" for key in sorted(counts))
                lines.append("")
            lines.append("## Details")
            lines.append("")
            details = []
            for note in result.notes:
                details.append(f"### {note.note_type.title()}: {note.source}")
                details.append("")
                if note.text:
                    details.append(note.text)
                    details.append("")
            for comment in loose:
                details.append(f"### Comment: {comment.cmt_id}")
                details.append("")
                details.append(f"Author: {comment.author}")
                details.append("")
                if comment.text:
                    details.append(comment.text)
                    details.append("")
            lines.extend(details)
        else:
            lines.append("No issues were found.")

        text = "\n".join(lines).strip() + "\n"
        aDoc = project.storage.getDocument(tHandle)
        aDoc.writeDocument(text)

    def _writeProvenance(self, path: Path, inPath: Path) -> None:
        """Write the source document and a manifest to the import folder."""
        try:
            importDir = path / "import"
            sourceDir = importDir / "source"
            sourceDir.mkdir(parents=True, exist_ok=True)
            target = sourceDir / f"original{inPath.suffix.lower()}"
            shutil.copyfile(inPath, target)
            data = {
                "source": inPath.name,
                "sha256": _fileSha256(inPath),
                "imported": time_module.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            writeTextFile(
                importDir / "manifest.json",
                jsonEncode(data, nmax=4),
                newline=CONFIG.lineEnding,
            )
        except Exception as exc:
            logger.error("Failed to write the import provenance", exc_info=exc)


def _fileSha256(path: Path) -> str:
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with open(path, mode="rb") as inFile:
        for chunk in iter(lambda: inFile.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
