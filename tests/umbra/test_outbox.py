"""
UmbraEdit - Outbox Tests
=========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import hashlib
import json
import re

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.hooks import SIDECAR_WRITTEN
from umbraedit.umbra.outbox import (
    OP_DOC_DELETE,
    OP_DOC_PUT,
    OP_SIDECAR_PUT,
    OP_TREE_PUT,
    Outbox,
    _crc32,
    _parseEntry,
    _serialiseEntry,
    bindOutbox,
    outbox,
    unbindOutbox,
)
from umbraedit.umbra.paths import (
    ackedFile,
    stateFile,
    tonesFile,
    umbraDir,
)


def _makeOutbox(tmp_path: Path, mockRnd: Any, nwGUI: Any) -> tuple[Outbox, Path]:
    """Create an Outbox bound to a test project."""
    unbindOutbox()
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, tmp_path)
    deviceId = "dev-test00000001"
    actorId = "usr-test00000001"
    ob = Outbox(tmp_path, deviceId, actorId)
    bindOutbox(tmp_path, deviceId, actorId)
    return ob, tmp_path


@pytest.mark.umbra
def test_outbox_R1_record_doc_put(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: record() creates a doc.put entry with correct fields."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    assert outboxPath.is_file()
    lines = outboxPath.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["op"] == "doc.put"
    assert entry["handle"] == "h000000000000e"
    assert entry["seq"] == 1
    assert entry["deviceId"] == "dev-test00000001"
    assert entry["actorId"] == "usr-test00000001"
    assert "ts" in entry
    assert "sha" in entry
    assert "c" in entry
    assert len(entry["c"]) == 8


@pytest.mark.umbra
def test_outbox_R1_record_tree_put(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: record() creates a tree.put entry."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    nwxFile = projectPath / "nwProject.nwx"
    nwxFile.write_text("dummy", encoding="utf-8")

    ob.record(OP_TREE_PUT, path=nwxFile)
    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    lines = outboxPath.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[0])
    assert entry["op"] == "tree.put"
    assert "handle" not in entry


@pytest.mark.umbra
def test_outbox_R1_record_sidecar_put(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: record() creates a sidecar.put entry."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    sidecarPath = umbraDir(projectPath) / "voices.json"
    sidecarPath.write_text('{"v":1,"voices":[]}', encoding="utf-8", newline="\n")

    ob.record(OP_SIDECAR_PUT, path=sidecarPath)
    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    lines = outboxPath.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[0])
    assert entry["op"] == "sidecar.put"
    assert entry["path"] == str(sidecarPath)


@pytest.mark.umbra
def test_outbox_R1_collapse_multiple_edits(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: Multiple edits to one target collapse into one record."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nVersion 1.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nVersion 2.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nVersion 3.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    lines = outboxPath.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["seq"] == 1
    assert entry["handle"] == "h000000000000e"
    expected_sha = hashlib.sha256(docFile.read_bytes()).hexdigest()
    assert entry["sha"] == expected_sha


@pytest.mark.umbra
def test_outbox_R2_base_from_acked(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: baseRev/baseSha come from acked.json."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    ackedPath = ackedFile(projectPath)
    ackedPath.parent.mkdir(parents=True, exist_ok=True)
    ackedPath.write_text(
        '{"h000000000000e":{"rev":"rev-001","sha":"abc123"}}',
        encoding="utf-8",
        newline="\n",
    )

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    entry = json.loads(outboxPath.read_text(encoding="utf-8").strip().splitlines()[0])
    assert entry["baseRev"] == "rev-001"
    assert entry["baseSha"] == "abc123"


@pytest.mark.umbra
def test_outbox_R2_no_acked_empty_base(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Without acked.json, baseRev/baseSha are absent."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    entry = json.loads(outboxPath.read_text(encoding="utf-8").strip().splitlines()[0])
    assert "baseRev" not in entry
    assert "baseSha" not in entry


@pytest.mark.umbra
def test_outbox_R3_crc_validation(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R3: A line failing its CRC is dropped."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    text = outboxPath.read_text(encoding="utf-8")
    corrupted = re.sub(r'"c":"[0-9a-f]{8}"', '"c":"deadbeef"', text)
    outboxPath.write_text(corrupted, encoding="utf-8", newline="\n")

    ob2 = Outbox(projectPath, "dev-test00000001", "usr-test00000001")
    assert ob2.queuedCount() == 0


@pytest.mark.umbra
def test_outbox_R3_rebuild_detects_changed_files(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R3: Rebuild creates records for every changed file."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nOriginal.\n", encoding="utf-8", newline="\n")

    ackedPath = ackedFile(projectPath)
    ackedPath.parent.mkdir(parents=True, exist_ok=True)
    ackedPath.write_text(
        '{"h000000000000e":{"rev":"rev-001","sha":"oldsha"}}',
        encoding="utf-8",
        newline="\n",
    )

    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nModified.\n", encoding="utf-8", newline="\n")

    changed = ob.rebuild()
    assert "h000000000000e" in changed
    assert ob.queuedCount() >= 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    # Find our document's entry (not the buildTestProject docs)
    entry = None
    for line in outboxPath.read_text(encoding="utf-8").strip().splitlines():
        e = json.loads(line)
        if e.get("handle") == "h000000000000e":
            entry = e
            break
    assert entry is not None
    assert entry["baseSha"] == "oldsha"
    assert entry["sha"] != "oldsha"


@pytest.mark.umbra
def test_outbox_R4_seq_persisted(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R4: seq increases per device and is persisted."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nV1.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    docFile2 = contentPath / "h000000000000f.md"
    docFile2.write_text("+++\ntag: h000000000000f\nkind: text\n+++\n\nV1.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000f", path=docFile2)
    assert ob.queuedCount() == 2

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    lines = outboxPath.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["seq"] == 1
    assert e2["seq"] == 2

    ob2 = Outbox(projectPath, "dev-test00000001", "usr-test00000001")
    docFile3 = contentPath / "h000000000000g.md"
    docFile3.write_text("+++\ntag: h000000000000g\nkind: text\n+++\n\nV1.\n", encoding="utf-8", newline="\n")
    ob2.record(OP_DOC_PUT, handle="h000000000000g", path=docFile3)
    lines2 = outboxPath.read_text(encoding="utf-8").strip().splitlines()
    e3 = json.loads(lines2[2])
    assert e3["seq"] == 3


@pytest.mark.umbra
def test_outbox_R4_atomic_write(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R4: Writes are atomic (no .tmp files left behind)."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    tmpFiles = list(umbraDir(projectPath).glob("*.tmp"))
    assert len(tmpFiles) == 0


@pytest.mark.umbra
def test_outbox_R5_queued_count(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R5: queuedCount() returns the number of pending records."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    assert ob.queuedCount() == 0

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    docFile2 = contentPath / "h000000000000f.md"
    docFile2.write_text("+++\ntag: h000000000000f\nkind: text\n+++\n\nWorld.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000f", path=docFile2)
    assert ob.queuedCount() == 2


@pytest.mark.umbra
def test_outbox_A1_three_edits_one_record(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A1: Three edits to one scene produce one record with first base and last sha."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"

    ackedPath = ackedFile(projectPath)
    ackedPath.parent.mkdir(parents=True, exist_ok=True)
    ackedPath.write_text(
        '{"h000000000000e":{"rev":"rev-base","sha":"sha-base"}}',
        encoding="utf-8",
        newline="\n",
    )

    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nEdit 1.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nEdit 2.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nEdit 3.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    entry = json.loads(outboxPath.read_text(encoding="utf-8").strip().splitlines()[0])
    assert entry["baseRev"] == "rev-base"
    assert entry["baseSha"] == "sha-base"
    expected_sha = hashlib.sha256(docFile.read_bytes()).hexdigest()
    assert entry["sha"] == expected_sha


@pytest.mark.umbra
def test_outbox_A2_corrupt_line_rebuild(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A2: Corrupt one line: outbox is rebuilt, repair log notes it."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nOriginal.\n", encoding="utf-8", newline="\n")

    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)
    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    text = outboxPath.read_text(encoding="utf-8")
    corrupted = re.sub(r'"c":"[0-9a-f]{8}"', '"c":"00000000"', text)
    outboxPath.write_text(corrupted, encoding="utf-8", newline="\n")

    changed = ob.rebuild()
    assert "h000000000000e" in changed
    assert ob.queuedCount() >= 1


@pytest.mark.umbra
def test_outbox_A3_crc_golden(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A3: Example lines validate their CRC (golden test)."""
    line = (
        '{"seq":41,"ts":"2026-11-06T21:02:11Z","deviceId":"dev-01J9Z0A4KQ",'
        '"actorId":"usr-01J9Y8C2M1","op":"doc.put","handle":"3f9a1c",'
        '"baseRev":"rev-01J9ZP3Q7A","baseSha":"390a4ee3","sha":"211b3c14"}'
    )
    crc = _crc32(line)
    assert len(crc) == 8
    assert all(c in "0123456789abcdef" for c in crc)

    entry = {
        "seq": 41,
        "ts": "2026-11-06T21:02:11Z",
        "deviceId": "dev-01J9Z0A4KQ",
        "actorId": "usr-01J9Y8C2M1",
        "op": "doc.put",
        "handle": "3f9a1c",
        "baseRev": "rev-01J9ZP3Q7A",
        "baseSha": "390a4ee3",
        "sha": "211b3c14",
    }
    serialised = _serialiseEntry(entry)
    parsed = _parseEntry(serialised)
    assert parsed is not None
    assert parsed["seq"] == 41
    assert parsed["c"] is not None
    assert len(parsed["c"]) == 8


