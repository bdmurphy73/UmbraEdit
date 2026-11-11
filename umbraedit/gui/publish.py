"""
UmbraEdit - Publish Dock
=========================

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

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from umbraedit import SHARED
from umbraedit.enum import nwStandardButton

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.guimain import GuiMain

logger = logging.getLogger(__name__)


class PublishDock(QDockWidget):
    """Dock widget for the Publish panel."""

    def __init__(self, main_window: GuiMain) -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self.setObjectName("PublishDock")
        self.setWindowTitle(self.tr("Publish"))

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        """Build the dock UI."""
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()

        self.cmb_edition = SHARED.theme.getStandardComboBox(self)
        self.cmb_edition.setMinimumWidth(200)
        toolbar.addWidget(QLabel(self.tr("Edition:")))
        toolbar.addWidget(self.cmb_edition)

        self.cmb_retailer = SHARED.theme.getStandardComboBox(self)
        self.cmb_retailer.setMinimumWidth(200)
        toolbar.addWidget(QLabel(self.tr("Retailer:")))
        toolbar.addWidget(self.cmb_retailer)

        toolbar.addStretch()

        self.btn_publish = SHARED.theme.getStandardButton(
            nwStandardButton.BUILD, self
        )
        self.btn_publish.setText(self.tr("Publish"))
        self.btn_publish.clicked.connect(self._on_publish)
        toolbar.addWidget(self.btn_publish)

        self.btn_handoff = SHARED.theme.getStandardButton(
            nwStandardButton.INSERT, self
        )
        self.btn_handoff.setText(self.tr("Handoff"))
        self.btn_handoff.clicked.connect(self._on_handoff)
        toolbar.addWidget(self.btn_handoff)

        self.btn_open_folder = SHARED.theme.getStandardButton(
            nwStandardButton.BROWSE, self
        )
        self.btn_open_folder.setText(self.tr("Open Folder"))
        self.btn_open_folder.clicked.connect(self._open_folder)
        toolbar.addWidget(self.btn_open_folder)

        layout.addLayout(toolbar)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Edition info and gate report
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()

        # Gate Report tab
        self.gate_table = QTableWidget()
        self.gate_table.setColumnCount(4)
        self.gate_table.setHorizontalHeaderLabels([
            self.tr("Rule"),
            self.tr("Severity"),
            self.tr("Message"),
            self.tr("Fix"),
        ])
        header = self.gate_table.horizontalHeader()
        if header:
            header.setStretchLastSection(True)
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.gate_table.setAlternatingRowColors(True)
        self.tab_widget.addTab(self.gate_table, self.tr("Gate Report"))

        # Jobs tab
        self.jobs_list = QListWidget()
        self.jobs_list.setAlternatingRowColors(True)
        self.tab_widget.addTab(self.jobs_list, self.tr("Jobs"))

        left_layout.addWidget(self.tab_widget)

        # Job actions
        job_actions = QHBoxLayout()
        self.btn_refresh_jobs = QPushButton(self.tr("Refresh Jobs"))
        self.btn_refresh_jobs.clicked.connect(self._refresh_jobs)
        job_actions.addWidget(self.btn_refresh_jobs)

        self.btn_open_job_folder = QPushButton(self.tr("Open Job Folder"))
        self.btn_open_job_folder.clicked.connect(self._open_job_folder)
        job_actions.addWidget(self.btn_open_job_folder)

        left_layout.addLayout(job_actions)

        splitter.addWidget(left_widget)

        # Right: Edition details / Package preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_tabs = QTabWidget()

        # Edition Details tab
        self.edition_details = QTableWidget()
        self.edition_details.setColumnCount(2)
        self.edition_details.setHorizontalHeaderLabels([
            self.tr("Property"),
            self.tr("Value"),
        ])
        header = self.edition_details.horizontalHeader()
        if header:
            header.setStretchLastSection(True)
        self.detail_tabs.addTab(self.edition_details, self.tr("Edition Details"))

        # Package Contents tab
        self.package_tree = QTreeWidget()
        self.package_tree.setHeaderLabels([
            self.tr("File"),
            self.tr("Size"),
            self.tr("SHA-256"),
        ])
        self.package_tree.setColumnWidth(0, 300)
        self.detail_tabs.addTab(self.package_tree, self.tr("Package Contents"))

        right_layout.addWidget(self.detail_tabs)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 500])

        layout.addWidget(splitter)
        self.setWidget(main_widget)

    def _connect_signals(self) -> None:
        """Connect signals."""
        self.cmb_edition.currentTextChanged.connect(self._on_edition_changed)
        self.cmb_retailer.currentTextChanged.connect(self._on_retailer_changed)
        self.jobs_list.itemClicked.connect(self._on_job_clicked)
        self.btn_refresh_jobs.clicked.connect(self._refresh_jobs)

    def refresh_editions(self) -> None:
        """Refresh the edition dropdown."""
        self.cmb_edition.clear()
        # This would be populated from the project's editions
        # For now, add placeholder

    def refresh_retailers(self) -> None:
        """Refresh the retailer dropdown."""
        self.cmb_retailer.clear()
        self.cmb_retailer.addItem(self.tr("(none)"), "")
        # Load retailers from JSON
        retailers_path = Path(__file__).parent.parent / "retailers.json"
        if retailers_path.exists():
            try:
                with open(retailers_path, encoding="utf-8") as f:
                    data = json.load(f)
                for retailer in data.get("retailers", []):
                    self.cmb_retailer.addItem(retailer["name"], retailer["id"])
            except Exception:
                pass

    def _on_edition_changed(self, edition_id: str) -> None:
        """Handle edition selection change."""
        self.refresh_gate_report()
        self.refresh_edition_details()
        self.refresh_jobs()

    def _on_retailer_changed(self, retailer_id: str) -> None:
        """Handle retailer selection change."""
        self.refresh_gate_report()

    def refresh_gate_report(self) -> None:
        """Refresh the gate report table."""
        self.gate_table.setRowCount(0)
        # This would run the gates and populate the table

    def refresh_edition_details(self) -> None:
        """Refresh edition details table."""
        self.edition_details.setRowCount(0)
        # Populate with edition metadata

    def refresh_jobs(self) -> None:
        """Refresh the jobs list."""
        self.jobs_list.clear()
        # This would list publish jobs from the project

    def _on_publish(self) -> None:
        """Run publish.package."""
        edition_id = self.cmb_edition.currentData()
        self.cmb_retailer.currentData()
        if not edition_id:
            QMessageBox.warning(self, self.tr("No Edition"), self.tr("Please select an edition first."))
            return
        # Trigger publish

    def _on_handoff(self) -> None:
        """Run publish.handoff."""
        edition_id = self.cmb_edition.currentData()
        if not edition_id:
            QMessageBox.warning(self, self.tr("No Edition"), self.tr("Please select an edition first."))
            return
        # Trigger handoff

    def _open_folder(self) -> None:
        """Open publish output folder."""

    def _on_job_clicked(self, item: QListWidgetItem) -> None:
        """Handle job selection."""
        job_data = item.data(Qt.ItemDataRole.UserRole)
        if job_data:
            self._show_job_details(job_data)

    def _show_job_details(self, job_data: dict) -> None:
        """Show job details in package tree."""
        self.package_tree.clear()
        # Populate with job package contents

    def _open_job_folder(self) -> None:
        """Open selected job's package folder."""


class PublishDockManager:
    """Manages the Publish dock lifecycle."""

    def __init__(self, main_window: GuiMain) -> None:
        self.main_window = main_window
        self.dock: PublishDock | None = None

    def create_dock(self) -> PublishDock:
        """Create the Publish dock."""
        from umbraedit.gui.publish import PublishDock
        self.dock = PublishDock(self.main_window)
        self.main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        return self.dock

    def show_dock(self) -> None:
        """Show the Publish dock."""
        if self.dock:
            self.dock.show()
            self.dock.raise_()

    def hide_dock(self) -> None:
        """Hide the Publish dock."""
        if self.dock:
            self.dock.hide()

    def refresh(self) -> None:
        """Refresh the dock content."""
        if self.dock:
            self.dock.refresh_editions()
            self.dock.refresh_retailers()
            self.dock.refresh_jobs()
