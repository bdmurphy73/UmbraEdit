"""
UmbraEdit - Undo Import Command
=================================

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

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QMessageBox, QWidget

from umbraedit.umbra.ingest.commit import undo_import_plan
from umbraedit.umbra.ingest.ingest_runs import _load_runs

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)


def undoImport(project: NWProject, parent: QWidget) -> None:
    """Undo the most recent import."""
    project_path = project.storage.storagePath
    if project_path is None:
        logger.error("Cannot undo import: project storage path is not set")
        return

    # Find the most recent completed import
    runs = _load_runs(project_path)
    completed_runs = [r for r in runs if r.status == "completed"]

    if not completed_runs:
        QMessageBox.information(
            parent,
            "Undo Import",
            "No completed imports to undo.",
        )
        return

    # Get the most recent import
    latest_run = max(completed_runs, key=lambda r: r.imported_at)

    # Confirm with user
    reply = QMessageBox.question(
        parent,
        "Undo Import",
        f"Undo import of {latest_run.file_path} (run {latest_run.run_id})?\n"
        f"This will remove all documents, notes, and metadata created by this import.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    if reply != QMessageBox.StandardButton.Yes:
        return

    # Perform undo
    success = undo_import_plan(project, latest_run.run_id)

    if success:
        QMessageBox.information(
            parent,
            "Undo Complete",
            "Import has been undone successfully.",
        )
    else:
        QMessageBox.critical(
            parent,
            "Undo Failed",
            "Failed to undo import. Check logs for details.",
        )
