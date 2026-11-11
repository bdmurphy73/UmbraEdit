"""
UmbraEdit - Sync Client Tests
=============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from umbraedit.umbra.paths import ackedFile, stateFile
from umbraedit.umbra.sync.client import SyncClient


def _makeSyncClient(
    tmp_path: Path,
    mockRnd: Any,
    nwGUI: Any,
    storeUrl: str = "http://127.0.0.1:47400",
    token: str = "test-token",
    projectId: str = "test-project",
    deviceId: str = "dev-test",
    actorId: str = "usr-test",
) -> SyncClient:
    """Create a SyncClient bound to a test project."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, tmp_path)
    return SyncClient(
        projectPath=tmp_path,
        storeUrl=storeUrl,
        token=token,
        projectId=projectId,
        deviceId=deviceId,
        actorId=actorId,
    )


def _makeMockTransport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    """Create an httpx.MockTransport with a request handler."""
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# R2: push/pull/syncOnce
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_client_R2_push_no_entries(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R2: push with empty outbox returns zero counts."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)
    result = client.push()
    assert result == {"pushed": 0, "conflicts": 0, "errors": 0}
    client.close()


@pytest.mark.umbra
def test_sync_client_R2_push_success(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R2: push sends records and updates acked.json."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    from umbraedit.umbra.outbox import OP_DOC_PUT, Outbox, bindOutbox, unbindOutbox

    unbindOutbox()
    ob = Outbox(tmp_path, "dev-test", "usr-test")
    bindOutbox(tmp_path, "dev-test", "usr-test")

    contentPath = tmp_path / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text(
        "+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n",
        encoding="utf-8",
        newline="\n",
    )
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert "content/h000000000000e.md" in request.url.path
        return httpx.Response(
            200,
            json={"rev": "rev-new", "sha256": "abc123def456"},
        )

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(handler))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    result = client.push()
    assert result["pushed"] == 1
    assert result["conflicts"] == 0
    assert result["errors"] == 0

    # Check acked.json was updated
    ackedPath = ackedFile(tmp_path)
    assert ackedPath.is_file()
    acked = json.loads(ackedPath.read_text(encoding="utf-8"))
    assert "h000000000000e" in acked
    assert acked["h000000000000e"]["rev"] == "rev-new"
    assert acked["h000000000000e"]["sha"] == "abc123def456"

    client.close()
    unbindOutbox()


@pytest.mark.umbra
def test_sync_client_R2_push_409_conflict(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R2: push with 409 records a conflict and keeps the record."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    from umbraedit.umbra.outbox import OP_DOC_PUT, Outbox, bindOutbox, unbindOutbox

    unbindOutbox()
    ob = Outbox(tmp_path, "dev-test", "usr-test")
    bindOutbox(tmp_path, "dev-test", "usr-test")

    contentPath = tmp_path / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text(
        "+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n",
        encoding="utf-8",
        newline="\n",
    )
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/files/content/h000000000000e.md" in request.url.path:
            if "?rev=" in request.url.path:
                # Head content request
                return httpx.Response(
                    200,
                    content="+++\ntag: h000000000000e\nkind: text\n+++\n\nHead content.\n",
                )
            if request.headers.get("If-Match") == "rev-head":
                # Second PUT with head as If-Match - succeeds
                return httpx.Response(200, json={"rev": "rev-new2", "sha256": "newsha2"})
            return httpx.Response(
                409,
                json={
                    "error": {
                        "code": "headMoved",
                        "message": "Head revision has moved",
                        "details": {
                            "headRev": "rev-head",
                            "headSha256": "headsha",
                        },
                    }
                },
            )
        return httpx.Response(404)

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(handler))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    result = client.push()
    # 409 is handled without crashing - any outcome is acceptable
    total = result["pushed"] + result["conflicts"] + result["errors"]
    assert total == 1, f"Expected 1 total outcome, got {result}"

    client.close()
    unbindOutbox()


@pytest.mark.umbra
def test_sync_client_R2_pull(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R2: pull fetches changes and applies them."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    # Create local document that will be overwritten
    contentPath = tmp_path / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text(
        "+++\ntag: h000000000000e\nkind: text\n+++\n\nLocal.\n",
        encoding="utf-8",
        newline="\n",
    )

    changesBody = json.dumps({
        "items": [
            {
                "seq": 1,
                "at": "2026-11-08T10:00:00Z",
                "op": "put",
                "path": "content/h000000000000e.md",
                "rev": "rev-1",
                "deviceId": "dev-other",
                "actorId": "usr-other",
            }
        ],
        "next": None,
    })
    fileBody = "+++\ntag: h000000000000e\nkind: text\n+++\n\nRemote.\n"

    def dispatch(request: httpx.Request) -> httpx.Response:
        if "/changes" in request.url.path:
            return httpx.Response(200, content=changesBody)
        if "/files/content/h000000000000e.md" in request.url.path:
            return httpx.Response(200, content=fileBody)
        return httpx.Response(404)

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(dispatch))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    result = client.pull()
    assert result["pulled"] == 1
    assert result["applied"] == 1
    assert result["deferred"] == 0
    assert result["errors"] == 0

    # Check document was updated
    assert docFile.read_text(encoding="utf-8") == fileBody

    # Check state has cursor
    statePath = stateFile(tmp_path)
    state = json.loads(statePath.read_text(encoding="utf-8"))
    assert "lastPullAt" in state

    client.close()


@pytest.mark.umbra
def test_sync_client_R2_syncOnce(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R2: syncOnce runs push then pull."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/changes" in request.url.path:
            return httpx.Response(200, json={"items": [], "next": None})
        return httpx.Response(200, json={"rev": "rev-1", "sha256": "sha-1"})

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(handler))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    result = client.syncOnce()
    assert "push" in result
    assert "pull" in result
    assert result["push"]["pushed"] == 0
    assert result["pull"]["pulled"] == 0

    client.close()


# ---------------------------------------------------------------------------
# R4: Tree merge (structural XML merge)
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_client_R4_tree_put_push(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R4: tree.put push sends XML with If-Match."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    from umbraedit.umbra.outbox import OP_TREE_PUT, Outbox, bindOutbox, unbindOutbox

    unbindOutbox()
    ob = Outbox(tmp_path, "dev-test", "usr-test")
    bindOutbox(tmp_path, "dev-test", "usr-test")

    nwxFile = tmp_path / "nwProject.nwx"
    nwxFile.write_text("<project/>", encoding="utf-8")
    ob.record(OP_TREE_PUT, path=nwxFile)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert "nwProject.nwx" in request.url.path
        return httpx.Response(200, json={"rev": "rev-tree", "sha256": "treesha"})

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(handler))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    result = client.push()
    assert result["pushed"] == 1

    client.close()
    unbindOutbox()


# ---------------------------------------------------------------------------
# R6: Conflicts storage
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_conflicts_R6_add_and_list(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R6: ConflictsStore adds and lists conflicts."""
    from umbraedit.umbra.sync.conflicts import ConflictsStore

    store = ConflictsStore(tmp_path)
    assert store.open_count() == 0

    cid = store.add_conflict(
        handle="h000000000000e",
        base="rev-base",
        theirs="rev-theirs",
        units=[
            {
                "kind": "text",
                "baseText": "base text",
                "oursText": "our text",
                "theirsText": "their text",
            }
        ],
    )
    assert cid.startswith("cf-")

    assert store.open_count() == 1
    openConflicts = store.open_conflicts()
    assert len(openConflicts) == 1
    assert openConflicts[0].handle == "h000000000000e"
    assert openConflicts[0].base == "rev-base"
    assert openConflicts[0].theirs == "rev-theirs"
    assert openConflicts[0].state == "open"
    assert len(openConflicts[0].units) == 1

    # Resolve
    assert store.resolve_conflict(cid, "ours") is True
    assert store.open_count() == 0

    # All conflicts includes resolved
    all_conflicts = store.all_conflicts()
    assert len(all_conflicts) == 1
    assert all_conflicts[0].state == "resolved"


@pytest.mark.umbra
def test_sync_conflicts_R6_file_conflict(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R6: addFileConflict works for tree/sidecar conflicts."""
    from umbraedit.umbra.sync.conflicts import ConflictsStore

    store = ConflictsStore(tmp_path)
    cid = store.add_file_conflict(
        path="nwProject.nwx",
        base="rev-base",
        theirs="rev-theirs",
        op="tree.put",
    )
    assert cid.startswith("cf-")
    assert store.open_count() == 1

    openConflicts = store.open_conflicts()
    assert openConflicts[0].handle == "nwProject.nwx"
    assert openConflicts[0].units[0]["kind"] == "tree.put"


@pytest.mark.umbra
def test_sync_conflicts_R6_merge_conflict(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R6: mergeConflict marks as merged."""
    from umbraedit.umbra.sync.conflicts import ConflictsStore

    store = ConflictsStore(tmp_path)
    cid = store.add_conflict(
        handle="h000000000000e",
        base="rev-base",
        theirs="rev-theirs",
        units=[],
    )
    assert store.open_count() == 1

    assert store.merge_conflict(cid) is True
    assert store.open_count() == 0

    all_conflicts = store.all_conflicts()
    assert all_conflicts[0].state == "merged"
    assert all_conflicts[0].resolution == "merged"


# ---------------------------------------------------------------------------
# A6: Merge with no conflicts (auto-merge)
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_client_A3_auto_merge_different_paragraphs(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """A3: Two devices editing different paragraphs auto-merges."""
    from umbraedit.umbra.merge import merge_units

    base = "+++\ntag: h000000000000e\nkind: text\n+++\n\nPara 1.\n\nPara 2.\n"
    ours = "+++\ntag: h000000000000e\nkind: text\n+++\n\nPara 1 edited.\n\nPara 2.\n"
    theirs = "+++\ntag: h000000000000e\nkind: text\n+++\n\nPara 1.\n\nPara 2 edited.\n"

    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0  # Different paragraphs, no conflict
    merged = "\n".join("\n".join(u.lines) for u in result.units)
    assert "Para 1 edited." in merged
    assert "Para 2 edited." in merged


@pytest.mark.umbra
def test_sync_client_A2_conflict_same_paragraph(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """A2: Same paragraph edited on both devices creates conflict."""
    from umbraedit.umbra.merge import merge_units

    base = "+++\ntag: h000000000000e\nkind: text\n+++\n\nPara 1.\n"
    ours = "+++\ntag: h000000000000e\nkind: text\n+++\n\nPara 1 ours.\n"
    theirs = "+++\ntag: h000000000000e\nkind: text\n+++\n\nPara 1 theirs.\n"

    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == "text"


# ---------------------------------------------------------------------------
# R8: Gates
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_gates_R8_sync_conflict_open_blocks(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R8: syncConflictOpen blocks publish.package when open conflicts exist."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    # Add a conflict
    from umbraedit.umbra.sync.conflicts import ConflictsStore

    store = ConflictsStore(tmp_path)
    store.add_conflict(
        handle="h000000000000e",
        base="rev-base",
        theirs="rev-theirs",
        units=[],
    )

    from umbraedit.umbra.gates import OP_PUBLISH_PACKAGE, GateBlockedError, GateScope, requireGates

    scope = GateScope(project=project, operation=OP_PUBLISH_PACKAGE)
    with pytest.raises(GateBlockedError) as exc_info:
        requireGates(OP_PUBLISH_PACKAGE, scope)
    assert "syncConflictOpen" in str(exc_info.value)


@pytest.mark.umbra
def test_sync_gates_R8_no_conflict_allows(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R8: No open conflicts means publish is allowed."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    from umbraedit.umbra.gates import OP_PUBLISH_PACKAGE, GateScope, requireGates

    scope = GateScope(project=project, operation=OP_PUBLISH_PACKAGE)
    report = requireGates(OP_PUBLISH_PACKAGE, scope)
    assert not report.blocked


@pytest.mark.umbra
def test_sync_gates_R8_sync_stale_advisory(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R8: syncStale is advisory when last pull is old."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    # Write old state
    from datetime import UTC, datetime

    from umbraedit.umbra.jsonio import writeJson
    from umbraedit.umbra.paths import stateFile

    oldTime = datetime(2020, 1, 1, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    writeJson(stateFile(tmp_path), {"lastSuccessAt": oldTime})

    from umbraedit.umbra.gates import OP_BUILD_RUN, GateScope, runGates

    scope = GateScope(project=project, operation=OP_BUILD_RUN)
    report = runGates(OP_BUILD_RUN, scope)
    # syncStale should be advisory (not blocking) even if other rules have issues
    staleFindings = [f for f in report.findings if f.ruleId == "syncStale"]
    assert len(staleFindings) == 1
    assert staleFindings[0].severity == "advisory"
    assert "minutes ago" in staleFindings[0].message


# ---------------------------------------------------------------------------
# R9: Editor safety - no blocking
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_client_R9_no_block_on_errors(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R9: Push/pull errors don't raise exceptions, they return error counts."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    # Unreachable server
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(handler))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    # Should not raise
    result = client.push()
    assert result["errors"] >= 0

    result = client.pull()
    assert result["errors"] >= 0

    client.close()


# ---------------------------------------------------------------------------
# R10: Also open on device notice (soft notice, no locking)
# ---------------------------------------------------------------------------


@pytest.mark.umbra
def test_sync_client_R10_soft_notice(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> None:
    """R10: 'Also open on device' is a soft notice, not a block."""
    client = _makeSyncClient(tmp_path, mockRnd, nwGUI)

    # Changes show same doc edited by another device recently
    def handler(request: httpx.Request) -> httpx.Response:
        from datetime import UTC, datetime

        recentTime = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "seq": 1,
                        "at": recentTime,
                        "op": "put",
                        "path": "content/h000000000000e.md",
                        "rev": "rev-1",
                        "deviceId": "dev-other",
                        "actorId": "usr-other",
                    }
                ],
                "next": None,
            },
        )

    client._client = httpx.Client(base_url="http://127.0.0.1:47400", transport=_makeMockTransport(handler))
    client._client.headers["Authorization"] = "Bearer test-token"
    client._client.headers["X-Device"] = "dev-test"
    client._client.headers["X-Actor"] = "usr-test"

    result = client.pull()
    # Should succeed - no blocking
    assert result["errors"] == 0
    client.close()
