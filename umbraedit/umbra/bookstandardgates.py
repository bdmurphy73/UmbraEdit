"""
UmbraEdit - Book Standard Gates
================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for Book Standard checks (P30).
"""  # noqa

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Gate rule IDs
RULE_BS_HEADING_SKIP = "bsHeadingSkip"
RULE_BS_DOUBLE_SPACE = "bsDoubleSpace"
RULE_BS_STRAIGHT_QUOTES = "bsStraightQuotes"
RULE_BS_MIXED_QUOTE_STYLE = "bsMixedQuoteStyle"
RULE_BS_DASH_USE = "bsDashUse"
RULE_BS_ELLIPSIS_STYLE = "bsEllipsisStyle"
RULE_BS_EMPTY_CHAPTER = "bsEmptyChapter"
RULE_BS_SCENE_BREAK_AT_EDGE = "bsSceneBreakAtEdge"
RULE_BS_FRONT_MATTER_ORDER = "bsFrontMatterOrder"
RULE_BS_TOC_MISSING = "bsTocMissing"
RULE_BS_ORPHAN_FOOTNOTE = "bsOrphanFootnote"

# Rules that block by default for print/EPUB targets
BLOCK_RULES = {
    RULE_BS_HEADING_SKIP,
    RULE_BS_EMPTY_CHAPTER,
    RULE_BS_SCENE_BREAK_AT_EDGE,
    RULE_BS_FRONT_MATTER_ORDER,
    RULE_BS_TOC_MISSING,
    RULE_BS_ORPHAN_FOOTNOTE,
}

# Rules that are advisory by default
ADVISORY_RULES = {
    RULE_BS_DOUBLE_SPACE,
    RULE_BS_STRAIGHT_QUOTES,
    RULE_BS_MIXED_QUOTE_STYLE,
    RULE_BS_DASH_USE,
    RULE_BS_ELLIPSIS_STYLE,
    RULE_BS_EMPTY_CHAPTER,
    RULE_BS_SCENE_BREAK_AT_EDGE,
    RULE_BS_FRONT_MATTER_ORDER,
    RULE_BS_TOC_MISSING,
    RULE_BS_ORPHAN_FOOTNOTE,
}


def _bsHeadingSkipFindings(scope: Any) -> "Iterable[Finding]":
    """Block: heading levels skip (e.g., H1 to H3)."""
    project = scope.project
    if not project:
        return

    # Only check for print/EPUB targets
    operation = scope.operation
    if operation not in {OP_BUILD_RUN, OP_PUBLISH_PACKAGE}:
        return

    # Only block for print/EPUB targets
    bFormat = scope.options.get("format")
    if bFormat not in {"PRINT_PDF", "EPUB_VALIDATED", "EPUB", "PDF"}:
        return

    # Get tokenizer from last build
    doc_build = scope.project.docBuild
    if not doc_build or not doc_build.lastBuild:
        return

    tokenizer = doc_build.lastBuild
    if not hasattr(tokenizer, "_blocks"):
        return

    prev_level = 0
    for block in getattr(tokenizer, "_blocks", []):
        block_type = block[0]
        if block_type in {1, 2, 3, 4}:  # HEAD1-HEAD4
            level = block[0]  # HEAD1=1, HEAD2=2, etc.
            if prev_level > 0 and level > prev_level + 1:
                yield Finding(
                    ruleId="bsHeadingSkip",
                    severity="block",
                    message=f"Heading level jumps from H{prev_level} to H{level}",
                    fix=f"Insert intermediate heading level H{prev_level + 1}",
                    handle="heading",
                    detail={"fromLevel": prev_level, "toLevel": level},
                )
            prev_level = level


def _bsDoubleSpaceFindings(scope: Any) -> "Iterable[Any]":
    """Advisory: double spaces after sentences."""
    # TODO: Implement
    return


def _bsStraightQuotesFindings(scope: Any) -> "Iterable[Any]":
    """Block/Advisory: straight quotes used in text."""
    project = scope.project
    if not project:
        return

    storage_path = project.storage.storagePath
    content_path = project.storage.contentPath
    if not content_path:
        return

    straight_single = re.compile(r"[\"']")
    curly_single_open = "\u2018"
    curly_single_close = "\u2019"
    curly_double_open = "\u201c"
    curly_double_close = "\u201d"

    for item in scope.project.tree:
        if not item.isFileType():
            continue
        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue
        try:
            text = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for match in straight_single.finditer(text):
            char = match.group()
            if char in ("'", '"'):
                # Check if it's not already curly
                context_start = max(0, match.start() - 10)
                context_end = min(len(text), match.end() + 10)
                context = text[context_start:context_end]
                if any(c in context for c in (curly_single_open, curly_single_close, curly_double_open, curly_double_close)):
                    continue  # Already using curly quotes nearby

                yield Finding(
                    ruleId="bsStraightQuotes",
                    severity="block",
                    message=f"Straight quote found: '{context}'",
                    fix="Replace with curly quotes (\u2018\u2019 or \u201c\u201d)",
                    handle="document",
                    detail={"context": context},
                )


