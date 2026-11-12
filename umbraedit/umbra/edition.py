"""
UmbraEdit - Edition Management
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

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.metadata import loadMetadata, Metadata
from umbraedit.umbra.paths import editionFile, metadataFile
from umbraedit.umbra.sheet import SheetManager, EntityRow

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Default edition configuration
DEFAULT_EDITION = {
    "v": SCHEMA_VERSION,
    "editionId": "",
    "language": "",
    "source": {
        "path": "",
        "editionId": "main",
        "projectId": "",
    },
    "docs": {},
    "titleTemplate": {"chapter": "Chapter {n}"},
    "translatable": [
        "book.title",
        "book.subtitle",
        "book.description",
        "book.keywords",
        "book.bisac",
        "custom.dedicationName",
    ],
    "pending": [],
}


@dataclass(frozen=True)
class EditionDoc:
    """Edition document status."""

    handle: str
    baseTextHash: str
    translatedAt: str | None = None
    status: str = "untranslated"  # untranslated, translated, stale
    guideAnalysis: str | None = None
    guideStatusAtTranslation: str | None = None


@dataclass(frozen=True)
class EditionInfo:
    """Edition metadata."""

    v: int = 1
    editionId: str = ""
    language: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    docs: dict[str, EditionDoc] = field(default_factory=dict)
    titleTemplate: dict[str, str] = field(default_factory=dict)
    translatable: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "editionId": self.editionId,
            "language": self.language,
            "source": self.source,
            "docs": {k: v.__dict__ for k, v in self.docs.items()},
            "titleTemplate": self.titleTemplate,
            "translatable": self.translatable,
            "pending": self.pending,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditionInfo:
        docs = {}
        for k, v in data.get("docs", {}).items():
            docs[k] = EditionDoc(**v)
        return cls(
            v=data.get("v", 1),
            editionId=data.get("editionId", ""),
            language=data.get("language", ""),
            source=data.get("source", {}),
            docs=docs,
            titleTemplate=data.get("titleTemplate", {"chapter": "Chapter {n}"}),
            translatable=data.get("translatable", []),
            pending=data.get("pending", []),
        )


def editionFilePath(projectPath: Path) -> Path:
    """Return the path to the edition.json file."""
    return editionFile(projectPath)


def loadEdition(projectPath: Path) -> EditionInfo:
    """Load edition info from project's umbra/edition.json."""
    path = editionFilePath(projectPath)
    if not path.is_file():
        return EditionInfo()
    try:
        data = readJson(path)
        if isinstance(data, dict):
            return EditionInfo.from_dict(data)
        logger.warning("edition.json does not contain an object, returning defaults")
        return EditionInfo()
    except Exception as e:
        logger.exception("Failed to load edition from %s", path)
        return EditionInfo()


def saveEdition(projectPath: Path, edition: EditionInfo) -> None:
    """Save edition info to project's umbra/edition.json atomically."""
    path = editionFilePath(projectPath)
    path.parent.mkdir(parents=True, exist_ok=True)
    writeJson(path, edition.to_dict())


def editionDirPath(projectPath: Path, editionId: str) -> Path:
    """Return the edition project directory path."""
    return projectPath.parent / f"{projectPath.name}-ed-{editionId}"


