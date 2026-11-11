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

from PyQt6.QtWidgets import QMessageBox

from umbraedit import SHARED
from umbraedit.umbra.ingest.ingest_runs import _load_runs
from umbraedit.umbra.ingest.commit import undo_import_plan

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)


def undoImport(project: "NWProject", parent: Any) -> None:
    """Undo the most recent import."""
    # Find the most recent completed import
    runs = _load_runs(SHARED.project.storage.storagePath)
    completed_runs = [r for r in runs if r.status == "completed"]

    if not completed_runs:
        QMessageBox.information(
            SHARED.mainGui,
            "Undo Import",
            "No completed imports to undo.",
        )
        return

    # Get the most recent import
    latest_run = max(completed_runs, key=lambda r: r.imported_at)

    # Confirm with user
    reply = QMessageBox.question(
        SHARED.mainGui,
        "Undo Import",
        f"Undo import of {latest_run.file_path} (run {latest_run.run_id})?\n"
        f"This will remove all documents, notes, and metadata created by this import.",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )

    if reply != QMessageBox.Yes:
        return

    # Perform undo
    from umbraedit.umbra.ingest.commit import undo_import_plan
    success = undo_import_plan(SHARED.project, latest_run.run_id)

    if success:
        QMessageBox.information(
            SHARED.mainGui,
            "Undo Complete",
            "Import has been undone successfully.",
        )
    else:
        QMessageBox.critical(
            SHARED.mainGui,
            "Undo Failed",
            "Failed to undo import. Check logs for details.",
        )