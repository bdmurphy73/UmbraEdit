"""
UmbraEdit - Token Gate Rules
============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for character slot tokens (P18): unresolved tokens block
build, audio chapter, and publish operations.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.tokens import findTokens

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _tokenUnresolvedFindings(scope: Any) -> Iterable[Finding]:
    """Block: unresolved tokens prevent build/audio/publish operations.

    Scans every document in the project for token syntax and reports
    any token whose slot has no character or whose attribute is empty
    or unknown.
    """
    proj = scope.project
    if not proj:
        return
    storagePath = proj.storage.storagePath
    if not storagePath:
        return
    contentPath = proj.storage.contentPath
    if not contentPath:
        return

    from umbraedit.umbra.sheet import SheetManager

    try:
        manager = SheetManager(storagePath)
        manager.buildFromProject(proj)
    except Exception:
        logger.exception("Could not load entity sheets for token gate")
        return

    # Build a set of known slot numbers for quick lookup
    knownSlots: set[int] = set()
    slotAttrs: dict[int, dict[str, str]] = {}
    for row in manager.iterEntities(kind="character"):
        slotVal = row.attrs.get("slot", "")
        if slotVal.isdigit():
            slotNum = int(slotVal)
            knownSlots.add(slotNum)
            slotAttrs[slotNum] = row.attrs

    for item in proj.tree:
        if not item.isFileType():
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        text = docFile.read_text(encoding="utf-8")
        parts = text.split("+++", 2)
        body = parts[2] if len(parts) >= 3 else text

        for token in findTokens(body):
            line = text[: token.start].count("\n") + 1
            if token.slot not in knownSlots:
                yield Finding(
                    ruleId="tokenUnresolved",
                    severity="block",
                    message=(
                        f"Token '{token.raw}' in '{item.itemName}' "
                        f"references slot {token.slot} which has no "
                        f"character assigned."
                    ),
                    fix=("Assign a character to the slot in the Sheets view, or remove the token."),
                    handle=item.itemHandle,
                    line=line,
                    detail={
                        "slot": token.slot,
                        "attr": token.attr,
                        "token": token.raw,
                        "itemName": item.itemName,
                    },
                )
                continue

            attrs = slotAttrs.get(token.slot, {})
            attrKey = token.attr or "full_name"
            if attrKey not in attrs and not attrKey.startswith("x_"):
                yield Finding(
                    ruleId="tokenUnresolved",
                    severity="block",
                    message=(f"Token '{token.raw}' in '{item.itemName}' references unknown attribute '{attrKey}'."),
                    fix=(f"Add '@attr: {attrKey} | value' to the character's sheet, or use an existing attribute."),
                    handle=item.itemHandle,
                    line=line,
                    detail={
                        "slot": token.slot,
                        "attr": token.attr,
                        "token": token.raw,
                        "itemName": item.itemName,
                    },
                )
                continue

            value = attrs.get(attrKey, "")
            if not value:
                yield Finding(
                    ruleId="tokenUnresolved",
                    severity="block",
                    message=(f"Token '{token.raw}' in '{item.itemName}' has an empty value for attribute '{attrKey}'."),
                    fix=(f"Set a value for '{attrKey}' in the character's sheet, or remove the token."),
                    handle=item.itemHandle,
                    line=line,
                    detail={
                        "slot": token.slot,
                        "attr": token.attr,
                        "token": token.raw,
                        "itemName": item.itemName,
                    },
                )


registerGate(
    GateRule(
        ruleId="tokenUnresolved",
        title="Unresolved Token",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_tokenUnresolvedFindings,
    )
)
