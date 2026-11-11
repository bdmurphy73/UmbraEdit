"""
UmbraEdit - Attribution Gate Rules
=====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2018 Veronica Berglyd Olsen and novelWriter contributors.

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

Additional Copyright (C) 2026 B.D. Murphy.
Changes: Updated attribProposalOpen gate to also count proposals from the
proposals system and added OP_PUBLISH_PACKAGE operation.
"""  # noqa

from __future__ import annotations

import logging
import re

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.proposals import count_open_proposals

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

_ATTR_DROP_RE = re.compile(r"\[attr:drop\](.*?)\[/attr\]", re.DOTALL)
_ATTR_PROPOSAL_RE = re.compile(r"\[attr:proposal\](.*?)\[/attr\]", re.DOTALL)
_POV_RE = re.compile(r"@pov:\s*(\S+)")


def _getVoiceMatrix(item: Any) -> str | None:
    """Return the voice_matrix attribute from an entity row, or None."""
    attrs = getattr(item, "attrs", None) or {}
    return attrs.get("voice_matrix")


def _findPovTag(text: str) -> str | None:
    """Return the @pov tag from document text, or None."""
    m = _POV_RE.search(text)
    return m.group(1) if m else None


def _checkAttribDropSameVoice(scope: Any) -> Iterable[Finding]:
    """Block: effective drop is true for a speaker whose voice_matrix
    equals the scene narration voice's voice_matrix.
    """
    proj = scope.project
    if proj is None:
        return
    contentPath = proj.storage.contentPath
    if not contentPath:
        return
    index = proj.index
    for item in proj.tree:
        if not item.isFileType():
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        try:
            text = docFile.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Could not read %s", docFile)
            continue

        # Find the POV tag (scene narration speaker)
        povTag = _findPovTag(text)
        povVoiceMatrix = None
        if povTag is not None:
            povRow = index.getEntity(povTag) if hasattr(index, "getEntity") else None
            if povRow is not None:
                povVoiceMatrix = _getVoiceMatrix(povRow)

        # Check each [attr:drop] span
        for m in _ATTR_DROP_RE.finditer(text):
            attrText = m.group(1).strip()
            # Extract speaker name from attribution text like "said Bob."
            speakerMatch = re.match(
                r"(?:said|asked|replied|whispered|shouted)\s+(.+?)\s*[.,!?]\s*$",
                attrText,
                re.IGNORECASE,
            )
            if speakerMatch is None:
                continue
            speakerName = speakerMatch.group(1)
            speakerRow = index.getEntity(speakerName) if hasattr(index, "getEntity") else None
            if speakerRow is None:
                continue
            speakerVoiceMatrix = _getVoiceMatrix(speakerRow)
            if speakerVoiceMatrix is None or povVoiceMatrix is None:
                continue
            if speakerVoiceMatrix == povVoiceMatrix:
                yield Finding(
                    ruleId="attribDropSameVoice",
                    severity="block",
                    message=f"Attribution drop for '{speakerName}' would silence the scene narration voice.",
                    fix="Remove the attribution drop or assign a different voice matrix.",
                    handle=item.itemHandle,
                    line=None,
                    detail={"tag": speakerName, "voice_matrix": speakerVoiceMatrix},
                )


def _checkAttribProposalOpen(scope: Any) -> Iterable[Finding]:
    """Advisory: unaccepted [attr:proposal] spans or proposal files exist."""
    proj = scope.project
    if proj is None:
        return
    contentPath = proj.storage.contentPath
    if not contentPath:
        return
    count = 0
    for item in proj.tree:
        if not item.isFileType():
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        try:
            text = docFile.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Could not read %s", docFile)
            continue
        if _ATTR_PROPOSAL_RE.search(text):
            count += 1
            yield Finding(
                ruleId="attribProposalOpen",
                severity="advisory",
                message="Unaccepted attribution proposal exists.",
                fix="Accept or reject the attribution proposal.",
                handle=item.itemHandle,
                line=None,
                detail={},
            )
    # Also count proposals from the proposals system (P34)
    try:
        proposal_count = count_open_proposals(proj)
        if proposal_count > 0:
            yield Finding(
                ruleId="attribProposalOpen",
                severity="advisory",
                message=f"{proposal_count} open proposal(s) awaiting review",
                fix="Accept or reject proposals in the Speakers dock",
                handle=None,
                detail={"openProposals": proposal_count},
            )
    except Exception:
        logger.exception("Could not count open proposals")


registerGate(
    GateRule(
        ruleId="attribDropSameVoice",
        title="Attribution Drop Same Voice",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkAttribDropSameVoice,
    )
)

registerGate(
    GateRule(
        ruleId="attribProposalOpen",
        title="Attribution Proposal Open",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkAttribProposalOpen,
    )
)
