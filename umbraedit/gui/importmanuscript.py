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
from typing import Any, TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from umbraedit import SHARED
from umbraedit.dialogs.importreview import importReviewDialog
from umbraedit.umbra.gates import OP_IMPORT_COMMIT, requireGates
from umbraedit.umbra.ingest import DocxIngestPipeline, ImportPlan
from umbraedit.umbra.ingest.ingest_runs import find_existing_import
from umbraedit.umbra.ingest.worker import IngestDispatcher

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)


class ImportManuscriptCommand(QObject):
    """Command to import a manuscript from a DOCX file."""

    def __init__(self, project: NWProject, parent: Any) -> None:
        super().__init__()
        self._project = project
        self._parent = parent
        self._dispatcher: IngestDispatcher | None = None
        self._progress: QProgressDialog | None = None

    def execute(self) -> None:
        """Execute the import manuscript command."""
        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            SHARED.mainGui,
            self.tr("Select DOCX Manuscript"),
            "",
            self.tr("Word Documents (*.docx *.docm)"),
        )

        if not file_path:
            return

        path = Path(file_path)

        # Check if file was already imported
        pipeline = DocxIngestPipeline(self._project.storage.storagePath)
        intake = pipeline._intake.process(Path(file_path))

        if intake.valid:
            existing = find_existing_import(
                self._project.storage.storagePath,
                intake.sha256,
            )
            if existing:
                reply = QMessageBox.question(
                    SHARED.mainGui,
                    self.tr("Already Imported"),
                    self.tr(
                        "This file was already imported on {0} (run {1}).\n"
                        "Import again?"
                    ).format(existing.imported_at, existing.run_id),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

        # Show progress dialog
        self._progress = QProgressDialog(
            self.tr("Analyzing manuscript..."),
            self.tr("Cancel"),
            0, 0,
            SHARED.mainGui,
        )
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.canceled.connect(self._cancel)

        # Create dispatcher
        self._dispatcher = IngestDispatcher(SHARED.mainGui, self._on_ingest_complete)
        self._dispatcher.run_ingest(Path(file_path), self._project)

    def _cancel(self) -> None:
        """Cancel the import."""
        if self._progress:
            self._progress.close()
            self._progress = None
        self._dispatcher = None

    def _on_ingest_complete(self, result: Any) -> None:
        """Handle completion of the ingest pipeline."""
        if self._progress:
            self._progress.close()
            self._progress = None

        if not result.success:
            QMessageBox.critical(
                SHARED.mainGui,
                self.tr("Import Failed"),
                self.tr("Failed to import manuscript: {0}").format(result.error),
            )
            return

        plan = result.plan
        if not plan:
            QMessageBox.critical(
                SHARED.mainGui,
                self.tr("Import Failed"),
                self.tr("Import pipeline returned no plan."),
            )
            return

        # Check for existing import warning
        existing = find_existing_import(
            self._project.storage.storagePath,
            result.plan.source.sha256 if result.plan else "",
        )
        if existing and existing.status == "completed":
            reply = QMessageBox.question(
                SHARED.mainGui,
                self.tr("Already Imported"),
                self.tr(
                    "This file was already imported on {0} (run {1}).\n"
                    "Import again?"
                ).format(existing.imported_at, existing.run_id),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # Show review dialog
        plan, accepted = importReviewDialog(SHARED.mainGui, self._project, plan)
        if accepted:
            # Commit the import
            self._commit_import(plan)

    def _commit_import(self, plan: ImportPlan) -> None:
        """Commit the import plan."""
        # Check gates
        from umbraedit.umbra.gates import GateScope
        scope = GateScope(project=self._project, options={"importPlan": plan.to_dict()})
        report = requireGates(OP_IMPORT_COMMIT, scope)

        if report.blocked:
            QMessageBox.warning(
                SHARED.mainGui,
                self.tr("Commit Blocked"),
                self.tr("Cannot commit import:\n{0}").format("\n".join(
                    f"{f.ruleId}: {f.message}" for f in report.findings if f.severity == "block"
                )),
            )
            return

        # Commit the import
        from umbraedit.umbra.ingest.commit import commit_import_plan
        result = commit_import_plan(self._project, plan)

        if result.success:
            QMessageBox.information(
                SHARED.mainGui,
                self.tr("Import Complete"),
                self.tr("Successfully imported manuscript as {0} documents.").format(
                    len(plan.documents)
                ),
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
