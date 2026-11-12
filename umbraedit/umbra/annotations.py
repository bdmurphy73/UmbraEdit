"""
UmbraEdit - Review Annotations
==============================

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

import contextlib
import json
import logging
import os
import time

from dataclasses import dataclass, field
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.paths import cacheDir

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable
    from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Annotation kinds
ANNOTATION_KINDS = frozenset({"note", "question", "todo"})

# Annotation statuses
ANNOTATION_STATUSES = frozenset({"open", "resolved"})

# Base32 alphabet for ID generation (Crockford's base32)
BASE32_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def _generate_annotation_id() -> str:
    """Generate an annotation ID: an- + 6 base32 chars."""
    # Use timestamp + random for uniqueness
    timestamp = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    random_part = os.urandom(3)
    combined = (timestamp << 24) | int.from_bytes(random_part, "big")

    # Convert to base32
    result = []
    for _ in range(6):
        result.append(BASE32_ALPHABET[combined & 0x1F])
        combined >>= 5
    return "an-" + "".join(reversed(result))


def _utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class AnnotationReply:
    """A reply to an annotation."""

    author: str
    at: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"author": self.author, "at": self.at, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotationReply:
        return cls(
            author=data["author"],
            at=data["at"],
            text=data["text"],
        )


@dataclass(frozen=True)
class Annotation:
    """An annotation record."""

    id: str
    handle: str
    kind: str  # note, question, todo
    status: str  # open, resolved
    author: str
    device: str
    at: str
    text: str
    replies: list[AnnotationReply] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "handle": self.handle,
            "kind": self.kind,
            "status": self.status,
            "author": self.author,
            "device": self.device,
            "at": self.at,
            "text": self.text,
            "replies": [r.to_dict() for r in self.replies],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Annotation:
        return cls(
            id=data["id"],
            handle=data["handle"],
            kind=data["kind"],
            status=data["status"],
            author=data["author"],
            device=data["device"],
            at=data["at"],
            text=data["text"],
            replies=[AnnotationReply.from_dict(r) for r in data.get("replies", [])],
        )


def _annotations_file(project_path: Path) -> Path:
    """Return the path to the annotations.jsonl file."""
    return cacheDir(project_path) / "annotations.jsonl"


def load_annotations(project_path: Path) -> list[Annotation]:
    """Load all annotations from the project's annotations.jsonl file."""
    path = _annotations_file(project_path)
    if not path.is_file():
        return []

    annotations = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        annotations.append(Annotation.from_dict(data))
                except json.JSONDecodeError:
                    logger.warning("Failed to parse annotation line: %s", line[:100])
    except Exception:
        logger.exception("Failed to load annotations from %s", path)
    return annotations


def save_annotations(project_path: Path, annotations: list[Annotation]) -> None:
    """Save all annotations to the project's annotations.jsonl file atomically."""
    path = _annotations_file(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            for ann in annotations:
                f.write(json.dumps(ann.to_dict(), separators=(",", ":"), sort_keys=True))
                f.write("\n")
        temp_path.replace(path)
    except Exception:
        logger.exception("Failed to save annotations to %s", path)
        with contextlib.suppress(OSError):
            temp_path.unlink()


def get_annotation(project_path: Path, annotation_id: str) -> Annotation | None:
    """Get a single annotation by ID."""
    for ann in load_annotations(project_path):
        if ann.id == annotation_id:
            return ann
    return None


def add_annotation(project_path: Path, annotation: Annotation) -> bool:
    """Add a new annotation."""
    annotations = load_annotations(project_path)
    # Check for duplicate ID
    if any(a.id == annotation.id for a in annotations):
        logger.warning("Annotation with ID %s already exists", annotation.id)
        return False
    annotations.append(annotation)
    save_annotations(project_path, annotations)
    return True


def update_annotation(project_path: Path, annotation: Annotation) -> bool:
    """Update an existing annotation."""
    annotations = load_annotations(project_path)
    for i, ann in enumerate(annotations):
        if ann.id == annotation.id:
            annotations[i] = annotation
            save_annotations(project_path, annotations)
            return True
    return False


def delete_annotation(project_path: Path, annotation_id: str) -> bool:
    """Delete an annotation by ID."""
    annotations = load_annotations(project_path)
    for i, ann in enumerate(annotations):
        if ann.id == annotation_id:
            annotations.pop(i)
            save_annotations(project_path, annotations)
            return True
    return False


def add_reply(project_path: Path, annotation_id: str, reply: AnnotationReply) -> bool:
    """Add a reply to an annotation."""
    annotations = load_annotations(project_path)
    for i, ann in enumerate(annotations):
        if ann.id == annotation_id:
            new_replies = [*list(ann.replies), reply]
            new_ann = Annotation(
                id=ann.id,
                handle=ann.handle,
                kind=ann.kind,
                status=ann.status,
                author=ann.author,
                device=ann.device,
                at=ann.at,
                text=ann.text,
                replies=new_replies,
            )
            annotations[i] = new_ann
            save_annotations(project_path, annotations)
            return True
    return False


def resolve_annotation(project_path: Path, annotation_id: str) -> bool:
    """Mark an annotation as resolved."""
    annotations = load_annotations(project_path)
    for i, ann in enumerate(annotations):
        if ann.id == annotation_id:
            if ann.status == "resolved":
                return False
            new_ann = Annotation(
                id=ann.id,
                handle=ann.handle,
                kind=ann.kind,
                status="resolved",
                author=ann.author,
                device=ann.device,
                at=ann.at,
                text=ann.text,
                replies=ann.replies,
            )
            annotations[i] = new_ann
            save_annotations(project_path, annotations)
            return True
    return False


def reopen_annotation(project_path: Path, annotation_id: str) -> bool:
    """Reopen a resolved annotation."""
    annotations = load_annotations(project_path)
    for i, ann in enumerate(annotations):
        if ann.id == annotation_id:
            if ann.status == "open":
                return False
            new_ann = Annotation(
                id=ann.id,
                handle=ann.handle,
                kind=ann.kind,
                status="open",
                author=ann.author,
                device=ann.device,
                at=ann.at,
                text=ann.text,
                replies=ann.replies,
            )
            annotations[i] = new_ann
            save_annotations(project_path, annotations)
            return True
    return False


def get_annotations_for_handle(project_path: Path, handle: str) -> list[Annotation]:
    """Get all annotations for a specific document handle."""
    return [a for a in load_annotations(project_path) if a.handle == handle]


def get_orphan_annotations(project_path: Path) -> list[Annotation]:
    """Get annotations that have no matching mark tag in the document."""
    # This is a stub - the actual implementation would check if the mark tag
    # exists in the document text. For now, we return empty list.
    return []


def iter_annotations(project_path: Path) -> Iterable[Annotation]:
    """Iterate over all annotations."""
    return load_annotations(project_path)
