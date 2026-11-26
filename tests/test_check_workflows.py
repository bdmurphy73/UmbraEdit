"""
UmbraEdit - Workflow Checks Tests
==================================

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

from utils.check_workflows import checkFile, main


@pytest.mark.base
def testWorkflow_noDuplicateKeys(tmp_path: Path):
    """Test that a workflow with duplicate keys is rejected."""
    wfFile = tmp_path / "bad.yml"
    wfFile.write_text(
        "\n".join([
            "name: Test",
            "on: workflow_dispatch",
            "jobs:",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v5",
            "        with:",
            "          path: .",
            "          path: ./src",
            "",
        ]),
        encoding="utf-8",
    )

    problems = checkFile(wfFile)
    assert problems
    assert "duplicate key" in problems[0]


@pytest.mark.base
def testWorkflow_validFile(tmp_path: Path):
    """Test that a valid workflow passes the check."""
    wfFile = tmp_path / "good.yml"
    wfFile.write_text(
        "\n".join([
            "name: Test",
            "on: workflow_dispatch",
            "jobs:",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v5",
            "        with:",
            "          path: .",
            "",
        ]),
        encoding="utf-8",
    )

    assert checkFile(wfFile) == []


@pytest.mark.base
def testWorkflow_repositoryWorkflows():
    """Test that all the workflow files in the repository are valid."""
    result = main([])
    assert result == 0


@pytest.mark.base
def testWorkflow_mainEntryPoint(monkeypatch: pytest.MonkeyPatch, capsys):
    """Test the command line entry point of the checker."""
    monkeypatch.setattr(sys, "argv", ["check_workflows.py"])
    assert main(None) == 0
    assert "no problems found" in capsys.readouterr().out
