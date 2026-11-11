"""
UmbraStore - Database layer
===========================

SQLite database with WAL mode and synchronous=FULL.
Manages schema, connections, and all data access for accounts,
projects, files, revisions, and events.
"""  # noqa

from __future__ import annotations

import sqlite3

from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tokenHash TEXT NOT NULL,
    createdAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    createdAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file (
    projectId TEXT NOT NULL,
    path TEXT NOT NULL,
    headRev TEXT,
    deleted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (projectId, path)
);

CREATE TABLE IF NOT EXISTS revision (
    id TEXT PRIMARY KEY,
    projectId TEXT NOT NULL,
    path TEXT NOT NULL,
    parentRev TEXT,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    actorId TEXT NOT NULL,
    deviceId TEXT NOT NULL,
    at TEXT NOT NULL,
    blobFile TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    projectId TEXT NOT NULL,
    at TEXT NOT NULL,
    op TEXT NOT NULL,
    path TEXT NOT NULL,
    rev TEXT,
    actorId TEXT,
    deviceId TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_project ON file(projectId);
CREATE INDEX IF NOT EXISTS idx_revision_project_path ON revision(projectId, path);
CREATE INDEX IF NOT EXISTS idx_revision_sha ON revision(sha256);
CREATE INDEX IF NOT EXISTS idx_event_project ON event(projectId);
CREATE INDEX IF NOT EXISTS idx_event_seq ON event(seq);
"""


def connect(dataDir: Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database at <dataDir>/umbrastore.db.

    Configures WAL journal mode and synchronous=FULL for crash safety.
    Returns a connection with row_factory set to sqlite3.Row.

    Uses check_same_thread=False so the connection can be used across
    threads (FastAPI runs sync dependencies in worker threads).
    """
    dataDir.mkdir(parents=True, exist_ok=True)
    dbPath = dataDir / "umbrastore.db"
    conn = sqlite3.connect(str(dbPath), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def initDatabase(dataDir: Path) -> None:
    """Initialise the database schema if not already present."""
    conn = connect(dataDir)
    conn.close()


def utcNow() -> str:
    """Return current UTC time as ISO 8601 with Z, seconds precision."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ulid() -> str:
    """Generate a ULID-like identifier (26 chars, crockford base32).

    Uses time-based first 10 chars + 16 random chars.
    """
    import secrets

    from datetime import UTC, datetime

    # Crockford base32 alphabet (no ambiguous chars: I, L, O, U)
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    # 48-bit timestamp (milliseconds since epoch)
    tsMs = int(datetime.now(UTC).timestamp() * 1000)
    tsChars = ""
    for _ in range(10):
        tsChars = alphabet[tsMs % 32] + tsChars
        tsMs //= 32

    # 80 bits of randomness encoded as 16 base32 chars
    randBytes = secrets.token_bytes(10)
    # Combine bytes into a big integer, then encode in base32
    randInt = int.from_bytes(randBytes, "big")
    randChars = ""
    for _ in range(16):
        randChars = alphabet[randInt % 32] + randChars
        randInt //= 32

    return tsChars + randChars


class Database:
    """Wrapper around a SQLite connection with helper methods."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        return self._conn.executemany(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def rowFactory(self, factory: Any) -> None:
        self._conn.row_factory = factory

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def createAccount(self, accountId: str, name: str, tokenHash: str, createdAt: str) -> None:
        self._conn.execute(
            "INSERT INTO account (id, name, tokenHash, createdAt) VALUES (?, ?, ?, ?)",
            (accountId, name, tokenHash, createdAt),
        )

    def getAccountById(self, accountId: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT id, name, tokenHash, createdAt FROM account WHERE id = ?",
            (accountId,),
        )
        return cur.fetchone()

    def getAccountByName(self, name: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT id, name, tokenHash, createdAt FROM account WHERE name = ?",
            (name,),
        )
        return cur.fetchone()

    def createProject(self, projectId: str, name: str, createdAt: str) -> None:
        self._conn.execute(
            "INSERT INTO project (id, name, createdAt) VALUES (?, ?, ?)",
            (projectId, name, createdAt),
        )

    def getProject(self, projectId: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT id, name, createdAt FROM project WHERE id = ?",
            (projectId,),
        )
        return cur.fetchone()

    def getFile(self, projectId: str, path: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT projectId, path, headRev, deleted FROM file WHERE projectId = ? AND path = ?",
            (projectId, path),
        )
        return cur.fetchone()

    def upsertFile(
        self,
        projectId: str,
        path: str,
        headRev: str | None,
        deleted: int,
    ) -> None:
        self._conn.execute(
            "INSERT INTO file (projectId, path, headRev, deleted) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(projectId, path) DO UPDATE SET "
            "headRev = excluded.headRev, deleted = excluded.deleted",
            (projectId, path, headRev, deleted),
        )

    def createRevision(
        self,
        revisionId: str,
        projectId: str,
        path: str,
        parentRev: str | None,
        sha256: str,
        size: int,
        actorId: str,
        deviceId: str,
        at: str,
        blobFile: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO revision "
            "(id, projectId, path, parentRev, sha256, size, actorId, deviceId, at, blobFile) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                revisionId,
                projectId,
                path,
                parentRev,
                sha256,
                size,
                actorId,
                deviceId,
                at,
                blobFile,
            ),
        )

    def getRevision(self, revisionId: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT id, projectId, path, parentRev, sha256, size, actorId, deviceId, at, blobFile "
            "FROM revision WHERE id = ?",
            (revisionId,),
        )
        return cur.fetchone()

    def getHeadRevision(self, projectId: str, path: str) -> sqlite3.Row | None:
        fileRow = self.getFile(projectId, path)
        if fileRow is None or fileRow["headRev"] is None:
            return None
        return self.getRevision(fileRow["headRev"])

    def listRevisions(self, projectId: str, path: str) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT id, projectId, path, parentRev, sha256, size, actorId, deviceId, at, blobFile "
            "FROM revision WHERE projectId = ? AND path = ? ORDER BY at ASC",
            (projectId, path),
        )
        return list(cur.fetchall())

    def createEvent(
        self,
        projectId: str,
        at: str,
        op: str,
        path: str,
        rev: str | None,
        actorId: str | None,
        deviceId: str | None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO event (projectId, at, op, path, rev, actorId, deviceId) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (projectId, at, op, path, rev, actorId, deviceId),
        )
        return cur.lastrowid or 0

    def listChanges(
        self,
        projectId: str,
        sinceSeq: int | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        if sinceSeq is not None:
            cur = self._conn.execute(
                "SELECT seq, projectId, at, op, path, rev, actorId, deviceId "
                "FROM event WHERE projectId = ? AND seq > ? "
                "ORDER BY seq ASC LIMIT ?",
                (projectId, sinceSeq, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT seq, projectId, at, op, path, rev, actorId, deviceId "
                "FROM event WHERE projectId = ? ORDER BY seq ASC LIMIT ?",
                (projectId, limit),
            )
        return list(cur.fetchall())

    def verifyBlobs(self, blobsDir: Path) -> list[tuple[str, str]]:
        """Verify every revision's blob SHA-256 matches its blobFile path.

        Returns a list of (revisionId, expectedSha) for mismatches.
        """
        mismatches: list[tuple[str, str]] = []
        cur = self._conn.execute("SELECT id, sha256, blobFile FROM revision")
        for row in cur.fetchall():
            revId = row["id"]
            expectedSha = row["sha256"]
            blobFile = row["blobFile"]
            # blobFile is like "blobs/ab/abc123", relative to dataDir.
            # blobsDir is dataDir/blobs, so strip the "blobs/" prefix.
            if blobFile.startswith("blobs/"):
                relPath = blobFile[6:]
            else:
                relPath = blobFile
            blobPath = blobsDir / relPath
            if not blobPath.is_file():
                mismatches.append((revId, expectedSha))
                continue
            import hashlib

            h = hashlib.sha256()
            with open(blobPath, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            actualSha = h.hexdigest()
            if actualSha != expectedSha:
                mismatches.append((revId, expectedSha))
        return mismatches

    def countEvents(self, projectId: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) AS c FROM event WHERE projectId = ?",
            (projectId,),
        )
        row = cur.fetchone()
        return row["c"] if row else 0