def createEdition(
    sourceProjectPath: Path,
    editionId: str,
    language: str,
    emptyText: bool = False,
    copyPronunciation: bool = False,
) -> Path | None:
    """
    Create a new edition project from a source project.

    Args:
        sourceProjectPath: Path to the source project
        editionId: Edition identifier (e.g., "zh-Hans")
        language: BCP 47 language code
        emptyText: If True, create documents with empty text instead of "untranslated"
        copyPronunciation: If True, copy pronunciation data (default: False)

    Returns:
        Path to the new edition project, or None on failure
    """
    editionPath = editionDirPath(sourceProjectPath, editionId)

    try:
        # Create edition directory
        editionPath.mkdir(parents=True, exist_ok=True)

        # Copy source project structure
        _copyProjectTree(sourceProjectPath, editionPath, emptyText, copyPronunciation)

        # Load source metadata
        sourceMetadata = loadMetadata(sourceProjectPath)

        # Create edition metadata
        editionMetadata = Metadata()
        editionMetadata.book = sourceMetadata.book.copy()
        editionMetadata.book["language"] = language
        editionMetadata.formats = sourceMetadata.formats.copy()
        editionMetadata.custom = sourceMetadata.custom.copy()

        # Mark translatable fields as pending
        editionPending = []
        for key in ["book.title", "book.subtitle", "book.description",
                    "book.keywords", "book.bisac", "custom.dedicationName"]:
            editionPending.append(key)

        # Save edition metadata
        saveMetadata(editionPath, editionMetadata)

        # Create edition.json
        editionInfo = EditionInfo(
            v=1,
            editionId=editionId,
            language=language,
            source={
                "path": str(sourceProjectPath.relative_to(editionPath.parent)),
                "editionId": "main",
                "projectId": "",
            },
            docs={},
            titleTemplate={"chapter": "Chapter {n}"},
            translatable=[
                "book.title",
                "book.subtitle",
                "book.description",
                "book.keywords",
                "book.bisac",
                "custom.dedicationName",
            ],
            pending=editionPending,
        )
        saveEdition(editionPath, editionInfo)

        # Copy entity notes (without pronunciation/voice_matrix)
        _copyEntityNotes(sourceProjectPath, editionPath, copyPronunciation)

        logger.info("Created edition %s at %s", editionId, editionPath)
        return editionPath

    except Exception as e:
        logger.exception("Failed to create edition: %s", e)
        # Clean up on failure
        if editionPath.exists():
            shutil.rmtree(editionPath, ignore_errors=True)
        return None


def _copyProjectTree(
    sourcePath: Path,
    destPath: Path,
    emptyText: bool,
    copyPronunciation: bool,
) -> None:
    """Copy project tree, handling document text appropriately."""
    contentSrc = sourcePath / "content"
    contentDest = destPath / "content"
    contentDest.mkdir(parents=True, exist_ok=True)

    for srcFile in contentSrc.glob("*.md"):
        destFile = contentDest / srcFile.name
        if emptyText:
            destFile.write_text("", encoding="utf-8")
        else:
            text = srcFile.read_text(encoding="utf-8")
            # Add status: untranslated to front matter
            if not text.startswith("+++"):
                text = "+++\n+++\n" + text
            parts = text.split("+++", 2)
            if len(parts) >= 3:
                header = parts[1]
                body = parts[2]
                # Add status keyword
                if "@status:" not in header:
                    header += "\n@status: untranslated"
                text = f"+++{header}+++\n{body}"
            destFile.write_text(text, encoding="utf-8")

    # Copy other project files
    for item in sourcePath.iterdir():
        if item.name in {"content", "umbra"}:
            continue
        dest = destPath / item.name
        if item.is_file():
            shutil.copy2(item, dest)
        elif item.is_dir():
            shutil.copytree(item, dest)


def _copyEntityNotes(
    sourcePath: Path,
    destPath: Path,
    copyPronunciation: bool,
) -> None:
    """Copy entity notes from source to edition, adjusting pronunciation data."""
    sourceSheet = SheetManager(sourcePath / "umbra")
    sourceSheet.buildFromProject(sourcePath)  # type: ignore

    destSheet = SheetManager(destPath / "umbra")
    destSheet.buildFromProject(destPath)  # type: ignore

    for entity in sourceSheet.iterEntities():
        if copyPronunciation:
            # Copy as-is
            destSheet._entityMap[entity.handle] = entity
        else:
            # Copy without pronunciation/voice_matrix
            newEntity = EntityRow(
                tag=entity.tag,
                handle=entity.handle,
                kind=entity.kind,
                aliases=entity.aliases.copy(),
                attrs=entity.attrs.copy(),
            )
            newEntity.attrs["pron_status"] = "todo"
            newEntity.attrs.pop("voice_matrix", None)
            newEntity.attrs.pop("pronunciation", None)
            destSheet._entityMap[entity.handle] = newEntity


