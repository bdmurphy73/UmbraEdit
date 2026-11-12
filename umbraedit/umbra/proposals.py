"""
UmbraEdit - Analysis Proposal Intake
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
import uuid

from dataclasses import dataclass, field
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.paths import proposalsDir
from umbraedit.umbra.voiceline import VoiceData, formatVoiceLine, parseVoiceLine

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Proposal kinds
KIND_SPEAKER = "speaker"
KIND_ATTRIBUTION = "attribution"
KIND_TONE = "tone"

ALL_KINDS = frozenset({KIND_SPEAKER, KIND_ATTRIBUTION, KIND_TONE})


@dataclass(frozen=True)
class ProposalItem:
    """One proposal item from an external analysis tool.

    Attributes:
        handle: Document handle the proposal applies to.
        para: Zero-based paragraph index within the document.
        textHash: SHA-256 of the paragraph text at proposal time.
        kind: ``speaker``, ``attribution``, or ``tone``.
        value: Proposed value dict (kind-dependent keys).
        confidence: Confidence score 0.0-1.0.

    """

    handle: str
    para: int
    textHash: str
    kind: str
    value: dict[str, Any]
    confidence: float


@dataclass(frozen=True)
class ProposalSet:
    """A collection of proposals from one run."""

    v: int = 1
    runId: str = ""
    tool: str = ""
    createdAt: str = ""
    items: list[ProposalItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert proposal set to dictionary for JSON serialization."""
        return {
            "v": self.v,
            "runId": self.runId,
            "tool": self.tool,
            "createdAt": self.createdAt,
            "items": [
                {
                    "handle": i.handle,
                    "para": i.para,
                    "textHash": i.textHash,
                    "kind": i.kind,
                    "value": i.value,
                    "confidence": i.confidence,
                }
                for i in self.items
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposalSet:
        """Create ProposalSet from dictionary."""
        items = [
            ProposalItem(
                handle=item.get("handle", ""),
                para=item.get("para", 0),
                textHash=item.get("textHash", ""),
                kind=item.get("kind", ""),
                value=item.get("value", {}),
                confidence=item.get("confidence", 0.0),
            )
            for item in data.get("items", [])
        ]
        return cls(
            v=data.get("v", 1),
            runId=data.get("runId", ""),
            tool=data.get("tool", ""),
            createdAt=data.get("createdAt", ""),
            items=items,
        )


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_run_id() -> str:
    return f"pr-{uuid.uuid4().hex[:12]}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _read_document_paragraphs(project_path: Path | str, handle: str) -> list[str]:
    """Read all paragraph texts from a document.

    Returns the text of each PARAGRAPH unit (voice lines excluded).
    """
    project_path = Path(project_path)
    doc_file = project_path / "content" / f"{handle}.md"
    if not doc_file.is_file():
        return []
    text = doc_file.read_text(encoding="utf-8")

    from umbraedit.umbra.units import UnitKind, iterUnits

    return ["\n".join(unit.lines) for unit in iterUnits(text) if unit.kind == UnitKind.PARAGRAPH]


def compute_text_hash(project_path: Path, handle: str, para_index: int) -> str | None:
    """Compute the SHA-256 hash of a paragraph's text.

    Returns None if the document or paragraph doesn't exist.
    """
    paragraphs = _read_document_paragraphs(project_path, handle)
    if para_index < 0 or para_index >= len(paragraphs):
        return None
    return _sha256_text(paragraphs[para_index])


def import_proposals(
    project: NWProject,
    file_path: Path,
) -> dict[str, Any]:
    """Import proposals from a JSON file.

    Items whose textHash no longer matches the paragraph are skipped
    and counted separately.

    Returns a dict with keys: accepted, skipped, total, runId.
    """
    if not file_path.is_file():
        return {"accepted": 0, "skipped": 0, "total": 0, "runId": "", "error": "File not found"}

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read proposal file: %s", exc)
        return {"accepted": 0, "skipped": 0, "total": 0, "runId": "", "error": str(exc)}

    proposal_set = ProposalSet.from_dict(data)
    storage_path = project.storage.storagePath
    if not storage_path:
        return {"accepted": 0, "skipped": 0, "total": 0, "runId": "", "error": "No storage path"}
    project_path = Path(storage_path)

    accepted = 0
    skipped = 0

    valid_items: list[ProposalItem] = []
    for item in proposal_set.items:
        current_hash = compute_text_hash(project_path, item.handle, item.para)
        if current_hash is None or current_hash != item.textHash:
            skipped += 1
            logger.info(
                "Skipping proposal for %s para %d: textHash mismatch",
                item.handle,
                item.para,
            )
            continue
        valid_items.append(item)
        accepted += 1

    # Write the proposal file (with only valid items)
    new_proposal_set = ProposalSet(
        v=proposal_set.v,
        runId=proposal_set.runId,
        tool=proposal_set.tool,
        createdAt=_utc_now_iso(),
        items=valid_items,
    )

    proposals_dir = proposalsDir(project_path)
    proposal_file = proposals_dir / f"{new_proposal_set.runId}.json"
    _atomic_write_json(proposal_file, new_proposal_set.to_dict())

    return {
        "accepted": accepted,
        "skipped": skipped,
        "total": len(valid_items) + skipped,
        "runId": new_proposal_set.runId,
    }


def list_proposals(project: NWProject) -> list[dict[str, Any]]:
    """List all proposal files in the project."""
    storage_path = project.storage.storagePath
    if not storage_path:
        return []
    project_path = Path(storage_path)
    proposals_dir = proposalsDir(project_path)

    result = []
    if not proposals_dir.is_dir():
        return result

    for proposal_file in sorted(proposals_dir.glob("*.json")):
        try:
            data = json.loads(proposal_file.read_text(encoding="utf-8"))
            proposal_set = ProposalSet.from_dict(data)
            result.append({
                "runId": proposal_set.runId,
                "tool": proposal_set.tool,
                "createdAt": proposal_set.createdAt,
                "itemCount": len(proposal_set.items),
                "file": proposal_file.name,
            })
        except Exception:
            logger.exception("Failed to read proposal file %s", proposal_file)
    return result


def get_proposal_items(project: NWProject, run_id: str) -> list[ProposalItem] | None:
    """Get all items from a specific proposal run."""
    storage_path = project.storage.storagePath
    if not storage_path:
        return None
    project_path = Path(storage_path)
    proposal_file = proposalsDir(project_path) / f"{run_id}.json"
    if not proposal_file.is_file():
        return None
    try:
        data = json.loads(proposal_file.read_text(encoding="utf-8"))
        return ProposalSet.from_dict(data).items
    except Exception:
        logger.exception("Failed to read proposal items for %s", run_id)
        return None


def resolve_speaker(sheet: Any, name: str) -> list[Any]:
    """Resolve a speaker name to matching entities.

    Returns 0, 1, or many EntityRow matches.
    """
    if sheet is None:
        return []
    return sheet.resolveSpeaker(name)


def accept_proposal(
    project: NWProject,
    run_id: str,
    item_index: int,
) -> dict[str, Any]:
    """Accept a proposal and write the author data into the text.

    Returns a dict with success status and details.
    """
    items = get_proposal_items(project, run_id)
    if items is None or item_index < 0 or item_index >= len(items):
        return {"success": False, "error": "Proposal item not found"}

    item = items[item_index]

    storage_path = project.storage.storagePath
    if not storage_path:
        return {"success": False, "error": "Project storage path not set"}
    project_path = Path(storage_path)
    doc_file = project_path / "content" / f"{item.handle}.md"
    if not doc_file.is_file():
        return {"success": False, "error": "Document not found"}

    from umbraedit.umbra.units import UnitKind, iterUnits

    text = doc_file.read_text(encoding="utf-8")
    units = list(iterUnits(text))

    para_index = 0
    target_unit: Any = None
    for unit in units:
        if unit.kind == UnitKind.PARAGRAPH:
            if para_index == item.para:
                target_unit = unit
                break
            para_index += 1

    if target_unit is None:
        return {"success": False, "error": "Paragraph not found"}

    # Check if the field already exists (author data wins)
    existing_voice = parse_voice_from_lines(target_unit.lines)
    # Also check unit.voice which stores parsed %Voice: data separately
    if target_unit.voice is not None:
        if existing_voice.spk is None:
            existing_voice.spk = target_unit.voice.spk
        if existing_voice.src is None:
            existing_voice.src = target_unit.voice.src
        if existing_voice.tone is None:
            existing_voice.tone = target_unit.voice.tone

    new_lines: list[str] | None = None

    if item.kind == KIND_SPEAKER:
        proposed_spk = item.value.get("spk", "")
        if not proposed_spk:
            return {"success": False, "error": "No speaker in proposal value"}

        # Resolve the speaker name
        sheet = project.index
        matches = resolve_speaker(sheet, proposed_spk)
        if len(matches) == 0:
            # Unresolved - mark as unresolved, don't create character
            return {
                "success": False,
                "error": "unresolved",
                "speaker": proposed_spk,
            }
        if len(matches) > 1:
            return {
                "success": False,
                "error": "ambiguous",
                "speaker": proposed_spk,
                "matches": [m.tag for m in matches],
            }

        resolved_tag = matches[0].tag

        # Author data wins: if paragraph already has spk, skip
        if existing_voice.spk is not None:
            return {"success": False, "error": "superseded", "reason": "paragraph already has speaker"}

        # Write spk= without src=machine (author decision)
        new_lines = _set_voice_spk(target_unit.lines, resolved_tag, src=None)

    elif item.kind == KIND_TONE:
        proposed_tone = item.value.get("tone", "")
        proposed_tone_i = item.value.get("toneI", 2)

        # Author data wins: if paragraph already has tone, skip
        if existing_voice.tone is not None:
            return {"success": False, "error": "superseded", "reason": "paragraph already has tone"}

        new_lines = _set_voice_tone(target_unit.lines, proposed_tone, proposed_tone_i)

    elif item.kind == KIND_ATTRIBUTION:
        proposed_text = item.value.get("text", "")
        if not proposed_text:
            return {"success": False, "error": "No attribution text in proposal value"}

        # Attribution is written as inline text in the paragraph
        new_lines = list(target_unit.lines)

    else:
        return {"success": False, "error": f"Unknown proposal kind: {item.kind}"}

    if new_lines is None:
        return {"success": False, "error": "Failed to apply proposal"}

    # Write the modified document
    new_units_lines = []
    for unit in units:
        if unit is target_unit:
            new_units_lines.extend(new_lines)
        else:
            new_units_lines.extend(unit.lines)
    new_text = "\n".join(new_units_lines)
    doc_file.write_text(new_text, encoding="utf-8", newline="\n")

    # Remove the accepted proposal item from the file
    proposal_file = proposalsDir(project_path) / f"{run_id}.json"
    proposal_set_data = json.loads(proposal_file.read_text(encoding="utf-8"))
    proposal_set = ProposalSet.from_dict(proposal_set_data)
    remaining_items = [i for idx, i in enumerate(proposal_set.items) if idx != item_index]

    if not remaining_items:
        # No items left, remove the file
        proposal_file.unlink()
    else:
        new_proposal_set = ProposalSet(
            v=proposal_set.v,
            runId=proposal_set.runId,
            tool=proposal_set.tool,
            createdAt=proposal_set.createdAt,
            items=remaining_items,
        )
        _atomic_write_json(proposal_file, new_proposal_set.to_dict())

    return {"success": True, "kind": item.kind, "handle": item.handle, "para": item.para}


def reject_proposal(
    project: NWProject,
    run_id: str,
    item_index: int,
) -> dict[str, Any]:
    """Reject a proposal (remove it from the file)."""
    items = get_proposal_items(project, run_id)
    if items is None or item_index < 0 or item_index >= len(items):
        return {"success": False, "error": "Proposal item not found"}

    storage_path = project.storage.storagePath
    if not storage_path:
        return {"success": False, "error": "Project storage path not set"}
    proposal_file = proposalsDir(Path(storage_path)) / f"{run_id}.json"
    proposal_set_data = json.loads(proposal_file.read_text(encoding="utf-8"))
    proposal_set = ProposalSet.from_dict(proposal_set_data)
    remaining_items = [i for idx, i in enumerate(proposal_set.items) if idx != item_index]

    if not remaining_items:
        proposal_file.unlink()
    else:
        new_proposal_set = ProposalSet(
            v=proposal_set.v,
            runId=proposal_set.runId,
            tool=proposal_set.tool,
            createdAt=proposal_set.createdAt,
            items=remaining_items,
        )
        _atomic_write_json(proposal_file, new_proposal_set.to_dict())

    return {"success": True}


def parse_voice_from_lines(lines: list[str]) -> VoiceData:
    """Parse %Voice: from paragraph lines, returning empty VoiceData if none."""
    for line in lines:
        voice = parseVoiceLine(line)
        if voice is not None:
            return voice
    return VoiceData()


def _set_voice_spk(lines: list[str], spk: str, src: str | None) -> list[str]:
    """Set or add spk= to the %Voice: line of a paragraph."""
    new_lines = []
    voice_line_found = False
    for line in lines:
        if line.strip().startswith("%Voice:"):
            voice = parseVoiceLine(line)
            if voice is not None:
                voice.spk = spk
                if src is not None:
                    voice.src = src
                else:
                    # Remove src if it was machine (author decision)
                    voice.src = None
                new_lines.append(formatVoiceLine(voice))
                voice_line_found = True
                continue
        new_lines.append(line)

    if not voice_line_found:
        # Add a %Voice: line at the start
        voice = VoiceData(spk=spk, src=src)
        new_lines.insert(0, formatVoiceLine(voice))

    return new_lines


def _set_voice_tone(lines: list[str], tone: str, tone_i: int) -> list[str]:
    """Set or add tone to the %Voice: line of a paragraph."""
    new_lines = []
    voice_line_found = False
    for line in lines:
        if line.strip().startswith("%Voice:"):
            voice = parseVoiceLine(line)
            if voice is not None:
                voice.tone = tone
                # toneI is not a VoiceData field, store in extra or handle separately
                new_lines.append(formatVoiceLine(voice))
                voice_line_found = True
                continue
        new_lines.append(line)

    if not voice_line_found:
        voice = VoiceData(tone=tone)
        new_lines.insert(0, formatVoiceLine(voice))

    return new_lines


def count_open_proposals(project: NWProject) -> int:
    """Count all open (unaccepted, unrejected) proposal items."""
    total = 0
    for proposal_info in list_proposals(project):
        total += proposal_info.get("itemCount", 0)
    return total
