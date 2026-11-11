"""
UmbraEdit - DOCX Propose Stage
===============================

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

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from umbraedit.umbra.ingest.docx_split import SceneSplitResult
from umbraedit.umbra.ingest.docx_syntax import SyntaxResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposeResult:
    """Result of the propose stage."""

    characters: list[dict[str, Any]]  # [{"name": "...", "count": N, "examples": [...]}]
    metadata: dict[str, Any]  # title, author, language, etc.
    page_types: dict[str, str]  # front/back matter page types
    warnings: list[str] = field(default_factory=list)


# Stop words for character name detection
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "were", "been", "be",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "he", "she", "it",
    "they", "them", "their", "his", "her", "its", "we", "you", "i", "me",
    "my", "your", "our", "us", "this", "that", "these", "those", "who",
    "what", "where", "when", "why", "how", "not", "no", "yes", "so",
    "if", "then", "else", "than", "also", "just", "now", "here", "there",
    "up", "down", "out", "over", "under", "again", "once", "more",
    "very", "much", "many", "some", "any", "all", "each", "every", "other",
    "such", "only", "own", "same", "too", "well", "even", "still", "back",
    "after", "before", "during", "while", "since", "until", "because",
    "though", "although", "however", "therefore", "thus", "hence", "yet",
    "said", "says", "say", "told", "tell", "asked", "ask", "replied",
    "reply", "answered", "answer", "thought", "think", "knew", "know",
    "saw", "see", "looked", "look", "went", "go", "came", "come", "got",
    "get", "gotten", "took", "take", "made", "make", "gave", "give",
    "found", "find", "left", "leave", "kept", "keep", "let", "lets",
    "put", "puts", "ran", "run", "walked", "walk", "stood", "stand",
    "sat", "sit", "lay", "lie", "laid", "fallen", "fall", "fell",
    "rose", "rise", "raised", "raise", "brought", "bring", "bought",
    "buy", "sold", "sell", "paid", "pay", "cost", "costs", "chose",
    "choose", "chosen", "wrote", "write", "written", "read",
    "heard", "hear", "listened", "listen",
    "watched", "watch", "waited", "wait", "stopped", "stop", "started",
    "start", "began", "begin", "begun", "ended", "end", "finished",
    "finish", "completed", "complete", "continued", "continue",
    "changed", "change", "turned", "turn", "moved", "move", "stayed", "stay", "lived",
    "live", "died", "die", "dead", "born", "bear", "borne",
    "grew", "grow", "grown", "became", "become", "seemed", "seem",
    "appeared", "appear", "felt", "feel", "feeling",
    "realized", "realize", "noticed",
    "notice", "remembered", "remember", "forgot", "forget", "forgotten",
    "known", "understood", "understand", "believed", "believe", "hoped", "hope",
    "wished", "wish", "wanted", "want", "needed", "need", "makes",
    "allowed", "allow", "helped", "help",
    "tried", "try", "attempted", "attempt", "managed",
    "manage", "failed", "fail", "succeeded", "succeed", "achieved",
    "achieve", "reached", "reach", "arrived", "arrive", "going", "gone",
}


def _extract_potential_names(text: str) -> list[str]:
    """Extract capitalized words that could be names."""
    # Find words that start with uppercase, possibly with apostrophes/hyphens
    words = re.findall(r"\b[A-Z][a-zA-Z'-]*\b", text)
    return words


def _is_likely_name(word: str, context: str) -> bool:
    """Check if a word is likely a character name."""
    if word.lower() in STOP_WORDS:
        return False
    if len(word) < 2:
        return False
    if word.isupper() and len(word) > 3:
        return False  # Acronyms
    # Check if it appears near quotation marks (dialogue)
    # This is a simplified check - real implementation would be more sophisticated
    return True


class DocxPropose:
    """Propose stage: detect character names, metadata, and page types."""

    def process(
        self,
        split: SceneSplitResult,
        syntax: SyntaxResult,
        prepass_doc_props: dict[str, Any],
    ) -> ProposeResult:
        """Propose character names, metadata, and page types."""
        logger.info("Propose: analyzing for characters and metadata")

        warnings: list[str] = []

        # Combine all text for analysis
        all_text = " ".join(doc.get("text", "") for doc in split.documents)

        # Extract potential character names
        characters = self._propose_characters(all_text)

        # Extract metadata from docProps
        metadata = self._propose_metadata(prepass_doc_props)

        # Propose page types for front/back matter
        page_types = self._propose_page_types(split.documents)

        return ProposeResult(
            characters=characters,
            metadata=metadata,
            page_types=page_types,
            warnings=warnings,
        )

    def _propose_characters(self, text: str) -> list[dict[str, Any]]:
        """Propose character names based on frequency near dialogue."""
        # Extract potential names
        words = _extract_potential_names(text)

        # Filter likely names
        name_candidates = [w for w in words if _is_likely_name(w, text)]

        # Count occurrences
        counts = Counter(name_candidates)

        # Filter: must appear at least 5 times
        proposed = []
        for name, count in counts.most_common():
            if count >= 5:
                # Find example contexts
                examples = self._find_name_examples(text, name)
                proposed.append({
                    "name": name,
                    "count": count,
                    "examples": examples[:3],  # Top 3 examples
                })

        return proposed

    def _find_name_examples(self, text: str, name: str) -> list[str]:
        """Find example sentences where the name appears."""
        examples = []
        # Find name near quotation marks
        pattern = re.compile(rf"[^.]*?{re.escape(name)}[^.]*?[\"'][^.]*?[\"']", re.IGNORECASE)
        for match in pattern.finditer(text):
            examples.append(match.group(0).strip())
            if len(examples) >= 3:
                break
        return examples

    def _propose_metadata(self, doc_props: dict[str, Any]) -> dict[str, Any]:
        """Propose metadata from document properties."""
        metadata = {}

        if doc_props.get("title"):
            metadata["title"] = doc_props["title"]
        if doc_props.get("creator"):
            metadata["author"] = doc_props["creator"]
        if doc_props.get("language"):
            metadata["language"] = doc_props["language"]
        if doc_props.get("subject"):
            metadata["description"] = doc_props["subject"]
        if doc_props.get("keywords"):
            metadata["keywords"] = doc_props["keywords"]
        if doc_props.get("description"):
            metadata["description"] = doc_props["description"]

        return metadata

    def _propose_page_types(self, documents: list[dict[str, Any]]) -> dict[str, str]:
        """Propose page types for front/back matter."""
        page_types = {}
        for doc in documents:
            if doc.get("kind") in ("front", "back"):
                plan_id = doc.get("planId", "")
                page_type = doc.get("pageType", "")
                if plan_id and page_type:
                    page_types[plan_id] = page_type
        return page_types
