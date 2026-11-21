"""
UmbraEdit - Project Conflict Dialog Tests
==========================================

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

from pathlib import Path

import pytest

from pytestqt.qtbot import QtBot

from umbraedit.dialogs.projectconflict import GuiProjectConflict, ProjectConflictAction
from umbraedit.guimain import GuiMain


@pytest.mark.gui
def testGuiProjectConflict_Main(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, nwGUI: GuiMain):
    """Test the project conflict dialog."""
    path = Path("/tmp/Inner Demon")

    dialog = GuiProjectConflict(nwGUI, path)
    with qtbot.waitExposed(dialog):
        dialog.show()

    # The path must be shown to the user
    assert str(path) in dialog.pathLabel.text()

    # The default action is to cancel
    assert dialog.action is ProjectConflictAction.CANCEL

    # The erase button selects the erase action
    dialog.btnErase.click()
    assert dialog.action is ProjectConflictAction.ERASE

    # The rename button selects the rename action
    dialog.btnRename.click()
    assert dialog.action is ProjectConflictAction.RENAME

    # The cancel button selects the cancel action
    dialog.btnCancel.click()
    assert dialog.action is ProjectConflictAction.CANCEL

    dialog.close()


@pytest.mark.gui
def testGuiProjectConflict_Ask(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, nwGUI: GuiMain):
    """Test the project conflict dialog helper function."""
    path = Path("/tmp/Inner Demon")

    # By default, the dialog is cancelled
    monkeypatch.setattr(GuiProjectConflict, "exec", lambda *a: None)
    assert GuiProjectConflict.ask(nwGUI, path) is ProjectConflictAction.CANCEL

    # The erase button
    monkeypatch.setattr(GuiProjectConflict, "exec", lambda self: self.btnErase.click())
    assert GuiProjectConflict.ask(nwGUI, path) is ProjectConflictAction.ERASE

    # The rename button
    monkeypatch.setattr(GuiProjectConflict, "exec", lambda self: self.btnRename.click())
    assert GuiProjectConflict.ask(nwGUI, path) is ProjectConflictAction.RENAME

    # The cancel button
    monkeypatch.setattr(GuiProjectConflict, "exec", lambda self: self.btnCancel.click())
    assert GuiProjectConflict.ask(nwGUI, path) is ProjectConflictAction.CANCEL
