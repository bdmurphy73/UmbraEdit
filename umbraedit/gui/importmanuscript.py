"""
UmbraEdit - Import Manuscript Command
======================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

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

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog, QWidget

from umbraedit import SHARED
from umbraedit.dialogs.importreview import importReviewDialog
from umbraedit.umbra.gates import OP_IMPORT_COMMIT, GateScope, runGates
from umbraedit.umbra.ingest import DocxIngestPipeline, ImportPlan
from umbraedit.umbra.ingest.ingest_runs import find_existing_import
from umbraedit.umbra.ingest.worker import IngestDispatcher, IngestJobResult

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)


def _dialogParent() -> Optional[QWidget]:
    """Return a valid parent widget for the import dialogs.

    The main window can be closed while an import is running, and the
    application can be shutting down when the result comes back. Using
    a deleted widget, or no widget at all, as the parent of a modal
    dialog is not allowed, and makes Qt abort the process. In that
    case, None is returned, and the caller must not open a dialog.

    Returns:
        The main GUI widget if it can be used, otherwise None.

    """
    if QApplication.instance() is None or QApplication.closingDown():
        return None
    try:
        gui = SHARED.mainGui
    except RuntimeError:
        return None
    if sip.isdeleted(gui):
        return None
    return gui


class ImportManuscriptCommand(QObject):
    """Command to import a manuscript from a DOCX file."""

    def __init__(self, project: NWProject, parent: Any) -> None:
        super().__init__()
        self._project = project
        self._parent = parent
        self._dispatcher: Optional[IngestDispatcher] = None
        self._progress: Optional[QProgressDialog] = None

    def execute(self) -> None:
        """Execute the import manuscript command."""
        parent = _dialogParent()
        if parent is None:
            logger.error("Cannot import manuscript: the main window is not available")
            return

        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            self.tr("Select DOCX Manuscript"),
            "",
            self.tr("Word Documents (*.docx *.docm)"),
        )

        if not file_path:
            return

        source_path = Path(file_path)
        project_path = self._project.storage.storagePath
        if project_path is None:
            logger.error("Cannot import manuscript: project storage path is not set")
            return

        # Check if file was already imported
        pipeline = DocxIngestPipeline(project_path)
        intake = pipeline._intake.process(source_path)

        if intake.valid:
            existing = find_existing_import(
                project_path,
                intake.sha256,
            )
            if existing:
                reply = QMessageBox.question(
                    parent,
                    self.tr("Already Imported"),
                    self.tr("This file was already imported on {0} (run {1}).\nImport again?").format(
                        existing.imported_at, existing.run_id
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        # Show progress dialog
        self._progress = QProgressDialog(
            self.tr("Analyzing manuscript..."),
            self.tr("Cancel"),
            0,
            0,
            parent,
        )
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.canceled.connect(self._cancel)

        # Create dispatcher
        self._dispatcher = IngestDispatcher(parent, self._on_ingest_complete)
        self._dispatcher.run_ingest(source_path, self._project)

    def _cancel(self) -> None:
        """Cancel the import."""
        if self._progress:
            self._progress.close()
            self._progress = None
        self._dispatcher = None

    def _on_ingest_complete(self, result: IngestJobResult) -> None:
        """Handle completion of the ingest pipeline."""
        if self._progress:
            self._progress.close()
            self._progress = None

        # The main window may have been closed while the import was
        # running. If so, there is nobody left to tell about the result.
        parent = _dialogParent()
        if parent is None:
            if not result.success:
                logger.error("Import failed: %s", result.error)
            else:
                logger.error("The main window was closed before the import could be reviewed")
            return

        if not result.success:
            QMessageBox.critical(
                parent,
                self.tr("Import Failed"),
                self.tr("Failed to import manuscript: {0}").format(result.error),
            )
            return

        plan = result.plan
        if plan is None:
            QMessageBox.critical(
                parent,
                self.tr("Import Failed"),
                self.tr("Import pipeline returned no plan."),
            )
            return

        project_path = self._project.storage.storagePath
        if project_path is None:
            logger.error("Cannot import manuscript: project storage path is not set")
            return

        # Check for existing import warning
        existing = find_existing_import(
            project_path,
            str(plan.source.get("sha256", "")),
        )
        if existing and existing.status == "completed":
            reply = QMessageBox.question(
                parent,
                self.tr("Already Imported"),
                self.tr("This file was already imported on {0} (run {1}).\nImport again?").format(
                    existing.imported_at, existing.run_id
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Show review dialog
        plan, accepted = importReviewDialog(parent, self._project, plan)
        if accepted:
            # Commit the import
            self._commit_import(plan)

    def _commit_import(self, plan: ImportPlan) -> None:
        """Commit the import plan."""
        # Check gates
        scope = GateScope(project=self._project, options={"importPlan": plan.to_dict()})
        report = runGates(OP_IMPORT_COMMIT, scope)

        if report.blocked:
            QMessageBox.warning(
                SHARED.mainGui,
                self.tr("Commit Blocked"),
                self.tr("Cannot commit import:\n{0}").format(
                    "\n".join(f"{f.ruleId}: {f.message}" for f in report.findings if f.severity == "block")
                ),
            )
            return

        # Commit the import
        from umbraedit.umbra.ingest.commit import commit_import_plan

        result = commit_import_plan(self._project, plan)

        if result.success:
            QMessageBox.information(
                SHARED.mainGui,
                self.tr("Import Complete"),
                self.tr("Successfully imported manuscript as {0} documents.").format(len(plan.documents)),
            )
        else:
            QMessageBox.critical(
                SHARED.mainGui,
                self.tr("Commit Failed"),
                self.tr("Failed to commit import: {0}").format(result.error or "Unknown error"),
            )


def importManuscript(project: NWProject, parent: Any) -> None:
    """Import a manuscript from a DOCX file."""
    command = ImportManuscriptCommand(project, parent)
    command.execute()
