"""
UmbraEdit - Pandoc JSON AST Tokenizer
======================================

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
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.formats.tokenizer import Tokenizer
from umbraedit.umbra.edition import EditionDoc, EditionInfo, loadEdition, saveEdition
from umbraedit.umbra.guide import parseGuideDoc
from umbraedit.umbra.paths import jobsDir, promptsDir
from umbraedit.umbra.settings import umbraSettings
from umbraedit.umbra.units import UnitKind, iterUnits

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# JSON schema for translation output validation
TRANSLATION_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["chapter", "paragraphs"],
    "properties": {
        "chapter": {"type": "string"},
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "text"],
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                    "attribution": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}

# Default translation prompt template
DEFAULT_TRANSLATION_PROMPT = (
    "Translate the following chapter from {sourceLanguage} to {targetLanguage}.\n\n"
    "Book: {{bookTitle}}\n"
    "Chapter: {{chapterTitle}}\n\n"
    "Style Guide:\n{{styleGuide}}\n\n"
    "Analysis:\n{{analysis}}\n\n"
    "Glossary (source form → target form, pronunciation):\n{{glossary}}\n\n"
    "Cast Voices (speaker, relationships, typical register):\n{{castVoices}}\n\n"
    "Previous Chapter Tail (last 3 translated paragraphs):\n{{previousTail}}\n\n"
    "Source Paragraphs (numbered, with notes and voice info):\n{{paragraphs}}\n\n"
    "Instructions:\n{{instructions}}\n\n"
    "Output Schema:\n{{outputSchema}}\n\n"
    "Output ONLY valid JSON matching the schema exactly. No extra text."
)

# Fixed instructions for translation
TRANSLATION_INSTRUCTIONS = (
    "Translate for meaning and intent, keep the voice and register, "
    "do not translate word for word, keep names as in the glossary, "
    "keep paragraph count, return JSON."
)


@dataclass(frozen=True)
class TranslationJob:
    """A translation job for a chapter or metadata."""

    v: int = 1
    id: str = ""
    edition: str = ""
    chapter: str = ""
    kind: str = "chapter"  # chapter, metadata
    status: str = "ready"  # ready, running, done, failed
    prompt_file: str = ""
    analysis_hash: str = ""
    source_hash: str = ""
    created_at: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "id": self.id,
            "edition": self.edition,
            "chapter": self.chapter,
            "kind": self.kind,
            "status": self.status,
            "promptFile": self.prompt_file,
            "analysisHash": self.analysis_hash,
            "sourceHash": self.source_hash,
            "createdAt": self.created_at,
            "result": self.result,
            "error": self.error,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslationJob:
        return cls(
            v=data.get("v", 1),
            id=data.get("id", ""),
            edition=data.get("edition", ""),
            chapter=data.get("chapter", ""),
            kind=data.get("kind", "chapter"),
            status=data.get("status", "ready"),
            prompt_file=data.get("promptFile", ""),
            analysis_hash=data.get("analysisHash", ""),
            source_hash=data.get("sourceHash", ""),
            created_at=data.get("createdAt", ""),
            result=data.get("result"),
            error=data.get("error"),
            options=data.get("options", {}),
        )


def _generate_ulid() -> str:
    """Generate a ULID-like identifier."""
    return uuid.uuid4().hex[:26]


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically using temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    temp_path.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically using temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def _load_prompt_template(project_path: Path) -> str:
    """Load the translation prompt template from edition project."""
    prompt_file = promptsDir(project_path) / "translate.md"
    if prompt_file.is_file():
        try:
            content = prompt_file.read_text(encoding="utf-8")
            # Check for version header
            if content.startswith("v"):
                lines = content.splitlines()
                if lines and lines[0].startswith("v"):
                    return "\n".join(lines[1:])
            return content
        except Exception:
            pass
    return DEFAULT_TRANSLATION_PROMPT


def _get_style_guide(source_project: Any, target_language: str) -> str:
    """Get all style guide documents combined plus target language document."""
    parts = []

    # Find all guide documents in the source project
    content_path = source_project.storage.contentPath
    if not content_path:
        return ""

    for item in source_project.tree:
        if not item.isFileType():
            continue
        if item.itemClass != source_project.classes.GUIDE:
            continue

        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue

        try:
            text = doc_file.read_text(encoding="utf-8")
            guide = parseGuideDoc(text)
        except Exception:
            continue

        if guide.kind == "style":
            parts.append(f"# Style Guide\n{guide.body}")
        elif guide.kind == "language" and guide.lang == target_language:
            parts.append(f"# Language Guide ({target_language})\n{guide.body}")

    return "\n\n".join(parts)


def _get_analysis(source_project: Any, chapter_handle: str) -> str:
    """Get the approved analysis for a chapter."""
    content_path = source_project.storage.contentPath
    if not content_path:
        return ""

    for item in source_project.tree:
        if not item.isFileType():
            continue
        if item.itemClass != source_project.classes.GUIDE:
            continue

        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue

        try:
            text = doc_file.read_text(encoding="utf-8")
            guide = parseGuideDoc(text)
        except Exception:
            continue

        if guide.kind == "analysis" and guide.chapter == chapter_handle and guide.status == "approved":
            parts = []
            if guide.body:
                parts.append(guide.body)
            for note in guide.para_notes:
                parts.append(
                    f"%Para: {note.index} h={note.hash8}\n"
                    f"Intent: {note.intent}\n"
                    f"Subtext: {note.subtext}\n"
                    f"Register: {note.register}\n"
                    f"Do not translate literally: {', '.join(note.do_not_translate) if note.do_not_translate else 'None'}\n"
                    f"Cultural: {note.cultural}"
                )
            return "\n\n".join(parts)

    return ""


def _get_glossary(edition_path: Path) -> str:
    """Get glossary entries as formatted text."""
    from umbraedit.umbra.edition import glossary

    entries = glossary(edition_path)
    if not entries:
        return "(empty)"

    lines = []
    for entry in entries:
        parts = [f"{entry['source']} → {entry['target']}"]
        if entry["pronunciation"]:
            parts.append(f"({entry['pronunciation']})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _get_cast_voices(source_project: Any, chapter_handle: str, edition_path: Path) -> str:
    """Get voice matrix info for speakers in the chapter."""
    from umbraedit.umbra.sheet import SheetManager

    sheet = SheetManager(edition_path / "umbra")
    sheet.buildFromProject(str(edition_path))

    # Find all speakers in the chapter
    speakers = set()
    content_path = source_project.storage.contentPath
    if not content_path:
        return ""

    chapter_ref = source_project.chapterOf(chapter_handle) if hasattr(source_project, "chapterOf") else None
    if not chapter_ref:
        # Fallback: check single document
        doc_file = content_path / f"{chapter_handle}.md"
        if doc_file.is_file():
            text = doc_file.read_text(encoding="utf-8")
            for unit in iterUnits(text):
                if unit.voice and unit.voice.spk:
                    speakers.add(unit.voice.spk)

    if not speakers:
        return "(none)"

    lines = []
    for spk in sorted(speakers):
        entity = sheet.getEntity(spk)
        if entity:
            rels = entity.attrs.get("relationships", "")
            register = entity.attrs.get("voice_register", "")
            lines.append(f"{spk}: relationships={rels}, register={register}")
        else:
            lines.append(f"{spk}: (no entity note)")
    return "\n".join(lines)


def _get_previous_tail(source_project: Any, edition_path: Path, chapter_handle: str) -> str:
    """Get the last 3 translated paragraphs of the previous chapter."""
    # This would require chapter ordering - simplified for now
    return "(none)"


def _get_source_paragraphs(
    source_project: Any,
    chapter_handle: str,
    edition_path: Path,
) -> str:
    """Get numbered source paragraphs with notes and voice info."""
    content_path = source_project.storage.contentPath
    if not content_path:
        return ""

    # Get analysis for paragraph notes
    analysis_text = _get_analysis(source_project, chapter_handle)
    analysis_guide = parseGuideDoc(analysis_text) if analysis_text else None
    para_notes = {note.index: note for note in analysis_guide.para_notes} if analysis_guide else {}

    paragraphs = []
    chapter_ref = source_project.chapterOf(chapter_handle) if hasattr(source_project, "chapterOf") else None
    handles = chapter_ref.handles if chapter_ref else [chapter_handle]

    para_index = 0
    for handle in handles:
        doc_file = content_path / f"{handle}.md"
        if not doc_file.is_file():
            continue
        text = doc_file.read_text(encoding="utf-8")

        for unit in iterUnits(text):
            if unit.kind != UnitKind.PARAGRAPH:
                continue

            voice_info = ""
            if unit.voice:
                spk = unit.voice.spk or ""
                tone = unit.voice.tone or ""
                intensity = unit.voice.intensity if hasattr(unit.voice, "intensity") else ""
                if spk or tone:
                    voice_info = f" (speaker: {spk}, tone: {tone}:{intensity})".strip()
                else:
                    voice_info = ""

            note = para_notes.get(para_index)
            note_text = ""
            if note:
                note_parts = []
                if note.intent:
                    note_parts.append(f"Intent: {note.intent}")
                if note.subtext:
                    note_parts.append(f"Subtext: {note.subtext}")
                if note.register:
                    note_parts.append(f"Register: {note.register}")
                if note.do_not_translate:
                    note_parts.append(f"Do not translate literally: {', '.join(note.do_not_translate)}")
                if note.cultural:
                    note_parts.append(f"Cultural: {note.cultural}")
                if note_parts:
                    note_text = " [" + "; ".join(note_parts) + "]"

            para_text = "\n".join(unit.lines).strip()
            paragraphs.append(f"[{para_index}] {para_text}{voice_info}{note_text}")
            para_index += 1

    return "\n\n".join(paragraphs)


def _get_source_hash(source_project: Any, chapter_handle: str) -> str:
    """Get the canonical text hash of the source chapter."""
    if hasattr(source_project, "getDocumentHash"):
        return source_project.getDocumentHash(chapter_handle)
    # Fallback: compute from file
    content_path = source_project.storage.contentPath
    if not content_path:
        return ""
    doc_file = content_path / f"{chapter_handle}.md"
    if not doc_file.is_file():
        return ""
    text = doc_file.read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _get_analysis_hash(source_project: Any, chapter_handle: str) -> str:
    """Get the hash of the approved analysis for the chapter."""
    content_path = source_project.storage.contentPath
    if not content_path:
        return ""
    for item in source_project.tree:
        if not item.isFileType():
            continue
        if item.itemClass != source_project.classes.GUIDE:
            continue
        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue
        try:
            text = doc_file.read_text(encoding="utf-8")
            guide = parseGuideDoc(text)
        except Exception:
            continue
        if guide.kind == "analysis" and guide.chapter == chapter_handle and guide.status == "approved":
            return hashlib.sha256(guide.body.encode("utf-8")).hexdigest()[:16]
    return ""


def _build_chapter_prompt(
    edition_path: Path,
    source_project: Any,
    chapter_handle: str,
    edition_info: Any,
) -> tuple[str, str, str]:
    """Build the translation prompt for a chapter. Returns (prompt, source_hash, analysis_hash)."""
    source_hash = _get_source_hash(source_project, chapter_handle)
    analysis_hash = _get_analysis_hash(source_project, chapter_handle)

    metadata = source_project.metadata if hasattr(source_project, "metadata") else loadMetadata(source_project.storage.storagePath)

    template = _load_prompt_template(edition_path)

    prompt = template.format(
        sourceLanguage=metadata.book.get("language", "en"),
        targetLanguage=edition_info.language,
        bookTitle=metadata.book.get("title", ""),
        chapterTitle=chapter_handle,  # TODO: get actual chapter title
        styleGuide=_get_style_guide(source_project, edition_info.language),
        analysis=_get_analysis(source_project, chapter_handle),
        glossary=_get_glossary(edition_path),
        castVoices=_get_cast_voices(source_project, chapter_handle, edition_path),
        previousTail=_get_previous_tail(source_project, edition_path, chapter_handle),
        paragraphs=_get_source_paragraphs(source_project, chapter_handle, edition_path),
        instructions=TRANSLATION_INSTRUCTIONS,
        outputSchema=json.dumps(TRANSLATION_OUTPUT_SCHEMA, indent=2),
    )

    return prompt, source_hash, analysis_hash


def _build_metadata_prompt(
    edition_path: Path,
    source_project: Any,
    edition_info: Any,
) -> tuple[str, str]:
    """Build the translation prompt for metadata. Returns (prompt, source_hash)."""
    # For metadata, we hash the pending fields
    metadata = source_project.metadata if hasattr(source_project, "metadata") else loadMetadata(source_project.storage.storagePath)
    pending = edition_info.pending

    source_data = {}
    for key in pending:
        parts = key.split(".")
        if len(parts) == 2:
            section, field = parts
            if section == "book":
                source_data[key] = metadata.book.get(field, "")
            elif section == "custom":
                source_data[key] = metadata.custom.get(field, "")

    source_hash = hashlib.sha256(json.dumps(source_data, sort_keys=True).encode()).hexdigest()[:16]

    template = _load_prompt_template(edition_path)

    prompt = template.format(
        sourceLanguage=metadata.book.get("language", "en"),
        targetLanguage=edition_info.language,
        bookTitle=metadata.book.get("title", ""),
        chapterTitle="(metadata)",
        styleGuide=_get_style_guide(source_project, edition_info.language),
        analysis="",
        glossary=_get_glossary(edition_path),
        castVoices="",
        previousTail="",
        paragraphs="\n".join(f"{k}: {v}" for k, v in source_data.items()),
        instructions=TRANSLATION_INSTRUCTIONS,
        outputSchema=json.dumps(TRANSLATION_OUTPUT_SCHEMA, indent=2),
    )

    return prompt, source_hash


def _validate_translation_result(result: dict[str, Any], expected_count: int) -> list[str]:
    """Validate translation result. Returns list of errors, empty if valid."""
    errors = []

    if "paragraphs" not in result:
        errors.append("Missing 'paragraphs' field")
        return errors

    paragraphs = result["paragraphs"]
    if not isinstance(paragraphs, list):
        errors.append("'paragraphs' must be an array")
        return errors

    if len(paragraphs) != expected_count:
        errors.append(f"Paragraph count mismatch: expected {expected_count}, got {len(paragraphs)}")
        return errors

    for i, para in enumerate(paragraphs):
        if not isinstance(para, dict):
            errors.append(f"Paragraph {i}: must be an object")
            continue
        if "index" not in para:
            errors.append(f"Paragraph {i}: missing 'index'")
            continue
        if para["index"] != i:
            errors.append(f"Paragraph {i}: index mismatch (got {para['index']})")
        if "text" not in para:
            errors.append(f"Paragraph {i}: missing 'text'")
            continue
        text = para["text"]
        if not text or not text.strip():
            errors.append(f"Paragraph {i}: empty text")
        if "{{" in text:
            errors.append(f"Paragraph {i}: contains unresolved placeholder '{{'")

    return errors


def _count_source_paragraphs(source_project: Any, chapter_handle: str) -> int:
    """Count paragraphs in the source chapter."""
    content_path = source_project.storage.contentPath
    if not content_path:
        return 0

    chapter_ref = source_project.chapterOf(chapter_handle) if hasattr(source_project, "chapterOf") else None
    handles = chapter_ref.handles if chapter_ref else [chapter_handle]

    count = 0
    for handle in handles:
        doc_file = content_path / f"{handle}.md"
        if not doc_file.is_file():
            continue
        text = doc_file.read_text(encoding="utf-8")
        for unit in iterUnits(text):
            if unit.kind == UnitKind.PARAGRAPH:
                count += 1
    return count


def importTranslationResult(edition_project: Any, job_id: str) -> tuple[bool, str | None]:
    """
    Import a translation result from a job file.

    Args:
        edition_project: The edition project object
        job_id: The job ID to import

    Returns:
        (success, error_message)
    """
    edition_path = Path(edition_project.storage.storagePath)
    jobs_dir = jobsDir(edition_path)
    job_file = jobs_dir / f"tj-{job_id}.json"
    prompt_file = jobs_dir / f"tj-{job_id}.prompt.md"

    if not job_file.is_file():
        return False, f"Job file not found: {job_file}"

    if not prompt_file.is_file():
        return False, f"Prompt file not found: {prompt_file}"

    try:
        with open(job_file, encoding="utf-8") as f:
            job_data = json.load(f)
    except Exception as e:
        return False, f"Failed to read job file: {e}"

    job = TranslationJob.from_dict(job_data)

    # Look for result file (for external tool)
    result_file = jobs_dir / f"tj-{job_id}.result.json"
    if result_file.is_file():
        try:
            with open(result_file, encoding="utf-8") as f:
                job.result = json.load(f)
        except Exception as e:
            return False, f"Failed to read result file: {e}"

    if not job.result:
        return False, "No result to import"

    # Validate result
    if job.kind == "chapter":
        source_project = edition_project  # Simplified
        expected_count = _count_source_paragraphs(source_project, job.chapter)
        errors = _validate_translation_result(job.result, expected_count)
        if errors:
            return False, "; ".join(errors)

        # Write translation as draft
        success = _apply_translation_draft(edition_project, job)
        if not success:
            return False, "Failed to apply translation draft"

    elif job.kind == "metadata":
        success = _apply_metadata_draft(edition_project, job)
        if not success:
            return False, "Failed to apply metadata draft"

    # Update job status
    job.status = "done"
    _atomic_write_json(jobs_dir / f"tj-{job_id}.json", job.to_dict())

    return True, None


def _apply_translation_draft(edition_project: Any, job: TranslationJob) -> bool:
    """Apply translation result as draft to edition document."""
    edition_path = Path(edition_project.storage.storagePath)
    edition_info = loadEdition(edition_path)

    # For now, we assume single document chapter
    chapter_handle = job.chapter
    content_path = edition_path / "content"
    doc_file = content_path / f"{chapter_handle}.md"

    if not doc_file.is_file():
        logger.error("Edition document not found: %s", doc_file)
        return False

    # Read current text
    current_text = doc_file.read_text(encoding="utf-8")

    # Create snapshot (pre_restore kind)
    from umbraedit.umbra.history import snapshotDocument
    snapshotDocument(edition_path, chapter_handle, "pre_restore", current_text)

    # Parse current units to preserve %Voice: lines
    units = list(iterUnits(current_text))
    para_units = [u for u in units if u.kind == UnitKind.PARAGRAPH]

    # Build new text with translated paragraphs
    result_paragraphs = {p["index"]: p for p in job.result.get("paragraphs", [])}

    new_lines = []
    para_idx = 0
    for unit in units:
        if unit.kind == UnitKind.PARAGRAPH:
            if para_idx in result_paragraphs:
                para_result = result_paragraphs[para_idx]
                translated_text = para_result["text"]

                # Preserve %Voice: line if present
                voice_lines = [line for line in unit.lines if line.strip().startswith("%Voice:")]
                other_lines = [line for line in unit.lines if not line.strip().startswith("%Voice:")]

                # Replace paragraph text with translated text
                new_lines.extend(voice_lines)
                new_lines.append(translated_text)
            else:
                new_lines.extend(unit.lines)
            para_idx += 1
        else:
            new_lines.extend(unit.lines)

    new_text = "\n".join(new_lines)

    # Write new text
    doc_file.write_text(new_text, encoding="utf-8")

    # Update edition status to "translated draft"
    if chapter_handle in edition_info.docs:
        edition_info.docs[chapter_handle].status = "translated draft"
        saveEdition(edition_path, edition_info)

    # Check for attribution loss
    # TODO: Check if attribution spans were lost

    return True


def _apply_metadata_draft(edition_project: Any, job: TranslationJob) -> bool:
    """Apply metadata translation result as draft."""
    edition_path = Path(edition_project.storage.storagePath)
    edition_info = loadEdition(edition_path)

    # Result should have chapter field with metadata key translations
    # For metadata, we expect result to have a different structure
    # This is simplified - in reality, metadata translation would have its own output schema
    return True


def runTranslationJobLocal(edition_project: Any, job_id: str) -> tuple[bool, str | None]:
    """
    Run a translation job using the local model endpoint.

    Args:
        edition_project: The edition project object
        job_id: The job ID to run

    Returns:
        (success, error_message)
    """
    edition_path = Path(edition_project.storage.storagePath)
    jobs_dir = jobsDir(edition_path)
    job_file = jobs_dir / f"tj-{job_id}.json"
    prompt_file = jobs_dir / f"tj-{job_id}.prompt.md"

    if not job_file.is_file():
        return False, f"Job file not found: {job_file}"

    if not prompt_file.is_file():
        return False, f"Prompt file not found: {prompt_file}"

    try:
        with open(job_file, encoding="utf-8") as f:
            job_data = json.load(f)
    except Exception as e:
        return False, f"Failed to read job file: {e}"

    job = TranslationJob.from_dict(job_data)

    # Update status to running
    job.status = "running"
    _atomic_write_json(job_file, job.to_dict())

    # Get endpoint settings
    endpoint = umbraSettings.getStr("translation.endpoint")
    if not endpoint:
        job.status = "failed"
        job.error = "Translation endpoint not configured"
        _atomic_write_json(job_file, job.to_dict())
        return False, job.error

    model = umbraSettings.getStr("translation.model")
    temperature = float(umbraSettings.getStr("translation.temperature", "0.2"))
    timeout = umbraSettings.getInt("translation.timeoutSeconds", 300)

    # Read prompt
    prompt = prompt_file.read_text(encoding="utf-8")

    # Call endpoint (with retry)
    for attempt in range(2):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{endpoint.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                result_text = data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("Translation attempt %d failed: %s", attempt + 1, e)
            if attempt == 1:
                job.status = "failed"
                job.error = str(e)
                _atomic_write_json(job_file, job.to_dict())
                return False, str(e)
            continue

        # Validate response
        try:
            result = json.loads(result_text)
            jsonschema.validate(result, TRANSLATION_OUTPUT_SCHEMA)
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            logger.warning("Invalid translation response, attempt %d: %s", attempt + 1, e)
            if attempt == 1:
                job.status = "failed"
                job.error = f"Invalid response: {e}"
                _atomic_write_json(job_file, job.to_dict())
                return False, str(e)
            continue

        # Success
        job.result = result
        job.status = "done"
        _atomic_write_json(job_file, job.to_dict())
        return True, None

    return False, "Max retries exceeded"


def retranslateStaleChapters(edition_project: Any) -> list[str]:
    """
    Queue translation jobs for stale chapters only.

    Args:
        edition_project: The edition project object

    Returns:
        List of job IDs created
    """
    edition_path = Path(edition_project.storage.storagePath)
    edition_info = loadEdition(edition_path)

    if not edition_info.source.get("path"):
        return []

    source_path = edition_path.parent / edition_info.source["path"]
    if not source_path.exists():
        return []

    # Get source project - simplified
    source_project = edition_project

    job_ids = []
    for handle, doc in edition_info.docs.items():
        if doc.status == "stale":
            # Check if source hash or analysis hash changed
            source_hash = _get_source_hash(source_project, handle)
            analysis_hash = _get_analysis_hash(source_project, handle)

            if doc.baseTextHash != source_hash or (doc.guideAnalysis and doc.guideAnalysis != analysis_hash):
                job = buildTranslationJob(edition_project, handle)
                if job:
                    job_ids.append(job.id)

    return job_ids


def _check_glossary_gaps(edition_path: Path, source_project: Any, chapter_handle: str) -> list[str]:
    """Check for entities mentioned in chapter that lack target form in glossary."""
    from umbraedit.umbra.edition import glossary
    from umbraedit.umbra.sheet import SheetManager

    glossary_entries = {e["source"]: e for e in glossary(edition_path)}
    sheet = SheetManager(edition_path / "umbra")
    sheet.buildFromProject(str(edition_path))

    # Find all speakers in chapter
    speakers = set()
    content_path = source_project.storage.contentPath
    if not content_path:
        return []

    doc_file = content_path / f"{chapter_handle}.md"
    if not doc_file.is_file():
        return []

    text = doc_file.read_text(encoding="utf-8")
    for unit in iterUnits(text):
        if unit.voice and unit.voice.spk:
            speakers.add(unit.voice.spk)

    gaps = []
    for spk in speakers:
        entity = sheet.getEntity(spk)
        if entity:
            target_form = entity.attrs.get("name_target", entity.tag)
            if target_form == entity.tag and spk not in glossary_entries:
                gaps.append(spk)

    return gaps


from umbraedit.umbra.history import HistoryManager, _historyManager
from umbraedit.umbra.edition import saveEdition
from umbraedit.umbra.history import snapshotDocument
from umbraedit.umbra.units import iterUnits, UnitKind
from umbraedit.umbra.units import iterUnits, UnitKind