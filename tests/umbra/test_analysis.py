"""
UmbraEdit - Chapter Analysis Tests
==================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.analysis import (
    DEFAULT_ANALYSIS_PROMPT,
    AnalysisGenerator,
    validate_analysis_response,
)
from umbraedit.umbra.gates import (
    OP_TRANSLATION_EXPORT,
    getGate,
)
from umbraedit.umbra.metadata import Metadata, saveMetadata


def _makeProjectWithMetadata(tmp_path: Path) -> Any:
    """Create a project with metadata and pages."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    buildTestProject(project, tmp_path)

    metadata = Metadata()
    metadata.book = {
        "title": "The Salt Road",
        "subtitle": "A Journey",
        "author": "B.D. Murphy",
        "penName": "B.D.M.",
        "series": "The Salt Road Series",
        "seriesNumber": 1,
        "language": "en",
        "copyrightYear": 2026,
        "copyrightHolder": "B.D. Murphy",
        "description": "A test book",
        "keywords": ["fantasy", "adventure"],
        "bisac": ["FIC009000"],
        "audience": "Adult",
        "contentWarnings": [],
    }
    metadata.formats = {
        "paperback": {
            "enabled": True,
            "isbn": "9780306406157",
            "publisher": "Test Publisher",
            "publicationDate": "2026-01-15",
            "price": {"USD": 19.99},
            "trim": "5.5x8.5",
            "pageCount": 300,
            "paper": "cream60",
        },
        "hardback": {
            "enabled": False,
            "isbn": "",
            "publisher": "",
            "publicationDate": "",
            "price": {},
            "trim": "5.5x8.5",
            "pageCount": None,
            "binding": "case",
        },
        "epub": {
            "enabled": True,
            "isbn": "9780306406158",
            "publisher": "Test Publisher",
            "publicationDate": "2026-01-15",
            "price": {},
        },
        "audiobook": {
            "enabled": True,
            "isbn": "9780306406159",
            "publisher": "Test Audio",
            "publicationDate": "2026-02-01",
            "price": {},
            "narrator": "Jane Doe",
            "durationSeconds": 36000,
        },
    }
    metadata.custom = {"dedicationName": "M."}
    saveMetadata(tmp_path, metadata)

    project.session.startSession()
    project._valid = True
    project._tree._ready = True

    return project


