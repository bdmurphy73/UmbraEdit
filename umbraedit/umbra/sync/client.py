"""
UmbraEdit - Sync Client
=======================

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

from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from pathlib import Path
from typing import Any

import httpx

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.merge import MergeResult, merge_units
from umbraedit.umbra.paths import (
    ackedFile,
    stateFile,
    umbraDir,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTBOX_FILE = "outbox.jsonl"

OP_DOC_PUT = "doc.put"
OP_DOC_DELETE = "doc.delete"
OP_TREE_PUT = "tree.put"
OP_SIDECAR_PUT = "sidecar.put"

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

# Sync state keys
STATE_LAST_PUSH = "lastPushAt"
STATE_LAST_PULL = "lastPullAt"
STATE_LAST_SUCCESS = "lastSuccessAt"
STATE_RETRY_BACKOFF = "retryBackoffSeconds"

# Default retry backoff: doubles each failure, max 300s
RETRY_INITIAL = 2
RETRY_MAX = 300

# Stale pull threshold (minutes) - overridable by setting
STALE_DEFAULT_MINUTES = 60


def _utcNow() -> str:
    """Return current UTC time as ISO 8601 with Z, seconds precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256Text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256File(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _atomicWriteJson(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON to a file (sorted keys, compact, trailing newline)."""
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


# ---------------------------------------------------------------------------
# Outbox access (thin wrapper around the outbox module)
# ---------------------------------------------------------------------------
def _loadOutboxEntries(projectPath: Path) -> list[dict[str, Any]]:
    """Load all outbox entries from outbox.jsonl, sorted by seq."""
    outboxPath = umbraDir(projectPath) / OUTBOX_FILE
    if not outboxPath.is_file():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with open(outboxPath, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)  # type: ignore[arg-type]
                except json.JSONDecodeError:
                    logger.exception("Skipping malformed outbox line: %r", line[:80])
    except Exception:
        logger.exception("Could not read outbox")
    entries.sort(key=lambda e: int(e.get("seq", 0)))
    return entries


def _loadAcked(projectPath: Path) -> dict[str, dict[str, str]]:
    """Load acked.json mapping handle -> {rev, sha}."""
    path = ackedFile(projectPath)
    if not path.is_file():
        return {}
    data = readJson(path, default={})
    if isinstance(data, dict):
        return data  # type: ignore[return-value]
    return {}


def _saveAcked(projectPath: Path, acked: dict[str, dict[str, str]]) -> None:
    """Atomically write acked.json."""
    writeJson(ackedFile(projectPath), acked)


def _removeOutboxEntries(projectPath: Path, keysToRemove: set[str]) -> None:
    """Remove entries from outbox.jsonl whose target key is in keysToRemove."""
    outboxPath = umbraDir(projectPath) / OUTBOX_FILE
    if not outboxPath.is_file():
        return

    entries: list[dict[str, Any]] = []
    try:
        with open(outboxPath, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _targetKey(entry) not in keysToRemove:
                    entries.append(entry)
    except Exception:
        logger.exception("Could not read outbox for removal")
        return

    # Rewrite atomically
    text = "".join(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for e in entries)
    outboxPath.write_text(text, encoding="utf-8", newline="\n")


def _targetKey(entry: dict[str, Any]) -> str:
    """Compute the collapse key for an outbox entry."""
    op = entry.get("op", "")
    handle = entry.get("handle") or ""
    path = entry.get("path") or ""
    if op == OP_TREE_PUT:
        return "tree.put"
    if op == OP_SIDECAR_PUT:
        return f"sidecar.put:{path}"
    return f"{op}:{handle}"


# ---------------------------------------------------------------------------
# Sync Client
# ---------------------------------------------------------------------------


class SyncClient:
    """Qt-free sync client for UmbraStore.

    Provides push(), pull(), and syncOnce() operations. All I/O uses httpx
    and is safe to call from a background QThread.
    """

    def __init__(
        self,
        projectPath: Path,
        storeUrl: str,
        token: str,
        projectId: str,
        deviceId: str,
        actorId: str,
    ) -> None:
        self._projectPath = projectPath
        self._storeUrl = storeUrl.rstrip("/")
        self._token = token
        self._projectId = projectId
        self._deviceId = deviceId
        self._actorId = actorId
        self._client = httpx.Client(base_url=self._storeUrl, timeout=30.0)
        self._client.headers["Authorization"] = f"Bearer {token}"
        self._client.headers["X-Device"] = deviceId
        self._client.headers["X-Actor"] = actorId

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    # -- Push ----------------------------------------------------------------

    def push(self) -> dict[str, Any]:
        """Push all pending outbox records to the server.

        Returns a dict with keys: pushed, conflicts, errors.
        """
        entries = _loadOutboxEntries(self._projectPath)
        if not entries:
            return {"pushed": 0, "conflicts": 0, "errors": 0}

        acked = _loadAcked(self._projectPath)
        pushed = 0
        conflicts = 0
        errors = 0
        removedKeys: set[str] = set()

        for entry in entries:
            op = entry.get("op", "")
            handle = entry.get("handle", "")
            path = entry.get("path", "")
            baseRev = entry.get("baseRev")
            baseSha = entry.get("baseSha")
            sha = entry.get("sha")

            try:
                if op == OP_DOC_PUT:
                    result = self._pushDoc(entry, handle, path, baseRev, baseSha, sha, acked)
                elif op == OP_TREE_PUT:
                    result = self._putFile(path, baseRev, "tree.put")
                elif op == OP_SIDECAR_PUT:
                    result = self._putFile(path, baseRev, "sidecar.put")
                elif op == OP_DOC_DELETE:
                    result = self._deleteFile(handle, baseRev)
                else:
                    logger.warning("Unknown op in outbox: %s", op)
                    errors += 1
                    continue

                if result == "pushed":
                    pushed += 1
                    removedKeys.add(_targetKey(entry))
                    # Update acked - re-read rev/sha from entry (may have been updated by _pushDoc)
                    entryRev = entry.get("rev", "")
                    entrySha = entry.get("sha", "")
                    if op == OP_DOC_PUT and handle:
                        acked[handle] = {"rev": entryRev, "sha": entrySha}
                    elif op in (OP_TREE_PUT, OP_SIDECAR_PUT) and path:
                        acked[path] = {"rev": entryRev, "sha": entrySha}
                elif result == "conflict":
                    conflicts += 1
                elif result == "error":
                    errors += 1
            except Exception:
                logger.exception("Push failed for entry %s", entry.get("seq"))
                errors += 1

        if removedKeys:
            _saveAcked(self._projectPath, acked)
            _removeOutboxEntries(self._projectPath, removedKeys)

        return {"pushed": pushed, "conflicts": conflicts, "errors": errors}

    def _pushDoc(
        self,
        entry: dict[str, Any],
        handle: str,
        path: str,
        baseRev: str | None,
        baseSha: str | None,
        sha: str | None,
        acked: dict[str, dict[str, str]],
    ) -> str:
        """Push a single document change. Returns 'pushed', 'conflict', or 'error'."""
        docFile = self._projectPath / "content" / f"{handle}.md"
        if not docFile.is_file():
            return "error"

        currentText = docFile.read_text(encoding="utf-8")
        currentSha = _sha256Text(currentText)

        headers: dict[str, str] = {}
        if baseRev:
            headers["If-Match"] = baseRev

        try:
            resp = self._client.put(
                f"/v1/projects/{self._projectId}/files/content/{handle}.md",
                content=currentText,
                headers=headers,
            )
        except httpx.RequestError:
            logger.exception("Push request failed for %s", handle)
            return "error"

        if resp.status_code == 200:
            data = resp.json()
            newRev = data.get("rev", "")
            newSha = data.get("sha256", currentSha)
            entry["rev"] = newRev
            entry["sha"] = newSha
            return "pushed"

        if resp.status_code == 409:
            # Conflict - need to merge
            body = resp.json()
            details = body.get("error", {}).get("details", {})
            headRev = details.get("headRev", "")

            # Fetch head content from server
            try:
                headResp = self._client.get(f"/v1/projects/{self._projectId}/files/content/{handle}.md?rev={headRev}")
                if headResp.status_code != 200:
                    return "error"
                headText = headResp.text
            except httpx.RequestError:
                return "error"

            # Get base content from history revision if available
            baseText = self._getBaseText(handle, baseRev)

            # Three-way merge
            result = merge_units(baseText, currentText, headText)

            if not result.conflicts:
                # Auto-merge succeeded - write merged file locally
                mergedText = self._unitsToText(result.units)
                docFile.write_text(mergedText, encoding="utf-8", newline="\n")

                # Push merged result with head as If-Match
                try:
                    resp2 = self._client.put(
                        f"/v1/projects/{self._projectId}/files/content/{handle}.md",
                        content=mergedText,
                        headers={"If-Match": headRev},
                    )
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        entry["rev"] = data2.get("rev", "")
                        entry["sha"] = data2.get("sha256", _sha256Text(mergedText))
                        # Record as merged conflict
                        self._recordConflict(handle, baseRev or "", headRev, result)
                        return "pushed"
                    return "error"
                except httpx.RequestError:
                    return "error"
            else:
                # Unresolved conflicts - store conflict record
                self._recordConflict(handle, baseRev or "", headRev, result)
                return "conflict"

        # Other error
        return "error"

    def _putFile(self, path: str, baseRev: str | None, op: str) -> str:
        """Push a file (tree or sidecar). Returns 'pushed', 'conflict', or 'error'."""
        filePath = Path(path)
        if not filePath.is_file():
            # Try relative to project root
            filePath = self._projectPath / path
        if not filePath.is_file():
            return "error"

        content = filePath.read_bytes()
        headers: dict[str, str] = {}
        if baseRev:
            headers["If-Match"] = baseRev

        try:
            resp = self._client.put(
                f"/v1/projects/{self._projectId}/files/{path}",
                content=content,
                headers=headers,
            )
        except httpx.RequestError:
            return "error"

        if resp.status_code == 200:
            resp.json()
            return "pushed"

        if resp.status_code == 409:
            body = resp.json()
            details = body.get("error", {}).get("details", {})
            headRev = details.get("headRev", "")
            # For tree/sidecar conflicts, store as conflict
            self._recordFileConflict(path, baseRev or "", headRev, op)
            return "conflict"

        return "error"

    def _deleteFile(self, handle: str, baseRev: str | None) -> str:
        """Delete a document file on the server."""
        headers: dict[str, str] = {}
        if baseRev:
            headers["If-Match"] = baseRev

        try:
            resp = self._client.delete(
                f"/v1/projects/{self._projectId}/files/content/{handle}.md",
                headers=headers,
            )
        except httpx.RequestError:
            return "error"

        if resp.status_code in (204, 200):
            return "pushed"
        if resp.status_code == 409:
            return "conflict"
        return "error"

    # -- Pull ----------------------------------------------------------------

    def pull(self) -> dict[str, Any]:
        """Pull remote changes since last pull cursor.

        Returns dict with keys: pulled, applied, deferred, errors.
        """
        state = self._loadState()
        cursor = state.get("cursor", "")

        try:
            params: dict[str, str | int] = {"limit": 500}
            if cursor:
                params["since"] = cursor

            resp = self._client.get(f"/v1/projects/{self._projectId}/changes", params=params)
        except httpx.RequestError:
            logger.exception("Pull request failed")
            return {"pulled": 0, "applied": 0, "deferred": 0, "errors": 1}

        if resp.status_code != 200:
            return {"pulled": 0, "applied": 0, "deferred": 0, "errors": 1}

        data = resp.json()
        items = data.get("items", [])
        nextCursor = data.get("next", "")

        applied = 0
        deferred = 0

        for item in items:
            op = item.get("op", "")
            path = item.get("path", "")
            rev = item.get("rev", "")

            if op == "put" and path.startswith("content/") and path.endswith(".md"):
                handle = path[len("content/") : -len(".md")]
                # Check if user is typing (defer if key pressed in last 800ms)
                if self._isUserTyping():
                    deferred += 1
                    continue
                result = self._applyDocPull(handle, path, rev)
                if result == "applied":
                    applied += 1
            elif op == "put" and path == "nwProject.nwx":
                # Tree change - structural merge
                result = self._applyTreePull(rev)
                if result == "applied":
                    applied += 1
            elif op == "put" and path in SYNCED_SIDECARS:
                result = self._applySidecarPull(path, rev)
                if result == "applied":
                    applied += 1

        if nextCursor:
            state["cursor"] = nextCursor
        state["lastPullAt"] = _utcNow()
        self._saveState(state)

        return {"pulled": len(items), "applied": applied, "deferred": deferred, "errors": 0}

    def _isUserTyping(self) -> bool:
        """Check if the user has been typing recently (within 800ms).

        This is checked via the GUI thread; when called from the sync worker
        thread we return False (no GUI available) so pulls are not deferred.
        The GUI worker thread should override this check.
        """
        return False

    def _loadState(self) -> dict[str, Any]:
        data = readJson(stateFile(self._projectPath), default={})
        if isinstance(data, dict):
            return data
        return {}

    def _saveState(self, state: dict[str, Any]) -> None:
        writeJson(stateFile(self._projectPath), state)

    def _getBaseText(self, handle: str, baseRev: str | None) -> str:
        """Get base document text from history revision or fetch from server."""
        # Try local history first
        if baseRev:
            from umbraedit.umbra.history import historyManager

            mgr = historyManager()
            if mgr is not None:
                text = mgr.readRevision(handle, baseRev)
                if text is not None:
                    return text

        # Fallback: current file content
        docFile = self._projectPath / "content" / f"{handle}.md"
        if docFile.is_file():
            return docFile.read_text(encoding="utf-8")
        return ""

    def _unitsToText(self, units: list[Any]) -> str:
        """Convert merged units back to text."""
        parts: list[str] = []
        for unit in units:
            lines = unit.lines if hasattr(unit, "lines") else [str(unit)]
            parts.append("\n".join(lines))
        return "\n".join(parts)

    def _recordConflict(self, handle: str, baseRev: str, theirsRev: str, result: MergeResult) -> None:
        """Record a document conflict in conflicts.json."""
        from umbraedit.umbra.sync.conflicts import ConflictsStore

        store = ConflictsStore(self._projectPath)
        units = [
            {
                "kind": c.kind,
                "baseText": "\n".join(c.base.lines) if c.base else "",
                "oursText": "\n".join(c.ours.lines) if c.ours else "",
                "theirsText": "\n".join(c.theirs.lines) if c.theirs else "",
            }
            for c in result.conflicts
        ]
        store.add_conflict(handle, baseRev, theirsRev, units)

    def _recordFileConflict(self, path: str, baseRev: str, theirsRev: str, op: str) -> None:
        """Record a file conflict (tree/sidecar)."""
        from umbraedit.umbra.sync.conflicts import ConflictsStore

        store = ConflictsStore(self._projectPath)
        store.add_file_conflict(path, baseRev, theirsRev, op)

    def _applyDocPull(self, handle: str, path: str, rev: str) -> str:
        """Apply a pulled document change locally."""
        try:
            resp = self._client.get(f"/v1/projects/{self._projectId}/files/{path}?rev={rev}")
            if resp.status_code != 200:
                return "error"
            theirText = resp.text
        except httpx.RequestError:
            return "error"

        docFile = self._projectPath / "content" / f"{handle}.md"
        if docFile.is_file():
            ourText = docFile.read_text(encoding="utf-8")
            # Simple case: if ours equals theirs, nothing to do
            if ourText == theirText:
                return "applied"
            # Otherwise, theirs wins (pull overwrites local)
            docFile.write_text(theirText, encoding="utf-8", newline="\n")
        else:
            docFile.write_text(theirText, encoding="utf-8", newline="\n")

        return "applied"

    def _applyTreePull(self, rev: str) -> str:
        """Apply a pulled tree (project XML) change."""
        try:
            resp = self._client.get(f"/v1/projects/{self._projectId}/files/nwProject.nwx?rev={rev}")
            if resp.status_code != 200:
                return "error"
            theirXml = resp.content
        except httpx.RequestError:
            return "error"

        nwxFile = self._projectPath / "nwProject.nwx"
        if nwxFile.is_file():
            ourXml = nwxFile.read_bytes()
            if ourXml == theirXml:
                return "applied"
            nwxFile.write_bytes(theirXml)
        else:
            nwxFile.write_bytes(theirXml)

        return "applied"

    def _applySidecarPull(self, path: str, rev: str) -> str:
        """Apply a pulled sidecar file change."""
        try:
            resp = self._client.get(f"/v1/projects/{self._projectId}/files/{path}?rev={rev}")
            if resp.status_code != 200:
                return "error"
            theirData = resp.content
        except httpx.RequestError:
            return "error"

        sidecarPath = self._projectPath / "umbra" / path
        if sidecarPath.is_file():
            ourData = sidecarPath.read_bytes()
            if ourData == theirData:
                return "applied"
            sidecarPath.write_bytes(theirData)
        else:
            sidecarPath.write_bytes(theirData)

        return "applied"

    # -- Sync Once -----------------------------------------------------------

    def syncOnce(self) -> dict[str, Any]:
        """Run one push and one pull cycle.

        Returns combined results.
        """
        pushResult = self.push()
        pullResult = self.pull()
        state = self._loadState()
        state["lastSuccessAt"] = _utcNow()
        state["retryBackoffSeconds"] = RETRY_INITIAL
        self._saveState(state)
        return {"push": pushResult, "pull": pullResult}

    def isReachable(self) -> bool:
        """Check if the server is reachable."""
        try:
            resp = self._client.get("/v1/health", timeout=5.0)
            return resp.status_code == 200
        except httpx.RequestError:
            return False


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def createClient(
    projectPath: Path,
    storeUrl: str,
    token: str,
    projectId: str,
    deviceId: str,
    actorId: str,
) -> SyncClient:
    """Create a SyncClient instance."""
    return SyncClient(
        projectPath=projectPath,
        storeUrl=storeUrl,
        token=token,
        projectId=projectId,
        deviceId=deviceId,
        actorId=actorId,
    )
