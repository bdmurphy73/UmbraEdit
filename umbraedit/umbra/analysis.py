"""
UmbraEdit - Chapter Analysis for Translation
=============================================

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
import time

from dataclasses import dataclass
from typing import Any

import httpx
import jsonschema

from umbraedit.umbra.metadata import Metadata, loadMetadata
from umbraedit.umbra.paths import promptsDir
from umbraedit.umbra.settings import umbraSettings
from umbraedit.umbra.units import UnitKind, iterUnits

logger = logging.getLogger(__name__)

# JSON schema for analysis output validation
ANALYSIS_SCHEMA = {
    "type": "object",
    "required": ["message", "intent", "characters", "paragraphs"],
    "properties": {
        "message": {"type": "string"},
        "intent": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tag", "wants", "relationships"],
                "properties": {
                    "tag": {"type": "string"},
                    "wants": {"type": "string"},
                    "relationships": {"type": "string"},
                },
            },
        },
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "intent", "subtext", "register", "doNotTranslateLiterally", "cultural"],
                "properties": {
                    "index": {"type": "integer"},
                    "intent": {"type": "string"},
                    "subtext": {"type": "string"},
                    "register": {"type": "string"},
                    "doNotTranslateLiterally": {"type": "array", "items": {"type": "string"}},
                    "cultural": {"type": "string"},
                },
            },
        },
    },
}

DEFAULT_ANALYSIS_PROMPT = (
    "Analyze the following chapter for translation purposes. Focus on the "
    "story's intent and message, not word-for-word translation.\n\n"
    "{{outputSchema}}\n\n"
    "Book: {{bookTitle}}\n"
    "Source Language: {{sourceLanguage}}\n"
    "Chapter: {{chapterTitle}}\n\n"
    "Style Guide:\n{{styleGuide}}\n\n"
    "Characters:\n{{characters}}\n\n"
    "Previous Chapter Summary:\n{{previousSummary}}\n\n"
    "Chapter Text:\n{{chapterText}}\n\n"
    "Instructions:\n{{instructions}}\n\n"
    "Output the analysis as valid JSON matching the schema exactly."
)


@dataclass
class AnalysisResult:
    """Result of an analysis generation."""

    message: str
    intent: str
    characters: list[dict[str, str]]
    paragraphs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message": self.message,
            "intent": self.intent,
            "characters": self.characters,
            "paragraphs": self.paragraphs,
        }


@dataclass
class AnalysisJob:
    """An analysis job for a chapter."""

    chapter_handle: str
    chapter_title: str
    edition: str = "main"
    run_id: str = ""
    prompt: str = ""
    prompt_hash: str = ""
    response_hash: str = ""
    status: str = "pending"  # pending, running, done, failed
    created_at: str = ""
    result: AnalysisResult | None = None
    error: str | None = None


class AnalysisGenerator:
    """Generates chapter analysis using a local LLM endpoint."""

    def __init__(self, project: Any) -> None:
        self.project = project
        self.storage_path = project.storage.storagePath
        self.content_path = project.storage.contentPath

    def _get_settings(self) -> dict[str, Any]:
        """Get analysis settings from project settings."""
        return {
            "endpoint": umbraSettings.getStr("analysis.endpoint"),
            "model": umbraSettings.getStr("analysis.model"),
            "temperature": umbraSettings.getStr("analysis.temperature"),
            "context_tokens": umbraSettings.getInt("analysis.contextTokens"),
            "timeout": umbraSettings.getInt("analysis.timeoutSeconds"),
        }

    def _load_prompt_template(self) -> str:
        """Load the analysis prompt template."""
        prompt_file = promptsDir(self.storage_path) / "analysis.md"
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
        # Return default if file not found or error
        return DEFAULT_ANALYSIS_PROMPT

    def _get_style_guide(self, metadata: Metadata) -> str:
        """Get all style guide documents combined."""
        # This would need access to guide documents
        # For now, return empty string
        return ""

    def _get_characters(self, chapter_handle: str, metadata: Metadata) -> str:
        """Get character information for the chapter."""
        # This would query the entity index for characters in this chapter
        return ""

    def _get_previous_summary(self, chapter_handle: str, metadata: Metadata) -> str:
        """Get the approved message from the previous chapter."""
        return ""

    def _build_chapter_text(self, chapter_handle: str) -> tuple[str, list[tuple[int, str, str]]]:
        """Build chapter text with paragraph numbering and voice data."""
        # Get chapter documents

        chapter_ref = self.chapterOf(chapter_handle)
        if not chapter_ref:
            return "", []

        paragraphs = []
        for handle in chapter_ref.handles:
            doc_file = self.content_path / f"{handle}.md"
            if not doc_file.is_file():
                continue
            text = doc_file.read_text(encoding="utf-8")
            # Parse units
            for unit in iterUnits(text):
                if unit.kind == UnitKind.PARAGRAPH:
                    voice_info = ""
                    if unit.voice:
                        voice_info = f" (speaker: {unit.voice.speaker}, tone: {unit.voice.tone}:{unit.voice.intensity})"
                    paragraphs.append((len(paragraphs), unit.text, voice_info))

        # Build text with numbered paragraphs
        text_parts = []
        for idx, text, voice in paragraphs:
            text_parts.append(f"[{idx}] {text}{voice}")

        return "\n\n".join(text_parts), [(idx, text, voice) for idx, text, voice in paragraphs]

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (roughly 1 token per 4 characters)."""
        return len(text) // 4

    def _chunk_chapter(
        self, chapter_text: str, paragraph_data: list[tuple[int, str, str]], max_tokens: int
    ) -> list[str]:
        """Split chapter at scene boundaries if it exceeds token budget."""
        # For now, return as single chunk
        # Full implementation would split at scene boundaries (UnitKind.SCENE)
        return [chapter_text]

    def _build_prompt(
        self,
        chapter_title: str,
        chapter_text: str,
        metadata: Metadata,
        previous_summary: str,
        style_guide: str,
        characters: str,
    ) -> str:
        """Build the analysis prompt."""
        template = self._load_prompt_template()

        output_schema = json.dumps(ANALYSIS_SCHEMA, indent=2)

        instructions = (
            "Translate for meaning and intent, not word for word. "
            "Keep the voice and register, do not translate word for word, "
            "keep names as in the glossary, keep paragraph count, return JSON."
        )

        return template.format(
            outputSchema=output_schema,
            bookTitle=metadata.book.get("title", ""),
            sourceLanguage=metadata.book.get("language", "en"),
            chapterTitle=chapter_title,
            styleGuide=style_guide,
            characters=characters,
            previousSummary=previous_summary,
            chapterText=chapter_text,
            instructions=instructions,
        )

    def _validate_response(self, response_text: str) -> AnalysisResult | None:
        """Validate and parse the model response."""
        try:
            data = json.loads(response_text)
            # Validate against schema
            jsonschema.validate(data, ANALYSIS_SCHEMA)
            return AnalysisResult(**data)
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            logger.warning("Invalid analysis response: %s", e)
            return None

    def _call_endpoint(self, prompt: str, settings: dict[str, Any]) -> str | None:
        """Call the local LLM endpoint."""
        endpoint = settings.get("endpoint")
        if not endpoint:
            logger.error("No analysis endpoint configured")
            return None

        try:
            with httpx.Client(timeout=settings.get("timeout", 300)) as client:
                response = client.post(
                    f"{endpoint.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": settings.get("model", ""),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": float(settings.get("temperature", 0.2)),
                        "max_tokens": settings.get("context_tokens", 8192),
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("Endpoint call failed: %s", e)
            return None

    def generate_analysis(self, chapter_handle: str, edition: str = "main") -> str | None:
        """Generate analysis for a chapter. Returns run ID on success, None on failure."""
        run_id = f"an-{hashlib.md5(f'{chapter_handle}{time.time()}'.encode()).hexdigest()[:12]}"

        # Get settings
        self._get_settings()

        # Load metadata
        loadMetadata(self.storage_path)

        # Check if endpoint is configured
        if not umbraSettings.getStr("analysis.endpoint"):
            logger.error("Analysis endpoint not configured")
            return None

        # Get chapter info
        chapter_title = "Chapter"
        # TODO: Get actual chapter title from tree

        # Build chapter text
        chapter_text, _para_data = self._build_chapter_text(chapter_handle)

        # Estimate tokens
        self._estimate_tokens(chapter_text)
        umbraSettings.getInt("analysis.contextTokens")

        # Chunk if needed
        chunks = self._chunk_chapter("", [], umbraSettings.getInt("analysis.contextTokens"))
        if len(chunks) > 1:
            logger.info("Chapter split into %d chunks", len(chunks))

        # Build prompt
        style_guide = self._get_style_guide({})
        characters = self._get_characters(chapter_handle, {})
        previous_summary = self._get_previous_summary(chapter_handle, {})

        prompt = self._build_prompt(
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            metadata={},
            previous_summary=previous_summary,
            style_guide=style_guide,
            characters=characters,
        )

        # Log prompt
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:16]
        self._log_run(
            run_id="",
            chapter=chapter_handle,
            model="",
            prompt_hash=prompt_hash,
            response_hash="",
            time=time.time(),
        )

        # Try up to 2 times
        for attempt in range(2):
            response_text = self._call_endpoint(
                prompt,
                {
                    "endpoint": "",
                    "model": "",
                    "temperature": 0.2,
                    "context_tokens": 8192,
                    "timeout": 300,
                },
            )
            if not response_text:
                logger.error("No response from endpoint")
                continue

            result = self._validate_response(response_text)
            if result:
                # Success - create guide document
                from umbraedit.umbra.guide import GuideDoc

                for _p in result.paragraphs:
                    # Create ParaNote for each paragraph
                    pass

                GuideDoc(
                    kind="analysis",
                    chapter=chapter_handle,
                    srchash="",  # TODO: compute chapter hash
                    status="draft",
                    body="",  # Will be formatted
                    para_notes=[],
                )

                # Write guide document
                # TODO: save guide document

                response_hash = hashlib.md5(response_text.encode()).hexdigest()[:16]
                self._log_run(
                    run_id="",
                    chapter=chapter_handle,
                    model="",
                    prompt_hash="",
                    response_hash=response_hash,
                    time=time.time(),
                )

                return "success"
            else:
                logger.warning("Invalid response, attempt %d", attempt + 1)

        # Both attempts failed
        self._save_failed_response(run_id, response_text or "")
        return None

    def _log_run(
        self,
        run_id: str,
        chapter: str,
        model: str,
        prompt_hash: str,
        response_hash: str,
        time: float,
    ) -> None:
        """Log analysis run to JSONL."""
        log_file = self.storage_path / "umbra" / "cache" / "analysis-log.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "run_id": run_id,
            "chapter": chapter,
            "model": "",
            "prompt_hash": "",
            "response_hash": "",
            "time": "",
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _save_failed_response(self, run_id: str, response: str) -> None:
        """Save failed response for debugging."""
        fail_dir = self.storage_path / "umbra" / "cache" / "analysis-failed"
        fail_dir.mkdir(parents=True, exist_ok=True)
        fail_file = fail_dir / f"{run_id}.txt"
        fail_file.write_text(response, encoding="utf-8")

    def reanalyse_stale(self, edition: str = "main") -> list[str]:
        """Re-analyse stale paragraphs only."""
        # TODO: Implement
        return []

    def approve_analysis(self, chapter_handle: str) -> bool:
        """Approve a draft analysis."""
        # TODO: Implement
        return True


def create_analysis_prompt(
    book_title: str,
    source_language: str,
    chapter_title: str,
    style_guide: str,
    characters: str,
    previous_summary: str,
    chapter_text: str,
) -> str:
    """Create an analysis prompt for a chapter."""
    template = DEFAULT_ANALYSIS_PROMPT

    output_schema = json.dumps(ANALYSIS_SCHEMA, indent=2)

    instructions = (
        "Translate for meaning and intent, not word for word. "
        "Keep the voice and register, do not translate word for word, "
        "keep names as in the glossary, keep paragraph count, return JSON."
    )

    return template.format(
        outputSchema=output_schema,
        bookTitle=book_title,
        sourceLanguage=source_language,
        chapterTitle=chapter_title,
        styleGuide=style_guide,
        characters=characters,
        previousSummary=previous_summary,
        chapterText=chapter_text,
        instructions=instructions,
    )


def validate_analysis_response(response_text: str) -> AnalysisResult | None:
    """Validate analysis response against schema."""
    try:
        data = json.loads(response_text)
        jsonschema.validate(data, ANALYSIS_SCHEMA)
        return AnalysisResult(**data)
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        logger.warning("Invalid analysis response: %s", e)
        return None
