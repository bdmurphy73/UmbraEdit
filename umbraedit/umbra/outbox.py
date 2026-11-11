"""
UmbraEdit - Change Log and Outbox
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
import hashlib
import json
import logging
import os
import tempfile
import zlib

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.hooks import (
    DOCUMENT_SAVED,
    PROJECT_SAVED,
    SIDECAR_WRITTEN,
    register,
)
from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import (
    ackedFile,
    stateFile,
    syncDir,
    umbraDir,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Outbox file (umbra/outbox.jsonl)
OUTBOX_FILE = "outbox.jsonl"

# Sync sub-folder
SYNC_DIR = "sync"
STATE_JSON = "state.json"
ACKED_JSON = "acked.json"

# Synced sidecar files
SYNCED_SIDECARS: frozenset[str] = frozenset({
    "voices.json",
    "tones.json",
    "sheet.json",
    "metadata.json",
    "settings.json",
    "pages.json",
    "series.json",
    "edition.json",
})

# Ops
OP_DOC_PUT = "doc.put"
OP_DOC_DELETE = "doc.delete"
OP_TREE_PUT = "tree.put"
OP_SIDECAR_PUT = "sidecar.put"

ALL_OPS: frozenset[str] = frozenset({
    OP_DOC_PUT,
    OP_DOC_DELETE,
    OP_TREE_PUT,
    OP_SIDECAR_PUT,
})


def _utcNow() -> str:
    """Return current UTC time as ISO 8601 with Z, seconds precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _crc32(line: str) -> str:
    """CRC-32 of a line, as lowercase 8-hex-digit string."""
    return f"{zlib.crc32(line.encode('utf-8')) & 0xFFFFFFFF:08x}"


