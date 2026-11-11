"""
UmbraStore - Test configuration and fixtures
============================================
"""  # noqa

from __future__ import annotations

import os

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from fastapi.testclient import TestClient


@pytest.fixture
def tmpDataDir(tmp_path: Path) -> Path:
    """Create a temporary data directory."""
    return tmp_path / "data"


@pytest.fixture
def db(tmpDataDir: Path) -> Generator:
    """Create a database connection and clean up after test."""
    from umbrastore.database import connect, initDatabase

    initDatabase(tmpDataDir)
    conn = connect(tmpDataDir)
    yield conn
    conn.close()


@pytest.fixture
def client(tmpDataDir: Path) -> Generator[TestClient, None, None]:
    """Create a TestClient with a fresh database."""
    os.environ["UMBRASTORE_DATA_DIR"] = str(tmpDataDir)
    import umbrastore.server as server_mod

    from umbrastore.blobs import BlobStore
    from umbrastore.database import Database, connect, initDatabase

    initDatabase(tmpDataDir)
    conn = connect(tmpDataDir)

    db = Database(conn)
    blobs = BlobStore(tmpDataDir)

    server_mod._db = db
    server_mod._blobs = blobs
    server_mod._dataDir = tmpDataDir

    with TestClient(server_mod.app) as tc:
        yield tc

    db.close()
    server_mod._db = None
    server_mod._blobs = None
    server_mod._dataDir = None


@pytest.fixture
def authToken(db: Any) -> str:
    """Create an account and return a bearer token."""
    from umbrastore.auth import generateToken, hashToken
    from umbrastore.database import Database, ulid, utcNow

    d = Database(db)
    accountId = ulid()
    name = "test-account"
    token = generateToken()
    tokenHash = hashToken(token)
    createdAt = utcNow()

    d.createAccount(accountId, name, tokenHash, createdAt)
    d.commit()
    d.close()
    return token


@pytest.fixture
def authHeaders(authToken: str) -> dict[str, str]:
    """Return authorization headers with a valid bearer token."""
    return {"Authorization": f"Bearer {authToken}"}


@pytest.fixture
def projectId(client: TestClient, authHeaders: dict[str, str]) -> str:
    """Create a project and return its ID."""
    resp = client.post("/v1/projects", json={"name": "Test Project"}, headers=authHeaders)
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]
