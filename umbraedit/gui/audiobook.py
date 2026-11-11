"""
UmbraEdit - Audio Dock
======================

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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
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


class AudioDock(QDockWidget):
    """Dock widget for the Audio panel."""

    def __init__(self, main_window: GuiMain) -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self.setObjectName("AudioDock")
        self.setWindowTitle(self.tr("Audio"))

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        """Build the dock UI."""
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_build_chapter = SHARED.theme.getStandardButton(
            nwStandardButton.BUILD, self
        )
        self.btn_build_chapter.setText(self.tr("Build Chapter"))
        self.btn_build_chapter.clicked.connect(self._build_chapter)
        toolbar.addWidget(self.btn_build_chapter)

        self.btn_build_book = SHARED.theme.getStandardButton(
            nwStandardButton.PRINT, self
        )
        self.btn_build_book.setText(self.tr("Build Book"))
        self.btn_build_book.clicked.connect(self._build_book)
        toolbar.addWidget(self.btn_build_book)

        self.btn_open_folder = SHARED.theme.getStandardButton(
            nwStandardButton.BROWSE, self
        )
        self.btn_open_folder.setText(self.tr("Open Folder"))
        self.btn_open_folder.clicked.connect(self._open_folder)
        toolbar.addWidget(self.btn_open_folder)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Chapter tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.chapter_tree = QTreeWidget()
        self.chapter_tree.setHeaderLabels([
            self.tr("Chapter"),
            self.tr("Status"),
            self.tr("Gate Findings"),
        ])
        self.chapter_tree.setColumnWidth(0, 200)
        self.chapter_tree.setColumnWidth(1, 80)
        self.chapter_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        left_layout.addWidget(self.chapter_tree)

        # Chapter actions
        chapter_actions = QHBoxLayout()
        self.btn_build_chapter_single = QPushButton(self.tr("Build Chapter"))
        self.btn_build_chapter_single.clicked.connect(self._build_selected_chapter)
        chapter_actions.addWidget(self.btn_build_chapter_single)
        left_layout.addLayout(chapter_actions)

        splitter.addWidget(left_widget)

        # Center: Chapter text / findings
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()

        # Text tab
        from PyQt6.QtWidgets import QPlainTextEdit
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        font = self.text_edit.font()
        font.setFamily("Monospace")
        font.setPointSize(10)
        self.text_edit.setFont(font)
        self.tab_widget.addTab(self.text_edit, self.tr("Text"))

        # Findings tab
        self.findings_list = QListWidget()
        self.findings_list.setAlternatingRowColors(True)
        self.tab_widget.addTab(self.findings_list, self.tr("Findings"))

        # Pronunciation tab
        self.pron_list = QListWidget()
        self.pron_list.setAlternatingRowColors(True)
        self.tab_widget.addTab(self.pron_list, self.tr("Pronunciation"))

        center_layout.addWidget(self.tab_widget)
        splitter.addWidget(center_widget)

        # Right: Details / Pronunciation / Gates
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_tabs = QTabWidget()

        # Findings detail
        self.findings_table = QTableWidget()
        self.findings_table.setColumnCount(3)
        self.findings_table.setHorizontalHeaderLabels([
            self.tr("Rule"),
            self.tr("Severity"),
            self.tr("Message"),
        ])
        header = self.findings_table.horizontalHeader()
        if header:
            header.setStretchLastSection(True)
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.findings_table)

        splitter.addWidget(right_widget)
        splitter.setSizes([300, 500, 300])

        layout.addWidget(splitter)
        self.setWidget(main_widget)

    def _connect_signals(self) -> None:
        """Connect signals."""
        self.chapter_tree.itemSelectionChanged.connect(self._on_chapter_selected)
        self.findings_list.itemClicked.connect(self._on_finding_clicked)

    def refresh_chapters(self) -> None:
        """Refresh the chapter list."""
        self.chapter_tree.clear()
        # This would be populated from the project

    def _on_chapter_selected(self) -> None:
        """Handle chapter selection."""
        items = self.chapter_tree.selectedItems()
        if not items:
            return
        item = items[0]
        chapter_handle = item.data(0, Qt.ItemDataRole.UserRole)
        if chapter_handle:
            self._load_chapter(chapter_handle)

    def _load_chapter(self, chapter_handle: str) -> None:
        """Load chapter text and findings."""
        # Load chapter text
        # self.text_edit.setPlainText(...)
        # Load findings
        self.findings_list.clear()
        # self.findings_list.addItems(...)

    def _on_finding_clicked(self, item: QListWidgetItem) -> None:
        """Handle finding click."""

    def _build_chapter(self) -> None:
        """Build audio for current chapter."""
        items = self.chapter_tree.selectedItems()
        if not items:
            return
        item = items[0]
        chapter_handle = item.data(0, Qt.ItemDataRole.UserRole)
        if not chapter_handle:
            return
        # Trigger chapter build

    def _build_selected_chapter(self) -> None:
        """Build audio for selected chapter."""
        items = self.chapter_tree.selectedItems()
        if not items:
            return
        item = items[0]
        chapter_handle = item.data(0, Qt.ItemDataRole.UserRole)
        if not chapter_handle:
            return
        # Trigger chapter build

    def _build_book(self) -> None:
        """Build complete audio book."""

    def _open_folder(self) -> None:
        """Open audio output folder."""


class AudioDockManager:
    """Manages the Audio dock lifecycle."""

    def __init__(self, main_window: GuiMain) -> None:
        self.main_window = main_window
        self.dock: AudioDock | None = None

    def create_dock(self) -> AudioDock:
        """Create the Audio dock."""
        from umbraedit.gui.audiobook import AudioDock
        self.dock = AudioDock(self.main_window)
        self.main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        return self.dock

    def show_dock(self) -> None:
        """Show the Audio dock."""
        if self.dock:
            self.dock.show()
            self.dock.raise_()

    def hide_dock(self) -> None:
        """Hide the Audio dock."""
        if self.dock:
            self.dock.hide()

    def refresh(self) -> None:
        """Refresh the dock content."""
        if self.dock:
            self.dock.refresh_chapters()
