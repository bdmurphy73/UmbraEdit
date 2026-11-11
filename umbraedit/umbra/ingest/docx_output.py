"""
UmbraEdit - DOCX Output Stage
==============================

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
import time
import uuid

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from umbraedit.umbra.ingest.docx_intake import IntakeResult
from umbraedit.umbra.ingest.docx_propose import ProposeResult
from umbraedit.umbra.ingest.docx_split import SceneSplitResult
from umbraedit.umbra.ingest.docx_syntax import SyntaxResult
from umbraedit.umbra.paths import cacheDir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportPlan:
    """Final import plan output."""

    v: int = 1
    run_id: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    documents: list[dict[str, Any]] = field(default_factory=list)
    characters: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, reviewed, committed, rolled_back

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "v": self.v,
            "runId": self.run_id,
            "source": self.source,
            "documents": self.documents,
            "characters": self.characters,
            "metadata": self.metadata,
            "findings": self.findings,
            "status": self.status,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True) + "\n"


def _generate_run_id() -> str:
    """Generate a ULID-like run ID."""
    # Simple ULID-like: ir- + timestamp + random
    timestamp = int(time.time() * 1000)
    random_part = uuid.uuid4().hex[:10]
    return f"ir-{timestamp:013d}-{random_part}"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically using temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    temp_path.replace(path)


class DocxOutput:
    """Output stage: write ImportPlan JSON to cache."""

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path
        self._cache_dir = cacheDir(project_path) / "import"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        intake: IntakeResult,
        split: SceneSplitResult,
        syntax: SyntaxResult,
        propose: ProposeResult,
    ) -> Path:
        """Write the import plan to cache."""
        run_id = _generate_run_id()
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Collect all findings
        all_findings = []
        all_findings.extend(syntax.warnings)
        all_findings.extend(propose.warnings)

        # Add critical findings
        if split.chapter_count == 0:
            all_findings.append("ingestNoHeadings: No chapter headings found")
        for doc in split.documents:
            if doc["kind"] == "scene" and not doc["text"].strip():
                all_findings.append(f"ingestEmptyScene: {doc['planId']}")

        plan = ImportPlan(
            v=1,
            run_id=run_id,
            source={
                "file": str(intake.file_path),
                "sha256": intake.sha256,
                "pandoc": intake.pandoc_version,
            },
            documents=syntax.documents,
            characters=propose.characters,
            metadata=propose.metadata,
            findings=all_findings,
        )

        # Write to cache
        output_file = self._cache_dir / f"{run_id}.json"
        _atomic_write_json(output_file, plan.to_dict())

        logger.info("Output: wrote import plan to %s", output_file)
        return output_file

    def load(self, run_id: str) -> ImportPlan | None:
        """Load an import plan from cache."""
        file_path = self._cache_dir / f"{run_id}.json"
        if not file_path.is_file():
            return None
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            # Convert camelCase keys to snake_case for dataclass
            if "runId" in data:
                data["run_id"] = data.pop("runId")
            return ImportPlan(**data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load import plan %s: %s", run_id, e)
            return None
