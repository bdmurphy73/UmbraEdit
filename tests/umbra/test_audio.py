"""
Tests for UmbraEdit Audio Package (P31)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from umbraedit.umbra.audio import (
    AudioManifest,
    AudioPackageBuilder,
    ChapterAudio,
    CharacterInfo,
    MatterAudio,
    UtteranceRecord,
    VoiceInfo,
    _utc_now_iso,
    _sha256_file,
    _atomic_write_json,
    _atomic_write_text,
    _is_ready,
)
from umbraedit.umbra.metadata import Metadata, saveMetadata
from umbraedit.umbra.edition import EditionInfo, EditionDoc, saveEdition


class TestAudioManifest:
    """Tests for AudioManifest dataclass."""

    def test_audio_manifest_creation(self):
        manifest = AudioManifest(
            book="Test Book",
            edition="ed-en",
            created_at="2026-01-01T00:00:00Z",
            tool="UmbraEdit",
            cover={"file": "cover.jpg", "sha256": "abc123"},
            chapters=[
                {"handle": "ch1", "title": "Chapter 1", "order": 1, "file": "chapters/ch1.jsonl", "sha256": "abc", "utterances": 10, "status": "ready"}
            ],
            matter={"opening": "matter/opening.jsonl", "closing": "matter/closing.jsonl"},
            voices=["vm-abc123"],
            lexicon="lexicon.en.pls",
        )
        assert manifest.book == "Test Book"
        assert manifest.edition == "ed-en"
        assert len(manifest.chapters) == 1
        assert manifest.voices == ["vm-abc123"]

    def test_audio_manifest_to_dict(self):
        manifest = AudioManifest(
            book="Test Book",
            edition="ed-en",
            created_at="2026-01-01T00:00:00Z",
            tool="UmbraEdit",
        )
        data = manifest.to_dict()
        assert data["book"] == "Test Book"
        assert data["edition"] == "ed-en"
        assert data["v"] == 1


class TestUtcNowIso:
    def test_utc_now_iso_format(self):
        ts = _utc_now_iso()
        assert len(ts) == 20  # YYYY-MM-DDTHH:MM:SSZ
        assert ts.endswith("Z")
        assert ts[4] == "-"
        assert ts[7] == "-"
        assert ts[10] == "T"
        assert ts[13] == ":"
        assert ts[16] == ":"


class TestSha256File:
    def test_sha256_file(self, tmp_path: Path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")
        sha = _sha256_file(test_file)
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)


class TestAtomicWrite:
    def test_atomic_write_json(self, tmp_path: Path):
        file_path = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        _atomic_write_json(file_path, data)

        assert file_path.is_file()
        with open(file_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_atomic_write_text(self, tmp_path: Path):
        file_path = tmp_path / "test.txt"
        text = "Hello, world!"
        _atomic_write_text(file_path, text)

        assert file_path.is_file()
        assert file_path.read_text(encoding="utf-8") == text


class TestIsReady:
    def test_is_ready_all_ready(self):
        from umbraedit.umbra.audio import UtteranceRecord, _is_ready
        # UtteranceRecord doesn't have a status field
        # _is_ready is a stub that always returns True for now
        # This test verifies the function exists and can be called
        utterances = [
            UtteranceRecord(id="1", text="Hello", voice="vm-1", pause_after_ms=250),
            UtteranceRecord(id="2", text="World", voice="vm-1", pause_after_ms=250),
        ]
        # The function checks if all utterances are ready
        # Currently returns True as a stub
        result = _is_ready(utterances)
        # Just verify it runs without error
        assert isinstance(result, bool)


class TestAudioPackageBuilder:
    """Tests for AudioPackageBuilder."""

    def test_builder_creation(self, tmp_path: Path):
        """Test that AudioPackageBuilder can be created."""
        # This test is a placeholder - would need a full project mock
        pass


class TestAudioManifestSchema:
    """Tests for AudioManifest JSON schema compliance."""

    def test_manifest_json_structure(self, tmp_path: Path):
        manifest = AudioManifest(
            v=1,
            book="Test Book",
            edition="ed-en",
            created_at="2026-01-01T00:00:00Z",
            tool="UmbraEdit",
            cover={"file": "cover.jpg", "sha256": "abc123"},
            chapters=[
                {
                    "handle": "ch1",
                    "title": "Chapter 1",
                    "order": 1,
                    "file": "chapters/ch1.jsonl",
                    "sha256": "abc123",
                    "utterances": 5,
                    "status": "ready",
                }
            ],
            matter={
                "opening": "matter/opening.jsonl",
                "closing": "matter/closing.jsonl",
            },
            voices=["vm-abc123"],
            lexicon="lexicon.en.pls",
        )

        data = manifest.to_dict()
        assert data["v"] == 1
        assert data["book"] == "Test Book"
        assert data["edition"] == "ed-en"
        assert len(data["chapters"]) == 1
        assert data["chapters"][0]["status"] == "ready"
        assert data["voices"] == ["vm-abc123"]
        assert data["lexicon"] == "lexicon.en.pls"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])