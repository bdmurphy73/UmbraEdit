"""
UmbraEdit - Packaging Utilities Tests
======================================

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

from datetime import datetime
from pathlib import Path

import pytest

from utils.common import extractVersion


@pytest.mark.base
def testPkg_extractVersion(monkeypatch: pytest.MonkeyPatch, fncPath: Path):
    """Test the extractVersion function."""
    pkgFile = fncPath / "umbraedit" / "__init__.py"
    pkgFile.parent.mkdir(parents=True)
    pkgFile.write_text(
        "\n".join([
            '__version__    = "2026.11.0024"',
            '__hexversion__ = "0x01000000"  # Changed by B.D. Murphy 2026',
            '__date__       = "2026-11-26"  # Changed by B.D. Murphy 2026',
            "",
        ]),
        encoding="utf-8",
    )

    with monkeypatch.context() as mp:
        mp.setattr("utils.common.ROOT_DIR", fncPath)
        numVers, hexVers, relDate = extractVersion(beQuiet=True)

    # The trailing comments must not leak into the values
    assert numVers == "2026.11.0024"
    assert hexVers == "0x01000000"
    assert relDate == "2026-11-26"

    # The release date must be usable by the package builders
    assert datetime.strptime(relDate, "%Y-%m-%d") == datetime(2026, 11, 26)


@pytest.mark.base
def testPkg_extractVersionCurrent():
    """Test the extractVersion function on the actual package."""
    numVers, hexVers, relDate = extractVersion(beQuiet=True)

    assert numVers
    assert "#" not in numVers
    assert hexVers.startswith("0x")
    assert "#" not in hexVers
    assert relDate != "Unknown"
    assert "#" not in relDate
    assert datetime.strptime(relDate, "%Y-%m-%d")
