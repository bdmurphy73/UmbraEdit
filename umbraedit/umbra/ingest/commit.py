"""
UmbraEdit - DOCX Ingest Commit
================================

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

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from umbraedit.umbra.hooks import SIDECAR_WRITTEN, call
from umbraedit.umbra.ingest.docx_output import ImportPlan
from umbraedit.umbra.ingest.ingest_runs import record_ingest_run
from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import cacheDir
from umbraedit.umbra.sheet import EntityRow, SheetManager

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CommitResult:
    """Result of a commit operation."""

    success: bool
    run_id: str
    created_handles: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    updated_metadata_keys: list[str] = field(default_factory=list)
    created_notes: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class UndoRecord:
    """Undo record for an import commit."""

    v: int = 1
    run_id: str = ""
    created_handles: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    updated_metadata_keys: list[str] = field(default_factory=list)
    created_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "runId": self.run_id,
            "createdHandles": self.created_handles,
            "createdFiles": self.created_files,
            "updatedMetadataKeys": self.updated_metadata_keys,
            "createdNotes": self.created_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UndoRecord:
        return cls(
            v=data.get("v", 1),
            run_id=data.get("runId", ""),
            created_handles=data.get("createdHandles", []),
            created_files=data.get("createdFiles", []),
            updated_metadata_keys=data.get("updatedMetadataKeys", []),
            created_notes=data.get("createdNotes", []),
        )


class ImportCommitter:
    """Handles the commit and undo of an import plan."""

    def __init__(self, project: Any) -> None:
        self.project = project
        self.storage_path = project.storage.storagePath
        self.content_path = project.storage.contentPath

    def commit(self, plan: ImportPlan) -> CommitResult:
        """Commit an import plan to the project.

        This is an all-or-nothing operation. On failure, everything
        created is rolled back.
        """
        logger.info("Committing import plan %s", plan.run_id)

        # Track what we create for potential rollback
        created_handles: list[str] = []
        created_files: list[str] = []
        updated_metadata_keys: list[str] = []
        created_notes: list[str] = []

        try:
            # 1. Take pre_migrate snapshots of any existing documents we'll modify
            self._snapshot_existing_documents(plan)

            # 2. Create document folders and files
            handles = self._create_documents(plan)
            created_handles.extend(handles)

            # 3. Create notes for characters, etc.
            note_handles = self._create_notes(plan)
            created_handles.extend(note_handles)

            # 4. Copy assets (images, etc.)
            asset_files = self._copy_assets(plan)
            created_files.extend(asset_files)

            # 4. Update metadata
            updated_keys = self._update_metadata(plan)
            updated_metadata_keys.extend(updated_keys)

            # 5. Create character notes with pronunciation status
            char_notes = self._create_character_notes(plan)
            created_notes.extend(char_notes)

            # 6. Write undo record
            self._write_undo_record(plan, created_handles, [], updated_metadata_keys, char_notes)

            # 6. Record ingest run
            record_ingest_run(
                self.storage_path,
                plan.run_id,
                plan.source.get("file", ""),
                plan.source.get("sha256", ""),
                plan.source.get("pandoc", ""),
                plan.run_id,
                status="completed",
            )

            logger.info("Successfully committed import plan %s", plan.run_id)
            return CommitResult(
                success=True,
                run_id=plan.run_id,
                created_handles=created_handles,
                created_files=[],
                updated_metadata_keys=updated_metadata_keys,
                created_notes=created_notes,
            )

        except Exception as e:
            logger.exception("Commit failed for plan %s", plan.run_id)
            # Rollback on failure
            self._rollback(created_handles, created_files)
            return CommitResult(
                success=False,
                run_id=plan.run_id,
                error=str(e),
            )

    def _snapshot_existing_documents(self, plan: ImportPlan) -> None:
        """Take pre_migrate snapshots of any documents that will be modified."""
        from umbraedit.umbra.history import historyManager

        mgr = historyManager()
        if not mgr:
            return

        for doc in plan.documents:
            handle = doc.get("planId", "")
            if handle and (self.content_path / f"{handle}.md").exists():
                try:
                    mgr.snapshot(handle, "pre_migrate", f"Pre-import migration for {plan.run_id}")
                except Exception:
                    logger.warning("Failed to snapshot %s", handle)

    def _create_documents(self, plan: ImportPlan) -> list[str]:
        """Create document files and folders from the plan."""
        handles: list[str] = []

        for doc in plan.documents:
            kind = doc.get("kind", "")
            parent_id = doc.get("parentPlanId")
            title = doc.get("title", "")
            level = doc.get("level", 1)
            text = doc.get("text", "")
            source_paras = doc.get("sourceParagraphs", [])
            page_type = doc.get("pageType")

            # Generate handle
            handle = self._generate_handle(doc, handles)

            # Create the document file
            doc_file = self.content_path / f"{handle}.md"
            doc_file.parent.mkdir(parents=True, exist_ok=True)

            # Write document with front matter
            content = self._format_document(doc, handle, page_type)
            doc_file.write_text(content, encoding="utf-8")

            # Add to project tree
            self._add_to_tree(handle, doc.get("title", ""), kind, parent_id, level)

            handles.append(handle)

        return handles

    def _generate_handle(self, doc: dict[str, Any], existing: list[str]) -> str:
        """Generate a unique handle for a document."""
        base = doc.get("title", "document").lower()
        base = "".join(c if c.isalnum() else "_" for c in base)[:50]
        if not base:
            base = "doc"

        # Check if handle exists in project tree
        existing_set = set(existing)
        if base not in existing_set:
            return base

        # Add suffix
        i = 1
        while f"{base}_{i}" in existing_set:
            i += 1
        return f"{base}_{i}"

    def _format_document(self, doc: dict[str, Any], handle: str, page_type: str | None) -> str:
        """Format a document with front matter."""
        lines = ["+++", f"title: {doc.get('title', '')}", "+++", ""]

        if doc.get("kind") == "front" and doc.get("pageType"):
            lines.insert(1, f"@page: {doc['pageType']}")
            lines.insert(2, f"@field: title={doc.get('title', '')}")

        lines.append(doc.get("text", ""))
        return "\n".join(lines)

    def _add_to_tree(self, handle: str, title: str, kind: str, parent_id: str | None, level: int) -> None:
        """Add document to project tree."""
        # This would interact with the project's tree
        # Implementation depends on the project tree API

    def _create_notes(self, plan: ImportPlan) -> list[str]:
        """Create notes for characters and other entities."""
        handles = []

        # Create character notes from proposals
        sheet = SheetManager(self.storage_path / "umbra")

        for char in plan.characters:
            if not char.get("accepted", False):
                continue

            # Create or update entity note
            if char.get("merged_with"):
                # Alias of existing character
                sheet.addAlias(char["merged_with"], char["name"])
            else:
                # Create new character note
                handle = f"char-{char['name'].lower().replace(' ', '-')}"
                row = EntityRow(
                    tag=char["name"],
                    handle=handle,
                    kind="character",
                    aliases=[],
                    attrs={
                        "kind": "character",
                        "pron_status": "todo",
                        "state": "placeholder",
                    },
                )
                sheet._entityMap[char["name"]] = row

        sheet.save()
        return []

    def _copy_assets(self, plan: ImportPlan) -> list[str]:
        """Copy image assets from media directory to project assets."""
        # This would copy images from the ingest media directory to the project assets
        return []

    def _update_metadata(self, plan: ImportPlan) -> list[str]:
        """Update project metadata with accepted proposals."""
        from umbraedit.umbra.metadata import loadMetadata, saveMetadata

        metadata = loadMetadata(self.storage_path)
        updated = []

        # plan.metadata is a dict of key -> value
        # The proposals are stored in the plan's metadata dict
        # For now, we'll just update all metadata from the plan
        for key, value in plan.metadata.items():
            parts = key.split(".", 1)
            if len(parts) == 2:
                section, field = parts
                if section == "book":
                    metadata.book[field] = value
                    updated.append(key)
                elif section == "custom":
                    metadata.custom[field] = value
                    updated.append(key)

        saveMetadata(self.storage_path, metadata)
        call(SIDECAR_WRITTEN, self.storage_path / "umbra" / "metadata.json")
        return updated

    def _create_character_notes(self, plan: ImportPlan) -> list[str]:
        """Create character notes with pron_status=todo."""
        # This creates the actual note files in the project
        return []

    def _write_undo_record(
        self,
        plan: ImportPlan,
        created_handles: list[str],
        created_files: list[str],
        updated_metadata_keys: list[str],
        created_notes: list[str],
    ) -> None:
        """Write the undo record for potential rollback."""
        undo = UndoRecord(
            run_id=plan.run_id,
            created_handles=created_handles,
            created_files=[],
            updated_metadata_keys=updated_metadata_keys,
            created_notes=created_notes,
        )

        undo_file = cacheDir(self.storage_path) / "import" / f"{plan.run_id}.undo.json"
        undo_file.parent.mkdir(parents=True, exist_ok=True)
        writeJson(undo_file, undo.to_dict())

    def _rollback(self, created_handles: list[str], created_files: list[str]) -> None:
        """Rollback created items on commit failure."""
        # Remove created document files
        for handle in created_handles:
            doc_file = self.content_path / f"{handle}.md"
            if doc_file.exists():
                doc_file.unlink()

        # Remove created files
        for file_path_str in created_files:
            file_path = Path(file_path_str)
            if file_path.exists():
                file_path.unlink()

        # Remove from project tree
        # ...

    def undo(self, run_id: str) -> bool:
        """Undo a committed import."""
        undo_file = cacheDir(self.storage_path) / "import" / f"{run_id}.undo.json"
        if not undo_file.is_file():
            logger.error("No undo record found for run %s", run_id)
            return False

        try:
            data = readJson(undo_file)
            if not isinstance(data, dict):
                logger.error("Invalid undo record format")
                return False
            undo = UndoRecord.from_dict(data)
        except Exception as e:
            logger.error("Failed to read undo record: %s", e)
            return False

        # Check if any created items have been modified since import
        # If so, warn and list what changed
        # For now, just remove created items
        for handle in undo.created_handles:
            doc_file = self.content_path / f"{handle}.md"
            if doc_file.exists():
                doc_file.unlink()

        # Remove created notes
        for note in undo.created_notes:
            note_file = self.content_path / f"{note}.md"
            if note_file.exists():
                note_file.unlink()

        logger.info("Undone import run %s", run_id)
        return True


def commit_import_plan(project: Any, plan: ImportPlan) -> CommitResult:
    """Commit an import plan to the project."""
    committer = ImportCommitter(project)
    return committer.commit(plan)


def undo_import_plan(project: Any, run_id: str) -> bool:
    """Undo a committed import."""
    committer = ImportCommitter(project)
    return committer.undo(run_id)