def getEditionStatus(
    editionPath: Path,
    handle: str,
    sourceProject: Any,
) -> str:
    """Get the translation status of a document in the edition."""
    edition = loadEdition(editionPath)
    doc = edition.docs.get(handle)
    if not doc:
        return "untranslated"

    # Check if source document has changed
    sourceProjectPath = editionPath.parent / edition.source["path"]
    sourceMetadata = loadMetadata(sourceProjectPath)
    sourceHash = sourceProject.getDocumentHash(handle)  # type: ignore

    if doc.baseTextHash != sourceHash:
        # Check if guide analysis changed
        guideAnalysis = doc.guideAnalysis
        if guideAnalysis:
            # Check guide status at translation time
            pass
        return "stale"

    return doc.status


def markAsTranslated(editionPath: Path, handle: str, sourceHash: str, analysisHash: str | None = None) -> bool:
    """Mark a document as translated in the edition."""
    edition = loadEdition(editionPath)
    if handle not in edition.docs:
        edition.docs[handle] = EditionDoc(handle=handle, baseTextHash=sourceHash)

    edition.docs[handle].status = "translated"
    edition.docs[handle].translatedAt = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    edition.docs[handle].baseTextHash = sourceHash
    if analysisHash:
        edition.docs[handle].guideAnalysis = analysisHash

    saveEdition(editionPath, edition)
    return True


def getPendingMetadata(editionPath: Path) -> list[str]:
    """Get list of pending metadata keys for the edition."""
    edition = loadEdition(editionPath)
    return edition.pending


def markMetadataTranslated(editionPath: Path, key: str) -> bool:
    """Mark a metadata key as translated."""
    edition = loadEdition(editionPath)
    if key in edition.pending:
        edition.pending.remove(key)
        saveEdition(editionPath, edition)
        return True
    return False


def getAlignment(editionPath: Path, handle: str) -> list[list[str | int]] | None:
    """Get paragraph alignment for a document."""
    alignFile = editionPath / "umbra" / "align" / f"{handle}.json"
    if not alignFile.is_file():
        return None
    try:
        data = readJson(alignFile)
        return data.get("pairs")
    except Exception:
        return None


def setAlignment(editionPath: Path, handle: str, pairs: list[list[int | str]]) -> bool:
    """Set paragraph alignment for a document."""
    alignFile = editionPath / "umbra" / "align" / f"{handle}.json"
    alignFile.parent.mkdir(parents=True, exist_ok=True)
    data = {"pairs": pairs}
    writeJson(alignFile, data)
    return True


def glossary(editionPath: Path) -> list[dict[str, str]]:
    """Build translation glossary for the edition."""
    from umbraedit.umbra.jsonio import readJson
    from umbraedit.umbra.sheet import EntityRow

    sheet_file = editionPath / "umbra" / "sheet.json"
    if not sheet_file.is_file():
        return []

    try:
        data = readJson(sheet_file)
        if not isinstance(data, dict):
            return []
    except Exception:
        return []

    entries = []
    for entity_data in data.get("entities", []):
        try:
            entity = EntityRow(**entity_data)
        except Exception:
            continue
        if entity.kind != "character":
            continue
        tag = entity.tag
        sourceForm = entity.tag
        targetForm = entity.attrs.get("name_target", entity.tag)
        pronunciation = entity.attrs.get("pronunciation", "")
        entries.append({
            "source": sourceForm,
            "target": targetForm,
            "pronunciation": pronunciation,
        })
    return entries


from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from umbraedit.umbra.guide import GuideDoc, parseGuideDoc
from umbraedit.umbra.guide import analysisStatus, staleParaNotes
from umbraedit.umbra.sheet import SheetManager, EntityRow
from umbraedit.umbra.paths import alignDir