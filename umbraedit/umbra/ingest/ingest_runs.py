"""
UmbraEdit - Ingest Runs Tracking
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
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from pathlib import Path
from typing import Any

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import ingestRunsFile

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IngestRun:
    """A record of an ingest run."""

    run_id: str
    file_path: str
    sha256: str
    pandoc_version: str
    imported_at: str
    status: str  # completed, rolled_back
    plan_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "filePath": self.file_path,
            "sha256": self.sha256,
            "pandocVersion": self.pandoc_version,
            "importedAt": self.imported_at,
            "status": self.status,
            "planId": self.plan_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestRun:
        return cls(
            run_id=data["runId"],
            file_path=data["filePath"],
            sha256=data["sha256"],
            pandoc_version=data["pandocVersion"],
            imported_at=data["importedAt"],
            status=data["status"],
            plan_id=data["planId"],
        )


def _load_runs(project_path: Path) -> list[IngestRun]:
    """Load all ingest runs from the project."""
    file_path = ingestRunsFile(project_path)
    if not file_path.is_file():
        return []
    try:
        data = readJson(file_path)
        if not isinstance(data, dict):
            return []
        runs_data = data.get("runs", [])
        return [IngestRun.from_dict(r) for r in runs_data]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to load ingest runs: %s", e)
        return []


def _save_runs(project_path: Path, runs: list[IngestRun]) -> None:
    """Save all ingest runs to the project atomically."""
    file_path = ingestRunsFile(project_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "v": 1,
        "runs": [r.to_dict() for r in runs],
    }
    writeJson(file_path, data)


def record_ingest_run(
    project_path: Path,
    run_id: str,
    file_path: str,
    sha256: str,
    pandoc_version: str,
    plan_id: str,
    status: str = "completed",
) -> None:
    """Record a completed ingest run."""
    imported_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = _load_runs(project_path)

    # Check if this file was already imported
    existing = next((r for r in runs if r.sha256 == sha256 and r.status == "completed"), None)
    if existing:
        logger.warning("File with SHA-256 %s was already imported as run %s", sha256, existing.run_id)

    new_run = IngestRun(
        run_id=run_id,
        file_path=file_path,
        sha256=sha256,
        pandoc_version=pandoc_version,
        imported_at=imported_at,
        status=status,
        plan_id=plan_id,
    )
    runs.append(new_run)
    _save_runs(project_path, runs)
    logger.info("Recorded ingest run %s for %s", run_id, file_path)


def find_existing_import(project_path: Path, sha256: str) -> IngestRun | None:
    """Find an existing import run for the given file hash."""
    runs = _load_runs(project_path)
    for run in runs:
        if run.sha256 == sha256 and run.status == "completed":
            return run
    return None
