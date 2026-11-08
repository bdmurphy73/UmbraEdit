"""
UmbraEdit - Speaker Authoring Gate Rules
=========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for speaker authoring (P09): unassigned speakers and
unpromoted one-off speakers. Registered via ``umbra.gates``.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.dialogue import DialogueConfig, findDialogueSpans
from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.units import UnitKind, iterUnits

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from umbraedit.umbra.voiceline import VoiceData

logger = logging.getLogger(__name__)

# Dialogue configuration, built once and reused.
_dialogue_config_holder: list[DialogueConfig] = []


def _configureDialogue() -> DialogueConfig:
    """Build a dialogue config from the app settings (lazy)."""
    if not _dialogue_config_holder:
        _dialogue_config_holder.append(DialogueConfig())
    return _dialogue_config_holder[0]


def _paragraphHasDialogue(text: str) -> bool:
    """Return True when the paragraph text contains a dialogue span."""
    return any(span.kind == "dialogue" for span in findDialogueSpans(text, _configureDialogue()))


def _iterDialogueParagraphs(scope: Any) -> Iterable[tuple[str, str, str, VoiceData | None]]:
    """Yield (handle, lineNo, text, voice) for paragraphs with a dialogue
    span.

    ``voice`` is the parsed ``%Voice:`` line, or None.
    """
    project = scope.project
    if project is None:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return
    contentPath = project.storage.contentPath
    if not contentPath:
        return
    for item in project.tree:
        if not item.isFileType():
            continue
        if scope.handles and item.itemHandle not in scope.handles:
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        text = docFile.read_text(encoding="utf-8")
        for unit in iterUnits(text):
            if unit.kind != UnitKind.PARAGRAPH:
                continue
            body = "\n".join(unit.lines)
            if _paragraphHasDialogue(body):
                yield item.itemHandle, str(unit.startLine), body, unit.voice


def _checkSpeakerUnassigned(scope: Any) -> Iterable[Finding]:
    """Advisory for build.run, block for audio.chapter.

    A paragraph with a dialogue span has no speaker, or a machine
    proposal.
    """
    for handle, lineNo, _body, voice in _iterDialogueParagraphs(scope):
        if voice is None:
            yield Finding(
                ruleId="speakerUnassigned",
                severity="block",
                message=f"Paragraph at line {lineNo} of '{handle}' has dialogue but no speaker.",
                fix="Assign a speaker in annotate mode (Alt+S).",
                handle=handle,
                line=None,
                detail={"handle": handle, "line": lineNo},
            )
        elif voice.src == "machine":
            yield Finding(
                ruleId="speakerUnassigned",
                severity="block",
                message=f"Paragraph at line {lineNo} of '{handle}' uses a machine-proposed speaker '{voice.spk}'.",
                fix="Confirm or change the speaker in annotate mode (Alt+S).",
                handle=handle,
                line=None,
                detail={"handle": handle, "line": lineNo, "spk": voice.spk},
            )


def _checkOneoffUnpromoted(scope: Any) -> Iterable[Finding]:
    """Advisory: a one-off speaker (``spk=~label``) with more than five
    dialogue paragraphs.

    """
    counts: dict[str, int] = {}
    for _handle, _lineNo, _body, voice in _iterDialogueParagraphs(scope):
        if voice and voice.spk and voice.spk.startswith("~"):
            counts[voice.spk] = counts.get(voice.spk, 0) + 1
    for label, count in sorted(counts.items()):
        if count > 5:
            yield Finding(
                ruleId="oneoffUnpromoted",
                severity="advisory",
                message=f"One-off speaker '{label}' speaks in {count} paragraphs; promote it to a character.",
                fix="Promote the one-off speaker in the Speakers dock or picker.",
                handle=None,
                line=None,
                detail={"label": label.lstrip("~"), "count": count},
            )


registerGate(
    GateRule(
        ruleId="speakerUnassigned",
        title="Speaker Unassigned",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkSpeakerUnassigned,
    )
)

registerGate(
    GateRule(
        ruleId="oneoffUnpromoted",
        title="One-off Speaker Unpromoted",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkOneoffUnpromoted,
    )
)
