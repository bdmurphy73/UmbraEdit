"""
UmbraEdit - Publish Package Builder
====================================

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
import subprocess

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.covers import loadCovers
from umbraedit.umbra.edition import EditionInfo, loadEdition
from umbraedit.umbra.gates import OP_PUBLISH_PACKAGE, GateScope, reportToJson, requireGates, runGates
from umbraedit.umbra.metadata import loadMetadata
from umbraedit.umbra.pages import PageManager
from umbraedit.umbra.paths import assetsDir

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Extended Markdown export: strip comments, %Voice: lines, resolve @tags, variables
# This is a simplified version - full implementation would use the tokenizer


class PublishPackageBuilder:
    """Builds a publish package for an edition."""

    def __init__(
        self,
        project: NWProject,
        edition_id: str,
        retailer_id: str | None = None,
        output_base: Path | None = None,
    ) -> None:
        self.project = project
        self.edition_id = edition_id
        self.retailer_id = retailer_id
        self.project_path = Path(project.storage.storagePath)
        self.edition_path = self.project_path.parent / f"{self.project_path.name}-ed-{edition_id}"
        self.output_base = output_base or (self.edition_path / "publish")
        self.package_dir = self.output_base / edition_id

    def _get_edition(self) -> EditionInfo | None:
        """Load edition metadata."""
        try:
            return loadEdition(self.edition_path)
        except Exception:
            return None

    def _get_source_metadata(self) -> Any:
        """Load source project metadata."""
        return loadMetadata(self.project_path)

    def _run_gates(self, options: dict | None = None) -> bool:
        """Run publish.package gates."""
        scope = GateScope(
            project=self.project,
            edition=self.edition_id,
            options=options or {"retailer": self.retailer_id},
        )
        try:
            settings = self.project.settings if hasattr(self.project, "settings") else None
            requireGates(OP_PUBLISH_PACKAGE, scope, settings)
            return True
        except Exception as exc:
            logger.error("Publish gates blocked: %s", exc)
            return False

    def _collect_documents(self) -> list[tuple[str, str, str]]:
        """Collect documents in matter order: front, body, back.
        Returns list of (handle, title, kind) where kind is front/body/back.
        """
        edition = self._get_edition()
        if not edition:
            return []

        # Get page documents for matter order
        page_manager = PageManager(self.edition_path)
        all_pages = page_manager.getAllPages()

        # Also get novel documents
        self._get_source_metadata()
        docs = []

        # Front matter
        front_types = (
            "frontMatter", "copyright", "dedication", "alsoBy", "epigraph",
            "map", "contents", "foreword", "preface", "acknowledgments",
            "introduction", "prologue"
        )
        for page in all_pages:
            page_type = page.get("pageType", "")
            matter = page.get("matter", "")
            if matter == "front" and page_type in front_types:
                doc_file = self.edition_path / "content" / f"{page.get('handle', '')}.md"
                if doc_file.exists():
                    docs.append((page.get("handle", ""), page.get("title", "") or page.get("handle", ""), "front"))

        # Body matter (chapters)
        for item in self.project.tree:
            if item.isFileType() and item.itemClass == self.project.classes.NOVEL:
                doc_file = self.edition_path / "content" / f"{item.itemHandle}.md"
                if doc_file.exists():
                    docs.append((item.itemHandle, item.itemName, "body"))

        # Back matter
        back_types = (
            "endMatter", "afterword", "epilogue", "appendix", "glossary",
            "bibliography", "index", "colophon", "aboutAuthor", "ads", "teaser"
        )
        for page in all_pages:
            page_type = page.get("pageType", "")
            matter = page.get("matter", "")
            if matter == "back" and page_type in back_types:
                doc_file = self.edition_path / "content" / f"{page.get('handle', '')}.md"
                if doc_file.exists():
                    docs.append((page.get("handle", ""), page.get("title", "") or page.get("handle", ""), "back"))

        return docs

    def _read_document(self, handle: str) -> str:
        """Read document text from edition."""
        doc_file = self.edition_path / "content" / f"{handle}.md"
        if doc_file.exists():
            return doc_file.read_text(encoding="utf-8")
        return ""

    def _strip_for_publish(self, text: str) -> str:
        """Strip comments, %Voice: lines, and resolve for publish export."""
        lines = text.split("\n")
        result = []
        in_frontmatter = False
        frontmatter_count = 0

        for line in lines:
            # Handle frontmatter
            if line.strip() == "+++":
                frontmatter_count += 1
                if frontmatter_count <= 2:
                    in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue

            # Strip %Voice: lines
            if line.strip().startswith("%Voice:"):
                continue

            # Strip comment lines
            if line.strip().startswith("%"):
                continue

            result.append(line)

        return "\n".join(result).strip() + "\n"

    def _collect_assets(self) -> dict[str, str]:
        """Collect used assets and return mapping of original path -> sha256 name."""
        assets_dir = assetsDir(self.edition_path)
        if not assets_dir.exists():
            return {}

        asset_map = {}
        for asset_file in assets_dir.iterdir():
            if asset_file.is_file():
                sha = self._sha256_file(asset_file)
                ext = asset_file.suffix
                new_name = f"{sha}{ext}"
                asset_map[str(asset_file)] = new_name
        return asset_map

    def _copy_assets(self, asset_map: dict[str, str]) -> None:
        """Copy assets to package with SHA-256 names."""
        assets_out = self.package_dir / "assets"
        assets_out.mkdir(parents=True, exist_ok=True)

        for src, dst_name in asset_map.items():
            dst = assets_out / dst_name
            if not dst.exists():
                shutil.copy2(src, dst)

    def _copy_covers(self) -> dict[str, str]:
        """Copy covers to package. Returns format -> filename mapping."""
        covers = loadCovers(self.edition_path)

        covers_out = self.package_dir / "covers"
        covers_out.mkdir(parents=True, exist_ok=True)

        result = {}
        for fmt, cover in covers.items():
            if cover.get("file"):
                src = self.edition_path / cover["file"]
                if src.exists():
                    ext = src.suffix
                    dst_name = f"{fmt}{ext}"
                    dst = covers_out / dst_name
                    shutil.copy2(src, dst)
                    result[fmt] = dst_name
        return result

    def _copy_audio(self) -> dict[str, Any] | None:
        """Copy audio package if ready. Returns audio manifest data."""
        edition = self._get_edition()
        if not edition:
            return None

        audio_dir = self.edition_path / "audio" / edition.editionId
        if not audio_dir.exists():
            return None

        manifest_path = audio_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return None

        # Check if all chapters are ready
        for chapter in manifest.get("chapters", []):
            if chapter.get("status") != "ready":
                return None

        # Copy audio directory
        audio_out = self.package_dir / "audio"
        if audio_out.exists():
            shutil.rmtree(audio_out)
        shutil.copytree(audio_dir, audio_out)

        return manifest

    def _copy_epub(self) -> dict[str, str] | None:
        """Copy EPUB output if built."""
        edition = self._get_edition()
        if not edition:
            return None

        # Look for EPUB in edition output
        epub_files = list(self.edition_path.glob("*.epub"))
        if not epub_files:
            return None

        epub_out = self.package_dir / "epub"
        epub_out.mkdir(parents=True, exist_ok=True)

        result = {}
        for epub in epub_files:
            dst = epub_out / epub.name
            shutil.copy2(epub, dst)
            result[epub.name] = f"epub/{epub.name}"
        return result

    def _copy_print(self) -> dict[str, str] | None:
        """Copy print PDF output if built."""
        edition = self._get_edition()
        if not edition:
            return None

        # Look for print PDF in edition output
        pdf_files = list(self.edition_path.glob("*print*.pdf"))
        if not pdf_files:
            return None

        print_out = self.package_dir / "print"
        print_out.mkdir(parents=True, exist_ok=True)

        result = {}
        for pdf in pdf_files:
            dst = print_out / pdf.name
            shutil.copy2(pdf, dst)
            result[pdf.name] = f"print/{pdf.name}"
        return result

    def _build_metadata_json(self) -> dict[str, Any]:
        """Build metadata.json for the package."""
        edition = self._get_edition()
        source_meta = self._get_source_metadata()

        if not edition or not source_meta:
            return {}

        return {
            "v": 1,
            "editionId": edition.editionId,
            "language": edition.language,
            "book": source_meta.book,
            "custom": source_meta.custom,
            "formats": source_meta.formats,
            "docs": {handle: doc.to_dict() for handle, doc in edition.docs.items()},
            "titleTemplate": edition.titleTemplate,
        }

    def _sha256_file(self, path: Path) -> str:
        """Calculate SHA-256 of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _verify_package(self, manifest: dict[str, Any]) -> bool:
        """Verify all files in package match manifest SHA-256."""
        for file_entry in manifest.get("files", []):
            file_path = self.package_dir / file_entry["path"]
            if not file_path.exists():
                logger.error("Missing file in package: %s", file_entry["path"])
                return False
            actual_sha = self._sha256_file(file_path)
            if actual_sha != file_entry["sha256"]:
                logger.error("SHA-256 mismatch for %s: expected %s, got %s",
                           file_entry["path"], file_entry["sha256"], actual_sha)
                return False
        return True

    def _parse_with_pandoc(self, md_path: Path) -> bool:
        """Parse manuscript.md with Pandoc to verify it's valid."""
        try:
            result = subprocess.run(
                ["pandoc", "--from=markdown", "--to=json", str(md_path)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.warning("Pandoc verification failed: %s", exc)
            return False

    def build(self) -> dict[str, Any]:
        """Build the complete publish package."""
        # Run gates
        if not self._run_gates({"retailer": self.retailer_id}):
            return {"success": False, "error": "Publish gates blocked"}

        # Clean/create package directory
        if self.package_dir.exists():
            shutil.rmtree(self.package_dir)
        self.package_dir.mkdir(parents=True, exist_ok=True)

        # Collect documents
        docs = self._collect_documents()

        # Build manuscript.md
        manuscript_parts = []
        for handle, title, _kind in docs:
            text = self._read_document(handle)
            stripped = self._strip_for_publish(text)
            manuscript_parts.append(f"# {title}\n\n{stripped}")

        manuscript_text = "\n\n---\n\n".join(manuscript_parts)

        manuscript_path = self.package_dir / "manuscript.md"
        manuscript_path.write_text(manuscript_text, encoding="utf-8", newline="\n")

        # Copy assets
        asset_map = self._collect_assets()
        self._copy_assets(asset_map)

        # Copy covers
        cover_map = self._copy_covers()

        # Copy audio if available
        audio_manifest = self._copy_audio()

        # Copy EPUB if available
        epub_map = self._copy_epub()

        # Copy print if available
        print_map = self._copy_print()

        # Build metadata.json
        metadata = self._build_metadata_json()
        metadata_path = self.package_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Build manifest.json with SHA-256 for every file
        manifest_files = []

        def add_file(rel_path: Path, category: str) -> None:
            abs_path = self.package_dir / rel_path
            if abs_path.exists():
                manifest_files.append({
                    "path": str(rel_path),
                    "sha256": self._sha256_file(abs_path),
                    "category": category,
                    "size": abs_path.stat().st_size,
                })

        add_file(Path("manuscript.md"), "manuscript")
        add_file(Path("metadata.json"), "metadata")

        for asset_name in asset_map.values():
            add_file(Path("assets") / asset_name, "asset")

        for cover_name in cover_map.values():
            add_file(Path("covers") / cover_name, "cover")

        if audio_manifest:
            # Add all audio files
            for root, _dirs, files in os.walk(self.package_dir / "audio"):
                for file in files:
                    rel = Path(root).relative_to(self.package_dir) / file
                    add_file(rel, "audio")

        if epub_map:
            for epub_name in epub_map:
                add_file(Path("epub") / epub_name, "epub")

        if print_map:
            for pdf_name in print_map:
                add_file(Path("print") / pdf_name, "print")

        manifest = {
            "v": SCHEMA_VERSION,
            "editionId": self.edition_id,
            "retailer": self.retailer_id,
            "createdAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files": manifest_files,
        }

        manifest_path = self.package_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Verify package
        if not self._verify_package(manifest):
            shutil.rmtree(self.package_dir)
            return {"success": False, "error": "Package verification failed (SHA-256 mismatch)"}

        # Verify manuscript.md with Pandoc
        if not self._parse_with_pandoc(manuscript_path):
            shutil.rmtree(self.package_dir)
            return {"success": False, "error": "Manuscript.md failed Pandoc validation"}

        # Run gate report and save as checks.json
        scope = GateScope(
            project=self.project,
            edition=self.edition_id,
            options={"retailer": self.retailer_id},
        )
        settings = self.project.settings if hasattr(self.project, "settings") else None
        report = runGates(OP_PUBLISH_PACKAGE, scope, settings)
        checks_path = self.package_dir / "checks.json"
        checks_path.write_text(
            json.dumps(reportToJson(report), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return {
            "success": True,
            "packagePath": str(self.package_dir),
            "manifest": manifest,
        }


def build_publish_package(
    project: NWProject,
    edition_id: str,
    retailer_id: str | None = None,
    output_base: Path | None = None,
) -> dict[str, Any]:
    """Build publish package for an edition."""
    builder = PublishPackageBuilder(project, edition_id, retailer_id, output_base)
    return builder.build()
