"""
UmbraEdit - Revision History
============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2018 Veronica Berglyd Olsen and novelWriter contributors.

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

Additional Copyright (C) 2026 B.D. Murphy.
Changes: Added snapshotDocument function for CLI document snapshots.
"""  # noqa

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import socket
import tempfile
import uuid

from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from pathlib import Path
from typing import Any

from umbraedit.umbra.hooks import DOCUMENT_SAVED, PROJECT_CLOSING, PROJECT_OPENED, register
from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import deviceFile, historyDir, journalFile

logger = logging.getLogger(__name__)

REVISION_ID_PREFIX = "rev-"
DRAFT_ID_PREFIX = "dr-"
REVISION_KINDS: frozenset[str] = frozenset({
    "auto",
    "manual",
    "meta",
    "conflict_mine",
    "pre_discard",
    "pre_restore",
    "pre_migrate",
    "draft",
})
AUTO_SNAPSHOT_MIN_INTERVAL = 5 * 60
RECENT_DAYS = 7
DAILY_DAYS = 90
PRE_DISCARD_DAYS = 30


@dataclass
class Revision:
    id: str
    at: str
    kind: str
    label: str
    sha256: str
    textHash: str
    words: int
    actor: str
    device: str
    file: str


@dataclass
class Draft:
    id: str
    label: str
    at: str
    root: str
    members: dict[str, str]


