"""
UmbraEdit - Rule-Based Proposer
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

import re

from pathlib import Path
from typing import Any

from umbraedit.umbra.proposals import (
    KIND_ATTRIBUTION,
    KIND_SPEAKER,
    ProposalItem,
    ProposalSet,
    _generate_run_id,
    _sha256_text,
    _utc_now_iso,
)

# Common English speech verbs
SPEECH_VERBS_EN = frozenset({
    "said",
    "asked",
    "replied",
    "whispered",
    "shouted",
    "yelled",
    "screamed",
    "murmured",
    "mumbled",
    "stammered",
    "stuttered",
    "declared",
    "announced",
    "proclaimed",
    "stated",
    "remarked",
    "commented",
    "observed",
    "noted",
    "added",
    "continued",
    "interrupted",
    "exclaimed",
    "cried",
    "gasped",
    "chuckled",
    "laughed",
    "sighed",
    "groaned",
    "muttered",
    "bellowed",
    "roared",
    "hissed",
    "snapped",
    "growled",
    "snarled",
    "wispered",
})

# Common pronouns adjacent to speech verbs
PRONOUNS = frozenset({
    "he",
    "she",
    "they",
    "it",
    "we",
    "i",
    "him",
    "her",
    "them",
    "us",
    "me",
    "his",
    "hers",
    "their",
    "its",
    "our",
    "my",
})

# Quote patterns
_OPEN_QUOTE_RE = re.compile(
    r"["
    "\u201c\u2018"
    "]"
)
_CLOSE_QUOTE_RE = re.compile(
    r"["
    "\u201d\u2019"
    "]"
)


def _find_speech_verbs(text: str, verbs: frozenset[str]) -> list[tuple[int, str, str]]:
    """Find speech-verb attribution patterns in text.

    Looks for patterns like: name + said + quote, or said + name + quote.
    Returns list of (position, speaker_name, quote_text).
    """
    results = []

    # Pattern: Name said "quote" or Name said, "quote"
    # Match capitalized word(s) followed by a speech verb
    name_verb_re = re.compile(
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+("
        + "|".join(sorted(verbs, key=len, reverse=True))
        + r")\b\s*(?:,?\s*)([\""
        + "\u201c\u2018"
        + "])"
    )

    for m in name_verb_re.finditer(text):
        name = m.group(1)
        m.group(2)
        m.group(3)
        # Find the closing quote
        close_quote = _CLOSE_QUOTE_RE.search(text, m.end())
        if close_quote:
            quote_text = text[m.end() : close_quote.start()]
            results.append((m.start(), name, quote_text))

    # Pattern: "quote," said Name
    quote_verb_re = re.compile(
        r"["
        '"\u201c\u2018'
        r"]([^\""
        "\u201d\u2019"
        r"]*?)["
        '"\u201d\u2019'
        r"]\s*(?:,?\s*)\b(" + "|".join(sorted(verbs, key=len, reverse=True)) + r")\b\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
    )

    for m in quote_verb_re.finditer(text):
        quote_text = m.group(1)
        m.group(2)
        name = m.group(3)
        results.append((m.start(), name, quote_text))

    return results


def _guess_speaker_alternation(
    project: Any,
    handle: str,
    target_para: int,
    sheet: Any,
) -> str | None:
    """Guess the speaker based on alternation from previous paragraphs.

    If the previous paragraph had a speaker, guess a different one
    (simple alternation between known speakers).
    """
    from umbraedit.umbra.units import UnitKind, iterUnits

    storage_path = project.storage.storagePath
    if not storage_path:
        return None
    doc_file = Path(storage_path) / "content" / f"{handle}.md"
    if not doc_file.is_file():
        return None

    text = doc_file.read_text(encoding="utf-8")
    units = list(iterUnits(text))

    # Collect speakers from previous paragraphs
    previous_speakers: list[str] = []
    current_para = 0
    for unit in units:
        if unit.kind == UnitKind.PARAGRAPH:
            if current_para == target_para:
                break
            for line in unit.lines:
                if line.strip().startswith("%Voice:"):
                    from umbraedit.umbra.voiceline import parseVoiceLine

                    voice = parseVoiceLine(line)
                    if voice and voice.spk:
                        previous_speakers.append(voice.spk)
                        break
            current_para += 1

    if not previous_speakers:
        return None

    # Get known speakers from sheet
    known_speakers: list[str] = []
    if sheet is not None:
        known_speakers.extend(row.tag for row in sheet.iterEntities() if row.kind == "character")

    if not known_speakers:
        return None

    last_speaker = previous_speakers[-1]
    # Pick a different speaker than the last one
    for spk in known_speakers:
        if spk != last_speaker:
            return spk

    return None


def propose_from_paragraph(
    project: Any,
    handle: str,
    para_index: int,
    text: str,
    sheet: Any,
) -> list[ProposalItem]:
    """Generate proposals for a single paragraph.

    Uses rule-based detection:
    1. Speech-verb attribution detection (speaker + quote pattern)
    2. Speaker alternation guess

    Returns list of ProposalItem objects.
    """
    items: list[ProposalItem] = []
    text_hash = _sha256_text(text)

    # 1. Speech-verb attribution detection
    speech_matches = _find_speech_verbs(text, SPEECH_VERBS_EN)
    for _position, speaker_name, _quote_text in speech_matches:
        # Check if the speaker name resolves to a known entity
        if sheet is not None:
            matches = sheet.resolveSpeaker(speaker_name)
            if len(matches) == 0:
                # Unknown speaker - mark as unresolved
                items.append(
                    ProposalItem(
                        handle=handle,
                        para=para_index,
                        textHash=text_hash,
                        kind=KIND_SPEAKER,
                        value={"spk": speaker_name, "unresolved": True},
                        confidence=0.5,
                    )
                )
                continue
            if len(matches) > 1:
                # Ambiguous
                items.append(
                    ProposalItem(
                        handle=handle,
                        para=para_index,
                        textHash=text_hash,
                        kind=KIND_SPEAKER,
                        value={"spk": speaker_name, "ambiguous": True},
                        confidence=0.4,
                    )
                )
                continue
            resolved_tag = matches[0].tag
        else:
            resolved_tag = speaker_name

        items.append(
            ProposalItem(
                handle=handle,
                para=para_index,
                textHash=text_hash,
                kind=KIND_SPEAKER,
                value={"spk": resolved_tag},
                confidence=0.75,
            )
        )

        # Also propose attribution
        attribution_text = f"{speaker_name} said"
        items.append(
            ProposalItem(
                handle=handle,
                para=para_index,
                textHash=text_hash,
                kind=KIND_ATTRIBUTION,
                value={"text": attribution_text},
                confidence=0.6,
            )
        )

    # 2. Speaker alternation guess
    if not any(i.kind == KIND_SPEAKER for i in items):
        guessed = _guess_speaker_alternation(project, handle, para_index, sheet)
        if guessed:
            items.append(
                ProposalItem(
                    handle=handle,
                    para=para_index,
                    textHash=text_hash,
                    kind=KIND_SPEAKER,
                    value={"spk": guessed, "alternation": True},
                    confidence=0.4,
                )
            )

    return items


def propose_from_document(
    project: Any,
    handle: str,
    sheet: Any,
) -> ProposalSet:
    """Generate proposals for all paragraphs in a document."""
    from umbraedit.umbra.units import UnitKind, iterUnits

    project_path = project.storage.storagePath
    doc_file = Path(project_path) / "content" / f"{handle}.md"
    if not doc_file.is_file():
        return ProposalSet(
            runId=_generate_run_id(),
            tool="umbra-proposer 0.1",
            createdAt=_utc_now_iso(),
            items=[],
        )

    text = doc_file.read_text(encoding="utf-8")
    units = list(iterUnits(text))

    all_items: list[ProposalItem] = []
    para_index = 0
    for unit in units:
        if unit.kind == UnitKind.PARAGRAPH:
            para_text = "\n".join(unit.lines)
            items = propose_from_paragraph(project, handle, para_index, para_text, sheet)
            all_items.extend(items)
            para_index += 1

    return ProposalSet(
        runId=_generate_run_id(),
        tool="umbra-proposer 0.1",
        createdAt=_utc_now_iso(),
        items=all_items,
    )


def propose_from_project(
    project: Any,
    handles: list[str] | None = None,
) -> ProposalSet:
    """Generate proposals for all (or selected) documents in a project."""
    if handles is None:
        handles = list(project.index.iterHandles())

    sheet = project.index
    all_items: list[ProposalItem] = []

    for handle in handles:
        doc_proposals = propose_from_document(project, handle, sheet)
        all_items.extend(doc_proposals.items)

    # Re-number runId
    return ProposalSet(
        runId=_generate_run_id(),
        tool="umbra-proposer 0.1",
        createdAt=_utc_now_iso(),
        items=all_items,
    )
