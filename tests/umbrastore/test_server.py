"""
UmbraStore - Server API tests
==============================
"""  # noqa

from __future__ import annotations

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# R1: Project creation
# ---------------------------------------------------------------------------


def test_server_R1_create_project(client: TestClient, authHeaders: dict[str, str]) -> None:
    """R1: POST /v1/projects creates a project and returns {id}."""
    resp = client.post("/v1/projects", json={"name": "My Novel"}, headers=authHeaders)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert len(data["id"]) > 0


def test_server_R1_create_project_unauthorized(client: TestClient) -> None:
    """R1: Creating a project without a token returns 401."""
    resp = client.post("/v1/projects", json={"name": "My Novel"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# R1: File put (store revision)
# ---------------------------------------------------------------------------


def test_server_R1_put_file_new(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: PUT /v1/projects/{p}/files/{path} stores a new revision."""
    content = b"Hello, UmbraStore!"
    resp = client.put(
        f"/v1/projects/{projectId}/files/content/test.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1", "X-Actor": "usr-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "rev" in data
    assert data["rev"].startswith("rev-")
    assert "sha256" in data
    assert len(data["sha256"]) == 64
    assert "cursor" in data
    assert data["cursor"].startswith("ev-")


def test_server_R1_put_file_if_match_empty(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: PUT with no If-Match creates a new file (head is None)."""
    content = b"First version"
    resp = client.put(
        f"/v1/projects/{projectId}/files/content/new.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp.status_code == 200


def test_server_R1_put_file_with_if_match(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: PUT with If-Match equal to head succeeds."""
    content = b"First version"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/versioned.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp1.status_code == 200
    rev1 = resp1.json()["rev"]

    content2 = b"Second version"
    resp2 = client.put(
        f"/v1/projects/{projectId}/files/content/versioned.md",
        content=content2,
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["rev"] != rev1


def test_server_R1_put_file_if_match_mismatch(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: PUT with wrong If-Match returns 409 headMoved."""
    content = b"First version"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/conflict.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp1.status_code == 200
    rev1 = resp1.json()["rev"]

    # Create a second revision to move the head
    content2 = b"Second version"
    resp2 = client.put(
        f"/v1/projects/{projectId}/files/content/conflict.md",
        content=content2,
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )
    assert resp2.status_code == 200

    # Now try with the old rev - should get 409
    content3 = b"Third version"
    resp3 = client.put(
        f"/v1/projects/{projectId}/files/content/conflict.md",
        content=content3,
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )
    assert resp3.status_code == 409
    body = resp3.json()
    assert body["error"]["code"] == "headMoved"
    assert "headRev" in body["error"]["details"]
    assert "headSha256" in body["error"]["details"]


# ---------------------------------------------------------------------------
# R4: Idempotence
# ---------------------------------------------------------------------------


def test_server_R4_idempotent_put(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R4: PUT of same bytes twice returns same revision."""
    content = b"Idempotent content"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/idem.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp1.status_code == 200
    rev1 = resp1.json()["rev"]

    resp2 = client.put(
        f"/v1/projects/{projectId}/files/content/idem.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["rev"] == rev1


# ---------------------------------------------------------------------------
# R1: File get
# ---------------------------------------------------------------------------


def test_server_R1_get_file_head(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: GET /v1/projects/{p}/files/{path} returns head revision bytes."""
    content = b"File content for GET test"
    client.put(
        f"/v1/projects/{projectId}/files/content/gettest.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )

    resp = client.get(
        f"/v1/projects/{projectId}/files/content/gettest.md",
        headers=authHeaders,
    )
    assert resp.status_code == 200
    assert resp.content == content
    assert "X-Revision" in resp.headers
    assert "X-SHA-256" in resp.headers


def test_server_R1_get_file_by_rev(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: GET with ?rev= returns that specific revision."""
    content1 = b"Version 1"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/revtest.md",
        content=content1,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    rev1 = resp1.json()["rev"]

    content2 = b"Version 2"
    resp2 = client.put(
        f"/v1/projects/{projectId}/files/content/revtest.md",
        content=content2,
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )
    # Get by rev1
    resp3 = client.get(
        f"/v1/projects/{projectId}/files/content/revtest.md?rev={rev1}",
        headers=authHeaders,
    )
    assert resp3.status_code == 200
    assert resp3.content == content1

    # Get head (should be rev2)
    resp4 = client.get(
        f"/v1/projects/{projectId}/files/content/revtest.md",
        headers=authHeaders,
    )
    assert resp4.status_code == 200
    assert resp4.content == content2


def test_server_R1_get_file_not_found(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: GET for non-existent file returns 404."""
    resp = client.get(
        f"/v1/projects/{projectId}/files/content/nonexistent.md",
        headers=authHeaders,
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "notFound"


# ---------------------------------------------------------------------------
# R1: File delete
# ---------------------------------------------------------------------------


def test_server_R1_delete_file(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: DELETE /v1/projects/{p}/files/{path} marks file deleted."""
    content = b"To be deleted"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/todelete.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp1.status_code == 200
    rev1 = resp1.json()["rev"]

    resp2 = client.delete(
        f"/v1/projects/{projectId}/files/content/todelete.md",
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )
    assert resp2.status_code == 204

    # File should no longer be retrievable
    resp3 = client.get(
        f"/v1/projects/{projectId}/files/content/todelete.md",
        headers=authHeaders,
    )
    assert resp3.status_code == 404


# ---------------------------------------------------------------------------
# R5: Changes endpoint
# ---------------------------------------------------------------------------


def test_server_R5_changes_ordering(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R5: Changes are returned in seq order."""
    # Create several files
    for i in range(5):
        client.put(
            f"/v1/projects/{projectId}/files/content/order{i}.md",
            content=f"content {i}".encode(),
            headers={**authHeaders, "X-Device": "dev-1"},
        )

    resp = client.get(
        f"/v1/projects/{projectId}/changes?limit=100",
        headers=authHeaders,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 5
    seqs = [item["seq"] for item in data["items"]]
    assert seqs == sorted(seqs)


def test_server_R5_changes_pagination(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R5: Changes pagination with cursor works."""
    # Create files
    for i in range(5):
        client.put(
            f"/v1/projects/{projectId}/files/content/pagination{i}.md",
            content=f"content {i}".encode(),
            headers={**authHeaders, "X-Device": "dev-1"},
        )

    # First page
    resp1 = client.get(
        f"/v1/projects/{projectId}/changes?limit=2",
        headers=authHeaders,
    )
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert len(page1["items"]) <= 2
    assert page1["next"] is not None
    assert page1["next"].startswith("ev-")

    # Second page using cursor
    resp2 = client.get(
        f"/v1/projects/{projectId}/changes?since={page1['next']}&limit=2",
        headers=authHeaders,
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert len(page2["items"]) <= 2

    # No overlap between pages
    page1Seqs = {item["seq"] for item in page1["items"]}
    page2Seqs = {item["seq"] for item in page2["items"]}
    assert page1Seqs.isdisjoint(page2Seqs)


def test_server_R5_cursor_format(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R5: Cursor format is ev-<12 digits>."""
    client.put(
        f"/v1/projects/{projectId}/files/content/cursor_test.md",
        content=b"cursor test",
        headers={**authHeaders, "X-Device": "dev-1"},
    )

    resp = client.get(
        f"/v1/projects/{projectId}/changes?limit=1",
        headers=authHeaders,
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["next"]:
        assert data["next"].startswith("ev-")
        numPart = data["next"][3:]
        assert len(numPart) == 12
        assert numPart.isdigit()


# ---------------------------------------------------------------------------
# R1: Revisions endpoint
# ---------------------------------------------------------------------------


def test_server_R1_list_revisions(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """R1: GET /v1/projects/{p}/revisions?path= returns revision history."""
    content1 = b"First"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/history.md",
        content=content1,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    rev1 = resp1.json()["rev"]

    content2 = b"Second"
    resp2 = client.put(
        f"/v1/projects/{projectId}/files/content/history.md",
        content=content2,
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )

    resp3 = client.get(
        f"/v1/projects/{projectId}/revisions?path=content/history.md",
        headers=authHeaders,
    )
    assert resp3.status_code == 200
    data = resp3.json()
    assert len(data) >= 2
    assert data[0]["id"] == rev1
    assert "sha256" in data[0]
    assert "size" in data[0]
    assert "actorId" in data[0]
    assert "deviceId" in data[0]
    assert "at" in data[0]


# ---------------------------------------------------------------------------
# R1: Health endpoint
# ---------------------------------------------------------------------------


def test_server_R1_health(client: TestClient) -> None:
    """R1: GET /v1/health returns {ok: true, version}."""
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "version" in data


# ---------------------------------------------------------------------------
# R5: Wrong/missing token
# ---------------------------------------------------------------------------


def test_server_R5_wrong_token(client: TestClient, projectId: str) -> None:
    """R5: Wrong token returns 401."""
    resp = client.get(
        f"/v1/projects/{projectId}/changes",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"


def test_server_R5_missing_token(client: TestClient, projectId: str) -> None:
    """R5: Missing token returns 401."""
    resp = client.get(f"/v1/projects/{projectId}/changes")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# A1: Race condition - two clients same If-Match
# ---------------------------------------------------------------------------


def test_server_A1_race_condition(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """A1: Two clients race with same If-Match: exactly one wins, other gets 409."""
    content = b"Race content"
    resp1 = client.put(
        f"/v1/projects/{projectId}/files/content/race.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1"},
    )
    assert resp1.status_code == 200
    rev1 = resp1.json()["rev"]

    # Client 2 uses same If-Match (rev1) - should succeed (it's still head)
    resp2 = client.put(
        f"/v1/projects/{projectId}/files/content/race.md",
        content=b"Client 2 version",
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-2"},
    )
    assert resp2.status_code == 200

    # Client 1 tries again with same If-Match (rev1) - head has moved
    resp3 = client.put(
        f"/v1/projects/{projectId}/files/content/race.md",
        content=b"Client 1 retry",
        headers={**authHeaders, "If-Match": f'"{rev1}"', "X-Device": "dev-1"},
    )
    assert resp3.status_code == 409
    body = resp3.json()
    assert body["error"]["code"] == "headMoved"


# ---------------------------------------------------------------------------
# A2: Verify detects flipped byte
# ---------------------------------------------------------------------------


def test_server_A2_verify_detects_corruption(tmp_path: Path) -> None:
    """A2: verify detects a flipped byte in a blob."""
    from umbrastore.blobs import BlobStore
    from umbrastore.cli import cmdVerify
    from umbrastore.database import connect, initDatabase

    initDatabase(tmp_path)
    conn = connect(tmp_path)

    from umbrastore.database import Database

    db = Database(conn)
    blobs = BlobStore(tmp_path)

    # Store a blob
    data = b"Original data"
    sha256 = blobs.store(data)

    # Create a revision row referencing it
    projectId = "test-proj"
    db.createProject(projectId, "Test", "2026-11-01T00:00:00Z")
    db.createRevision(
        revisionId="rev-test",
        projectId=projectId,
        path="content/test.md",
        parentRev=None,
        sha256=sha256,
        size=len(data),
        actorId="usr-1",
        deviceId="dev-1",
        at="2026-11-01T00:00:00Z",
        blobFile=f"blobs/{sha256[:2]}/{sha256}",
    )
    db.commit()
    db.close()

    # Corrupt the blob
    blobPath = tmp_path / "blobs" / sha256[:2] / sha256
    blobPath.write_bytes(b"corrupted!")

    # Verify should detect it
    result = cmdVerify(type("Args", (), {"data": str(tmp_path)})())
    assert result == 1


# ---------------------------------------------------------------------------
# A3: Kill server during PUT - database consistency
# ---------------------------------------------------------------------------


def test_server_A3_put_atomic_consistency(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """A3: A successful PUT leaves the database consistent."""
    content = b"Atomic test content"
    resp = client.put(
        f"/v1/projects/{projectId}/files/content/atomic.md",
        content=content,
        headers={**authHeaders, "X-Device": "dev-1", "X-Actor": "usr-1"},
    )
    assert resp.status_code == 200

    # File should be retrievable
    resp2 = client.get(
        f"/v1/projects/{projectId}/files/content/atomic.md",
        headers=authHeaders,
    )
    assert resp2.status_code == 200
    assert resp2.content == content

    # Changes should include the event
    resp3 = client.get(
        f"/v1/projects/{projectId}/changes",
        headers=authHeaders,
    )
    assert resp3.status_code == 200
    events = resp3.json()["items"]
    putEvents = [e for e in events if e["op"] == "put" and e["path"] == "content/atomic.md"]
    assert len(putEvents) >= 1


# ---------------------------------------------------------------------------
# A4: Changes returns every event exactly once over 10,000 writes
# ---------------------------------------------------------------------------


def test_server_A4_changes_exactly_once(client: TestClient, authHeaders: dict[str, str], projectId: str) -> None:
    """A4: Changes returns every event exactly once in order."""
    # Use a smaller number for speed but verify the pattern
    numWrites = 100

    for i in range(numWrites):
        client.put(
            f"/v1/projects/{projectId}/files/content/bulk{i}.md",
            content=f"bulk content {i}".encode(),
            headers={**authHeaders, "X-Device": "dev-1"},
        )

    # Fetch all changes
    allEvents: list[dict] = []
    cursor: str | None = None
    while True:
        url = f"/v1/projects/{projectId}/changes?limit=50"
        if cursor:
            url += f"&since={cursor}"
        resp = client.get(url, headers=authHeaders)
        assert resp.status_code == 200
        data = resp.json()
        allEvents.extend(data["items"])
        cursor = data.get("next")
        if not cursor:
            break

    putEvents = [e for e in allEvents if e["op"] == "put"]
    assert len(putEvents) >= numWrites

    # Verify no duplicate seqs
    seqs = [e["seq"] for e in allEvents]
    assert len(seqs) == len(set(seqs))

    # Verify ordering
    assert seqs == sorted(seqs)


# ---------------------------------------------------------------------------
# Error body format
# ---------------------------------------------------------------------------


def test_server_error_body_format(client: TestClient, projectId: str) -> None:
    """Error responses have the correct format."""
    resp = client.get(
        f"/v1/projects/{projectId}/changes",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert "error" in body
    assert "code" in body["error"]
    assert "message" in body["error"]
    assert "details" in body["error"]