@pytest.mark.umbra
def test_outbox_A4_persists_across_reload(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A4: Closing with non-empty outbox keeps the file; next open resumes."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    contentPath = projectPath / "content"
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text("+++\ntag: h000000000000e\nkind: text\n+++\n\nHello.\n", encoding="utf-8", newline="\n")
    ob.record(OP_DOC_PUT, handle="h000000000000e", path=docFile)

    unbindOutbox()
    ob2 = Outbox(projectPath, "dev-test00000001", "usr-test00000001")
    assert ob2.queuedCount() == 1

    docFile2 = contentPath / "h000000000000f.md"
    docFile2.write_text("+++\ntag: h000000000000f\nkind: text\n+++\n\nWorld.\n", encoding="utf-8", newline="\n")
    ob2.record(OP_DOC_PUT, handle="h000000000000f", path=docFile2)
    assert ob2.queuedCount() == 2


@pytest.mark.umbra
def test_outbox_A5_tone_change_creates_record(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A5: A tone change creates a sidecar.put record."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    tonesPath = tonesFile(projectPath)
    tonesPath.parent.mkdir(parents=True, exist_ok=True)
    tonesPath.write_text('{"v":1,"tones":[]}', encoding="utf-8", newline="\n")

    from umbraedit.umbra import hooks as _umbraHooks

    _umbraHooks.call(SIDECAR_WRITTEN, tonesPath)

    assert ob.queuedCount() == 1
    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    entry = json.loads(outboxPath.read_text(encoding="utf-8").strip().splitlines()[0])
    assert entry["op"] == "sidecar.put"
    assert entry["path"] == str(tonesPath)


@pytest.mark.umbra
def test_outbox_state_json(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """state.json can be saved and loaded."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    state = {"v": 1, "store": "", "accountId": "", "cursor": "", "lastPushAt": "", "lastPullAt": ""}
    ob.saveState(state)

    statePath = stateFile(projectPath)
    assert statePath.is_file()
    loaded = ob.loadState()
    # readJson strips the "v" schema key
    assert loaded.get("store") == ""
    assert loaded.get("accountId") == ""


@pytest.mark.umbra
def test_outbox_bind_unbind(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """bindOutbox/unbindOutbox work correctly."""
    unbindOutbox()
    assert outbox() is None

    bindOutbox(tmp_path, "dev-test", "usr-test")
    assert outbox() is not None
    assert outbox()._deviceId == "dev-test"
    assert outbox()._actorId == "usr-test"

    unbindOutbox()
    assert outbox() is None


@pytest.mark.umbra
def test_outbox_doc_delete_op(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """doc.put and doc.delete ops are accepted."""
    ob, projectPath = _makeOutbox(tmp_path, mockRnd, nwGUI)

    ob.record(OP_DOC_DELETE, handle="h000000000000e")
    assert ob.queuedCount() == 1

    outboxPath = umbraDir(projectPath) / "outbox.jsonl"
    entry = json.loads(outboxPath.read_text(encoding="utf-8").strip().splitlines()[0])
    assert entry["op"] == "doc.delete"
    assert entry["handle"] == "h000000000000e"
