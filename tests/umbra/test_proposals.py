"""
Tests for UmbraEdit Analysis Proposal Intake (P34).

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

import json

from pathlib import Path

import pytest

from umbraedit.umbra.proposals import (
    ProposalItem,
    ProposalSet,
    _sha256_text,
    accept_proposal,
    compute_text_hash,
    import_proposals,
    list_proposals,
)
from umbraedit.umbra.proposer import SPEECH_VERBS_EN, propose_from_paragraph


class TestProposalDataModel:
    """Tests for ProposalItem and ProposalSet dataclasses."""

    def test_proposal_item_creation(self) -> None:
        """Test creating a ProposalItem."""
        item = ProposalItem(
            handle="ch1",
            para=0,
            textHash="abc123",
            kind="speaker",
            value={"spk": "Bob"},
            confidence=0.82,
        )
        assert item.handle == "ch1"
        assert item.para == 0
        assert item.textHash == "abc123"
        assert item.kind == "speaker"
        assert item.value == {"spk": "Bob"}
        assert item.confidence == 0.82

    def test_proposal_set_to_dict(self) -> None:
        """Test ProposalSet.to_dict serialization."""
        item = ProposalItem(
            handle="ch1",
            para=0,
            textHash="abc123",
            kind="speaker",
            value={"spk": "Bob"},
            confidence=0.82,
        )
        ps = ProposalSet(
            v=1,
            runId="pr-test",
            tool="test",
            createdAt="2026-01-01T00:00:00Z",
            items=[item],
        )
        d = ps.to_dict()
        assert d["v"] == 1
        assert d["runId"] == "pr-test"
        assert len(d["items"]) == 1
        assert d["items"][0]["handle"] == "ch1"

    def test_proposal_set_from_dict(self) -> None:
        """Test ProposalSet.from_dict deserialization."""
        data = {
            "v": 1,
            "runId": "pr-test",
            "tool": "test",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": "abc123",
                    "kind": "speaker",
                    "value": {"spk": "Bob"},
                    "confidence": 0.82,
                }
            ],
        }
        ps = ProposalSet.from_dict(data)
        assert ps.runId == "pr-test"
        assert len(ps.items) == 1
        assert ps.items[0].handle == "ch1"


class TestSha256:
    """Tests for SHA-256 text hashing."""

    def test_sha256_text(self) -> None:
        """Test SHA-256 of simple text."""
        h = _sha256_text("hello world")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_sha256_text_unicode(self) -> None:
        """Test SHA-256 of unicode text."""
        h = _sha256_text("Hello, world! © 2026")
        assert len(h) == 64

    def test_sha256_text_empty(self) -> None:
        """Test SHA-256 of empty text."""
        h = _sha256_text("")
        assert len(h) == 64


class TestImportProposals:
    """Tests for importing proposals."""

    def test_import_proposals_valid(self, tmp_path: Path) -> None:
        """R1/A1: Importing a file with 3 items shows 3 proposals."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text(
            "Paragraph one text.\n\nParagraph two text.\n\nParagraph three text.\n",
            encoding="utf-8",
        )

        p1_hash = _sha256_text("Paragraph one text.")
        p2_hash = _sha256_text("Paragraph two text.")
        p3_hash = _sha256_text("Paragraph three text.")

        proposal_data = {
            "v": 1,
            "runId": "pr-test1",
            "tool": "test-proposer",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": p1_hash,
                    "kind": "speaker",
                    "value": {"spk": "Bob"},
                    "confidence": 0.82,
                },
                {
                    "handle": "ch1",
                    "para": 1,
                    "textHash": p2_hash,
                    "kind": "speaker",
                    "value": {"spk": "Alice"},
                    "confidence": 0.9,
                },
                {
                    "handle": "ch1",
                    "para": 2,
                    "textHash": p3_hash,
                    "kind": "tone",
                    "value": {"tone": "angry", "toneI": 3},
                    "confidence": 0.75,
                },
            ],
        }
        proposal_file = tmp_path / "proposal.json"
        proposal_file.write_text(json.dumps(proposal_data), encoding="utf-8")

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()

        result = import_proposals(MockProject(), proposal_file)  # type: ignore[arg-type]
        assert result["accepted"] == 3
        assert result["skipped"] == 0
        assert result["total"] == 3
        assert result["runId"] == "pr-test1"

        proposals_dir = umbra_path / "proposals"
        assert (proposals_dir / "pr-test1.json").is_file()

    def test_import_proposals_texthash_mismatch(self, tmp_path: Path) -> None:
        """R1: Items whose textHash no longer matches are skipped."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text("Original paragraph text.\n", encoding="utf-8")

        proposal_data = {
            "v": 1,
            "runId": "pr-test2",
            "tool": "test",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": "wronghash12345",
                    "kind": "speaker",
                    "value": {"spk": "Bob"},
                    "confidence": 0.82,
                }
            ],
        }
        proposal_file = tmp_path / "proposal2.json"
        proposal_file.write_text(json.dumps(proposal_data), encoding="utf-8")

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()

        result = import_proposals(MockProject(), proposal_file)  # type: ignore[arg-type]
        assert result["accepted"] == 0
        assert result["skipped"] == 1
        assert result["total"] == 1


class TestListProposals:
    """Tests for listing proposals."""

    def test_list_proposals_empty(self, tmp_path: Path) -> None:
        """Test listing proposals when none exist."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()

        result = list_proposals(MockProject())  # type: ignore[arg-type]
        assert result == []

    def test_list_proposals_with_files(self, tmp_path: Path) -> None:
        """Test listing proposals when files exist."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()
        proposals_dir = umbra_path / "proposals"
        proposals_dir.mkdir()

        proposal_data = {
            "v": 1,
            "runId": "pr-list-test",
            "tool": "test",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": "abc",
                    "kind": "speaker",
                    "value": {"spk": "Bob"},
                    "confidence": 0.8,
                }
            ],
        }
        (proposals_dir / "pr-list-test.json").write_text(json.dumps(proposal_data), encoding="utf-8")

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()

        result = list_proposals(MockProject())  # type: ignore[arg-type]
        assert len(result) == 1
        assert result[0]["runId"] == "pr-list-test"
        assert result[0]["itemCount"] == 1


class TestProposer:
    """Tests for the rule-based proposer."""

    def test_speech_verbs_non_empty(self) -> None:
        """R6: Rule-based proposer has speech verbs."""
        assert len(SPEECH_VERBS_EN) > 0
        assert "said" in SPEECH_VERBS_EN
        assert "asked" in SPEECH_VERBS_EN
        assert "whispered" in SPEECH_VERBS_EN

    def test_propose_from_paragraph_speech_verb(self, tmp_path: Path) -> None:
        """R6/A4: Proposer finds 'said Uncle Bob' next to a quote."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        (project_path / "umbra").mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text('"Hello," said Uncle Bob.\n', encoding="utf-8")

        class MockSheet:
            def iterEntities(self) -> list:
                return []

            def resolveSpeaker(self, name: str) -> list:
                if name == "Uncle Bob":

                    class MockEntity:
                        tag = "bob"

                    return [MockEntity()]
                return []

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()
            index = MockSheet()

        items = propose_from_paragraph(MockProject(), "ch1", 0, '"Hello," said Uncle Bob.', MockSheet())
        speaker_proposals = [i for i in items if i.kind == "speaker"]
        assert len(speaker_proposals) >= 1