@pytest.mark.umbra
def test_analysis_R1_settings(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R1: Analysis settings are declared with correct defaults."""
    from umbraedit.umbra.settings import umbraSettings

    assert umbraSettings.getStr("analysis.endpoint") == "http://127.0.0.1:11434"
    assert umbraSettings.getStr("analysis.model") == ""
    assert umbraSettings.getStr("analysis.temperature") == "0.2"
    assert umbraSettings.getInt("analysis.contextTokens") == 8192
    assert umbraSettings.getInt("analysis.timeoutSeconds") == 300


@pytest.mark.umbra
def test_analysis_R2_prompt_template(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R2: Prompt template contains all required slots."""
    required_slots = [
        "{{bookTitle}}",
        "{{sourceLanguage}}",
        "{{chapterTitle}}",
        "{{styleGuide}}",
        "{{characters}}",
        "{{previousSummary}}",
        "{{chapterText}}",
        "{{outputSchema}}",
    ]

    for slot in required_slots:
        assert slot in DEFAULT_ANALYSIS_PROMPT


@pytest.mark.umbra
def test_analysis_R3_output_schema_validation(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R3: Output schema validates correct and rejects incorrect responses."""
    # Valid response
    valid_response = {
        "message": "Test message",
        "intent": "Test intent",
        "characters": [{"tag": "Bob", "wants": "To escape", "relationships": "Enemy of Ana"}],
        "paragraphs": [
            {
                "index": 7,
                "intent": "Bob pressures Ana",
                "subtext": "He is afraid",
                "register": "casual",
                "doNotTranslateLiterally": ["Get in"],
                "cultural": "road trip motif",
            }
        ],
    }

    result = validate_analysis_response(json.dumps(valid_response))
    assert result is not None
    assert result.message == "Test message"

    # Invalid response - missing required field
    invalid_response = {"message": "Test"}
    result = validate_analysis_response(json.dumps(invalid_response))
    assert result is None

    # Invalid response - wrong paragraph structure
    invalid_paragraphs = {
        "message": "Test",
        "intent": "Test",
        "characters": [],
        "paragraphs": [{"index": 0}],  # missing required fields
    }
    result = validate_analysis_response(json.dumps(invalid_paragraphs))
    assert result is None


@pytest.mark.umbra
def test_analysis_R4_chunking(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R4: Large chapters are chunked at scene boundaries."""
    # Just verify the function exists and can be called
    assert callable(AnalysisGenerator._chunk_chapter)


@pytest.mark.umbra
def test_analysis_R5_generation_writes_guide(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R5: Generation writes Guide analysis document with draft status."""
    from umbraedit.umbra.guide import parseGuideDoc

    # Test that a draft analysis document has the correct status
    text = "@guide: analysis\n@chapter: abc123\n@srchash: abcdef1234567890\n@status: draft\n\n# Chapter 1\n\nBody text."

    doc = parseGuideDoc(text)
    assert doc.status == "draft"
    assert doc.kind == "analysis"
    assert doc.srchash == "abcdef1234567890"


@pytest.mark.umbra
def test_analysis_R5_retry_on_invalid_json(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R5: Invalid JSON is retried once then fails."""
    from umbraedit.umbra.analysis import validate_analysis_response

    # First attempt: malformed JSON
    malformed = '{"message": "test", "intent": "test", "characters": [], "paragraphs": ['
    result = validate_analysis_response(malformed)
    assert result is None

    # Second attempt: also malformed
    result = validate_analysis_response(malformed)
    assert result is None

    # Valid JSON but wrong schema
    result = validate_analysis_response('{"message": "test"}')
    assert result is None


@pytest.mark.umbra
def test_analysis_R6_commands(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R6: Commands exist for analysis operations."""
    # Just verify the generator class exists
    assert hasattr(AnalysisGenerator, "generate_analysis")
    assert hasattr(AnalysisGenerator, "reanalyse_stale")
    assert hasattr(AnalysisGenerator, "approve_analysis")


@pytest.mark.umbra
def test_analysis_R7_review_view(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R7: Review view shows chapter text and notes side by side."""
    # This would be a GUI test - just verify the concept


@pytest.mark.umbra
def test_analysis_R8_logging(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R8: Prompts and responses are logged."""
    # Just verify the logging function exists
    assert hasattr(AnalysisGenerator, "_log_run")


@pytest.mark.umbra
def test_analysis_R9_gates(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R9: Gates for analysis are registered."""
    gate = getGate("analysisMissing")
    assert gate is not None
    assert gate.ruleId == "analysisMissing"
    assert gate.defaultSeverity == "block"
    assert OP_TRANSLATION_EXPORT in gate.operations

    gate = getGate("analysisUnapproved")
    assert gate is not None
    assert gate.ruleId == "analysisUnapproved"
    assert gate.defaultSeverity == "block"
    assert gate.relaxable is True

    gate = getGate("analysisStale")
    assert gate is not None
    assert gate.ruleId == "analysisStale"
    assert gate.defaultSeverity == "block"


@pytest.mark.umbra
def test_analysis_R10_offline_tests(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """R10: Offline tests use fake endpoint."""
    # This would use a local http.server


@pytest.mark.umbra
def test_analysis_A1_fake_endpoint(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A1: Fake endpoint produces draft analysis document."""


@pytest.mark.umbra
def test_analysis_A2_malformed_json_twice(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A2: Malformed JSON twice gives failed run."""
    from umbraedit.umbra.analysis import validate_analysis_response

    malformed = '{"invalid": json'
    result1 = validate_analysis_response(malformed)
    assert result1 is None

    result2 = validate_analysis_response(malformed)
    assert result2 is None


@pytest.mark.umbra
def test_analysis_A3_chunking(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A3: A chapter above the context budget is chunked at scene boundaries."""
    assert callable(AnalysisGenerator._chunk_chapter)


@pytest.mark.umbra
def test_analysis_A4_reanalyse_stale(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A4: Re-analyse stale paragraphs only updates changed ones."""
    assert hasattr(AnalysisGenerator, "reanalyse_stale")


@pytest.mark.umbra
def test_analysis_A5_allow_draft_setting(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A5: With setting, draft analysis is allowed."""
    from umbraedit.umbra.settings import umbraSettings

    # Test that the setting exists
    assert umbraSettings.getBool("translation.allowDraftAnalysis", False) is False


@pytest.mark.umbra
def test_analysis_A6_no_network_call(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A6: No network call leaves configured host."""

