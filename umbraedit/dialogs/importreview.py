"""
UmbraEdit - Import Review Dialog
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

import json
import logging

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import (
    QSortFilterProxyModel,
    Qt,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from umbraedit.types import QtAccepted, QtRoleAccept, QtRoleReject, QtUserRole
from umbraedit.umbra.gates import OP_IMPORT_COMMIT, requireGates
from umbraedit.umbra.ingest import (
    ImportPlan,
    record_ingest_run,
)
from umbraedit.umbra.paths import cacheDir

logger = logging.getLogger(__name__)

# Custom roles for tree items
DOC_PLAN_ID_ROLE = QtUserRole
DOC_KIND_ROLE = QtUserRole + 1
DOC_LEVEL_ROLE = QtUserRole + 2
DOC_SOURCE_PARAS_ROLE = QtUserRole + 3
DOC_PAGE_TYPE_ROLE = QtUserRole + 3


@dataclass
class CharacterProposal:
    """A proposed character from the ingest."""

    name: str
    count: int
    examples: list[str]
    accepted: bool = False
    merged_with: str | None = None
    existing_tag: str | None = None


@dataclass
class MetadataProposal:
    """A proposed metadata field."""

    key: str
    value: str
    accepted: bool = False


@dataclass
class PageTypeProposal:
    """A proposed page type for front/back matter."""

    plan_id: str
    page_type: str
    accepted: bool = False


class ImportReviewModel:
    """Model for the import review dialog."""

    def __init__(self, plan: ImportPlan) -> None:
        self.plan = plan
        self.characters: list[CharacterProposal] = []
        self.metadata: list[MetadataProposal] = []
        self.page_types: list[PageTypeProposal] = []
        self.findings: list[str] = []

    def load_from_plan(self) -> None:
        """Load proposals from the import plan."""
        # Load characters
        for char in self.plan.characters:
            self.characters.append(CharacterProposal(
                name=char.get("name", ""),
                count=char.get("count", 0),
                examples=char.get("examples", []),
            ))

        # Load metadata proposals
        for key, value in self.plan.metadata.items():
            self.metadata.append(MetadataProposal(key=key, value=value))

        # Load page types
        for doc in self.plan.documents:
            if doc.get("pageType"):
                self.page_types.append(PageTypeProposal(
                    plan_id=doc["planId"],
                    page_type=doc["pageType"],
                ))

        # Load findings
        self.findings = self.plan.findings.copy()

    def get_blocking_findings(self) -> list[str]:
        """Get findings that block commit."""
        blocking = []
        for f in self.findings:
            if f.startswith("ingestNoHeadings:") or f.startswith("ingestEmptyScene:") \
                    or f.startswith("ingestLostFeature:") or f.startswith("ingestImageFailed:") \
                    or f.startswith("ingestFootnoteUnmapped:"):
                blocking.append(f)
        return blocking

    def has_blocking_findings(self) -> bool:
        return len(self.get_blocking_findings()) > 0


class ImportTreeModel:
    """Tree model for the document tree view."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def get_documents(self) -> list[dict[str, Any]]:
        return self.documents

    def move_document(self, from_index: int, to_index: int) -> None:
        """Move a document from one index to another."""
        if 0 <= from_index < len(self.documents) and 0 <= to_index < len(self.documents):
            doc = self.documents.pop(from_index)
            self.documents.insert(to_index, doc)

    def add_document(self, index: int, document: dict[str, Any]) -> None:
        self.documents.insert(index, document)

    def remove_document(self, index: int) -> dict[str, Any] | None:
        if 0 <= index < len(self.documents):
            return self.documents.pop(index)
        return None


