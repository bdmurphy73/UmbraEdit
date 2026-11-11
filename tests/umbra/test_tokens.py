"""
UmbraEdit - Entity Sheet Tests
======================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.dialogue import DialogueConfig, findDialogueSpans
from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    getGate,
)
from umbraedit.umbra.tokens import (
    findTokens,
    isKnownAttr,
    resolveTokens,
)


def _makeSheetManager(tmp_path: Path) -> Any:
    """Create a SheetManager bound to a test project with characters."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    SheetManager = __import__("umbraedit.umbra.sheet", fromlist=["SheetManager"]).SheetManager

    mgr = SheetManager(tmp_path)

    # Write document files with @attr metadata in the body
    contentPath = project.storage.contentPath
    assert contentPath is not None

    # Find document files created by buildTestProject
    doc_files = sorted(contentPath.glob("*.md"))
    assert len(doc_files) >= 2, "Expected at least 2 document files"

    for i, docFile in enumerate(doc_files):
        handle = docFile.stem
        fn_name = "Ana" if i == 0 else "Robert"
        ln_name = "Soler" if i == 0 else "Vega"
        slot = str(i + 1)
        docFile.write_text(
            f"+++\ntag: {handle}\nkind: character\n"
            f"+++\n@tag: {handle}\n@attr: slot | {slot}\n"
            f"@attr: fn | {fn_name}\n@attr: ln | {ln_name}\n"
            f"@alias: {fn_name}\n\nScene text.\n",
            encoding="utf-8",
            newline="\n",
        )

    project.session.startSession()
    project._valid = True
    project._tree._ready = True

    return mgr, project


