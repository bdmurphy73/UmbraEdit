"""
UmbraEdit - DOCX Syntax Conversion Stage
=========================================

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
import re

from dataclasses import dataclass, field
from typing import Any

from umbraedit.umbra.ingest.docx_split import SceneSplitResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyntaxResult:
    """Result of the syntax conversion stage."""

    documents: list[dict[str, Any]]  # Updated documents with converted syntax
    warnings: list[str] = field(default_factory=list)


# Shortcode mappings (Word formatting -> novelWriter shortcodes)
FORMATTING_SHORTCODES = {
    "bold": ("{b}", "{/b}"),
    "italic": ("{i}", "{/i}"),
    "underline": ("{u}", "{/u}"),
    "strike": ("{s}", "{/s}"),
    "small_caps": ("{sc}", "{/sc}"),
}

# Smart quote mappings
SMART_QUOTES = {
    "\u201c": '"',  # Left double quote
    "\u201d": '"',  # Right double quote
    "\u2018": "'",  # Left single quote
    "\u2019": "'",  # Right single quote
    "\u201c": '"',
    "\u201d": '"',
}

# Non-breaking space and soft hyphen
SPECIAL_CHARS = {
    "\u00a0": " ",  # Non-breaking space
    "\u00ad": "",   # Soft hyphen
}


def _normalize_smart_quotes(text: str) -> str:
    """Convert smart quotes to curly quotes."""
    for smart, curly in SMART_QUOTES.items():
        text = text.replace(smart, curly)
    return text


def _handle_special_chars(text: str) -> str:
    """Handle non-breaking spaces and soft hyphens."""
    for char, replacement in SPECIAL_CHARS.items():
        text = text.replace(char, replacement)
    return text


def _convert_formatting(text: str) -> str:
    """Convert Word formatting markers to novelWriter shortcodes."""
    # This is a simplified version - real implementation would parse
    # the run_formatting data from pre-pass
    # For now, we look for simple markdown-style markers
    text = re.sub(r"\*\*(.+?)\*\*", r"{b}\1{/b}", text)
    text = re.sub(r"__(.+?)__", r"{b}\1{/b}", text)
    text = re.sub(r"\*(.+?)\*", r"{i}\1{/i}", text)
    text = re.sub(r"_(.+?)_", r"{i}\1{/i}", text)
    text = re.sub(r"~~(.+?)~~", r"{s}\1{/s}", text)
    return text


def _convert_footnotes(text: str, footnotes: dict[str, str]) -> str:
    """Convert [FOOTNOTE:id] markers to novelWriter footnote syntax."""
    def replace_fn(match: re.Match) -> str:
        fn_id = match.group(1)
        fn_text = footnotes.get(fn_id, f"[footnote {fn_id} not found]")
        # Use a short key for the footnote
        return f"[footnote:{fn_id}]\n%Footnote.{fn_id}: {fn_text}"

    return re.sub(r"\[FOOTNOTE:([^\]]+)\]", replace_fn, text)


def _convert_comments(text: str, comments: dict[str, dict[str, Any]]) -> str:
    """Convert [COMMENT:id] markers to comment lines."""
    def replace_cmt(match: re.Match) -> str:
        cmt_id = match.group(1)
        cmt = comments.get(cmt_id, {})
        author = cmt.get("author", "Unknown")
        cmt_text = cmt.get("text", "")
        return f"% {author}: {cmt_text}"

    return re.sub(r"\[COMMENT:([^\]]+)\]", replace_cmt, text)


def _convert_images(text: str, images: list[dict[str, Any]]) -> str:
    """Convert [IMAGE:rid] markers to [image:...] lines."""
    def replace_img(match: re.Match) -> str:
        rid = match.group(1)
        # Find image info
        for img in images:
            if img.get("rid") == rid:
                alt = img.get("alt", img.get("filename", "image"))
                return f"[image:{img['filename']}|{alt}]"
        return f"[image:missing:{rid}]"

    return re.sub(r"\[IMAGE:([^\]]+)\]", replace_img, text)


class DocxSyntax:
    """Syntax stage: convert to novelWriter syntax."""

    def process(
        self,
        split: SceneSplitResult,
        prepass_paragraphs: list[Any],  # ParagraphRecord list
        prepass_footnotes: dict[str, str],
        prepass_comments: dict[str, dict[str, Any]],
        prepass_images: list[dict[str, Any]],
    ) -> SyntaxResult:
        """Convert all documents to novelWriter syntax."""
        logger.info("Syntax: converting %d documents", len(split.documents))

        warnings: list[str] = []
        converted_docs = []

        for doc in split.documents:
            text = doc.get("text", "")

            # Apply conversions
            text = _normalize_smart_quotes(text)
            text = _handle_special_chars(text)
            text = _convert_formatting(text)
            text = _convert_footnotes(text, prepass_footnotes)
            text = _convert_comments(text, prepass_comments)
            text = _convert_images(text, prepass_images)

            # Normalize whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = text.strip()

            converted_doc = dict(doc)
            converted_doc["text"] = text
            converted_docs.append(converted_doc)

        return SyntaxResult(
            documents=converted_docs,
            warnings=warnings,
        )
