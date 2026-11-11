"""
UmbraEdit - Publish Handoff Jobs
=================================

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

import hashlib
import json
import logging
import uuid

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from umbraedit.umbra.gates import OP_PUBLISH_HANDOFF, GateScope, requireGates
from umbraedit.umbra.paths import jobsDir

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Job status values
JobStatus = Literal["ready", "claimed", "done", "failed"]


@dataclass(frozen=True)
class PublishJob:
    """A publish handoff job."""

    v: int = 1
    id: str = ""
    status: JobStatus = "ready"
    package: str = ""
    manifestSha256: str = ""
    createdAt: str = ""
    claimedBy: str | None = None
    result: dict[str, Any] | None = None
    retailer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert job to dictionary for JSON serialization."""
        return {
            "v": self.v,
            "id": self.id,
            "status": self.status,
            "package": self.package,
            "manifestSha256": self.manifestSha256,
            "createdAt": self.createdAt,
            "claimedBy": self.claimedBy,
            "result": self.result,
            "retailer": self.retailer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublishJob:
        """Create a PublishJob from a dictionary."""
        return cls(
            v=data.get("v", 1),
            id=data.get("id", ""),
            status=data.get("status", "ready"),
            package=data.get("package", ""),
            manifestSha256=data.get("manifestSha256", ""),
            createdAt=data.get("createdAt", ""),
            claimedBy=data.get("claimedBy"),
            result=data.get("result"),
            retailer=data.get("retailer"),
        )


def _generate_ulid() -> str:
    """Generate a ULID-like identifier."""
    return uuid.uuid4().hex[:26]


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _atomic_rename_claim(job_path: Path, new_status: JobStatus, claimer: str) -> bool:
    """Atomically claim a job by renaming status from ready to claimed."""
    max_retries = 3
    for _ in range(max_retries):
        try:
            with open(job_path, encoding="utf-8") as f:
                job_data = json.load(f)

            if job_data.get("status") != "ready":
                return False

            job_data["status"] = new_status
            job_data["claimedBy"] = claimer

            _atomic_write_json(job_path, job_data)
            return True
        except Exception:
            continue
    return False


def create_publish_job(
    project: NWProject,
    package_path: Path,
    retailer_id: str | None = None,
) -> dict[str, Any]:
    """Create a publish handoff job file.

    Args:
        project: The project
        package_path: Path to the publish package directory
        retailer_id: Optional retailer ID

    Returns:
        Dict with success status and job info

    """
    # Verify package exists and has manifest
    manifest_path = package_path / "manifest.json"
    if not manifest_path.exists():
        return {"success": False, "error": "Package manifest not found"}

    try:
        with open(manifest_path, encoding="utf-8") as f:
            json.load(f)
    except Exception as exc:
        return {"success": False, "error": f"Failed to read manifest: {exc}"}

    # Calculate manifest SHA-256
    manifest_sha = _sha256_file(manifest_path)

    # Create job
    job_id = _generate_ulid()
    job = PublishJob(
        id=job_id,
        status="ready",
        package=str(package_path),
        manifestSha256=manifest_sha,
        createdAt=_utc_now_iso(),
        retailer=retailer_id,
    )

    # Write job file
    storage_path = project.storage.storagePath
    if not storage_path:
        return {"success": False, "error": "Project storage path not set"}
    jobs_dir = jobsDir(storage_path)
    job_file = jobs_dir / f"pj-{job_id}.json"

    _atomic_write_json(job_file, job.to_dict())

    return {"success": True, "jobId": job_id, "jobFile": str(job_file), "job": job.to_dict()}


def claim_publish_job(
    project: NWProject,
    job_id: str,
    claimer: str,
) -> dict[str, Any]:
    """Claim a publish job (atomically change status from ready to claimed).

    Args:
        project: The project
        job_id: The job ID to claim
        claimer: Identifier of the claiming tool/process

    Returns:
        Dict with success status and job info

    """
    storage_path = project.storage.storagePath
    if not storage_path:
        return {"success": False, "error": "Project storage path not set"}
    jobs_dir = jobsDir(storage_path)
    job_file = jobs_dir / f"pj-{job_id}.json"

    if not job_file.exists():
        return {"success": False, "error": "Job not found"}

    if _atomic_rename_claim(job_file, "claimed", claimer):
        with open(job_file, encoding="utf-8") as f:
            job_data = json.load(f)
        return {"success": True, "job": job_data}
    else:
        return {"success": False, "error": "Job not available for claiming (already claimed or not ready)"}


def complete_publish_job(
    project: NWProject,
    job_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Mark a publish job as done with result.

    Args:
        project: The project
        job_id: The job ID
        result: Result data from the external tool

    Returns:
        Dict with success status

    """
    storage_path = project.storage.storagePath
    if not storage_path:
        return {"success": False, "error": "Project storage path not set"}

    jobs_dir = jobsDir(storage_path)
    job_file = jobs_dir / f"pj-{job_id}.json"

    if not job_file.exists():
        return {"success": False, "error": "Job not found"}

    try:
        with open(job_file, encoding="utf-8") as f:
            job_data = json.load(f)

        if job_data.get("status") != "claimed":
            return {"success": False, "error": "Job not in claimed state"}

        job_data["status"] = "done"
        job_data["result"] = result

        _atomic_write_json(job_file, job_data)
        return {"success": True, "job": job_data}
    except Exception as exc:
        return {"success": False, "error": f"Failed to complete job: {exc}"}


def fail_publish_job(
    project: NWProject,
    job_id: str,
    error: str,
) -> dict[str, Any]:
    """Mark a publish job as failed.

    Args:
        project: The project
        job_id: The job ID
        error: Error message

    Returns:
        Dict with success status

    """
    storage_path = project.storage.storagePath
    if not storage_path:
        return {"success": False, "error": "Project storage path not set"}

    jobs_dir = jobsDir(storage_path)
    job_file = jobs_dir / f"pj-{job_id}.json"

    if not job_file.exists():
        return {"success": False, "error": "Job not found"}

    try:
        with open(job_file, encoding="utf-8") as f:
            job_data = json.load(f)

        job_data["status"] = "failed"
        job_data["result"] = {"error": error}

        _atomic_write_json(job_file, job_data)
        return {"success": True, "job": job_data}
    except Exception as exc:
        return {"success": False, "error": f"Failed to fail job: {exc}"}


def list_publish_jobs(project: NWProject) -> list[dict[str, Any]]:
    """List all publish jobs for a project."""
    storage_path = project.storage.storagePath
    if not storage_path:
        return []
    jobs_dir = jobsDir(storage_path)
    if not jobs_dir.exists():
        return []

    jobs = []
    for job_file in sorted(jobs_dir.glob("pj-*.json")):
        try:
            with open(job_file, encoding="utf-8") as f:
                job_data = json.load(f)
            jobs.append(job_data)
        except Exception:
            continue
    return jobs


def get_publish_job(project: NWProject, job_id: str) -> dict[str, Any] | None:
    """Get a specific publish job."""
    storage_path = project.storage.storagePath
    if not storage_path:
        return None
    jobs_dir = jobsDir(storage_path)
    job_file = jobs_dir / f"pj-{job_id}.json"

    if not job_file.exists():
        return None

    try:
        with open(job_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run_handoff_gates(project: NWProject, edition_id: str) -> dict[str, Any]:
    """Run publish.handoff gates before creating job."""
    scope = GateScope(
        project=project,
        edition=edition_id,
    )
    try:
        settings = project.settings if hasattr(project, "settings") else None
        requireGates(OP_PUBLISH_HANDOFF, scope, settings)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
