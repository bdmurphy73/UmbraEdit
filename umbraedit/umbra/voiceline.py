"""
UmbraEdit - Voice Line Parser
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Parses and formats `%Voice:` annotation lines. These are paragraph-level
metadata lines that tell the audio tools who speaks and how. They are
comments for every existing tool: counting ignores them, other exports
skip them.
"""  # noqa

from __future__ import annotations

import re

from dataclasses import dataclass, field

VOICE_PREFIX = "%Voice:"

# Canonical key order for formatting
_CANONICAL_ORDER = ["spk", "src", "tone", "ntone", "lang", "scope"]

# Valid keys
_VALID_KEYS = frozenset(_CANONICAL_ORDER)

# Regex to match the prefix (case-sensitive)
_PREFIX_RE = re.compile(r"^%Voice:\s*")

# Regex to parse key=value pairs
_KV_RE = re.compile(r"(\w+)=(\S+)")


@dataclass
class VoiceData:
    """Parsed data from a `%Voice:` annotation line.

    Attributes:
        spk: Dialogue speaker (tag, narrator, or ~one_off_label).
        src: "machine" if spk is a proposal, absent means author.
        tone: Tone of the dialogue (key or key:1-3).
        ntone: Tone of the narration.
        lang: BCP 47 language code for the dialogue.
        scope: "scene" marks the scene annotation line.
        extra: Unknown keys preserved for round-trip.

    """

    spk: str | None = None
    src: str | None = None
    tone: str | None = None
    ntone: str | None = None
    lang: str | None = None
    scope: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


def isVoiceLine(line: str) -> bool:
    """Return True if the line is a `%Voice:` annotation line."""
    return _PREFIX_RE.match(line) is not None


def parseVoiceLine(line: str) -> VoiceData | None:
    """Parse a `%Voice:` annotation line.

    Returns None if the line is not a `%Voice:` line.
    Returns a VoiceData with None fields for absent keys.
    """
    match = _PREFIX_RE.match(line)
    if not match:
        return None

    remainder = line[match.end():].strip()
    data = VoiceData()
    unknown: dict[str, str] = {}

    for kv in _KV_RE.finditer(remainder):
        key = kv.group(1)
        value = kv.group(2)

        if key == "spk":
            data.spk = value
        elif key == "src":
            data.src = value
        elif key == "tone":
            data.tone = value
        elif key == "ntone":
            data.ntone = value
        elif key == "lang":
            data.lang = value
        elif key == "scope":
            data.scope = value
        else:
            unknown[key] = value

    data.extra = unknown
    return data


def formatVoiceLine(data: VoiceData) -> str:
    """Format a VoiceData as a canonical `%Voice:` line.

    Keys are written in canonical order. Defaults are omitted.
    Unknown keys are written after the known keys.
    """
    parts: list[str] = []

    for key in _CANONICAL_ORDER:
        value = getattr(data, key, None)
        if value is not None:
            parts.append(f"{key}={value}")

    for key in sorted(data.extra):
        parts.append(f"{key}={data.extra[key]}")

    if not parts:
        return f"{VOICE_PREFIX}"

    return f"{VOICE_PREFIX} {' '.join(parts)}"
