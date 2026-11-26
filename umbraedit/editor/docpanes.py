"""
UmbraEdit - GUI Document Panes
================================

This file is a part of UmbraEdit.

Copyright (C) 2026 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import logging

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QFileDialog, QSplitter, QVBoxLayout, QWidget

from umbraedit import CONFIG, SHARED
from umbraedit.common import formatFileFilter
from umbraedit.constants import nwKeyWords
from umbraedit.core.imageimport import (
    ImageImportError,
    ImageImportReason,
    ProjectImage,
    importProjectImage,
    listProjectImages,
    readProjectImageByPath,
    removeImportedProjectImage,
    removeProjectImage,
    verifyImportedProjectImage,
)
from umbraedit.core.imagemeta import ImageMetadata, formatImageMetadata, referencedImagePaths
from umbraedit.core.safeio import captureRegularFileIdentity
from umbraedit.editor.editor import GuiDocEditor
from umbraedit.editor.viewer import GuiDocViewer
from umbraedit.editor.viewerpanel import GuiDocViewerPanel
from umbraedit.enum import nwDocAction, nwDocInsert, nwDocMode, nwView

if TYPE_CHECKING:
    from umbraedit.core.imageimport import ImportedImage
    from umbraedit.core.project import NWProject
    from umbraedit.dialogs.preferences import GuiNeedsUpdate
    from umbraedit.guimain import GuiMain

logger = logging.getLogger(__name__)


class GuiDocPanes(QWidget):
    """Gui Widget: Document Panes."""

    def __init__(self, mainGui: GuiMain) -> None:
        super().__init__(mainGui)

        self.mainGui = mainGui

        # Internal State
        self._switchingDocument = False

        # Components
        self.docEditor = GuiDocEditor(self)
        self.docViewer = GuiDocViewer(self)
        self.docViewerPanel = GuiDocViewerPanel(self)

        # Viewer Splitter
        self.splitView = QSplitter(Qt.Orientation.Vertical, self)
        self.splitView.addWidget(self.docViewer)
        self.splitView.addWidget(self.docViewerPanel)
        self.splitView.setHandleWidth(4)
        self.splitView.setOpaqueResize(False)
        self.splitView.setSizes(CONFIG.viewPanePos)
        self.splitView.setCollapsible(0, False)
        self.splitView.setCollapsible(1, False)

        # Main Splitter
        self.splitMain = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitMain.addWidget(self.docEditor)
        self.splitMain.addWidget(self.splitView)
        self.splitMain.setOpaqueResize(False)
        self.splitMain.setHandleWidth(4)
        self.splitMain.setCollapsible(0, False)
        self.splitMain.setCollapsible(1, False)

        # Editor / Viewer Default State
        self.splitView.setVisible(False)
        self.docEditor.closeSearch()

        # Assemble
        self.outerBox = QVBoxLayout()
        self.outerBox.addWidget(self.splitMain)
        self.outerBox.setContentsMargins(0, 0, 0, 0)

        self.setLayout(self.outerBox)

        # Connect Signals
        SHARED.indexAvailable.connect(self.docEditor.indexHasAppeared)
        SHARED.indexAvailable.connect(self.docViewer.indexHasAppeared)
        SHARED.indexAvailable.connect(self.docViewerPanel.indexHasAppeared)
        SHARED.indexChangedRefs.connect(self.docViewerPanel.updateChangedRefs)
        SHARED.indexChangedTags.connect(self.docEditor.updateChangedTags)
        SHARED.indexChangedTags.connect(self.docViewer.updateChangedTags)
        SHARED.indexChangedTags.connect(self.docViewerPanel.updateChangedTags)
        SHARED.indexCleared.connect(self.docViewerPanel.indexWasCleared)
        SHARED.projectItemChanged.connect(self.docEditor.onProjectItemChanged)
        SHARED.projectItemChanged.connect(self.docViewer.onProjectItemChanged)
        SHARED.projectItemChanged.connect(self.docViewerPanel.onProjectItemChanged)
        SHARED.spellLanguageChanged.connect(self.docEditor.processSpellCheckChange)
        SHARED.statusLabelsChanged.connect(self.docViewerPanel.updateStatusLabels)

        self.docEditor.closeEditorRequest.connect(self.closeDocEditor)
        self.docEditor.formattedViewRequest.connect(self.showFormattedView)
        self.docEditor.loadDocumentTagRequest.connect(self._followTag)
        self.docEditor.openDocumentRequest.connect(self.openDocumentInMode)
        self.docEditor.requestNextDocument.connect(self.openNextDocument)

        self.docViewer.closeDocumentRequest.connect(self.closeDocViewer)
        self.docViewer.documentLoaded.connect(self.docViewerPanel.updateHandle)
        self.docViewer.loadDocumentTagRequest.connect(self._followTag)
        self.docViewer.openDocumentRequest.connect(self.openDocumentInMode)
        self.docViewer.reloadDocumentRequest.connect(self._reloadViewer)
        self.docViewer.togglePanelVisibility.connect(self._toggleViewerPanelVisibility)

        self.docViewerPanel.loadDocumentTagRequest.connect(self._followTag)
        self.docViewerPanel.openDocumentRequest.connect(self.openDocumentInMode)

    ##
    #  Class Methods
    ##

    def initPanes(self) -> None:
        """Initialise the editor and viewer."""
        self.docEditor.initEditor()
        self.docViewer.initViewer()

    def updateTheme(self, syntax: bool = False) -> None:
        """Update theme elements."""
        self.docEditor.updateTheme()
        self.docViewer.updateTheme()
        self.docViewerPanel.updateTheme()
        if syntax:
            self.docEditor.updateSyntaxColors()

    def applySettings(self, update: GuiNeedsUpdate) -> None:
        """Apply changed preferences to the editor and viewer."""
        if update.editor or update.syntax or update.theme:
            self.docEditor.initEditor()
        if update.viewer or update.syntax or update.theme:
            self.docViewer.initViewer()
        if update.viewport:
            if not update.editor:
                self.docEditor.initViewport()
            if not update.viewer:
                self.docViewer.initViewport()
        if not update.editor:
            self.docEditor.initSettings(updateVimMode=update.vim)
        if not update.viewer:
            self.docViewer.initSettings()

    def saveLayout(self) -> None:
        """Save the layout state to config."""
        if not SHARED.focusMode and self.docViewerPanel.isVisible():
            CONFIG.viewPanePos = self.splitView.sizes()
        CONFIG.showViewerPanel = self.docViewerPanel.isVisible()

    def setFocusMode(self, focusMode: bool) -> None:
        """Show or hide pane elements for focus mode."""
        self.docEditor.docFooter.setVisible(not (focusMode and CONFIG.hideFocusFooter))
        self.docEditor.docHeader.setFocusMode(focusMode)
        self.splitView.setVisible(not focusMode and self.docViewer.docHandle is not None)

    def cycleFocus(self) -> None:
        """Move focus to the viewer if the editor has it, otherwise to the editor."""
        if self.splitView.isVisible() and self.docEditor.anyFocus():
            self.docViewer.setFocus()
        else:
            self.docEditor.setFocus()

    def openProjectTasks(self) -> None:
        """Run open project tasks, and restore the last open documents."""
        self.docEditor.toggleSpellCheck(SHARED.project.data.spellCheck)
        self.docViewerPanel.openProjectTasks()
        self.mainGui.imageAssets.refreshAssets()

        # If no document was recorded, open the first one found
        lastEdited = SHARED.project.data.getLastHandle("editor")
        if lastEdited is None:
            for nwItem in SHARED.project.tree:
                if nwItem and nwItem.isFileType():
                    lastEdited = nwItem.itemHandle
                    break

        if lastEdited is not None:
            self.openDocument(lastEdited, doScroll=True)

        if lastViewed := SHARED.project.data.getLastHandle("viewer"):
            self.viewDocument(lastViewed)

    def closeProjectTasks(self) -> None:
        """Run close project tasks. The document is saved by the caller."""
        if SHARED.focusMode:
            SHARED.setFocusMode(False)
        self.docEditor.clearEditor()
        self.docViewer.clearNavHistory()
        self.closeViewerPanel(byUser=False)
        self.docViewerPanel.closeProjectTasks()
        self.mainGui.imageAssets.clearAssets()

    ##
    #  Document Methods
    ##

    def closeDocument(self) -> None:
        """Close the document and clear the editor and title field."""
        if SHARED.hasProject:
            # Disable focus mode if it is active
            if SHARED.focusMode:
                SHARED.setFocusMode(False)
            self.saveDocument()
            self.docEditor.clearEditor()

    def openDocument(
        self,
        tHandle: Optional[str],
        tLine: Optional[int] = None,
        sTitle: Optional[str] = None,
        changeFocus: bool = True,
        doScroll: bool = False,
    ) -> bool:
        """Open a specific document, optionally at a given line."""
        if not (SHARED.hasProject and tHandle):
            logger.error("Nothing to open")
            return False

        if self._switchingDocument:
            logger.debug("Ignoring re-entrant request to open '%s'", tHandle)
            return False

        if sTitle and tLine is None and (hItem := SHARED.project.index.getItemHeading(tHandle, sTitle)):
            tLine = hItem.line

        self.mainGui.changeView(nwView.EDITOR)
        if tHandle == self.docEditor.docHandle:
            self.docEditor.setCursorLine(tLine)
        else:
            self._switchingDocument = True
            try:
                self.closeDocument()
                if self.docEditor.loadText(tHandle, tLine):
                    self.mainGui.projView.setSelectedHandle(tHandle, doScroll=doScroll)
                else:
                    return False
            finally:
                self._switchingDocument = False

        if changeFocus:
            self.docEditor.setFocus()

        return True

    def saveDocument(self, force: bool = False) -> bool:
        """Save the current document and report whether it succeeded."""
        if not SHARED.hasProject:
            return False
        self.docEditor.saveCursorPosition()
        if force or self.docEditor.docChanged:
            return self.docEditor.saveText()
        return True

    def importDocument(self) -> None:
        """Import the text contained in an out-of-project text file, and
        insert the text into the currently open document.
        """
        if not SHARED.hasProject:
            logger.error("No project open")
            return

        if self.docEditor.docHandle is None:
            SHARED.error(self.tr("Please open a document to import the text file into."))
            return

        lastPath = CONFIG.lastPath("import")
        ffilter = formatFileFilter(["*.txt", "*.md", "*"])
        loadFile, _ = QFileDialog.getOpenFileName(self, self.tr("Import File"), str(lastPath), filter=ffilter)
        if not loadFile.strip():
            return

        try:
            with open(loadFile, mode="rt", encoding="utf-8") as inFile:
                text = inFile.read()
            CONFIG.setLastPath("import", loadFile)
        except Exception as exc:
            SHARED.error(self.tr("Could not read file. The file must be an existing text file."), exc=exc)
            return

        if not self.docEditor.isEmpty:
            msgYes = SHARED.question(
                self.tr(
                    "Importing the file will overwrite the current content of the document. Do you want to proceed?"
                )
            )
            if not msgYes:
                return

        self.docEditor.replaceText(text)

    @pyqtSlot()
    def addProjectImage(self) -> None:
        """Add an image asset to the project without changing a document."""
        if not SHARED.hasProject:
            SHARED.error(self.tr("Please open a project before importing an image."))
            return

        project = SHARED.project
        projectPath = project.storage.storagePath
        lastPath = CONFIG.lastPath("image")
        fileFilter = formatFileFilter(["*.jpg", "*.png"])
        loadFile, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Image"),
            str(lastPath),
            filter=fileFilter,
        )
        if not loadFile.strip():
            SHARED.newStatusMessage(self.tr("Image import cancelled. No changes were made."))
            return

        if not (
            SHARED.hasProject
            and SHARED.project is project
            and project.storage.storagePath == projectPath
            and project.storage.isOpen()
        ):
            SHARED.error(self.tr("The active project changed while selecting an image. Please try again."))
            return

        try:
            imported = importProjectImage(project, loadFile)
        except ImageImportError as exc:
            SHARED.error(self._imageImportErrorMessage(exc), exc=exc)
            return
        except Exception as exc:
            logger.error("Unexpected error while importing a project image", exc_info=exc)
            SHARED.error(self.tr("Could not copy the image into the project."), exc=exc)
            return

        try:
            verifyImportedProjectImage(project, imported)
        except OSError as exc:
            cleanupFailed = not self._cleanupImportedImage(project, imported)
            details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
            SHARED.error(
                self.tr("The active project changed while importing the image. Please try again."),
                details=details,
                exc=exc,
            )
            return

        if not (
            SHARED.hasProject
            and SHARED.project is project
            and project.storage.storagePath == projectPath
            and project.storage.isOpen()
        ):
            cleanupFailed = not self._cleanupImportedImage(project, imported)
            details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
            SHARED.error(
                self.tr("The active project changed while importing the image. Please try again."),
                details=details,
            )
            return

        CONFIG.setLastPath("image", loadFile)
        self.mainGui.imageAssets.refreshAssets()
        self.mainGui.imageAssets.selectAsset(imported.relativePath)
        SHARED.newStatusMessage(self.tr("Imported image: {0}").format(imported.relativePath))

    @pyqtSlot(object, int, int, str)
    def insertProjectImage(self, image: ProjectImage, width: int, height: int, position: str) -> None:
        """Insert a stored project image into the current document."""
        if not isinstance(image, ProjectImage):
            logger.error("Invalid project image")
            SHARED.error(self.tr("The selected image is not valid."))
            return
        if not SHARED.hasProject:
            SHARED.error(self.tr("Please open a project before inserting an image."))
            return

        try:
            current = next(
                (entry for entry in listProjectImages(SHARED.project) if entry.relativePath == image.relativePath),
                None,
            )
            if current is None or current.identity != image.identity:
                raise OSError("The project image changed before it could be inserted")
            readProjectImageByPath(SHARED.project, image.relativePath)
            value = formatImageMetadata(
                ImageMetadata(
                    relativePath=image.relativePath,
                    width=width,
                    height=height,
                    position=position,
                )
            )
        except Exception as exc:
            logger.error("Could not validate the selected project image", exc_info=exc)
            SHARED.error(self.tr("The selected image is not valid."), exc=exc)
            self.mainGui.imageAssets.refreshAssets()
            return

        atEnd = False
        if self.docEditor.docHandle is None:
            if not self._openFallbackDocument():
                SHARED.error(self.tr("Please open a document to insert the image into."))
                return
            atEnd = True

        if not self.docEditor.insertMetaValueAt(nwKeyWords.IMAGE_KEY, value, atEnd=atEnd):
            SHARED.error(self.tr("Could not insert the image reference into the document."))
            return

        SHARED.newStatusMessage(self.tr("Inserted image: {0}").format(image.relativePath))

    @pyqtSlot(object)
    def deleteProjectImage(self, image: ProjectImage) -> None:
        """Delete an unreferenced image asset from the project."""
        if not isinstance(image, ProjectImage):
            logger.error("Invalid project image")
            SHARED.error(self.tr("The selected image is not valid."))
            return
        if not SHARED.hasProject:
            SHARED.error(self.tr("Please open a project before deleting an image."))
            return

        try:
            current = next(
                (entry for entry in listProjectImages(SHARED.project) if entry.relativePath == image.relativePath),
                None,
            )
            if current is None or current.identity != image.identity:
                raise OSError("The project image changed before it could be deleted")
            references = self._referencedProjectImages()
        except Exception as exc:
            logger.error("Could not verify project image references", exc_info=exc)
            SHARED.error(self.tr("Could not verify whether the image is still in use."), exc=exc)
            self.mainGui.imageAssets.refreshAssets()
            return

        if self._projectImageIsReferenced(image, references):
            SHARED.error(self.tr("The selected image is referenced by a document and cannot be deleted."))
            return

        if not SHARED.question(self.tr("Delete the selected image from the project?")):
            return

        # A document can change while the confirmation dialog is open.
        # Check again immediately before the identity-bound deletion so
        # a newly added reference always wins over deletion.
        try:
            references = self._referencedProjectImages()
        except Exception as exc:
            logger.error("Could not recheck project image references", exc_info=exc)
            SHARED.error(self.tr("Could not verify whether the image is still in use."), exc=exc)
            return
        if self._projectImageIsReferenced(image, references):
            SHARED.error(self.tr("The selected image is referenced by a document and cannot be deleted."))
            return

        try:
            removeProjectImage(SHARED.project, image)
        except Exception as exc:
            logger.error("Could not delete project image '%s'", image.relativePath, exc_info=exc)
            SHARED.error(self.tr("Could not delete the selected image from the project."), exc=exc)
            self.mainGui.imageAssets.refreshAssets()
            return

        self.mainGui.imageAssets.refreshAssets()
        SHARED.newStatusMessage(self.tr("Deleted image: {0}").format(image.relativePath))

    @pyqtSlot(str)
    def insertImage(self, keyword: str) -> None:
        """Import a project image and insert its reference in the document."""
        if keyword not in (nwKeyWords.COVER_KEY, nwKeyWords.ICON_KEY):
            logger.error("Invalid image keyword '%s'", keyword)
            SHARED.error(self.tr("The requested image type is not valid."))
            return

        if not SHARED.hasProject:
            SHARED.error(self.tr("Please open a project before importing an image."))
            return

        project = SHARED.project
        projectPath = project.storage.storagePath
        atEnd = self.docEditor.docHandle is None
        documentHandle = self.docEditor.docHandle
        document = self.docEditor.document()
        documentRevision = document.revision() if document is not None else -1
        capturedCursor = self.docEditor.textCursor()
        lastPath = CONFIG.lastPath("image")
        fileFilter = formatFileFilter(["*.jpg", "*.png"])
        loadFile, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Image"),
            str(lastPath),
            filter=fileFilter,
        )

        # The file chooser is modal, but restore the complete cursor
        # state immediately so cancellation and all subsequent failure
        # paths leave the editor exactly where it was before the chooser
        # was opened. Do not restore it into a changed context.
        currentDocument = self.docEditor.document()
        if atEnd:
            sameDocument = self.docEditor.docHandle is None
            sameRevision = True
        else:
            sameDocument = (
                currentDocument is not None
                and self.docEditor.docHandle == documentHandle
                and capturedCursor.document() is currentDocument
            )
            sameRevision = (
                currentDocument is not None and sameDocument and currentDocument.revision() == documentRevision
            )
        sameProject = (
            SHARED.hasProject
            and SHARED.project is project
            and project.storage.storagePath == projectPath
            and project.storage.isOpen()
        )
        sameContext = sameProject and sameDocument and sameRevision
        if sameContext and not atEnd:
            self.docEditor.setTextCursor(capturedCursor)
        if not loadFile.strip():
            if sameContext:
                SHARED.newStatusMessage(self.tr("Image import cancelled. No changes were made."))
            else:
                SHARED.error(
                    self.tr("The active project or document changed while selecting an image. Please try again.")
                )
            return

        if not sameContext:
            SHARED.error(self.tr("The active project or document changed while selecting an image. Please try again."))
            return

        try:
            imported = importProjectImage(project, loadFile)
        except ImageImportError as exc:
            if sameDocument and not atEnd:
                self.docEditor.setTextCursor(capturedCursor)
            if exc.reason == ImageImportReason.NO_PROJECT:
                message = self.tr("Please open a project before importing an image.")
            elif exc.reason == ImageImportReason.NOT_FOUND:
                message = self.tr("The selected image file could not be found.")
            elif exc.reason == ImageImportReason.UNSUPPORTED_TYPE:
                message = self.tr("The selected file must be a JPG or PNG image.")
            elif exc.reason == ImageImportReason.INVALID_IMAGE:
                message = self.tr("The selected file is not a valid JPG or PNG image.")
            elif exc.reason == ImageImportReason.FORMAT_MISMATCH:
                message = self.tr("The selected image format does not match its file extension.")
            elif exc.reason == ImageImportReason.IMAGE_TOO_LARGE:
                message = self.tr("The selected image is too large to import safely.")
            else:
                message = self.tr("Could not copy the image into the project.")
            SHARED.error(message, exc=exc)
            return
        except Exception as exc:
            if sameDocument and not atEnd:
                self.docEditor.setTextCursor(capturedCursor)
            logger.error("Unexpected error while importing a project image", exc_info=exc)
            SHARED.error(self.tr("Could not copy the image into the project."), exc=exc)
            return

        try:
            verifyImportedProjectImage(project, imported)
        except OSError as exc:
            cleanupFailed = not self._cleanupImportedImage(project, imported)
            details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
            SHARED.error(
                self.tr("The active project or document changed while importing the image. Please try again."),
                details=details,
                exc=exc,
            )
            return

        currentDocument = self.docEditor.document()
        sameProjectAfterImport = (
            SHARED.hasProject
            and SHARED.project is project
            and project.storage.storagePath == projectPath
            and project.storage.isOpen()
        )
        if atEnd:
            sameDocumentAfterImport = self.docEditor.docHandle is None
            sameRevisionAfterImport = True
        else:
            sameDocumentAfterImport = (
                currentDocument is not None
                and self.docEditor.docHandle == documentHandle
                and capturedCursor.document() is currentDocument
            )
            sameRevisionAfterImport = (
                currentDocument is not None
                and sameDocumentAfterImport
                and currentDocument.revision() == documentRevision
            )
        if not (sameDocumentAfterImport and sameRevisionAfterImport and sameProjectAfterImport):
            cleanupFailed = not self._cleanupImportedImage(project, imported)
            details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
            SHARED.error(
                self.tr("The active project or document changed while importing the image. Please try again."),
                details=details,
            )
            return

        if atEnd:
            # Defer opening a fallback document until the image has been
            # selected and imported. Cancelling the chooser must not
            # change which document is open.
            if not self._openFallbackDocument():
                cleanupFailed = not self._cleanupImportedImage(project, imported)
                details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
                SHARED.error(
                    self.tr("Please open a document to insert the image into."),
                    details=details,
                )
                return

            documentHandle = self.docEditor.docHandle
            document = self.docEditor.document()
            sameProjectAfterFallback = (
                SHARED.hasProject
                and SHARED.project is project
                and project.storage.storagePath == projectPath
                and project.storage.isOpen()
            )
            if not sameProjectAfterFallback:
                cleanupFailed = not self._cleanupImportedImage(project, imported)
                details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
                SHARED.error(
                    self.tr("The active project or document changed while importing the image. Please try again."),
                    details=details,
                )
                return
            if document is None or documentHandle is None:
                cleanupFailed = not self._cleanupImportedImage(project, imported)
                details = self.tr("The imported image could not be removed.") if cleanupFailed else ""
                SHARED.error(
                    self.tr("Please open a document to insert the image into."),
                    details=details,
                )
                return

        insertError: Optional[Exception] = None
        try:
            inserted = self.docEditor.insertMetaValueAt(
                keyword,
                imported.relativePath,
                afterHeading=True,
                atEnd=atEnd,
            )
        except Exception as exc:
            logger.error("Unexpected error while inserting an image reference", exc_info=exc)
            inserted = False
            insertError = exc

        if not inserted:
            if sameDocument and not atEnd:
                self.docEditor.setTextCursor(capturedCursor)
            cleanupFailed = not self._cleanupImportedImage(project, imported)
            if cleanupFailed:
                message = self.tr(
                    "Could not insert the image reference into the document. The imported image could not be removed."
                )
            else:
                message = self.tr("Could not insert the image reference into the document.")
            SHARED.error(message, exc=insertError)
            return

        CONFIG.setLastPath("image", loadFile)
        self.mainGui.imageAssets.refreshAssets()
        self.mainGui.imageAssets.selectAsset(imported.relativePath)
        SHARED.newStatusMessage(self.tr("Imported image: {0}").format(imported.relativePath))

    def viewDocument(
        self, tHandle: Optional[str] = None, sTitle: Optional[str] = None, changeFocus: bool = False
    ) -> None:
        """Load a document for viewing in the view panel."""
        if not SHARED.hasProject:
            logger.error("No project open")
            return

        if tHandle is None:
            logger.debug("Viewing document, but no handle provided")

            if self.docEditor.hasFocus():
                tHandle = self.docEditor.docHandle

            if tHandle is not None:
                self.saveDocument()
            else:
                tHandle = self.mainGui.projView.getSelectedHandle()

            if tHandle is None:
                tHandle = SHARED.project.data.getLastHandle("viewer")

            if tHandle is None:
                logger.debug("No document to view, giving up")
                return

        # Make sure main tab is in Editor view
        self.mainGui.changeView(nwView.EDITOR)

        # If we're loading the document in the editor, it may need to be saved
        if tHandle == self.docEditor.docHandle and self.docEditor.docChanged:
            self.saveDocument()

        logger.debug("Viewing document with handle '%s'", tHandle)
        updateHistory = tHandle != self.docViewer.docHandle
        if self.docViewer.loadText(tHandle, updateHistory=updateHistory):
            if not self.splitView.isVisible():
                cursorVisible = self.docEditor.cursorIsVisible()
                self.splitView.setVisible(True)
                self.splitMain.setSizes([1, 1])
                self.docViewerPanel.setVisible(CONFIG.showViewerPanel)

                # Since editor width changes, we need to make sure we
                # restore cursor visibility in the editor. See #1302
                if cursorVisible:
                    self.docEditor.ensureCursorVisible(centre=False)

            if sTitle:
                self.docViewer.navigateTo(f"#{tHandle}:{sTitle}")
            if changeFocus:
                self.docViewer.setFocus()

    def closeViewerPanel(self, byUser: bool = True) -> None:
        """Close the document view panel."""
        self.docViewer.clearViewer()
        if byUser:
            # Only reset the last handle if the user called this
            SHARED.project.data.setLastHandle(None, "viewer")

        cursorVisible = self.docEditor.cursorIsVisible()

        self.splitView.setVisible(False)
        self.splitMain.refresh()  # Resize now, not on the next layout pass

        # Since editor width changes, we need to make sure we restore
        # cursor visibility in the editor. See #1302
        if cursorVisible:
            self.docEditor.ensureCursorVisible(centre=False)

    def _openFallbackDocument(self) -> bool:
        """Open a document to use when no insertion location is active."""
        handles = self._projectDocumentHandles()
        lastHandle = SHARED.project.data.getLastHandle("editor")
        if lastHandle:
            handles = [lastHandle, *(handle for handle in handles if handle != lastHandle)]
        return any(self.openDocument(handle) for handle in handles)

    def _projectDocumentHandles(self) -> list[str]:
        """Return the current file handles from the live project tree.

        ``ProjectTree.allDocs()`` is a cached list intended for novel
        structure queries. It is not invalidated for documents added
        below non-novel roots, so destructive reference checks must not
        rely on it.
        """
        return [item.itemHandle for item in SHARED.project.tree if item.isFileType()]

    def _referencedProjectImages(self) -> set[str]:
        """Return all image paths referenced by project documents."""
        references: set[str] = set()
        currentHandle = self.docEditor.docHandle
        handles = self._projectDocumentHandles()
        if currentHandle and currentHandle not in handles:
            handles.append(currentHandle)

        for handle in handles:
            if handle == currentHandle:
                text = self.docEditor.getText()
            else:
                text = SHARED.project.storage.getDocument(handle).readDocument()
                if text is None:
                    raise OSError(f"Could not read document '{handle}'")
            references.update(referencedImagePaths(text))

        return references

    @staticmethod
    def _projectImageIsReferenced(image: ProjectImage, references: set[str]) -> bool:
        """Check whether any reference resolves to the selected image object.

        Exact path matches cover normal metadata. The identity comparison
        also protects projects on case-insensitive file systems, where a
        differently cased path can refer to the same image file.
        """
        if image.relativePath in references:
            return True

        for relativePath in references:
            fileName = relativePath.rsplit("/", 1)[-1]
            referencePath = image.path.parent / fileName
            try:
                identity = captureRegularFileIdentity(referencePath)
            except OSError:
                # Fail closed if a referenced path cannot be inspected
                # safely. It may be the selected image under another name.
                return True
            if identity is not None and identity == image.identity:
                return True

        return False

    def _imageImportErrorMessage(self, exc: ImageImportError) -> str:
        """Return a user-facing message for an image import error."""
        if exc.reason == ImageImportReason.NO_PROJECT:
            return self.tr("Please open a project before importing an image.")
        elif exc.reason == ImageImportReason.NOT_FOUND:
            return self.tr("The selected image file could not be found.")
        elif exc.reason == ImageImportReason.UNSUPPORTED_TYPE:
            return self.tr("The selected file must be a JPG or PNG image.")
        elif exc.reason == ImageImportReason.INVALID_IMAGE:
            return self.tr("The selected file is not a valid JPG or PNG image.")
        elif exc.reason == ImageImportReason.FORMAT_MISMATCH:
            return self.tr("The selected image format does not match its file extension.")
        elif exc.reason == ImageImportReason.IMAGE_TOO_LARGE:
            return self.tr("The selected image is too large to import safely.")
        else:
            return self.tr("Could not copy the image into the project.")

    def _cleanupImportedImage(self, project: NWProject, imported: ImportedImage) -> bool:
        """Remove an imported image after its project context was lost."""
        try:
            removeImportedProjectImage(project, imported)
        except OSError:
            logger.warning("Could not remove an uninserted project image after validation failed", exc_info=True)
            return False
        return True

    ##
    #  Public Slots
    ##

    @pyqtSlot()
    def closeDocEditor(self) -> None:
        """Close the document editor. This does not hide the editor."""
        self.closeDocument()
        SHARED.project.data.setLastHandle(None, "editor")

    @pyqtSlot()
    def closeDocViewer(self) -> None:
        """Close the document viewer."""
        self.closeViewerPanel()

    @pyqtSlot()
    def showFormattedView(self) -> None:
        """Open the current document in the formatted right-hand panel."""
        if not SHARED.hasProject:
            return
        if handle := self.docEditor.docHandle:
            # The viewer renders project content read from storage. Save
            # first so the formatted panel always represents the current
            # editor text, even when another document is already open in
            # the viewer.
            if not self.saveDocument():
                return
            self.viewDocument(tHandle=handle, changeFocus=True)
        else:
            self.viewDocument(changeFocus=True)

    @pyqtSlot(nwDocAction)
    def passDocumentAction(self, action: nwDocAction) -> None:
        """Pass on a document action to the editor or viewer based on
        which one has focus, or if neither has focus, ignore it.
        """
        if self.docEditor.hasFocus():
            self.docEditor.docAction(action)
        elif self.docViewer.hasFocus():
            self.docViewer.docAction(action)

    @pyqtSlot(str)
    @pyqtSlot(nwDocInsert)
    def passDocumentInsert(self, content: str | nwDocInsert) -> None:
        """Pass on a document insert action to the document editor if it
        has focus. If not, ignore it.
        """
        if self.docEditor.hasFocus():
            self.docEditor.insertText(content)

    @pyqtSlot()
    def forceSaveDocument(self) -> None:
        """Save document even of it has not changed."""
        self.saveDocument(force=True)

    @pyqtSlot(str, nwDocMode, str, bool)
    def openDocumentInMode(self, tHandle: str, mode: nwDocMode, sTitle: str, setFocus: bool) -> None:
        """Handle an open document request."""
        if mode == nwDocMode.EDIT:
            self.openDocument(tHandle, sTitle=sTitle, changeFocus=setFocus)
        elif mode == nwDocMode.VIEW:
            self.viewDocument(tHandle=tHandle, sTitle=sTitle, changeFocus=setFocus)
        else:  # pragma: no cover
            pass

    @pyqtSlot(str, int, int, bool)
    def openDocumentSelection(self, tHandle: str, selStart: int, selLength: int, changeFocus: bool) -> None:
        """Open a document and select a section of the text."""
        if self.openDocument(tHandle, changeFocus=changeFocus):
            self.docEditor.setCursorSelection(selStart, selLength)

    @pyqtSlot(str, bool, bool)
    def openNextDocument(self, tHandle: str, wrapAround: bool, goBack: bool) -> None:
        """Open the next (or previous) document in the project tree,
        next to the document with the given handle. Stop when reaching
        the edge unless the wrapAround flag is set.
        """
        if not SHARED.hasProject:
            return

        allDocs = SHARED.project.tree.allDocs()
        if tHandle not in allDocs:
            logger.error("Could not find next document for '%s'", tHandle)
            return

        idx = allDocs.index(tHandle) + (-1 if goBack else 1)
        if wrapAround:
            idx %= len(allDocs)
        if 0 <= idx < len(allDocs):
            self.openDocument(allDocs[idx], tLine=(-1 if goBack else 1), doScroll=True)

    @pyqtSlot("QWidget*", "QWidget*")
    def onFocusChanged(self, old: QWidget, new: QWidget) -> None:
        """Update the focus state of the editor and viewer."""
        if isinstance(new, QWidget):
            docEditor = self.docEditor.isAncestorOf(new)
            docViewer = not docEditor and self.docViewer.isAncestorOf(new)
            self.docEditor.changeFocusState(docEditor)
            self.docViewer.changeFocusState(docViewer)

    ##
    #  Private Slots
    ##

    @pyqtSlot(str, nwDocMode)
    def _followTag(self, tag: str, mode: nwDocMode) -> None:
        """Follow a tag after user interaction with a link."""
        tHandle, sTitle = SHARED.project.index.getTagSource(tag)
        if tHandle is None:
            SHARED.error(
                self.tr(
                    "Could not find the reference for tag '{0}'. It either doesn't "
                    "exist, or the index is out of date. The index can be updated "
                    "from the Tools menu, or by pressing {1}."
                ).format(tag, "F9")
            )
        else:
            self.openDocumentInMode(tHandle, mode, sTitle, True)

    @pyqtSlot()
    def _reloadViewer(self) -> None:
        """Reload the document in the viewer."""
        if self.docEditor.docHandle == self.docViewer.docHandle:
            # If the two panels have the same document, save any changes in the editor
            self.saveDocument()
        self.docViewer.reloadText()

    @pyqtSlot()
    def _toggleViewerPanelVisibility(self) -> None:
        """Toggle the visibility of the document viewer panel."""
        CONFIG.showViewerPanel = not CONFIG.showViewerPanel
        self.docViewerPanel.setVisible(CONFIG.showViewerPanel)
