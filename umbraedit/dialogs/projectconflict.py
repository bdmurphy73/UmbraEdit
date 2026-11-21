"""
UmbraEdit - GUI Project Conflict Dialog
========================================

This file is a part of UmbraEdit.

Copyright (C) 2026 B.D. Murphy and UmbraEdit contributors.

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

from enum import Enum
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QPushButton, QVBoxLayout, QWidget

from umbraedit import SHARED
from umbraedit.enum import nwStandardButton
from umbraedit.extensions.modified import NDialog
from umbraedit.types import QtRoleAction, QtRoleReject

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectConflictAction(Enum):
    """The action the user chose to resolve a project conflict."""

    ERASE = 0
    RENAME = 1
    CANCEL = 2


class GuiProjectConflict(NDialog):
    """GUI: Project Location Conflict Dialog.

    This dialog is shown when a project cannot be created because a
    location with the same name already exists. Instead of just failing,
    the user is given the option to erase the existing location, to use a
    different name, or to cancel the operation.
    """

    def __init__(self, parent: QWidget, path: Path) -> None:
        super().__init__(parent=parent)

        logger.debug("Create: GuiProjectConflict")
        self.setObjectName("GuiProjectConflict")
        self.setWindowTitle(self.tr("Project Location Exists"))
        self.setMinimumWidth(420)

        self._action = ProjectConflictAction.CANCEL

        # Message
        # =======

        self.infoLabel = QLabel(
            self.tr("A location with the same name already exists, so the project cannot be created."),
            self,
        )
        self.infoLabel.setWordWrap(True)

        self.pathLabel = QLabel(str(path), self)
        self.pathLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.pathLabel.setWordWrap(True)
        self.pathLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.warnLabel = QLabel(
            self.tr("Erasing the location will permanently delete everything stored there. This cannot be undone."),
            self,
        )
        self.warnLabel.setWordWrap(True)

        # Buttons
        # =======

        self.btnErase = QPushButton(SHARED.theme.getIcon("remove:remove"), self.tr("Erase and Replace"), self)
        self.btnErase.setToolTip(self.tr("Delete the existing location and replace it with the new project."))
        self.btnErase.setAutoDefault(False)
        self.btnErase.clicked.connect(self._onErase)

        self.btnRename = QPushButton(SHARED.theme.getIcon("edit:change"), self.tr("Change Name"), self)
        self.btnRename.setToolTip(self.tr("Create the project with a different name."))
        self.btnRename.setAutoDefault(False)
        self.btnRename.clicked.connect(self._onRename)

        self.btnCancel = SHARED.theme.getStandardButton(nwStandardButton.CANCEL, self)
        self.btnCancel.clicked.connect(self._onCancel)

        self.btnBox = QDialogButtonBox(self)
        self.btnBox.addButton(self.btnErase, QtRoleAction)
        self.btnBox.addButton(self.btnRename, QtRoleAction)
        self.btnBox.addButton(self.btnCancel, QtRoleReject)
        self.btnCancel.setDefault(True)

        # Assemble
        # ========

        self.outerBox = QVBoxLayout()
        self.outerBox.addWidget(self.infoLabel, 0)
        self.outerBox.addWidget(self.pathLabel, 0)
        self.outerBox.addWidget(self.warnLabel, 0)
        self.outerBox.addWidget(self.btnBox, 0)
        self.outerBox.setSpacing(12)

        self.setLayout(self.outerBox)

        logger.debug("Ready: GuiProjectConflict")

    def __del__(self) -> None:  # pragma: no cover
        """Class destructor."""
        logger.debug("Delete: GuiProjectConflict")

    ##
    #  Properties
    ##

    @property
    def action(self) -> ProjectConflictAction:
        """Return the action the user selected."""
        return self._action

    ##
    #  Public Slots
    ##

    @classmethod
    def ask(cls, parent: QWidget, path: Path) -> ProjectConflictAction:
        """Pop the dialog and return the selected action."""
        dialog = cls(parent, path)
        dialog.exec()
        action = dialog.action
        dialog.softDelete()
        return action

    ##
    #  Private Slots
    ##

    def _onErase(self) -> None:
        """Handle the user choosing to erase the existing location."""
        self._action = ProjectConflictAction.ERASE
        self.close()

    def _onRename(self) -> None:
        """Handle the user choosing to use a different name."""
        self._action = ProjectConflictAction.RENAME
        self.close()

    def _onCancel(self) -> None:
        """Handle the user cancelling the operation."""
        self._action = ProjectConflictAction.CANCEL
        self.close()
