"""
Tests for UmbraEdit Publish Package (P32)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from umbraedit.umbra.handoff import (
    PublishJob,
    _generate_ulid,
    _utc_now_iso,
    _sha256_file,
    _atomic_write_json,
)
from umbraedit.umbra.publishgates import _load_retailers


class TestUlid:
    """Tests for ULID generation."""

    def test_generate_ulid(self):
        ulid = _generate_ulid()
        assert len(ulid) == 26
        assert all(c in "0123456789abcdef" for c in ulid)


class TestUtcNowIso:
    """Tests for UTC timestamp."""

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
    """Tests for SHA-256 file hashing."""

    def test_sha256_file(self, tmp_path: Path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")
        sha = _sha256_file(test_file)
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)


class TestAtomicWrite:
    """Tests for atomic write functions."""

    def test_atomic_write_json(self, tmp_path: Path):
        file_path = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        _atomic_write_json(file_path, data)

        assert file_path.is_file()
        with open(file_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data


class TestPublishJob:
    """Tests for PublishJob dataclass."""

    def test_publish_job_creation(self):
        job = PublishJob(
            id="test123",
            status="ready",
            package="/path/to/package",
            manifestSha256="abc123",
            createdAt="2026-01-01T00:00:00Z",
            retailer="kdp-paperback",
        )
        assert job.id == "test123"
        assert job.status == "ready"
        assert job.retailer == "kdp-paperback"

    def test_publish_job_to_dict(self):
        job = PublishJob(id="test123", status="ready", package="/path", manifestSha256="abc")
        data = job.to_dict()
        assert data["id"] == "test123"
        assert data["status"] == "ready"
        assert data["package"] == "/path"
        assert data["manifestSha256"] == "abc"

    def test_publish_job_from_dict(self):
        data = {
            "v": 1,
            "id": "test123",
            "status": "done",
            "package": "/path",
            "manifestSha256": "abc",
            "createdAt": "2026-01-01T00:00:00Z",
            "claimedBy": "tool",
            "result": {"success": True},
            "retailer": "kdp-paperback",
        }
        job = PublishJob.from_dict(data)
        assert job.id == "test123"
        assert job.status == "done"
        assert job.claimedBy == "tool"
        assert job.retailer == "kdp-paperback"


class TestRetailers:
    """Tests for retailer matrix."""

    def test_load_retailers(self):
        retailers = _load_retailers()
        assert len(retailers) > 0

        # Check required fields
        for retailer in retailers:
            assert "id" in retailer
            assert "name" in retailer
            assert "formats" in retailer
            assert "requires" in retailer
            assert "limits" in retailer

    def test_kdp_paperback_exists(self):
        retailers = _load_retailers()
        kdp = next((r for r in retailers if r["id"] == "kdp-paperback"), None)
        assert kdp is not None
        assert "paperback" in kdp["formats"]
        assert "book.title" in kdp["requires"]
        assert "edition.isbn.paperback" in kdp["requires"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])