@pytest.mark.umbra
def test_tokens_R1_findTokens_basic(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: findTokens finds all {charN attr} tokens in order."""
    text = "Hello {char1 fn}, meet {char2 ln} and {char3}."
    tokens = findTokens(text)
    assert len(tokens) == 3
    assert tokens[0].raw == "{char1 fn}"
    assert tokens[0].slot == 1
    assert tokens[0].attr == "fn"
    assert tokens[0].start == 6
    assert tokens[0].end == 16

    assert tokens[1].raw == "{char2 ln}"
    assert tokens[1].slot == 2
    assert tokens[1].attr == "ln"

    assert tokens[2].raw == "{char3}"
    assert tokens[2].slot == 3
    assert tokens[2].attr == ""


@pytest.mark.umbra
def test_tokens_R1_findTokens_escaped(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    r"""R1: Escaped braces \\{ are not tokens."""
    text = "\\{char1 fn} and {char2 fn}"
    tokens = findTokens(text)
    assert len(tokens) == 2


@pytest.mark.umbra
def test_tokens_R1_findTokens_no_tokens(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: Text without tokens returns empty list."""
    text = "Just plain text with no tokens at all."
    assert findTokens(text) == []


@pytest.mark.umbra
def test_tokens_R1_isKnownAttr(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: isKnownAttr recognises built-in and custom keys."""
    assert isKnownAttr("fn")
    assert isKnownAttr("ln")
    assert isKnownAttr("full_name")
    assert isKnownAttr("nick")
    assert isKnownAttr("title")
    assert isKnownAttr("suffix")
    assert isKnownAttr("x_custom_key")
    assert isKnownAttr("")  # empty defaults to full_name
    assert not isKnownAttr("unknown_key")
    assert not isKnownAttr("invalid")


@pytest.mark.umbra
def test_tokens_R1_resolveTokens_success(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: resolveTokens replaces tokens with attribute values."""
    _mgr, project = _makeSheetManager(tmp_path)

    text = "{char1 fn} met {char2 ln} for coffee."
    result, unresolved = resolveTokens(text, project)

    assert "Ana" in result
    assert "Vega" in result
    assert "{char1 fn}" not in result
    assert "{char2 ln}" not in result
    assert unresolved == []


@pytest.mark.umbra
def test_tokens_R1_resolveTokens_empty_attr(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: resolveTokens flags tokens with empty attribute values."""
    _mgr, project = _makeSheetManager(tmp_path)

    text = "{char1 nickname} is here."
    result, unresolved = resolveTokens(text, project)

    assert "{char1 nickname}" in result  # not replaced
    assert len(unresolved) == 1
    assert unresolved[0].token.slot == 1
    assert unresolved[0].token.attr == "nickname"


@pytest.mark.umbra
def test_tokens_R1_resolveTokens_no_character(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: resolveTokens flags tokens for slots without characters."""
    _mgr, project = _makeSheetManager(tmp_path)

    text = "{char99 fn} is missing."
    result, unresolved = resolveTokens(text, project)

    assert "{char99 fn}" in result  # not replaced
    assert len(unresolved) == 1
    assert unresolved[0].token.slot == 99


@pytest.mark.umbra
def test_tokens_R1_resolveTokens_mixed(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: resolveTokens resolves some tokens and flags others."""
    _mgr, project = _makeSheetManager(tmp_path)

    text = "{char1 fn} and {char99 fn} went out."
    result, unresolved = resolveTokens(text, project)

    assert "Ana" in result
    assert "{char99 fn}" in result
    assert len(unresolved) == 1
    assert unresolved[0].token.slot == 99


@pytest.mark.umbra
def test_tokens_A1_fn_resolved(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A1: {char1 fn} builds as the first name once slot 1 has fn."""
    _mgr, project = _makeSheetManager(tmp_path)

    text = "{char1 fn} nodded."
    result, unresolved = resolveTokens(text, project)
    assert result == "Ana nodded."
    assert unresolved == []


@pytest.mark.umbra
def test_tokens_A2_fn_change_updates_output(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A2: Changing fn changes output without document edits."""
    _mgr, project = _makeSheetManager(tmp_path)

    text = "{char1 fn} is here."
    result1, _ = resolveTokens(text, project)
    assert "Ana" in result1

    # Change fn in the document file (first document = slot 1)
    contentPath = project.storage.contentPath
    assert contentPath is not None
    doc_files = sorted(contentPath.glob("*.md"))
    assert len(doc_files) >= 1
    docFile = doc_files[0]  # First document = slot 1
    text_content = docFile.read_text(encoding="utf-8")
    text_content = text_content.replace("@attr: fn | Ana", "@attr: fn | Bella")
    docFile.write_text(text_content, encoding="utf-8", newline="\n")

    text2 = "{char1 fn} is here."
    result2, _ = resolveTokens(text2, project)
    assert "Bella" in result2
    assert "Ana" not in result2


@pytest.mark.umbra
def test_tokens_A3_escaped_brace_stays_literal(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    r"""A3: \\{char1 fn} is treated as a token (backslash is literal)."""
    _mgr, project = _makeSheetManager(tmp_path)
    text = "\\{char1 fn} is not a token."
    tokens = findTokens(text)
    assert len(tokens) == 1

    result, unresolved = resolveTokens(text, project)
    assert "{char1 fn}" not in result  # token was replaced
    assert "Ana" in result  # replaced with Ana
    assert unresolved == []


@pytest.mark.umbra
def test_tokens_R2_tokenizer_preprocess_hook(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Tokenizer preprocess hook replaces tokens before export."""
    _mgr, project = _makeSheetManager(tmp_path)

    contentPath = project.storage.contentPath
    assert contentPath is not None
    docFile = contentPath / "h000000000000e.md"
    docFile.write_text(
        "+++\ntag: h000000000000e\nkind: character\n"
        "@attr: slot | 1\n@attr: fn | Ana\n@attr: ln | Soler\n"
        "@alias: Ana\n+++\n\nScene text.\n",
        encoding="utf-8",
        newline="\n",
    )

    text = "Hello {char1 fn}!"
    result, _unresolved = resolveTokens(text, project)
    assert result == "Hello Ana!"


@pytest.mark.umbra
def test_tokens_R6_token_unresolved_gate_registered(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: The tokenUnresolved gate rule is registered."""
    gate = getGate("tokenUnresolved")
    assert gate is not None
    assert gate.ruleId == "tokenUnresolved"
    assert gate.defaultSeverity == "block"
    assert OP_BUILD_RUN in gate.operations
    assert OP_AUDIO_CHAPTER in gate.operations
    assert OP_PUBLISH_PACKAGE in gate.operations


@pytest.mark.umbra
def test_tokens_R7_renaming_updates_output(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R7: Renaming a character (changing fn) updates resolved output."""
    _mgr, project = _makeSheetManager(tmp_path)

    contentPath = project.storage.contentPath
    assert contentPath is not None
    # Find the first document (slot 1) and ensure it has Ana
    doc_files = sorted(contentPath.glob("*.md"))
    assert len(doc_files) >= 1
    docFile = doc_files[0]
    text_content = docFile.read_text(encoding="utf-8")
    text_content = text_content.replace("@attr: fn | Ana", "@attr: fn | Ana")  # ensure Ana
    docFile.write_text(text_content, encoding="utf-8", newline="\n")

    text = "{char1 fn} is the main character."
    result1, _ = resolveTokens(text, project)
    assert "Ana" in result1

    # Rename the character
    text_content = docFile.read_text(encoding="utf-8")
    text_content = text_content.replace("@attr: fn | Ana", "@attr: fn | Bella")
    docFile.write_text(text_content, encoding="utf-8", newline="\n")

    result2, _ = resolveTokens(text, project)
    assert "Bella" in result2
    assert "Ana" not in result2


@pytest.mark.umbra
def test_tokens_A4_placeholder_creation(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A4: Placeholder creation takes slot N and survives reopen."""
    _mgr, project = _makeSheetManager(tmp_path)

    # Find the third document file (create one if needed)
    contentPath = project.storage.contentPath
    assert contentPath is not None
    doc_files = sorted(contentPath.glob("*.md"))
    if len(doc_files) < 3:
        # Create a third document file for the placeholder
        docFile = contentPath / "h0000000000003.md"
    else:
        docFile = doc_files[2]  # Third document

    docFile.write_text(
        "+++\ntag: h0000000000003\nkind: character\n"
        "@attr: slot | 3\n@attr: fn | Placeholder\n@attr: ln | Three\n"
        "@alias: Placeholder 3\n+++\n\nPlaceholder text.\n",
        encoding="utf-8",
        newline="\n",
    )

    text = "{char3 fn} is a placeholder."
    result, unresolved = resolveTokens(text, project)
    assert "Placeholder" in result
    assert unresolved == []


@pytest.mark.umbra
def test_tokens_A5_dialogue_span_not_broken(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A5: Token in dialogue paragraph does not break dialogue spans."""
    # Use QUOTE_STRAIGHT (1) for straight quotes
    config = DialogueConfig(quoteStyle=1)
    text = 'Alice said "hello world" and {char1 fn} nodded.'
    spans = findDialogueSpans(text, config)
    dialogue_spans = [s for s in spans if s.kind == "dialogue"]
    assert len(dialogue_spans) >= 1