class TestAcceptProposal:
    """Tests for accepting proposals."""

    def test_accept_proposal_writes_voice(self, tmp_path: Path) -> None:
        """R3/A2: Accepting writes author data into the text."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()
        proposals_dir = umbra_path / "proposals"
        proposals_dir.mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text("Hello world.\n", encoding="utf-8")

        proposal_data = {
            "v": 1,
            "runId": "pr-accept-test",
            "tool": "test",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": _sha256_text("Hello world."),
                    "kind": "speaker",
                    "value": {"spk": "Bob"},
                    "confidence": 0.82,
                }
            ],
        }
        (proposals_dir / "pr-accept-test.json").write_text(json.dumps(proposal_data), encoding="utf-8")

        class MockEntity:
            tag = "bob"

        class MockSheet:
            def iterEntities(self) -> list:
                return [MockEntity()]

            def resolveSpeaker(self, name: str) -> list:
                if name == "Bob":
                    return [MockEntity()]
                return []

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()
            index = MockSheet()

        result = accept_proposal(MockProject(), "pr-accept-test", 0)  # type: ignore[arg-type]
        assert result["success"] is True

        ch1_text = ch1.read_text(encoding="utf-8")
        assert "%Voice: spk=bob" in ch1_text

        remaining = list_proposals(MockProject())  # type: ignore[arg-type]
        assert len(remaining) == 0


class TestAcceptProposalAuthorWins:
    """Tests for R4: Author data always wins."""

    def test_accept_proposal_superseded(self, tmp_path: Path) -> None:
        """R4/A5: Paragraph that already has spk shows no speaker proposal."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()
        proposals_dir = umbra_path / "proposals"
        proposals_dir.mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text("%Voice: spk=alice\nHello world.\n", encoding="utf-8")

        proposal_data = {
            "v": 1,
            "runId": "pr-supersede-test",
            "tool": "test",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": _sha256_text("Hello world."),
                    "kind": "speaker",
                    "value": {"spk": "Bob"},
                    "confidence": 0.82,
                }
            ],
        }
        (proposals_dir / "pr-supersede-test.json").write_text(json.dumps(proposal_data), encoding="utf-8")

        class MockEntity:
            tag = "bob"

        class MockSheet:
            def iterEntities(self) -> list:
                return [MockEntity()]

            def resolveSpeaker(self, name: str) -> list:
                if name == "Bob":
                    return [MockEntity()]
                return []

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()
            index = MockSheet()

        result = accept_proposal(MockProject(), "pr-supersede-test", 0)  # type: ignore[arg-type]
        assert result["success"] is False
        assert result["error"] == "superseded"

        ch1_text = ch1.read_text(encoding="utf-8")
        assert "%Voice: spk=alice" in ch1_text
        assert "spk=bob" not in ch1_text