def _bsMixedQuoteStyleFindings(scope: Any) -> "Iterable[Any]":
    """Advisory: mixed quote styles."""
    # TODO: Implement
    return


def _bsDashUseFindings(scope: Any) -> "Iterable[Any]":
    """Advisory: hyphen used as dash between spaces."""
    project = scope.project
    if not project:
        return

    content_path = project.storage.contentPath
    if not content_path:
        return

    dash_pattern = re.compile(r"\s-\s")

    for item in scope.project.tree:
        if not item.isFileType():
            continue
        doc_file = project.storage.contentPath / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue
        try:
            text = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for match in re.finditer(r"\s-\s", text):
            context_start = max(0, match.start() - 20)
            context_end = min(len(text), match.end() + 20)
            context = text[context_start:context_end]
            yield Finding(
                ruleId="bsDashUse",
                severity="advisory",
                message=f"Hyphen used as dash: '{context}'",
                fix="Use em dash (\u2014) or en dash (\u2013) for dashes",
                handle="document",
                detail={"context": context},
            )


def _bsEllipsisStyleFindings(scope: Any) -> "Iterable[Any]":
    """Advisory: inconsistent ellipsis style."""
    project = scope.project
    if not project:
        return

    content_path = project.storage.contentPath
    if not content_path:
        return

    ellipsis_patterns = [
        (re.compile(r"\.\.\."), "three dots"),
        (re.compile(r"\u2026"), "unicode ellipsis"),
    ]

    styles_found = set()
    for item in scope.project.tree:
        if not item.isFileType():
            continue
        doc_file = project.storage.contentPath / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue
        try:
            text = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for pattern, style in ellipsis_patterns:
            if pattern.search(text):
                styles_found.add(style)

    if len(styles_found) > 1:
        yield Finding(
            ruleId="bsEllipsisStyle",
            severity="advisory",
            message=f"Mixed ellipsis styles: {', '.join(styles_found)}",
            fix="Use consistent ellipsis style (prefer Unicode \u2026)",
            handle="document",
            detail={"styles": list(styles_found)},
        )


def _bsEmptyChapterFindings(scope: Any) -> "Iterable[Any]":
    """Block/Advisory: chapter with no content."""
    project = scope.project
    if not project:
        return

    # Only block for print/EPUB targets
    bFormat = scope.options.get("format")
    if bFormat not in {"PRINT_PDF", "EPUB_VALIDATED", "EPUB", "PDF"}:
        return

    content_path = scope.project.storage.contentPath
    if not content_path:
        return

    from umbraedit.formats.tokenizer import Tokenizer

    for item in scope.project.tree:
        if not item.isFileType() or not item.isDocumentLayout():
            continue
        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue

        try:
            text = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Tokenize and check for content
        tokenizer = Tokenizer(project)
        tokenizer.setText(text)
        tokenizer.tokenizeText()

        has_content = False
        for block in getattr(tokenizer, "_blocks", []):
            if block[0] in {1, 2, 3, 4, 5, 6, 7}:  # Text content blocks
                if block[2].strip():
                    has_content = True
                    break

        if not has_content:
            yield Finding(
                ruleId="bsEmptyChapter",
                severity="block",
                message=f"Chapter '{item.itemName}' has no content",
                fix="Add content to the chapter or remove it",
                handle=item.itemHandle,
                detail={"chapter": item.itemName},
            )


def _bsSceneBreakAtEdgeFindings(scope: Any) -> "Iterable[Any]":
    """Block/Advisory: scene break at start or end of chapter."""
    project = scope.project
    if not project:
        return

    bFormat = scope.options.get("format")
    if bFormat not in {"PRINT_PDF", "EPUB_VALIDATED", "EPUB", "PDF"}:
        return

    content_path = scope.project.storage.contentPath
    if not content_path:
        return

    from umbraedit.formats.tokenizer import Tokenizer, BlockTyp

    for item in scope.project.tree:
        if not item.isFileType() or not item.isDocumentLayout():
            continue
        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue

        try:
            text = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        tokenizer = Tokenizer(project)
        tokenizer.setText(text)
        tokenizer.tokenizeText()

        blocks = getattr(tokenizer, "_blocks", [])
        if not blocks:
            continue

        # Check first and last non-empty block
        content_blocks = [b for b in blocks if b[0] in {BlockTyp.TEXT, BlockTyp.HEAD1, BlockTyp.HEAD2, BlockTyp.HEAD3, BlockTyp.HEAD4}]
        if not content_blocks:
            continue

        first = content_blocks[0]
        last = content_blocks[-1]

        # Check first block for scene break
        if first[0] == BlockTyp.SCENE_SEP:
            yield Finding(
                ruleId="bsSceneBreakAtEdge",
                severity="block",
                message=f"Chapter '{item.itemName}' starts with a scene break",
                fix="Remove scene break from chapter start or add content before it",
                handle=item.itemHandle,
                detail={"position": "start"},
            )

        # Check last block for scene break
        if last[0] == BlockTyp.SCENE_SEP:
            yield Finding(
                ruleId="bsSceneBreakAtEdge",
                severity="block",
                message=f"Chapter '{item.itemName}' ends with a scene break",
                fix="Remove scene break from chapter end or add content after it",
                handle=item.itemHandle,
                detail={"position": "end"},
            )


