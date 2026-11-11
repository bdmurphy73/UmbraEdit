"""
UmbraStore - CLI tests
=======================
"""  # noqa

from __future__ import annotations

import contextlib
import io
import zipfile

from contextlib import redirect_stdout
from pathlib import Path

import pytest


def test_cli_R2_add_account_prints_token(tmp_path: Path) -> None:
    """R2: add-account creates account and prints token."""
    from umbrastore.cli import buildParser

    dataDir = tmp_path / "data"
    parser = buildParser()
    args = parser.parse_args(["add-account", "--data", str(dataDir), "--name", "test-user"])

    f = io.StringIO()
    with redirect_stdout(f):
        result = args.func(args)

    assert result == 0
    token = f.getvalue().strip()
    assert len(token) > 0

    # Verify account was created by checking database
    from umbrastore.database import Database, connect, initDatabase

    initDatabase(dataDir)
    conn = connect(dataDir)
    db = Database(conn)
    account = db.getAccountByName("test-user")
    assert account is not None
    db.close()


def test_cli_R2_backup_creates_zip(tmp_path: Path) -> None:
    """R2: backup creates a zip file with database and blobs."""
    from umbrastore.auth import generateToken, hashToken
    from umbrastore.cli import buildParser
    from umbrastore.database import Database, connect, initDatabase, ulid, utcNow

    dataDir = tmp_path / "data"
    outputZip = tmp_path / "backup.zip"

    # First create some data
    initDatabase(dataDir)
    conn = connect(dataDir)
    db = Database(conn)

    accountId = ulid()
    token = generateToken()
    db.createAccount(accountId, "backup-test", hashToken(token), utcNow())
    db.createProject("proj-1", "Backup Project", utcNow())
    db.commit()
    db.close()

    # Run backup
    parser = buildParser()
    args = parser.parse_args(["backup", "--data", str(dataDir), "--output", str(outputZip)])

    f = io.StringIO()
    with redirect_stdout(f):
        result = args.func(args)

    assert result == 0
    assert outputZip.is_file()

    # Verify zip contents
    with zipfile.ZipFile(str(outputZip)) as zf:
        names = zf.namelist()
        assert "umbrastore.db" in names


def test_cli_R2_verify_ok(tmp_path: Path) -> None:
    """R2: verify passes when all blobs are intact."""
    from umbrastore.blobs import BlobStore
    from umbrastore.cli import buildParser
    from umbrastore.database import Database, connect, initDatabase, utcNow

    dataDir = tmp_path / "data"
    initDatabase(dataDir)

    conn = connect(dataDir)
    db = Database(conn)
    dataDir / "blobs"

    db.createProject("proj-1", "Verify Test", utcNow())
    blobs = BlobStore(dataDir)
    sha256 = blobs.store(b"Verify data")

    db.createRevision(
        revisionId="rev-verify",
        projectId="proj-1",
        path="content/test.md",
        parentRev=None,
        sha256=sha256,
        size=11,
        actorId="usr-1",
        deviceId="dev-1",
        at=utcNow(),
        blobFile=f"blobs/{sha256[:2]}/{sha256}",
    )
    db.commit()
    db.close()

    # Run verify
    parser = buildParser()
    args = parser.parse_args(["verify", "--data", str(dataDir)])

    f = io.StringIO()
    with redirect_stdout(f):
        result = args.func(args)

    assert result == 0
    assert "Verification OK" in f.getvalue()


def test_cli_R2_verify_fails_on_corruption(tmp_path: Path) -> None:
    """R2: verify fails when a blob is corrupted."""
    from umbrastore.blobs import BlobStore
    from umbrastore.cli import buildParser
    from umbrastore.database import Database, connect, initDatabase, utcNow

    dataDir = tmp_path / "data"
    initDatabase(dataDir)

    conn = connect(dataDir)
    db = Database(conn)
    blobsDir = dataDir / "blobs"

    db.createProject("proj-1", "Verify Fail", utcNow())
    blobs = BlobStore(dataDir)
    sha256 = blobs.store(b"Verify data")

    db.createRevision(
        revisionId="rev-verify-fail",
        projectId="proj-1",
        path="content/test.md",
        parentRev=None,
        sha256=sha256,
        size=11,
        actorId="usr-1",
        deviceId="dev-1",
        at=utcNow(),
        blobFile=f"blobs/{sha256[:2]}/{sha256}",
    )
    db.commit()
    db.close()

    # Corrupt the blob
    blobPath = blobsDir / sha256[:2] / sha256
    blobPath.write_bytes(b"corrupted")

    # Run verify
    parser = buildParser()
    args = parser.parse_args(["verify", "--data", str(dataDir)])

    f = io.StringIO()
    with redirect_stdout(f):
        result = args.func(args)

    assert result == 1
    assert "FAILED" in f.getvalue()


def test_cli_R3_tls_warning_without_cert(tmp_path: Path) -> None:
    """R3: Binding to non-loopback without TLS prints warning."""
    from umbrastore.cli import buildParser

    dataDir = tmp_path / "data"
    parser = buildParser()

    # Test with non-loopback host, no TLS, no --allow-insecure -> should fail
    args = parser.parse_args(["serve", "--data", str(dataDir), "--host", "192.168.1.100", "--port", "47400"])

    f = io.StringIO()
    e = io.StringIO()
    with redirect_stdout(f), contextlib.redirect_stderr(e):
        result = args.func(args)

    assert result == 1
    assert "TLS" in e.getvalue() or "tls" in e.getvalue().lower()


def test_cli_help() -> None:
    """CLI help works (exits with 0)."""
    from umbrastore.cli import buildParser

    parser = buildParser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
