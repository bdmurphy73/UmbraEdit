"""
UmbraEdit - File Integrity Gates
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

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_BACKUP_ROTATE,
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    OP_SYNC_PUSH,
    Finding,
    GateRule,
    registerGate,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

REPAIRS_JSONL = "repairs.jsonl"

# Rule IDs
RULE_FILE_UNRECOVERABLE = "fileUnrecoverable"
RULE_FILE_CORRUPTED = "fileCorrupted"
RULE_FILE_UNREPAIRED = "fileUnrepaired"


def _getProjectPath(scope: Any) -> str | None:
    """Safely get the project path from a gate scope."""
    try:
        if not scope.project:
            return None
        storage = scope.project.storage
        projectPath = getattr(storage, "projectPath", None)
        if projectPath is None:
            return None
        return str(projectPath)
    except Exception:
        return None


def _unrecoverableFindings(scope: Any) -> Iterable[Finding]:
    """Block: unacknowledged unrecoverable problems block key operations."""
    projectPath = _getProjectPath(scope)
    if not projectPath:
        return

    from pathlib import Path

    project = Path(projectPath)
    repairsFile = project / "umbra" / REPAIRS_JSONL
    if not repairsFile.is_file():
        return

    acknowledged = set()
    acknowledgedFile = project / "umbra" / "repairs-acknowledged.json"
    if acknowledgedFile.is_file():
        try:
            data = json.loads(acknowledgedFile.read_text(encoding="utf-8"))
            acknowledged = set(data.get("acknowledged", []))
        except Exception:
            pass

    try:
        with open(repairsFile, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if (
                    entry.get("severity") == "unrecoverable"
                    and not entry.get("acknowledged", False)
                    and entry.get("id") not in acknowledged
                ):
                    yield Finding(
                        ruleId=RULE_FILE_UNRECOVERABLE,
                        severity="block",
                        message=f"Unrecoverable file: {entry.get('handle', 'unknown')}. "
                        f"Acknowledge or repair before continuing.",
                        fix="Open the Repairs dialog, acknowledge resolved issues, and restore damaged files.",
                        handle=entry.get("handle"),
                        line=None,
                        detail={"problemId": entry.get("id"), "action": entry.get("action")},
                    )
    except Exception:
        logger.exception("Could not read repairs file %s", repairsFile)


def _corruptedFindings(scope: Any) -> Iterable[Finding]:
    """Block: corrupted files that cannot be repaired."""
    projectPath = _getProjectPath(scope)
    if not projectPath:
        return

    from pathlib import Path

    project = Path(projectPath)
    repairsFile = project / "umbra" / "repairs.jsonl"
    if not repairsFile.is_file():
        return

    acknowledgedFile = project / "umbra" / "repairs-acknowledged.json"
    acknowledged = set()
    if acknowledgedFile.is_file():
        try:
            data = json.loads(acknowledgedFile.read_text(encoding="utf-8"))
            acknowledged = set(data.get("acknowledged", []))
        except Exception:
            pass

    try:
        with open(repairsFile, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                severity = entry.get("severity", "")
                if severity in ("block", "unrecoverable") and entry.get("id") not in acknowledged:
                    yield Finding(
                        ruleId=RULE_FILE_CORRUPTED,
                        severity="block",
                        message=f"Corrupted file: {entry.get('handle', 'unknown')}. "
                        f"Repair required before building, syncing, or publishing.",
                        fix="Run Verify Project and repair damaged documents.",
                        handle=entry.get("handle"),
                        line=None,
                        detail={"problemId": entry.get("id")},
                    )
    except Exception:
        logger.exception("Could not read repairs file %s", repairsFile)


def _unrepairedFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: some files could not be repaired automatically."""
    projectPath = _getProjectPath(scope)
    if not projectPath:
        return

    from pathlib import Path

    project = Path(projectPath)
    repairsFile = project / "umbra" / "repairs.jsonl"
    if not repairsFile.is_file():
        return

    acknowledgedFile = project / "umbra" / "repairs-acknowledged.json"
    acknowledged = set()
    if acknowledgedFile.is_file():
        try:
            data = json.loads(acknowledgedFile.read_text(encoding="utf-8"))
            acknowledged = set(data.get("acknowledged", []))
        except Exception:
            pass

    try:
        with open(repairsFile, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("severity") == "repair" and entry.get("id") not in acknowledged:
                    yield Finding(
                        ruleId=RULE_FILE_UNREPAIRED,
                        severity="advisory",
                        message=f"File could not be repaired: {entry.get('handle', 'unknown')}.",
                        fix="Review the Repairs dialog and manually restore affected documents.",
                        handle=entry.get("handle"),
                        line=None,
                        detail={"problemId": entry.get("id")},
                    )
    except Exception:
        logger.exception("Could not read repairs file %s", repairsFile)


registerGate(
    GateRule(
        ruleId=RULE_FILE_UNRECOVERABLE,
        title="File Unrecoverable",
        operations=frozenset({OP_BUILD_RUN, OP_SYNC_PUSH, OP_PUBLISH_PACKAGE, OP_BACKUP_ROTATE}),
        defaultSeverity="block",
        relaxable=False,
        check=_unrecoverableFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_FILE_CORRUPTED,
        title="File Corrupted",
        operations=frozenset({OP_BUILD_RUN, OP_SYNC_PUSH, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_corruptedFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_FILE_UNREPAIRED,
        title="File Unrepaired",
        operations=frozenset(),
        defaultSeverity="advisory",
        relaxable=True,
        check=_unrepairedFindings,
    )
)
