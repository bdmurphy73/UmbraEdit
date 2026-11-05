"""
UmbraEdit - GUI i18n Tests
============================

This file is a part of UmbraEdit.

Copyright (C) 2022 Veronica Berglyd Olsen and UmbraEdit contributors.

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
import sys

from collections.abc import Callable
from pathlib import Path

import pytest

from PyQt6.QtWidgets import QApplication, QDialog, QWidget
from pytestqt.qtbot import QtBot

from umbraedit import CONFIG, SHARED
from umbraedit.core.project import NWProject
from umbraedit.dialogs.about import GuiAbout
from umbraedit.dialogs.preferences import GuiPreferences
from umbraedit.dialogs.projectsettings import GuiProjectSettings
from umbraedit.dialogs.wordlist import GuiWordList
from umbraedit.guimain import GuiMain
from umbraedit.manuscript.manuscript import GuiManuscript
from umbraedit.tools.dictionaries import GuiDictionaries
from umbraedit.tools.welcome import GuiWelcome
from umbraedit.tools.writingstats import GuiWritingStats

from tests.helpers import buildTestProject

LANG_DATA = CONFIG.listLanguages(CONFIG.LANG_NW)
PROJ_DATA = CONFIG.listLanguages(CONFIG.LANG_PROJ)


@pytest.mark.gui
@pytest.mark.skipif(sys.platform != "linux", reason="Linux Only")
@pytest.mark.skipif(not LANG_DATA, reason="No i18n Data")
@pytest.mark.parametrize("language", [a for a, b in LANG_DATA])
def testGuiI18n_Localisation(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    nwGUI: GuiMain,
    projPath: Path,
):
    """Test loading the gui with a specific language."""
    monkeypatch.setattr(QDialog, "exec", lambda *a: None)

    # Set the test language
    CONFIG.guiLocale = language
    CONFIG.initLocalisation(QApplication.instance())  # type: ignore

    buildTestProject(NWProject(), projPath)
    nwGUI.openProject(projPath)
    nwGUI.show()

    def showDialog(func: Callable[[], None], dType: type[QWidget]) -> None:
        func()
        qtbot.waitUntil(lambda: SHARED.findTopLevelWidget(dType) is not None, timeout=1000)
        dialog = SHARED.findTopLevelWidget(dType)
        assert isinstance(dialog, dType)
        assert dialog is not None
        dialog.deleteLater()

    showDialog(nwGUI.showWelcomeDialog, GuiWelcome)
    showDialog(nwGUI.showPreferencesDialog, GuiPreferences)
    showDialog(nwGUI.showProjectSettingsDialog, GuiProjectSettings)
    showDialog(nwGUI.showBuildManuscriptDialog, GuiManuscript)
    showDialog(nwGUI.showProjectWordListDialog, GuiWordList)
    showDialog(nwGUI.showWritingStatsDialog, GuiWritingStats)
    showDialog(nwGUI.showAboutNWDialog, GuiAbout)
    showDialog(nwGUI.showDictionariesDialog, GuiDictionaries)

    qtbot.wait(20)
    nwGUI.closeMain()


@pytest.mark.base
@pytest.mark.parametrize("language", [a for a, b in PROJ_DATA if a != "en_GB"])
def testGuiI18n_ProjectExport(language: str):
    """Check that a project language file matches the en_GB reference."""
    langPath = Path(CONFIG.nwLangPath)
    reference = json.loads((langPath / "project_en_GB.json").read_text(encoding="utf-8"))
    data = json.loads((langPath / f"project_{language}.json").read_text(encoding="utf-8"))
    assert data.keys() == reference.keys()
    assert all(isinstance(v, str) and v for v in data.values())
