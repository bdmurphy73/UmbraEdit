"""
UmbraEdit - Windows Build Tests
===============================

This file is a part of UmbraEdit.

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

import sys

from pathlib import Path

import pytest

from utils.build_windows import LAUNCHER_NAME, verifyPayload


@pytest.mark.base
def testWindows_validPayload(tmp_path: Path):
    """Test that a payload with the UmbraEdit launcher passes."""
    (tmp_path / LAUNCHER_NAME).write_bytes(b"MZ")
    (tmp_path / "umbraedit.ico").write_bytes(b"icon")
    (tmp_path / "lib").mkdir()

    verifyPayload(tmp_path)


@pytest.mark.base
def testWindows_missingLauncher(tmp_path: Path):
    """Test that a payload without the launcher is rejected."""
    (tmp_path / "umbraedit.ico").write_bytes(b"icon")

    with pytest.raises(SystemExit) as exc:
        verifyPayload(tmp_path)
    assert exc.value.code == 1


@pytest.mark.base
def testWindows_legacyNameInPayload(tmp_path: Path):
    """Test that a payload with the upstream product name is rejected."""
    (tmp_path / LAUNCHER_NAME).write_bytes(b"MZ")
    (tmp_path / "novelWriter.exe").write_bytes(b"MZ")

    with pytest.raises(SystemExit) as exc:
        verifyPayload(tmp_path)
    assert exc.value.code == 1


@pytest.mark.base
def testWindows_legacyNameInSubFolder(tmp_path: Path):
    """Test that the upstream product name is caught in sub folders too."""
    (tmp_path / LAUNCHER_NAME).write_bytes(b"MZ")
    subDir = tmp_path / "lib" / "novelWriter"
    subDir.mkdir(parents=True)
    (subDir / "novelWriter.py").write_text("text", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        verifyPayload(tmp_path)
    assert exc.value.code == 1


if __name__ == "__main__":
    sys.exit(0)