def _bsFrontMatterOrderFindings(scope: Any) -> "Iterable[Any]":
    """Block/Advisory: front matter order incorrect."""
    # TODO: Implement proper front matter order checking
    return


def _bsTocMissingFindings(scope: Any) -> "Iterable[Any]":
    """Block: Table of Contents missing for print/EPUB."""
    project = scope.project
    if not project:
        return

    bFormat = scope.options.get("format")
    if bFormat not in {"PRINT_PDF", "EPUB_VALIDATED", "EPUB", "PDF"}:
        return

    # Check if TOC is enabled in build settings
    build = scope.project.docBuild
    if build and build.getBool("epub.nestedToc"):
        return  # TOC is enabled

    yield Finding(
        ruleId="bsTocMissing",
        severity="block",
        message="Table of Contents is missing for print/EPUB output",
        fix="Enable 'Nested Table of Contents' in EPUB options or add TOC to front matter",
        handle="build",
        detail={"format": scope.options.get("format")},
    )


def _bsOrphanFootnoteFindings(scope: Any) -> "Iterable[Any]":
    """Block: footnote without reference."""
    project = scope.project
    if not project:
        return

    content_path = project.storage.contentPath
    if not content_path:
        return

    # Collect all footnote references
    refs = set()
    footnotes = set()

    for item in scope.project.tree:
        if not item.isFileType():
            continue
        doc_file = content_path / f"{item.itemHandle}.md"
        if not doc_file.is_file():
            continue
        try:
            text = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Find footnote references [^1] or [^note]
        for match in re.finditer(r"\[\^([^\]]+)\]", text):
            refs.add(match.group(1))

        # Find footnote definitions [^1]: text
        for match in re.finditer(r"\[\^([^\]]+)\]:\s*(.+)", text):
            footnotes.add(match.group(1))

    # Find orphan footnotes (defined but not referenced)
    for fn in footnotes:
        if fn not in refs:
            yield Finding(
                ruleId="bsOrphanFootnote",
                severity="block",
                message=f"Footnote '^{fn}' is defined but never referenced",
                fix="Add a reference [^{fn}] in the text or remove the footnote",
                handle="footnote",
                detail={"footnote": fn},
            )

    # Find unresolved references
    for ref in refs:
        if ref not in footnotes:
            yield Finding(
                ruleId="bsOrphanFootnote",
                severity="block",
                message=f"Footnote reference '^{ref}' has no definition",
                fix="Add footnote definition [^{ref}]: ... or remove the reference",
                handle="footnote",
                detail={"reference": ref},
            )


# Register all Book Standard gates
registerGate(
    GateRule(
        ruleId="bsHeadingSkip",
        title="Book Standard: Heading Level Skip",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsHeadingSkipFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsDoubleSpace",
        title="Book Standard: Double Space After Sentence",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_bsDoubleSpaceFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsStraightQuotes",
        title="Book Standard: Straight Quotes",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsStraightQuotesFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsMixedQuoteStyle",
        title="Book Standard: Mixed Quote Style",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_bsMixedQuoteStyleFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsDashUse",
        title="Book Standard: Hyphen as Dash",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_bsDashUseFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsEllipsisStyle",
        title="Book Standard: Ellipsis Style",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_bsEllipsisStyleFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsEmptyChapter",
        title="Book Standard: Empty Chapter",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsEmptyChapterFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsSceneBreakAtEdge",
        title="Book Standard: Scene Break at Chapter Edge",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsSceneBreakAtEdgeFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsFrontMatterOrder",
        title="Book Standard: Front Matter Order",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsFrontMatterOrderFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsTocMissing",
        title="Book Standard: Missing Table of Contents",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsTocMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bsOrphanFootnote",
        title="Book Standard: Orphan Footnote",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_bsOrphanFootnoteFindings,
    )
)