def _sha256File(path: Path) -> str:
    """Return the SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _serialiseEntry(entry: dict[str, Any]) -> str:
    """Serialise an outbox entry to a JSON line with CRC-32.

    Builds the JSON without the ``c`` field, computes the CRC-32 of that
    string, then inserts ``,"c":"<crc>"}`` before the closing brace.
    """
    entryNoC = {k: v for k, v in entry.items() if k != "c" and v is not None}
    lineNoC = json.dumps(entryNoC, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    c = _crc32(lineNoC)
    return lineNoC[:-1] + f',"c":"{c}"}}'


def _parseEntry(line: str) -> dict[str, Any] | None:
    """Parse an outbox line, validating its CRC-32.

    Returns None if the line is malformed or has a bad CRC.
    """
    line = line.rstrip("\n")
    if not line:
        return None
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None

    c = entry.get("c")
    if c is None:
        return None

    # Recompute CRC on the line without the c field
    cIdx = line.rfind(',"c":')
    if cIdx < 0:
        return None
    lineNoC = line[:cIdx] + line[line.rfind("}", cIdx) :]
    # Actually, strip ",...c" part properly: find ",c":"..."} at end
    # Simpler: rebuild line without c from the parsed dict
    entryNoC = {k: v for k, v in entry.items() if k != "c"}
    lineNoC = json.dumps(entryNoC, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expectedC = _crc32(lineNoC)
    if c != expectedC:
        return None

    return entry


class Outbox:
    """The change log / outbox for a project.

    Records every change (document save, tree save, sidecar write) as a
    JSON Lines entry in ``<project>/umbra/outbox.jsonl``. Multiple edits
    to the same target collapse into a single record that keeps the first
    ``baseRev``/``baseSha`` and the latest ``sha``.
    """

    def __init__(self, projectPath: Path, deviceId: str, actorId: str) -> None:
        self._projectPath = projectPath
        self._deviceId = deviceId
        self._actorId = actorId
        self._outboxPath = umbraDir(projectPath) / OUTBOX_FILE
        self._syncDir = syncDir(projectPath)
        self._statePath = stateFile(projectPath)
        self._ackedPath = ackedFile(projectPath)
        self._seq = 0
        self._pending: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._loaded = False

    ##
    #  Loading / persistence
    ##

    def _ensureLoaded(self) -> None:
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        """Load existing outbox entries from disk, validating CRCs."""
        if not self._outboxPath.is_file():
            return
        try:
            with open(self._outboxPath, encoding="utf-8") as f:
                for line in f:
                    entry = _parseEntry(line)
                    if entry is None:
                        continue
                    targetKey = self._targetKey(entry)
                    self._pending[targetKey] = entry
                    if targetKey not in self._order:
                        self._order.append(targetKey)
                    self._seq = max(self._seq, int(entry.get("seq", 0)))
        except Exception:
            logger.exception("Could not load outbox")

    def _persist(self) -> None:
        """Atomically rewrite the whole outbox file."""
        self._syncDir.mkdir(parents=True, exist_ok=True)
        lines = []
        for key in self._order:
            entry = self._pending[key]
            lines.append(_serialiseEntry(entry))
        text = "".join(line + "\n" for line in lines)

        fd, tempPath = tempfile.mkstemp(dir=str(self._outboxPath.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tempPath, str(self._outboxPath))
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tempPath)
            raise

    def _loadAcked(self) -> dict[str, dict[str, str]]:
        """Load acked.json, mapping handle -> {rev, sha}."""
        if not self._ackedPath.is_file():
            return {}
        try:
            data = readJson(self._ackedPath)
            if isinstance(data, dict):
                return data  # type: ignore[return-value]
            return {}
        except Exception:
            logger.exception("Could not read acked.json")
            return {}

    def _saveState(self, state: dict[str, Any]) -> None:
        """Atomically write state.json."""
        writeJson(self._statePath, state)

    def loadState(self) -> dict[str, Any]:
        """Load state.json."""
        data = readJson(self._statePath, default={})
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
        return {}

    def saveState(self, state: dict[str, Any]) -> None:
        """Save state.json."""
        self._saveState(state)

    def saveAcked(self, acked: dict[str, dict[str, str]]) -> None:
        """Atomically write acked.json."""
        writeJson(self._ackedPath, acked)

    ##
    #  Public API
    ##

    def _targetKey(self, entry: dict[str, Any]) -> str:
        """Compute the collapse key for an entry."""
        op = entry.get("op", "")
        handle = entry.get("handle") or ""
        path = entry.get("path") or ""
        if op == OP_TREE_PUT:
            return "tree.put"
        if op == OP_SIDECAR_PUT:
            return f"sidecar.put:{path}"
        return f"{op}:{handle}"

    def record(self, op: str, handle: str | None = None, path: Path | None = None) -> None:
        """Record a change in the outbox.

        Args:
            op: The operation type (``doc.put``, ``doc.delete``,
                ``tree.put``, ``sidecar.put``).
            handle: The document handle, if applicable.
            path: The file path, if applicable.

        Multiple edits to the same target collapse into one record that
        keeps the first ``baseRev``/``baseSha`` and the latest ``sha``.

        """
        if op not in ALL_OPS:
            logger.warning("Unknown outbox op: %s", op)
            return

        self._ensureLoaded()

        targetKey = self._targetKey({
            "op": op,
            "handle": handle or "",
            "path": str(path) if path else "",
        })

        # Get baseRev/baseSha from acked.json
        acked = self._loadAcked()
        baseRev = None
        baseSha = None
        if handle and handle in acked:
            entry = acked[handle]
            baseRev = entry.get("rev")
            baseSha = entry.get("sha")

        # Compute current sha from the file on disk
        sha = None
        checkPath = path
        if checkPath is None and handle is not None:
            contentPath = self._projectPath / "content"
            checkPath = contentPath / f"{handle}.md"
        if checkPath is not None and checkPath.is_file():
            sha = _sha256File(checkPath)

        if targetKey in self._pending:
            # Collapse: keep first baseRev/baseSha, latest sha
            existing = self._pending[targetKey]
            entry: dict[str, Any] = {
                "seq": existing.get("seq", 0),
                "ts": existing.get("ts", _utcNow()),
                "deviceId": existing.get("deviceId", self._deviceId),
                "actorId": existing.get("actorId", self._actorId),
                "op": op,
            }
            if handle is not None:
                entry["handle"] = handle
            if path is not None:
                entry["path"] = str(path)
            # Keep first baseRev/baseSha
            entry["baseRev"] = existing.get("baseRev") or baseRev
            entry["baseSha"] = existing.get("baseSha") or baseSha
            # Latest sha
            entry["sha"] = sha if sha is not None else existing.get("sha")
            self._pending[targetKey] = entry
        else:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": _utcNow(),
                "deviceId": self._deviceId,
                "actorId": self._actorId,
                "op": op,
            }
            if handle is not None:
                entry["handle"] = handle
            if path is not None:
                entry["path"] = str(path)
            if baseRev is not None:
                entry["baseRev"] = baseRev
            if baseSha is not None:
                entry["baseSha"] = baseSha
            if sha is not None:
                entry["sha"] = sha
            self._pending[targetKey] = entry
            self._order.append(targetKey)

        self._persist()

    def queuedCount(self) -> int:
        """Return the number of pending outbox records."""
        self._ensureLoaded()
        return len(self._pending)

    def rebuild(self) -> list[str]:
        """Rebuild the outbox by comparing each synced file's SHA-256
        with ``acked.json``. Every file that differs gets a record.

        Returns the list of handles/paths that were added.
        """
        self._ensureLoaded()
        changed: list[str] = []
        acked = self._loadAcked()

        # Check all documents in content/
        contentPath = self._projectPath / "content"
        if contentPath.is_dir():
            for docFile in sorted(contentPath.glob("*.md")):
                handle = docFile.stem
                sha = _sha256File(docFile)
                ackedEntry = acked.get(handle, {})
                if ackedEntry.get("sha") != sha:
                    self.record(OP_DOC_PUT, handle=handle, path=docFile)
                    changed.append(handle)

        # Check all synced sidecar files
        for name in SYNCED_SIDECARS:
            path = umbraDir(self._projectPath) / name
            if path.is_file():
                sha = _sha256File(path)
                # Sidecars are keyed by path in acked
                ackedEntry = acked.get(str(path), {})
                if ackedEntry.get("sha") != sha:
                    self.record(OP_SIDECAR_PUT, path=path)
                    changed.append(str(path))

        self._persist()
        return changed


# Module-level singleton (bound to the current project)
_outbox: Outbox | None = None


def bindOutbox(projectPath: Path, deviceId: str, actorId: str) -> None:
    """Bind the outbox to a project and register its hook handlers."""
    global _outbox  # noqa: PLW0603
    _outbox = Outbox(projectPath, deviceId, actorId)
    # (Re)register hook handlers; they may have been cleared by tests
    register(DOCUMENT_SAVED, _onDocumentSaved)
    register(PROJECT_SAVED, _onProjectSaved)
    register(SIDECAR_WRITTEN, _onSidecarWritten)


def unbindOutbox() -> None:
    """Unbind the outbox from the current project and remove hook handlers."""
    global _outbox  # noqa: PLW0603
    _outbox = None


def outbox() -> Outbox | None:
    """Return the bound outbox instance, or None."""
    return _outbox


def _onDocumentSaved(handle: str, text: str) -> None:
    """Record a doc.put entry when a document is saved."""
    if _outbox is not None:
        contentPath = _outbox._projectPath / "content"  # noqa: SLF001
        docFile = contentPath / f"{handle}.md"
        _outbox.record(OP_DOC_PUT, handle=handle, path=docFile)


def _onProjectSaved(project: Any) -> None:
    """Record a tree.put entry when the project is saved."""
    if _outbox is not None:
        storagePath = _outbox._projectPath  # noqa: SLF001
        nwxFile = storagePath / "nwProject.nwx"
        _outbox.record(OP_TREE_PUT, path=nwxFile)


def _onSidecarWritten(path: Path) -> None:
    """Record a sidecar.put entry when a sidecar is written."""
    if _outbox is not None:
        _outbox.record(OP_SIDECAR_PUT, path=path)
