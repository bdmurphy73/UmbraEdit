"""UmbraEdit - Canonical Text Hash.

This file is a part of UmbraEdit, a fork of novelWriter.
Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
SHA-256 hash of text with annotations removed. Used for translation
and audio staleness tracking.
"""  # noqa

from __future__ import annotations

import hashlib
import re

from umbraedit.umbra.voiceline import VOICE_PREFIX

# Patterns to strip for the canonical form
_VOICE_LINE_RE = re.compile(r"^%Voice:.*$", re.MULTILINE)
_ATTR_RE = re.compile(r"\[/attr\]|\[attr(?::\w+)?\]")
_UTT_RE = re.compile(r"\[/utt\]|\[utt:[^\]]*\]")


def canonicalTextHash(text: str) -> str:
    """Return the SHA-256 hash of the canonical form of the text.

    The canonical form strips:
    - `%Voice:` lines (entire lines)
    - `[attr]`/`[attr:drop]`/`[attr:keep]`/`[/attr]` tags (content kept)
    - `[utt:...]`/`[/utt]` tags (content kept)
    - Trailing whitespace per line
    - Leading/trailing blank lines
    """
    # Remove %Voice: lines entirely
    stripped = _VOICE_LINE_RE.sub("", text)

    # Remove attr/utt tags (keep the inner content)
    stripped = _ATTR_RE.sub("", stripped)
    stripped = _UTT_RE.sub("", stripped)

    # Normalise trailing whitespace per line
    lines = [line.rstrip() for line in stripped.split("\n")]

    # Remove leading/trailing blank lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    canonical = "\n".join(lines)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
