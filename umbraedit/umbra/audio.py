"""
UmbraEdit - Audio Package Builder
==================================

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
import shutil

from dataclasses import dataclass, field
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.lexicon import collectLexemes, exportLexicon
from umbraedit.umbra.metadata import loadMetadata
from umbraedit.umbra.paths import assetsDir
from umbraedit.umbra.sheet import SheetManager
from umbraedit.umbra.utterances import (
    deriveUtterances,
)
from umbraedit.umbra.voicestore import VoiceStore

if TYPE_CHECKING:  # pragma: no cover

    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Default minimum pause durations (ms)
DEFAULT_MIN_PAUSE_MS = 250
PARAGRAPH_PAUSE_MS = 600
SCENE_BREAK_PAUSE_MS = 1200


@dataclass(frozen=True)
class UtteranceRecord:
    """An utterance record for the audio package."""

    id: str
    text: str
    voice: str  # voice matrix code
    pause_after_ms: int
    attribution: list[str] = field(default_factory=list)
    skip: str | None = None
    pron: list[dict[str, Any]] = field(default_factory=list)
    speaker: str | None = None
    tone: str | None = None
    lang: str | None = None


@dataclass(frozen=True)
class ChapterAudio:
    """Audio package data for a chapter."""

    handle: str
    title: str
    order: int
    file: str
    sha256: str
    utterances: list[UtteranceRecord]
    status: str  # "ready" | "test"


@dataclass(frozen=True)
class MatterAudio:
    """Audio for front/end matter."""

    file: str
    utterances: list[UtteranceRecord]


@dataclass(frozen=True)
class VoiceInfo:
    """Voice matrix info for manifest."""

    code: str
    label: str
    engine: str
    languages: list[str]
    used_by: list[str]


@dataclass(frozen=True)
class CharacterInfo:
    """Character info for manifest."""

    tag: str
    name: str
    kind: str
    voice_code: str | None
    languages: list[str]


@dataclass(frozen=True)
class AudioManifest:
    """Audio package manifest."""

    v: int = 1
    book: str = ""
    edition: str = ""
    created_at: str = ""
    tool: str = ""
    cover: dict[str, str] = field(default_factory=dict)
    chapters: list[dict[str, Any]] = field(default_factory=list)
    matter: dict[str, str] = field(default_factory=dict)
    voices: list[dict[str, Any]] = field(default_factory=list)
    lexicon: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest to dictionary for JSON serialization."""
        return {
            "v": self.v,
            "book": self.book,
            "edition": self.edition,
            "createdAt": self.created_at,
            "tool": self.tool,
            "cover": self.cover,
            "chapters": self.chapters,
            "matter": self.matter,
            "voices": self.voices,
            "lexicon": self.lexicon,
        }


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


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _is_ready(utterances: list[UtteranceRecord]) -> bool:
    """Check if all utterances in a chapter are ready.
    Stub implementation - always returns True.
    """
    return True