class GuiImportReview:
    """Import Review Dialog."""

    def __init__(self, parent: Any, project: Any, plan: ImportPlan) -> None:
        self.parent = parent
        self.project = project
        self.plan = plan
        self.model = ImportReviewModel(plan)
        self.tree_model = ImportTreeModel(plan.documents)

        # State
        self._commit_allowed = False
        self._modified = False

        # UI Components
        self.tree_view: Any = None
        self.text_edit: Any = None
        self.findings_list: Any = None
        self.characters_list: Any = None
        self.metadata_list: Any = None
        self.page_types_list: Any = None

        self._setup_ui()
        self._load_plan()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        # Main splitter
        self.splitter = QSplitter()
        self.splitter.setOrientation(Qt.Horizontal)

        # Left: Document Tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        tree_label = QLabel(self.tr("Planned Documents"))
        self.tree_view = QTreeView()
        self.tree_view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree_view.setDefaultDropAction(Qt.MoveAction)
        self.tree_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree_view.setDragEnabled(True)
        self.tree_view.setAcceptDrops(True)
        self.tree_view.setDropIndicatorShown(True)
        self.tree_view.setHeaderHidden(False)
        self.tree_view.setModel(ImportTreeModelProxy(self.tree_model))
        self.tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)

        left_layout.addWidget(QLabel(self.tr("Planned Documents")))
        left_layout.addWidget(self.tree_view)

        # Center: Text Pane
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.addWidget(QLabel(self.tr("Document Text")))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(QFont("Monospace", 10))
        self.text_edit.textChanged.connect(self._on_text_changed)
        center_layout.addWidget(self.text_edit)

        # Right: Findings / Proposals
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._create_findings_tab(), self.tr("Findings"))
        self.tab_widget.addTab(self._create_characters_tab(), self.tr("Characters"))
        self.tab_widget.addTab(self._create_metadata_tab(), self.tr("Metadata"))
        self.tab_widget.addTab(self._create_page_types_tab(), self.tr("Page Types"))
        right_layout.addWidget(self.tab_widget)

        # Add to splitter
        self.splitter.addWidget(left_widget)
        self.splitter.addWidget(center_widget)
        self.splitter.addWidget(right_widget)
        self.splitter.setSizes([300, 500, 300])

        # Main layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)

        # Buttons
        button_box = QDialogButtonBox()
        self.btn_commit = QPushButton(self.tr("Commit Import"))
        self.btn_commit.setEnabled(False)
        self.btn_commit.clicked.connect(self._on_commit)
        button_box.addButton(self.btn_commit, QtRoleAccept)

        self.btn_undo = QPushButton(self.tr("Undo Import"))
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._on_undo)
        button_box.addButton(self.btn_undo, QtRoleReject)

        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        button_box.addButton(self.btn_cancel, QtRoleReject)

        self.addLayout(self.outerBox)
        self.outerBox.addWidget(self.splitter)
        self.outerBox.addWidget(button_box)

        self.setLayout(self.outerBox)

    def _create_findings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.findings_list = QListWidget()
        self.findings_list.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.findings_list)
        return widget

    def _create_characters_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.characters_list = QListWidget()
        self.characters_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.characters_list)
        return widget

    def _create_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.metadata_list = QListWidget()
        self.metadata_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.metadata_list)
        return widget

    def _create_page_types_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.page_types_list = QListWidget()
        self.page_types_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.page_types_list)
        return widget

    def _load_plan(self) -> None:
        """Load the import plan into the UI."""
        self.model.load_from_plan()

        # Build tree
        self._rebuild_tree()

        # Load findings
        self._refresh_findings()

        # Load characters
        self._refresh_characters()

        # Load metadata
        self._refresh_metadata()

        # Load page types
        self._refresh_page_types()

        # Update commit button state
        self._update_commit_button()

    def _rebuild_tree(self) -> None:
        """Rebuild the tree view from the model."""
        # Implementation would build QStandardItemModel or similar

    def _refresh_findings(self) -> None:
        self.findings_list.clear()
        for finding in self.model.findings:
            item = QListWidgetItem(finding)
            if finding.startswith(("ingestNoHeadings:", "ingestEmptyScene:",
                                   "ingestLostFeature:", "ingestImageFailed:",
                                   "ingestFootnoteUnmapped:")):
                item.setForeground(QColor("red"))
            elif finding.startswith("ingestUnknownStyle:"):
                item.setForeground(QColor("orange"))
            self.findings_list.addItem(item)

    def _refresh_characters(self) -> None:
        self.characters_list.clear()
        for char in self.model.characters:
            text = f"{char.name} ({char.count} occurrences)"
            if char.examples:
                text += f" — {', '.join(char.examples[:2])}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, char)
            self.characters_list.addItem(item)

    def _refresh_metadata(self) -> None:
        self.metadata_list.clear()
        for meta in self.model.metadata:
            item = QListWidgetItem(f"{meta.key}: {meta.value}")
            item.setData(Qt.UserRole, meta)
            self.metadata_list.addItem(item)

    def _refresh_page_types(self) -> None:
        self.page_types_list.clear()
        for pt in self.model.page_types:
            item = QListWidgetItem(f"{pt.plan_id}: {pt.page_type}")
            item.setData(Qt.UserRole, pt)
            self.page_types_list.addItem(item)

    def _on_tree_selection_changed(self) -> None:
        """Handle tree selection change."""
        indexes = self.tree_view.selectionModel().selectedIndexes()
        if indexes:
            index = indexes[0]
            plan_id = index.data(DOC_PLAN_ID_ROLE)
            if plan_id:
                self._show_document_text(plan_id)

    def _show_document_text(self, plan_id: str) -> None:
        """Show the text for the selected document."""
        doc = next((d for d in self.tree_model.documents if d["planId"] == plan_id), None)
        if doc:
            self.text_edit.setPlainText(doc.get("text", ""))
            self.text_edit.setReadOnly(False)

    def _on_text_changed(self) -> None:
        """Handle text edit."""
        self._modified = True
        # Update the document text in the model
        # Re-evaluate findings
        self._reevaluate_findings()

    def _reevaluate_findings(self) -> None:
        """Re-evaluate findings based on current state."""
        # This would re-run the gates

    def _update_commit_button(self) -> None:
        """Update commit button state."""
        blocking = self.model.get_blocking_findings()
        self.btn_commit.setEnabled(len(blocking) == 0)
        if blocking:
            self.btn_commit.setToolTip(f"Blocked by: {', '.join(blocking[:3])}")
        else:
            self.btn_commit.setToolTip("")

    @pyqtSlot()
    def _on_commit(self) -> None:
        """Commit the import."""
        # Check gates
        scope = ...  # Would need proper gate scope
        report = requireGates(OP_IMPORT_COMMIT, scope)
        if report.blocked:
            QMessageBox.warning(self, self.tr("Commit Blocked"),
                                self.tr("Cannot commit: {0}").format("; ".join(
                                    [f.message for f in report.findings if f.severity == "block"]
                                )))
            return

        # Perform commit
        self._perform_commit()

    def _perform_commit(self) -> None:
        """Perform the actual commit operation."""
        # 1. Take pre_migrate snapshots
        # 2. Create documents and folders
        # 3. Create notes and assets
        # 4. Update metadata
        # 5. Write undo record
        # 6. Update status to committed

        # Write undo record
        undo_record = {
            "v": 1,
            "runId": self.plan.run_id,
            "createdHandles": [],
            "createdFiles": [],
            "updatedMetadataKeys": [],
            "createdNotes": [],
        }

        # Write undo record
        undo_file = cacheDir(self.project.storage.storagePath) / "import" / f"{self.plan.run_id}.undo.json"
        undo_file.parent.mkdir(parents=True, exist_ok=True)
        with open(undo_file, "w", encoding="utf-8") as f:
            json.dump(undo_record, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")

        # Update plan status
        self.plan.status = "committed"

        # Record ingest run
        record_ingest_run(
            self.project.storage.storagePath,
            self.plan.run_id,
            str(self.plan.source["file"]),
            self.plan.source["sha256"],
            self.plan.source["pandoc"],
            self.plan.run_id,
        )

        self.accept()

    @pyqtSlot()
    def _on_undo(self) -> None:
        """Undo the import."""
        # Read undo record and remove created items
        undo_file = cacheDir(self.project.storage.storagePath) / "import" / f"{self.plan.run_id}.undo.json"
        if not undo_file.is_file():
            QMessageBox.warning(self, self.tr("Undo Failed"),
                                self.tr("No undo record found."))
            return

        with open(undo_file, encoding="utf-8") as f:
            undo = json.load(f)

        # Check if created items are unchanged
        # If any changed, warn and list what changed
        # Remove created items

        self.plan.status = "rolled_back"
        self.accept()

    def reject(self) -> None:
        """Cancel the import."""
        self.plan.status = "cancelled"
        super().reject()

    def data(self) -> tuple[ImportPlan, bool]:
        """Return the plan and whether it was committed."""
        return self.plan, self.result() == QtAccepted

    @classmethod
    def getPlan(cls, parent: Any, project: Any, plan: ImportPlan) -> tuple[ImportPlan, bool]:
        """Show the dialog and return the plan."""
        dialog = cls(parent, project, plan)
        dialog.exec()
        plan, accepted = dialog.data()
        return plan, accepted


# Proxy model for tree view
class ImportTreeModelProxy(QSortFilterProxyModel):
    """Proxy model for the import tree."""

    def __init__(self, source_model: ImportTreeModel) -> None:
        super().__init__()
        self.setSourceModel(source_model)
        self.setSortRole(Qt.DisplayRole)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)


# Factory function
def importReviewDialog(parent: Any, project: Any, plan: ImportPlan) -> tuple[ImportPlan, bool]:
    """Show the import review dialog and return the plan and acceptance status."""
    dialog = GuiImportReview(parent, project, plan)
    dialog.exec()
    return dialog.data()