class TestAcceptProposalUnresolved:
    """Tests for R5: Unknown speaker creates nothing."""

    def test_accept_proposal_unresolved(self, tmp_path: Path) -> None:
        """R3/A3: A proposal for an unknown speaker creates nothing."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()
        umbra_path = project_path / "umbra"
        umbra_path.mkdir()
        proposals_dir = umbra_path / "proposals"
        proposals_dir.mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text("Hello world.\n", encoding="utf-8")

        proposal_data = {
            "v": 1,
            "runId": "pr-unresolved-test",
            "tool": "test",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": [
                {
                    "handle": "ch1",
                    "para": 0,
                    "textHash": _sha256_text("Hello world."),
                    "kind": "speaker",
                    "value": {"spk": "Unknown Person"},
                    "confidence": 0.5,
                }
            ],
        }
        (proposals_dir / "pr-unresolved-test.json").write_text(json.dumps(proposal_data), encoding="utf-8")

        class MockSheet:
            def iterEntities(self) -> list:
                return []

            def resolveSpeaker(self, name: str) -> list:
                return []

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()
            index = MockSheet()

        result = accept_proposal(MockProject(), "pr-unresolved-test", 0)  # type: ignore[arg-type]
        assert result["success"] is False
        assert result["error"] == "unresolved"

        ch1_text = ch1.read_text(encoding="utf-8")
        assert "%Voice:" not in ch1_text


class TestComputeTextHash:
    """Tests for compute_text_hash."""

    def test_compute_text_hash(self, tmp_path: Path) -> None:
        """Test computing text hash of a paragraph."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        content_path = project_path / "content"
        content_path.mkdir()

        ch1 = content_path / "ch1.md"
        ch1.write_text("Hello world.\n", encoding="utf-8")

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()

        h = compute_text_hash(MockProject().storage.storagePath, "ch1", 0)  # type: ignore[arg-type]
        assert h == _sha256_text("Hello world.")

    def test_compute_text_hash_invalid(self, tmp_path: Path) -> None:
        """Test computing text hash for invalid inputs."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()

        class MockStorage:
            storagePath = str(project_path)

        class MockProject:
            storage = MockStorage()

        assert compute_text_hash(MockProject().storage.storagePath, "nonexistent", 0) is None  # type: ignore[arg-type]

        content_path = project_path / "content"
        content_path.mkdir()
        ch1 = content_path / "ch1.md"
        ch1.write_text("Only one paragraph.\n", encoding="utf-8")
        assert compute_text_hash(MockProject().storage.storagePath, "ch1", 5) is None  # type: ignore[arg-type]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