class AudioPackageBuilder:
    """Builds an audio package for an edition."""

    def __init__(self, project: NWProject, edition_id: str) -> None:
        self.project = project
        self.edition_id = edition_id
        storage_path = project.storage.storagePath
        if not storage_path:
            raise ValueError("Project storage path is not set")
        self.project_path = Path(storage_path)
        self.edition_path = self.project_path.parent / f"{self.project_path.name}-ed-{edition_id}"
        self.output_dir = self.edition_path / "audio" / edition_id
        self.assets_dir = assetsDir(self.edition_path)
        self.edition_assets_dir = assetsDir(Path(self.edition_path))

    def _get_edition_sheet(self) -> SheetManager:
        """Get the edition's sheet manager."""
        sheet = SheetManager(self.edition_path / "umbra")
        sheet.buildFromProject(str(self.edition_path))
        return sheet

    def _get_source_sheet(self) -> SheetManager:
        """Get the source project's sheet manager."""
        source_path = self.edition_path.parent / self.edition_path.name.replace(f"-ed-{self.edition_id}", "")
        sheet = SheetManager(Path(source_path) / "umbra")
        sheet.buildFromProject(str(source_path))
        return sheet

    def _get_voice_store(self) -> VoiceStore:
        """Get the edition's voice store."""
        return VoiceStore(self.edition_path)

    def _get_source_voice_store(self) -> VoiceStore:
        """Get the source project's voice store."""
        source_path = self.edition_path.parent / self.edition_path.name.replace(f"-ed-{self.edition_id}", "")
        return VoiceStore(Path(source_path))

    def _get_lexicon(self) -> list:
        """Get the pronunciation lexicon data for the edition language."""
        edition = loadMetadata(self.edition_path)
        lang = edition.book.get("language", "en")
        from umbraedit.umbra.sheet import SheetManager
        sheet = SheetManager(self.edition_path / "umbra")
        sheet.buildFromProject(str(self.edition_path))
        rows = sheet.iterEntities()
        return collectLexemes(rows, lang)

    def _get_edition_metadata(self) -> dict[str, Any]:
        """Get edition metadata."""
        meta = loadMetadata(self.edition_path)
        return {
            "book": dict(meta.book),
            "custom": dict(meta.custom),
            "formats": dict(meta.formats) if meta.formats else {},
        }

    def _get_source_metadata(self) -> dict[str, Any]:
        """Get source project metadata."""
        source_path = self.edition_path.parent / self.edition_path.name.replace(f"-ed-{self.edition_id}", "")
        meta = loadMetadata(Path(source_path))
        return {
            "book": dict(meta.book),
            "custom": dict(meta.custom),
            "formats": dict(meta.formats) if meta.formats else {},
        }

    def _get_cover_path(self) -> Path | None:
        """Get the audiobook cover path."""
        meta = self._get_edition_metadata()
        cover_file = meta["formats"].get("audiobook", {}).get("cover")
        if cover_file:
            cover_path = self.edition_path / cover_file
            if cover_path.exists():
                return cover_path
        return None

    def _copy_cover(self, output_dir: Path) -> dict[str, str] | None:
        """Copy cover image to output directory."""
        cover_path = self._get_cover_path()
        if not cover_path:
            return None
        dest = output_dir / ("cover" + cover_path.suffix)
        shutil.copy2(cover_path, dest)
        return {
            "file": dest.name,
            "sha256": _sha256_file(dest),
        }

    def _collect_voice_matrices(self, utterances: list[dict]) -> set[str]:
        """Collect voice matrix codes used in utterances."""
        codes = set()
        for u in utterances:
            if u.get("voice"):
                codes.add(u["voice"])
        return codes

    def _copy_voice_matrices(self, codes: set[str], output_dir: Path) -> None:
        """Copy voice matrix files to output directory."""
        voice_store = self._get_voice_store()
        source_store = self._get_source_voice_store()
        voices_dir = output_dir / "voices"
        voices_dir.mkdir(parents=True, exist_ok=True)

        for code in codes:
            # Try edition store first, then source
            data = voice_store.getVoiceMatrix(code)
            if data is None:
                data = source_store.getVoiceMatrix(code)
            if data:
                dest = voices_dir / f"{code}.uvmx"
                _atomic_write_bytes(dest, data)

    def _build_voices_json(self, codes: set[str]) -> list[dict]:
        """Build voices.json entries."""
        voice_store = self._get_voice_store()
        self._get_source_voice_store()
        sheet = self._get_edition_sheet()

        entries = []
        for code in sorted(codes):
            entry = voice_store.getVoiceEntry(code)
            if not entry:
                entry = self._get_source_voice_store().getVoiceEntry(code)
            if entry:
                # Find which characters use this voice
                used_by = [
                    entity.tag
                    for entity in sheet.iterEntities()
                    if entity.attrs.get("voice_matrix") == code
                ]
                entries.append({
                    "code": entry.code,
                    "label": entry.label,
                    "engine": entry.engine,
                    "languages": entry.languages,
                    "used_by": used_by,
                })
        return entries

    def _build_characters_json(self, utterances: list[dict]) -> list[dict]:
        """Build characters.json from utterances."""
        sheet = self._get_edition_sheet()
        speakers = set()
        for u in utterances:
            if u.get("speaker"):
                speakers.add(u["speaker"])

        chars = []
        for tag in sorted(speakers):
            entity = sheet.getEntity(tag)
            if entity:
                chars.append({
                    "tag": entity.tag,
                    "name": entity.tag,
                    "kind": entity.kind,
                    "voice_code": entity.attrs.get("voice_matrix"),
                    "languages": entity.attrs.get("languages", "").split(",") if entity.attrs.get("languages") else [],
                })
        return chars

    def _build_tones_json(self) -> list[dict[str, Any]]:
        """Build tones.json from edition."""
        sheet = self._get_edition_sheet()
        tones = sheet.loadTones()
        return [
            {
                "key": t.key,
                "label": t.label,
                "appliesTo": t.appliesTo,
                "audioHint": t.audioHint,
                "order": t.order,
            }
            for t in tones
        ]

    def _copy_lexicon(self, output_dir: Path) -> str:
        """Copy lexicon files to output directory."""
        meta = self._get_edition_metadata()
        lang = meta["book"].get("language", "en")
        dest = output_dir / f"lexicon.{lang}.pls"
        exportLexicon(self.edition_path, lang, dest)
        # Also write JSON version
        json_dest = output_dir / f"lexicon.{lang}.json"
        exportLexicon(self.edition_path, lang, json_dest)
        return f"lexicon.{lang}.pls"

    def _get_chapter_utterances(self, chapter_handle: str) -> list[dict]:
        """Get utterances for a chapter."""
        # Read chapter content
        content_path = self.edition_path / "content" / f"{chapter_handle}.md"
        if not content_path.exists():
            return []

        text = content_path.read_text(encoding="utf-8")

        # Get project index
        from umbraedit.umbra.sheet import SheetManager
        sheet = SheetManager(self.edition_path / "umbra")
        sheet.buildFromProject(str(self.edition_path))
        index = sheet

        # Get voice store
        from umbraedit.umbra.voicestore import VoiceStore
        store = VoiceStore(self.edition_path)

        # Derive utterances
        utterances = deriveUtterances(
            handle=chapter_handle,
            text=text,
            project=None,  # We don't have full project here, but index is used
            index=index,
            store=store,
        )

        # Convert to dict format expected by _process_utterances
        return [
            {
                "id": u.id,
                "text": u.text,
                "speaker": u.speaker,
                "voice": u.voice,
                "tone": u.tone,
                "toneI": u.toneI,
                "lang": u.lang,
                "kind": u.kind,
                "skip": u.skip,
                "attribution": u.attribution,
                "pronunciation": u.pron,
            }
            for u in utterances
        ]

    def _process_utterances(self, utterances: list) -> list[UtteranceRecord]:
        """Process utterances into audio package records."""
        records = []
        for u in utterances:
            # Get voice matrix code for speaker
            voice_code = u.get("voice", "")
            if not voice_code:
                # Try to get from speaker entity
                speaker = u.get("speaker", "")
                if speaker:
                    sheet = self._get_edition_sheet()
                    entity = sheet.getEntity(speaker)
                    if entity:
                        voice_code = entity.attrs.get("voice_matrix", "")

            # Get pronunciation spans
            pron_spans = u.get("pronunciation", [])
            pron_list = [
                {
                    "start": span.start,
                    "end": span.end,
                    "tag": span.tag,
                    "respelling": span.respelling,
                    "ipa": span.ipa,
                }
                for span in pron_spans
            ]

            # Get attribution
            attribution = u.get("attribution", [])

            # Determine skip
            skip = None
            if u.get("attrib_drop"):
                skip = "attribution"

            # Determine pause after
            pause_after = self._calculate_pause_after(u)

            record = UtteranceRecord(
                id=u.get("id", ""),
                text=u.get("text", ""),
                voice=voice_code,
                pause_after_ms=pause_after,
                attribution=attribution,
                skip=skip,
                pron=pron_list,
                speaker=u.get("speaker"),
                tone=u.get("tone"),
                lang=u.get("lang"),
            )
            records.append(record)
        return records

    def _calculate_pause_after(self, utterance: dict) -> int:
        """Calculate pause after utterance."""
        # This is simplified - real implementation would consider
        # paragraph breaks, scene breaks, etc.
        return DEFAULT_MIN_PAUSE_MS

    def _build_chapter_audio(self, chapter_handle: str, order: int) -> ChapterAudio:
        """Build audio data for a chapter."""
        utterances = self._get_chapter_utterances(chapter_handle)
        if not utterances:
            return ChapterAudio(
                handle=chapter_handle,
                title="",
                order=order,
                file=f"chapters/{chapter_handle}.jsonl",
                sha256="",
                utterances=[],
                status="test",
            )

        # Process utterances
        self._process_utterances(utterances)

        # Write chapter JSONL
        output_dir = self.output_dir / "chapters"
        output_dir.mkdir(parents=True, exist_ok=True)
        _ = output_dir / f"{chapter_handle}.jsonl"

        # For now, create placeholder
        return ChapterAudio(
            handle=chapter_handle,
            title="",
            order=order,
            file=f"chapters/{chapter_handle}.jsonl",
            sha256="",
            utterances=[],
            status="test",
        )

    def _build_matter_audio(self) -> tuple[MatterAudio | None, MatterAudio | None]:
        """Build spoken front and end matter."""
        # Get spoken matter pages from P21
        # This would query the pages system for pages with audio variant = spoken
        return None, None

    def _build_report(self, chapter_handle: str) -> dict:
        """Build report for a chapter."""
        return {
            "dropped_attributions": [],
            "removed_chars": 0,
            "total_chars": 0,
            "pronunciation_entries": 0,
        }

    def build_chapter(self, chapter_handle: str, order: int) -> ChapterAudio:
        """Build audio package for a single chapter."""
        # Run gates

        # This would need a proper project scope
        # For now, return a test chapter
        return self._build_chapter_audio(chapter_handle, order)

    def build_book(self) -> dict:
        """Build complete audio package for the edition."""
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy cover first
        cover_info = self._copy_cover(self.output_dir)

        # Copy voice matrices (placeholder - would need actual voice codes)
        voice_codes = set()

        # Get all chapters (placeholder - would iterate over edition chapters)
        chapters = []

        # Build chapters (placeholder)
        for i, chapter in enumerate(chapters):
            chapter_audio = self._build_chapter_audio(chapter, i + 1)
            chapters.append({
                "handle": chapter_audio.handle,
                "title": chapter_audio.title,
                "order": chapter_audio.order,
                "file": chapter_audio.file,
                "sha256": chapter_audio.sha256,
                "utterances": len(chapter_audio.utterances),
                "status": chapter_audio.status,
            })
            # Collect voice codes
            for u in chapter_audio.utterances:
                if u.voice:
                    voice_codes.add(u.voice)

        # Copy voice matrices
        self._copy_voice_matrices(voice_codes, self.output_dir)

        # Build voices.json
        voices = self._build_voices_json(voice_codes)

        # Copy lexicon
        lexicon = self._copy_lexicon(self.output_dir)

        # Create manifest with all data
        manifest = AudioManifest(
            book="",
            edition=self.edition_id,
            created_at=_utc_now_iso(),
            tool="UmbraEdit",
            cover=cover_info or {},
            chapters=chapters,
            voices=voices,
            lexicon=lexicon,
        )

        # Write manifest
        _atomic_write_json(self.output_dir / "manifest.json", manifest.to_dict())

        return {"success": True, "path": str(self.output_dir)}


def build_audio_chapter(project: NWProject, edition_id: str, chapter_handle: str) -> dict:
    """Build audio package for a single chapter."""
    builder = AudioPackageBuilder(project, edition_id)
    chapter_audio = builder.build_chapter(edition_id, 1)
    return {"success": True, "chapter": chapter_audio}


def build_audio_book(project: NWProject, edition_id: str) -> dict:
    """Build complete audio package for an edition."""
    builder = AudioPackageBuilder(project, edition_id)
    return builder.build_book()


def _get_narration_speaker(project_path: Path, edition_lang: str) -> str:
    """Get the narration speaker for the edition."""
    meta = loadMetadata(Path(project_path))
    narrator = meta.formats.get("audiobook", {}).get("narrator")
    if narrator:
        return narrator
    # Default to first narrator entity
    return "Narrator"


if __name__ == "__main__":
    pass