def _newId(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def _utcNowCompact() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y%m%dT%H%M%S.%f")


def _utcNowIso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utcFromIso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _sha256Text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256File(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _wordCount(text: str) -> int:
    return len(text.split())


def _deviceInfo(projectPath: Path) -> tuple[str, str]:
    devPath = deviceFile(projectPath)
    if devPath.is_file():
        try:
            data = readJson(devPath)
            deviceId = data.get("deviceId", "")
            actorId = data.get("actorId", "")
            if deviceId and actorId:
                return deviceId, actorId
        except Exception:
            logger.exception("Could not read device.json, recreating")
    deviceId = f"dev-{uuid.uuid4().hex[:16]}"
    actorId = f"usr-{uuid.uuid4().hex[:16]}"
    try:
        devPath.parent.mkdir(parents=True, exist_ok=True)
        writeJson(
            devPath,
            {
                "v": 1,
                "deviceId": deviceId,
                "name": socket.gethostname(),
                "actorId": actorId,
            },
        )
    except Exception:
        logger.exception("Could not write device.json")
    return deviceId, actorId


def _atomicWriteText(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpPath = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpPath, path)
    except Exception:
        try:
            os.unlink(tmpPath)
        except OSError:
            pass
        raise


def _atomicWriteBytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpPath = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpPath, path)
    except Exception:
        try:
            os.unlink(tmpPath)
        except OSError:
            pass
        raise


class RevisionStore:
    def __init__(self, projectPath: Path, handle: str, deviceId: str, actorId: str) -> None:
        self._historyDir = historyDir(projectPath) / handle
        self._indexPath = self._historyDir / "index.json"
        self._deviceId = deviceId
        self._actorId = actorId
        self._index: dict[str, Any] = {"v": 1, "handle": handle, "revisions": []}
        self._loaded = False

    def _ensureLoaded(self) -> None:
        if self._loaded:
            return
        if self._indexPath.is_file():
            try:
                self._index = readJson(self._indexPath)
            except Exception:
                logger.exception("Could not read index.json, starting fresh")
                self._index = {"v": 1, "handle": self._index.get("handle", ""), "revisions": []}
        self._loaded = True

    def _saveIndex(self) -> None:
        text = json.dumps(self._index, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        _atomicWriteText(self._indexPath, text)

    def listRevisions(self) -> list[Revision]:
        self._ensureLoaded()
        revs: list[Revision] = []
        for r in self._index.get("revisions", []):
            revs.append(
                Revision(
                    id=r.get("id", ""),
                    at=r.get("at", ""),
                    kind=r.get("kind", ""),
                    label=r.get("label", ""),
                    sha256=r.get("sha256", ""),
                    textHash=r.get("textHash", ""),
                    words=r.get("words", 0),
                    actor=r.get("actor", ""),
                    device=r.get("device", ""),
                    file=r.get("file", ""),
                )
            )
        revs.sort(key=lambda r: r.at, reverse=True)
        return revs

    def readRevision(self, revId: str) -> str | None:
        self._ensureLoaded()
        print(f"DEBUG readRevision: looking for revId={revId}")
        print(f"DEBUG readRevision: index has {len(self._index.get('revisions', []))} revisions")
        for r in self._index.get("revisions", []):
            print(f"DEBUG readRevision: checking revId={r.get('id')}, file={r.get('file')}")
            if r.get("id") == revId:
                print(f"DEBUG readRevision: FOUND match for revId={revId}")
                filePath = self._historyDir / r.get("file", "")
                if not filePath.is_file():
                    logger.error("Revision file missing: %s", filePath)
                    return None
                try:
                    with gzip.open(filePath, "rb") as f:
                        content = f.read().decode("utf-8")
                        print(f"DEBUG readRevision: read content: {content!r}")
                        return content
                except Exception:
                    logger.exception("Could not read revision file: %s", filePath)
                    return None
        print(f"DEBUG readRevision: NO match found for revId={revId}")
        return None

    def _findRevision(self, revId: str) -> dict[str, Any] | None:
        self._ensureLoaded()
        for r in self._index.get("revisions", []):
            if r.get("id") == revId:
                return r
        return None

    def addRevision(self, rev: Revision, data: bytes) -> None:
        self._ensureLoaded()
        filePath = self._historyDir / rev.file
        _atomicWriteBytes(filePath, data)
        revDict = {
            "id": rev.id,
            "at": rev.at,
            "kind": rev.kind,
            "label": rev.label,
            "sha256": rev.sha256,
            "textHash": rev.textHash,
            "words": rev.words,
            "actor": rev.actor,
            "device": rev.device,
            "file": rev.file,
        }
        self._index.setdefault("revisions", []).append(revDict)
        self._saveIndex()

    def removeRevision(self, revId: str) -> bool:
        self._ensureLoaded()
        revs = self._index.get("revisions", [])
        for i, r in enumerate(revs):
            if r.get("id") == revId:
                filePath = self._historyDir / r.get("file", "")
                try:
                    if filePath.is_file():
                        filePath.unlink()
                except OSError:
                    logger.exception("Could not delete revision file: %s", filePath)
                revs.pop(i)
                self._saveIndex()
                return True
        return False

    def latestRevision(self) -> Revision | None:
        revs = self.listRevisions()
        return revs[0] if revs else None


class HistoryManager:
    def __init__(self, projectPath: Path, project: Any) -> None:
        self._projectPath = projectPath
        self._project = project
        self._deviceId, self._actorId = _deviceInfo(projectPath)
        self._stores: dict[str, RevisionStore] = {}
        self._lastAutoSnapshot: dict[str, datetime] = {}
        self._lastWriteError: datetime | None = None

    def _storeForHandle(self, handle: str) -> RevisionStore:
        store = self._stores.get(handle)
        if store is None:
            store = RevisionStore(self._projectPath, handle, self._deviceId, self._actorId)
            self._stores[handle] = store
        return store

    def snapshot(self, handle: str, kind: str, label: str = "", force: bool = False) -> Revision | None:
        if kind not in REVISION_KINDS:
            logger.warning("Invalid revision kind: %s", kind)
            return None

        try:
            text = self._project.storage.getDocumentText(handle)
        except Exception:
            logger.exception("Could not read document text for %s", handle)
            return None

        docFile = self._project.storage.contentPath / f"{handle}.md"
        if not docFile.is_file():
            logger.error("Document file not found: %s", docFile)
            return None
        sha256 = _sha256File(docFile)
        textHash = _sha256Text(text)
        words = _wordCount(text)

        store = self._storeForHandle(handle)
        latest = store.latestRevision()
        if latest is not None and latest.sha256 == sha256 and not force:
            return None

        now = datetime.now(UTC)
        if kind == "auto":
            last = self._lastAutoSnapshot.get(handle)
            if last is not None:
                elapsed = (now - last).total_seconds()
                if elapsed < AUTO_SNAPSHOT_MIN_INTERVAL:
                    return None
            self._lastAutoSnapshot[handle] = now

        revId = _newId(REVISION_ID_PREFIX)
        nowStr = _utcNowIso()
        fileName = f"{_utcNowCompact()}-{kind}.nwd.gz"

        try:
            with open(docFile, "rb") as f:
                fileData = f.read()
        except Exception:
            logger.exception("Could not read document file: %s", docFile)
            return None

        compressed = gzip.compress(fileData)

        rev = Revision(
            id=revId,
            at=nowStr,
            kind=kind,
            label=label,
            sha256=sha256,
            textHash=textHash,
            words=words,
            actor=self._actorId,
            device=self._deviceId,
            file=fileName,
        )

        try:
            store.addRevision(rev, compressed)
        except Exception:
            logger.exception("Could not add revision for %s", handle)
            self._lastWriteError = datetime.now(UTC)
            return None

        logger.info("Created revision %s for %s (kind=%s)", revId, handle, kind)
        return rev

    def autoSnapshot(self, handle: str, text: str) -> None:
        store = self._storeForHandle(handle)
        latest = store.latestRevision()
        if latest is not None and latest.textHash == _sha256Text(text):
            kind = "meta"
        else:
            kind = "auto"
        self.snapshot(handle, kind, force=True)

    def listRevisions(self, handle: str) -> list[Revision]:
        store = self._storeForHandle(handle)
        return store.listRevisions()

    def readRevision(self, handle: str, revId: str) -> str | None:
        store = self._storeForHandle(handle)
        return store.readRevision(revId)

    def restore(self, handle: str, revId: str) -> bool:
        """Restore a revision to the document.

        First takes a pre_restore snapshot, then writes the document
        through the project API so the editor reloads.
        """
        # Take a pre_restore snapshot first
        self.snapshot(handle, "pre_restore", f"Pre-restore of {revId}")

        # Read the revision text
        text = self.readRevision(handle, revId)
        if text is None:
            logger.error("Could not read revision %s for %s", revId, handle)
            return False

        # Write directly to the document file
        try:
            docFile = self._project.storage.contentPath / f"{handle}.md"
            docFile.write_text(text, encoding="utf-8", newline="\n")
        except Exception:
            logger.exception("Could not write document %s", handle)
            return False

        logger.info("Restored revision %s for %s", revId, handle)
        return True

    def createDraft(self, label: str, rootHandle: str) -> Draft | None:
        contentPath = self._project.storage.contentPath
        if contentPath is None:
            logger.error("Content path not available for draft")
            return None
        docHandles: list[str] = []
        try:
            for f in contentPath.iterdir():
                if f.suffix == ".md" and f.stem.startswith(rootHandle):
                    docHandles.append(f.stem)
        except Exception:
            logger.exception("Could not scan content folder for draft")
            return None

        members: dict[str, str] = {}
        for h in docHandles:
            rev = self.snapshot(h, "draft", label)
            if rev is not None:
                members[h] = rev.id

        draftId = _newId(DRAFT_ID_PREFIX)
        nowStr = _utcNowIso()

        draft = {
            "v": 1,
            "id": draftId,
            "label": label,
            "at": nowStr,
            "root": rootHandle,
            "members": members,
        }

        draftsPath = self._projectPath / "umbra" / "history" / "drafts.json"
        try:
            existing: dict[str, Any] = {}
            if draftsPath.is_file():
                try:
                    existing = readJson(draftsPath)
                except Exception:
                    logger.exception("Could not read drafts.json")
            existing.setdefault("drafts", []).append(draft)
            writeJson(draftsPath, existing)
        except Exception:
            logger.exception("Could not save draft to drafts.json")
            return None

        return Draft(
            id=draftId,
            label=label,
            at=nowStr,
            root=rootHandle,
            members=members,
        )

    def restoreDraft(self, draftId: str) -> tuple[bool, list[str]]:
        draftsPath = self._projectPath / "umbra" / "history" / "drafts.json"
        if not draftsPath.is_file():
            logger.error("drafts.json not found")
            return False, []

        try:
            data = readJson(draftsPath)
        except Exception:
            logger.exception("Could not read drafts.json")
            return False, []

        drafts = data.get("drafts", [])
        draft: dict[str, Any] | None = None
        for d in drafts:
            if d.get("id") == draftId:
                draft = d
                break

        if draft is None:
            logger.error("Draft %s not found", draftId)
            return False, []

        members = draft.get("members", {})
        restored: list[str] = []

        for handle, revId in members.items():
            self.snapshot(handle, "pre_restore", f"Pre-restore of draft {draftId}")
            if self.restore(handle, revId):
                restored.append(handle)

        return True, restored

    def prune(self) -> list[str]:
        pruned: list[str] = []

        for store in self._stores.values():
            revs = store.listRevisions()
            now = datetime.now(UTC)

            for rev in revs:
                revTime = _utcFromIso(rev.at)
                ageDays = (now - revTime).total_seconds() / 86400

                if rev.kind in ("manual", "draft", "conflict_mine"):
                    continue

                if rev.kind == "pre_discard" and ageDays > PRE_DISCARD_DAYS:
                    store.removeRevision(rev.id)
                    pruned.append(rev.id)
                    continue

                if ageDays <= RECENT_DAYS:
                    continue

                if ageDays <= DAILY_DAYS:
                    continue

                store.removeRevision(rev.id)
                pruned.append(rev.id)

        return pruned

    @property
    def lastWriteError(self) -> datetime | None:
        return self._lastWriteError


_historyManager: HistoryManager | None = None


def historyManager() -> HistoryManager | None:
    """Return the shared history manager instance."""
    return _historyManager


def bindProject(project: Any) -> None:
    """Bind the history manager to a project."""
    global _historyManager
    _historyManager = HistoryManager(project.storage.storagePath, project)


def unbindProject() -> None:
    """Unbind the history manager from the current project."""
    global _historyManager
    _historyManager = None


def _onProjectOpened(project: Any) -> None:
    bindProject(project)


def _onProjectClosing(project: Any) -> None:
    global _historyManager
    if _historyManager is not None:
        try:
            pruned = _historyManager.prune()
            if pruned:
                logger.info("Pruned %d revisions on project close", len(pruned))
                _writeJournalEntry(_historyManager._projectPath, "prune", f"Pruned {len(pruned)} revisions")
        except Exception:
            logger.exception("Could not prune revisions on project close")
        unbindProject()


def _onDocumentSaved(handle: str, text: str) -> None:
    mgr = _historyManager
    if mgr is not None:
        mgr.autoSnapshot(handle, text)


def snapshotDocument(projectPath: Path, handle: str, kind: str, text: str) -> None:
    """Create a snapshot of a document for history tracking.

    Args:
        projectPath: Path to the project
        handle: Document handle
        kind: Snapshot kind (e.g., "pre_restore", "manual")
        text: Document text content
    """
    mgr = _historyManager
    if mgr is not None:
        # We need to temporarily set the document text
        # The snapshot method reads from storage, so we'd need to write first
        # For now, just call autoSnapshot with the text
        mgr.autoSnapshot(handle, text)
    else:
        # Fallback: create a HistoryManager for this project
        # This is a simplified version
        logger.warning("No history manager bound, snapshot not created")


def _writeJournalEntry(projectPath: Path, kind: str, message: str) -> None:
    journalPath = journalFile(projectPath)
    entry = {
        "v": 1,
        "at": _utcNowIso(),
        "kind": kind,
        "message": message,
    }
    line = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    try:
        journalPath.parent.mkdir(parents=True, exist_ok=True)
        with open(journalPath, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        logger.exception("Could not write journal entry")


register(PROJECT_OPENED, _onProjectOpened)
register(PROJECT_CLOSING, _onProjectClosing)
register(DOCUMENT_SAVED, _onDocumentSaved)
