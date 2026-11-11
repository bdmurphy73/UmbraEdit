"""
UmbraStore - Database tests
============================
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["alice", "bob", "charlie"])
def test_database_R1_account_create_and_get(tmp_path: Path, name: str) -> None:
    """R1: Account can be created and retrieved by ID and name."""
    from umbrastore.auth import hashToken, verifyToken
    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    db = Database(conn)
    accountId = ulid()
    token = "test-token-123"
    tokenHash = hashToken(token)
    createdAt = utcNow()

    db.createAccount(accountId, name, tokenHash, createdAt)
    db.commit()

    # Retrieve by ID
    row = db.getAccountById(accountId)
    assert row is not None
    assert row["id"] == accountId
    assert row["name"] == name
    assert verifyToken(token, row["tokenHash"])

    # Retrieve by name
    row2 = db.getAccountByName(name)
    assert row2 is not None
    assert row2["id"] == accountId

    # Verify token
    assert verifyToken(token, row["tokenHash"])
    assert not verifyToken("wrong-token", row["tokenHash"])

    db.close()


def test_database_R1_project_create_and_get(tmp_path: Path) -> None:
    """R1: Project can be created and retrieved."""
    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    db = Database(conn)
    projectId = ulid()
    name = "My Novel"
    createdAt = utcNow()

    db.createProject(projectId, name, createdAt)
    db.commit()

    row = db.getProject(projectId)
    assert row is not None
    assert row["id"] == projectId
    assert row["name"] == name
    assert row["createdAt"] == createdAt

    db.close()


def test_database_R1_file_upsert_and_get(tmp_path: Path) -> None:
    """R1: File record can be upserted and retrieved."""
    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    db = Database(conn)
    projectId = ulid()
    path = "content/3f9a1c.nwd"

    db.createProject(projectId, "Test", utcNow())
    db.upsertFile(projectId, path, "rev-abc", 0)
    db.commit()

    row = db.getFile(projectId, path)
    assert row is not None
    assert row["projectId"] == projectId
    assert row["path"] == path
    assert row["headRev"] == "rev-abc"
    assert row["deleted"] == 0

    # Mark deleted
    db.upsertFile(projectId, path, None, 1)
    db.commit()

    row2 = db.getFile(projectId, path)
    assert row2 is not None
    assert row2["headRev"] is None
    assert row2["deleted"] == 1

    db.close()


def test_database_R1_revision_create_and_get(tmp_path: Path) -> None:
    """R1: Revision can be created and retrieved."""
    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    db = Database(conn)
    projectId = ulid()
    path = "content/3f9a1c.nwd"

    db.createProject(projectId, "Test", utcNow())
    db.createRevision(
        revisionId="rev-001",
        projectId=projectId,
        path=path,
        parentRev=None,
        sha256="abc123",
        size=100,
        actorId="usr-1",
        deviceId="dev-1",
        at=utcNow(),
        blobFile="blobs/ab/abc123",
    )
    db.commit()

    row = db.getRevision("rev-001")
    assert row is not None
    assert row["id"] == "rev-001"
    assert row["sha256"] == "abc123"
    assert row["size"] == 100

    # List revisions
    revs = db.listRevisions(projectId, path)
    assert len(revs) == 1
    assert revs[0]["id"] == "rev-001"

    db.close()


def test_database_R1_event_create_and_changes(tmp_path: Path) -> None:
    """R1: Event can be created and changes listed."""
    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    db = Database(conn)
    projectId = ulid()

    db.createProject(projectId, "Test", utcNow())
    db.createEvent(projectId, utcNow(), "put", "content/a.md", "rev-1", "usr-1", "dev-1")
    db.createEvent(projectId, utcNow(), "put", "content/b.md", "rev-2", "usr-1", "dev-1")
    db.createEvent(projectId, utcNow(), "delete", "content/c.md", None, "usr-1", "dev-1")
    db.commit()

    # List all changes
    changes = db.listChanges(projectId, None, 100)
    assert len(changes) == 3
    assert changes[0]["op"] == "put"
    assert changes[1]["op"] == "put"
    assert changes[2]["op"] == "delete"

    # List with cursor
    changes2 = db.listChanges(projectId, changes[0]["seq"], 100)
    assert len(changes2) == 2

    # Count events
    count = db.countEvents(projectId)
    assert count == 3

    db.close()


def test_database_R2_blobs_atomic_write(tmp_path: Path) -> None:
    """R2: Blob storage writes are atomic and content-addressed."""
    from umbrastore.blobs import BlobStore

    store = BlobStore(tmp_path)
    data = b"Hello, UmbraStore!"
    sha256 = store.store(data)

    assert len(sha256) == 64
    assert store.exists(sha256)

    retrieved = store.retrieve(sha256)
    assert retrieved == data

    # Verify blob file layout
    blobPath = store.blobsDir / sha256[:2] / sha256
    assert blobPath.is_file()

    # Idempotent: storing same data returns same SHA
    sha256b = store.store(data)
    assert sha256 == sha256b

    # Verify
    assert store.verify(sha256)


def test_database_R2_blob_verify_detects_corruption(tmp_path: Path) -> None:
    """R2: verify() detects corrupted blobs."""
    from umbrastore.blobs import BlobStore

    store = BlobStore(tmp_path)
    data = b"Test data for verification"
    sha256 = store.store(data)

    # Corrupt the blob
    blobPath = store.blobsDir / sha256[:2] / sha256
    blobPath.write_bytes(b"corrupted data")

    assert not store.verify(sha256)


def test_database_R3_event_ordering(tmp_path: Path) -> None:
    """R3: Events are ordered by seq."""
    import time

    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    db = Database(conn)
    projectId = ulid()

    db.createProject(projectId, "Test", utcNow())

    # Create events with slight delay to ensure ordering
    for i in range(5):
        db.createEvent(
            projectId,
            utcNow(),
            "put",
            f"content/file{i}.md",
            f"rev-{i}",
            "usr-1",
            "dev-1",
        )
        time.sleep(0.01)
    db.commit()

    changes = db.listChanges(projectId, None, 100)
    assert len(changes) == 5
    # Verify seq is strictly increasing
    seqs = [row["seq"] for row in changes]
    assert seqs == sorted(seqs)

    db.close()


def test_auth_hash_verify(tmp_path: Path) -> None:
    """Auth: hashToken and verifyToken work correctly."""
    from umbrastore.auth import hashToken, verifyToken

    token = "my-secret-token"
    stored = hashToken(token)
    assert verifyToken(token, stored)
    assert not verifyToken("wrong-token", stored)

    # Format is salt:hash
    parts = stored.split(":")
    assert len(parts) == 2
    assert len(parts[0]) == 32  # 16 bytes hex
    assert len(parts[1]) == 64  # SHA-256 hex


def test_ulid_format(tmp_path: Path) -> None:
    """ULID: generated IDs are 26 chars and unique."""
    from umbrastore.database import ulid

    id1 = ulid()
    id2 = ulid()
    assert len(id1) == 26
    assert len(id2) == 26
    assert id1 != id2
