"""
UmbraEdit - Sync Conflicts Storage
==================================

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

import contextlib
import json
import logging
import os
import tempfile
import uuid

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from umbraedit.umbra.jsonio import readJson
from umbraedit.umbra.paths import conflictsFile

logger = logging.getLogger(__name__)

CONFLICT_ID_PREFIX = "cf-"


def _utcNow() -> str:
    """Return current UTC time as ISO 8601 with Z, seconds precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _newConflictId() -> str:
    """Generate a new conflict ID."""
    return f"{CONFLICT_ID_PREFIX}{uuid.uuid4().hex[:16]}"


def _atomicWriteJson(path: Path, data: Any) -> None:
    """Atomically write JSON (sorted keys, compact, trailing newline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    fd, tmpPath = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpPath, str(path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmpPath)
        raise


class ConflictRecord:
    """A single conflict record."""

    def __init__(
        self,
        conflict_id: str,
        handle: str,
        state: str,
        base: str,
        theirs: str,
        created_at: str,
        units: list[dict[str, Any]],
        resolved_at: str | None = None,
        resolution: str | None = None,
    ) -> None:
        self.id = conflict_id
        self.handle = handle
        self.state = state  # "open" | "merged" | "resolved"
        self.base = base
        self.theirs = theirs
        self.created_at = created_at
        self.units = units
        self.resolved_at = resolved_at
        self.resolution = resolution

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d: dict[str, Any] = {
            "id": self.id,
            "handle": self.handle,
            "state": self.state,
            "base": self.base,
            "theirs": self.theirs,
            "createdAt": self.created_at,
            "units": self.units,
        }
        if self.resolved_at is not None:
            d["resolvedAt"] = self.resolved_at
        if self.resolution is not None:
            d["resolution"] = self.resolution
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConflictRecord:
        """Create from dictionary."""
        return cls(
            conflict_id=d["id"],
            handle=d["handle"],
            state=d["state"],
            base=d["base"],
            theirs=d["theirs"],
            created_at=d["createdAt"],
            units=d.get("units", []),
            resolved_at=d.get("resolvedAt"),
            resolution=d.get("resolution"),
        )


class ConflictsStore:
    """Manages sync conflicts stored in <project>/umbra/sync/conflicts.json."""

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path
        self._path = conflictsFile(project_path)
        self._conflicts: list[ConflictRecord] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        if not self._path.is_file():
            self._conflicts = []
            return
        try:
            data = readJson(self._path, default=[])
            if isinstance(data, list):
                self._conflicts = [ConflictRecord.from_dict(item) for item in data]
            else:
                self._conflicts = []
        except Exception:
            logger.exception("Could not read conflicts.json")
            self._conflicts = []

    def _save(self) -> None:
        data = [c.to_dict() for c in self._conflicts]
        _atomicWriteJson(self._path, data)

    def open_conflicts(self) -> list[ConflictRecord]:
        """Return all conflicts with state 'open'."""
        self._ensure_loaded()
        return [c for c in self._conflicts if c.state == "open"]

    def all_conflicts(self) -> list[ConflictRecord]:
        """Return all conflicts."""
        self._ensure_loaded()
        return list(self._conflicts)

    def add_conflict(
        self,
        handle: str,
        base: str,
        theirs: str,
        units: list[dict[str, Any]],
    ) -> str:
        """Add a new document conflict. Returns the conflict ID."""
        self._ensure_loaded()
        conflict_id = _newConflictId()
        record = ConflictRecord(
            conflict_id=conflict_id,
            handle=handle,
            state="open",
            base=base,
            theirs=theirs,
            created_at=_utcNow(),
            units=units,
        )
        self._conflicts.append(record)
        self._save()
        return conflict_id

    def add_file_conflict(
        self,
        path: str,
        base: str,
        theirs: str,
        op: str,
    ) -> str:
        """Add a new file conflict (tree/sidecar). Returns the conflict ID."""
        self._ensure_loaded()
        conflict_id = _newConflictId()
        record = ConflictRecord(
            conflict_id=conflict_id,
            handle=path,
            state="open",
            base=base,
            theirs=theirs,
            created_at=_utcNow(),
            units=[
                {
                    "kind": op,
                    "baseText": "",
                    "oursText": "",
                    "theirsText": "",
                }
            ],
        )
        self._conflicts.append(record)
        self._save()
        return conflict_id

    def resolve_conflict(self, conflict_id: str, resolution: str) -> bool:
        """Mark a conflict as resolved. Returns True if found and updated."""
        self._ensure_loaded()
        for record in self._conflicts:
            if record.id == conflict_id:
                record.state = "resolved"
                record.resolved_at = _utcNow()
                record.resolution = resolution
                self._save()
                return True
        return False

    def merge_conflict(self, conflict_id: str) -> bool:
        """Mark a conflict as auto-merged. Returns True if found and updated."""
        self._ensure_loaded()
        for record in self._conflicts:
            if record.id == conflict_id:
                record.state = "merged"
                record.resolved_at = _utcNow()
                record.resolution = "merged"
                self._save()
                return True
        return False

    def open_count(self) -> int:
        """Return the number of open conflicts."""
        return len(self.open_conflicts())
