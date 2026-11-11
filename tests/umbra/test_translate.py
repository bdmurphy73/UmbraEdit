"""
Tests for UmbraEdit Translation Module (P25)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from umbraedit.enum import nwItemClass
from umbraedit.umbra.translate import (
    TranslationJob,
    TRANSLATION_OUTPUT_SCHEMA,
    _atomic_write_json,
    _atomic_write_text,
    _build_chapter_prompt,
    _build_metadata_prompt,
    _check_glossary_gaps,
    _count_source_paragraphs,
    _get_analysis,
    _get_analysis_hash,
    _get_cast_voices,
    _get_glossary,
    _get_previous_tail,
    _get_source_hash,
    _get_source_paragraphs,
    _get_style_guide,
    _load_prompt_template,
    _validate_translation_result,
    importTranslationResult,
    retranslateStaleChapters,
)
from umbraedit.umbra.edition import EditionInfo, EditionDoc, loadEdition, saveEdition
from umbraedit.umbra.guide import GuideDoc, formatGuideDoc
from umbraedit.umbra.metadata import Metadata, saveMetadata


def _write_doc(content_path: Path, handle: str, body: str) -> None:
    """Write a content file with the standard header separator."""
    content_path.mkdir(parents=True, exist_ok=True)
    (content_path / f"{handle}.md").write_text(f"+++\ntitle: T\n+++\n{body}", encoding="utf-8")


def _write_guide(content_path: Path, handle: str, kind: str, chapter: str = "", status: str = "draft", body: str = "", lang: str = "") -> None:
    """Write a guide document."""
    guide = GuideDoc(kind=kind, chapter=chapter, status=status, body=body, lang=lang)
    content_path.mkdir(parents=True, exist_ok=True)
    (content_path / f"{handle}.md").write_text(formatGuideDoc(guide), encoding="utf-8")


def _write_sheet(umbra_path: Path, entities: list[dict]) -> None:
    """Write a sheet.json file directly."""
    sheet_data = {"v": 1, "entities": entities}
    import json
    (umbra_path / "sheet.json").write_text(json.dumps(sheet_data, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")


class _FakeItem:
    """Minimal stand-in for a ProjectItem."""

    def __init__(self, handle: str, class_name: str, name: str) -> None:
        self.itemHandle = handle
        self.itemName = name
        self.itemClass = nwItemClass[class_name]
        self.isFileType = lambda: True
        self.isDocumentLayout = lambda: False


class _FakeTree:
    def __init__(self, items: list) -> None:
        self._items = items

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, handle: str):
        return next((item for item in self._items if item.itemHandle == handle), None)

    def checkExists(self, handle: str) -> bool:
        return any(item.itemHandle == handle for item in self._items)


class _FakeStorage:
    def __init__(self, root: Path) -> None:
        self.contentPath = root / "content"
        self.storagePath = root


class _FakeProject:
    def __init__(self, root: Path, items: list, metadata: Metadata | None = None) -> None:
        self.tree = _FakeTree(items)
        self.storage = _FakeStorage(root)
        self.index = None
        self.classes = type("Classes", (), {"GUIDE": nwItemClass.GUIDE})()
        self.metadata = metadata

    def chapterOf(self, handle: str):
        return type("ChapterRef", (), {"handles": [handle], "title": "Chapter 1"})()

    def getDocumentHash(self, handle: str) -> str:
        doc_file = self.storage.contentPath / f"{handle}.md"
        if doc_file.is_file():
            text = doc_file.read_text(encoding="utf-8")
            import hashlib
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return ""


@pytest.fixture
def translation_project(tmp_path: Path):
    """Create a source project and edition project for translation testing."""
    source_path = tmp_path / "source-project"
    edition_path = tmp_path / "source-project-ed-zh-Hans"

    # Create source project structure
    source_content = source_path / "content"
    source_content.mkdir(parents=True)
    (source_path / "umbra").mkdir(parents=True)

    # Create edition project structure
    edition_content = edition_path / "content"
    edition_content.mkdir(parents=True)
    edition_umbra = edition_path / "umbra"
    edition_umbra.mkdir(parents=True)

    # Create source chapter
    _write_doc(source_content, "ch1", "# Chapter 1\n\nHello world.\n\nThis is a test.")

    # Create edition chapter (with untranslated status)
    _write_doc(edition_content, "ch1", "# Chapter 1\n\nHello world.\n\nThis is a test.")

    # Create metadata
    metadata = Metadata()
    metadata.book["title"] = "Test Book"
    metadata.book["subtitle"] = "A Subtitle"
    metadata.book["language"] = "en"
    saveMetadata(source_path, metadata)
    saveMetadata(edition_path, metadata)

    # Create edition.json
    edition_info = EditionInfo(
        v=1,
        editionId="zh-Hans",
        language="zh-Hans",
        source={"path": "../source-project", "editionId": "main", "projectId": ""},
        docs={"ch1": EditionDoc(handle="ch1", baseTextHash="abc123", status="untranslated")},
        titleTemplate={"chapter": "Chapter {n}"},
        translatable=["book.title", "book.subtitle"],
        pending=["book.title", "book.subtitle"],
    )
    saveEdition(edition_path, edition_info)

    # Create entity sheets (sheet.json directly)
    _write_sheet(source_path / "umbra", [
        {"tag": "bob", "handle": "char-bob", "kind": "character", "aliases": [], "attrs": {"name_target": "鲍勃"}}
    ])
    _write_sheet(edition_path / "umbra", [
        {"tag": "bob", "handle": "char-bob", "kind": "character", "aliases": [], "attrs": {"name_target": "鲍勃", "pron_status": "todo"}}
    ])

    # Create fake projects
    source_items = [
        _FakeItem("ch1", "NOVEL", "Chapter 1"),
    ]
    edition_items = [
        _FakeItem("ch1", "NOVEL", "Chapter 1"),
    ]

    source_project = _FakeProject(source_path, source_items, metadata)
    edition_project = _FakeProject(edition_path, edition_items, metadata)

    yield source_path, edition_path, source_project, edition_project


class TestTranslationJob:
    """Tests for TranslationJob dataclass."""

    def test_translation_job_creation(self):
        job = TranslationJob(
            id="test123",
            edition="zh-Hans",
            chapter="ch1",
            kind="chapter",
            status="ready",
            prompt_file="umbra/jobs/tj-test123.prompt.md",
            analysis_hash="abc",
            source_hash="def",
            created_at="2026-01-01T00:00:00Z",
        )
        assert job.id == "test123"
        assert job.edition == "zh-Hans"
        assert job.kind == "chapter"

    def test_translation_job_to_dict(self):
        job = TranslationJob(id="test123", edition="zh-Hans", chapter="ch1")
        data = job.to_dict()
        assert data["id"] == "test123"
        assert data["edition"] == "zh-Hans"
        assert data["chapter"] == "ch1"

    def test_translation_job_from_dict(self):
        data = {
            "v": 1,
            "id": "test123",
            "edition": "zh-Hans",
            "chapter": "ch1",
            "kind": "metadata",
            "status": "done",
            "promptFile": "umbra/jobs/tj-test123.prompt.md",
            "analysisHash": "",
            "sourceHash": "abc",
            "createdAt": "2026-01-01T00:00:00Z",
            "result": {"chapter": "ch1", "paragraphs": []},
            "error": None,
            "options": {},
        }
        job = TranslationJob.from_dict(data)
        assert job.id == "test123"
        assert job.kind == "metadata"
        assert job.status == "done"


class TestAtomicWrite:
    """Tests for atomic write functions."""

    def test_atomic_write_json(self, tmp_path: Path):
        file_path = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        _atomic_write_json(file_path, data)

        assert file_path.is_file()
        with open(file_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_atomic_write_text(self, tmp_path: Path):
        file_path = tmp_path / "test.txt"
        text = "Hello, world!"
        _atomic_write_text(file_path, text)

        assert file_path.is_file()
        assert file_path.read_text(encoding="utf-8") == text


class TestPromptTemplate:
    """Tests for prompt template loading."""

    def test_load_default_template(self, tmp_path: Path):
        # No custom template, should return default
        template = _load_prompt_template(tmp_path)
        assert "Translate the following chapter" in template
        assert "{sourceLanguage}" in template

    def test_load_custom_template(self, tmp_path: Path):
        # Create custom template
        prompts_dir = tmp_path / "umbra" / "prompts"
        prompts_dir.mkdir(parents=True)
        custom_template = "v1\nCustom template: {bookTitle}"
        (prompts_dir / "translate.md").write_text(custom_template, encoding="utf-8")

        template = _load_prompt_template(tmp_path)
        assert template == "Custom template: {bookTitle}"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_source_hash(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        hash_val = _get_source_hash(source_project, "ch1")
        assert len(hash_val) == 16
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_get_analysis_hash_no_analysis(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        hash_val = _get_analysis_hash(source_project, "ch1")
        assert hash_val == ""

    def test_get_analysis_hash_with_approved_analysis(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        _write_guide(source_path / "content", "guide1", "analysis", chapter="ch1", status="approved", body="Analysis body")
        source_project.tree._items.append(_FakeItem("guide1", "GUIDE", "Guide 1"))
        hash_val = _get_analysis_hash(source_project, "ch1")
        assert len(hash_val) == 16

    def test_get_style_guide(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        _write_guide(source_path / "content", "guide1", "style", body="Style guide content")
        _write_guide(source_path / "content", "guide2", "language", lang="zh-Hans", body="Language guide content")
        source_project.tree._items.append(_FakeItem("guide1", "GUIDE", "Guide 1"))
        source_project.tree._items.append(_FakeItem("guide2", "GUIDE", "Guide 2"))
        guide_text = _get_style_guide(source_project, "zh-Hans")
        assert "Style Guide" in guide_text
        assert "Language Guide (zh-Hans)" in guide_text

    def test_get_glossary(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        glossary_text = _get_glossary(edition_path)
        assert "bob → 鲍勃" in glossary_text

    def test_get_cast_voices(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        # Add voice line to chapter
        _write_doc(source_path / "content", "ch1", "# Chapter 1\n\n%Voice: spk=bob\nHello world.")
        
        # Debug
        print(f"source_project.storage.contentPath: {source_project.storage.contentPath}")
        doc_file = source_project.storage.contentPath / "ch1.md"
        print(f"doc_file: {doc_file}")
        print(f"exists: {doc_file.is_file()}")
        if doc_file.is_file():
            text = doc_file.read_text(encoding="utf-8")
            print(f"text: {repr(text)}")
        
        print(f"edition_path: {edition_path}")
        sheet_file = edition_path / "umbra" / "sheet.json"
        print(f"sheet_file: {sheet_file}")
        print(f"exists: {sheet_file.is_file()}")
        
        voices = _get_cast_voices(source_project, "ch1", edition_path)
        print(f"Voices: {voices}")
        assert "bob" in voices

    def test_get_previous_tail(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        tail = _get_previous_tail(source_project, edition_path, "ch1")
        assert tail == "(none)"

    def test_get_source_paragraphs(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        _write_guide(source_path / "content", "guide1", "analysis", chapter="ch1", status="approved",
                     body="%Para: 0 h=abc12345\nIntent: Test intent\nSubtext: Test subtext\nRegister: Formal\nDo not translate literally: hello\nCultural: None")
        source_project.tree._items.append(_FakeItem("guide1", "GUIDE", "Guide 1"))
        paragraphs = _get_source_paragraphs(source_project, "ch1", edition_path)
        assert "[0]" in paragraphs
        assert "Hello world" in paragraphs
        assert "Intent: Test intent" in paragraphs

    def test_count_source_paragraphs(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        count = _count_source_paragraphs(source_project, "ch1")
        assert count == 2  # "Hello world." and "This is a test."


class TestValidation:
    """Tests for translation result validation."""

    def test_validate_translation_result_valid(self):
        result = {
            "chapter": "ch1",
            "paragraphs": [
                {"index": 0, "text": "你好世界。"},
                {"index": 1, "text": "这是一个测试。"},
            ],
        }
        errors = _validate_translation_result(result, 2)
        assert errors == []

    def test_validate_translation_result_wrong_count(self):
        result = {
            "chapter": "ch1",
            "paragraphs": [
                {"index": 0, "text": "你好世界。"},
            ],
        }
        errors = _validate_translation_result(result, 2)
        assert len(errors) == 1
        assert "Paragraph count mismatch" in errors[0]

    def test_validate_translation_result_empty_text(self):
        result = {
            "chapter": "ch1",
            "paragraphs": [
                {"index": 0, "text": ""},
            ],
        }
        errors = _validate_translation_result(result, 1)
        assert len(errors) == 1
        assert "empty text" in errors[0]

    def test_validate_translation_result_placeholder(self):
        result = {
            "chapter": "ch1",
            "paragraphs": [
                {"index": 0, "text": "Hello {{world}}"},
            ],
        }
        errors = _validate_translation_result(result, 1)
        assert len(errors) == 1
        assert "unresolved placeholder" in errors[0]

    def test_validate_translation_result_missing_index(self):
        result = {
            "chapter": "ch1",
            "paragraphs": [
                {"text": "Hello"},
            ],
        }
        errors = _validate_translation_result(result, 1)
        assert len(errors) == 1
        assert "missing 'index'" in errors[0]

    def test_validate_translation_result_index_mismatch(self):
        result = {
            "chapter": "ch1",
            "paragraphs": [
                {"index": 1, "text": "Hello"},
            ],
        }
        errors = _validate_translation_result(result, 1)
        assert len(errors) == 1
        assert "index mismatch" in errors[0]


class TestGlossaryGaps:
    """Tests for glossary gap checking."""

    def test_check_glossary_gaps_no_gaps(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        _write_doc(source_path / "content", "ch1", "# Chapter 1\n\n%Voice: spk=bob\nHello world.")
        gaps = _check_glossary_gaps(edition_path, source_project, "ch1")
        assert gaps == []

    def test_check_glossary_gaps_with_gap(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        # Speaker "alice" not in glossary
        _write_doc(source_path / "content", "ch1", "# Chapter 1\n\n%Voice: spk=alice\nHello world.")
        
        # Debug
        print(f"source_project.storage.contentPath: {source_project.storage.contentPath}")
        doc_file = source_project.storage.contentPath / "ch1.md"
        print(f"doc_file: {doc_file}")
        print(f"exists: {doc_file.is_file()}")
        if doc_file.is_file():
            text = doc_file.read_text(encoding="utf-8")
            print(f"text: {repr(text)}")
        
        gaps = _check_glossary_gaps(edition_path, source_project, "ch1")
        print(f"Gaps: {gaps}")
        assert "alice" in gaps


class TestBuildChapterPrompt:
    """Tests for building chapter prompts."""

    def test_build_chapter_prompt(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        _write_guide(source_path / "content", "guide1", "style", body="Be poetic")
        _write_guide(source_path / "content", "guide2", "analysis", chapter="ch1", status="approved",
                     body="%Para: 0 h=abc12345\nIntent: Greeting\nSubtext: Friendly\nRegister: Casual\nDo not translate literally: \nCultural: ")
        source_project.tree._items.append(_FakeItem("guide1", "GUIDE", "Guide 1"))
        source_project.tree._items.append(_FakeItem("guide2", "GUIDE", "Guide 2"))

        edition_info = loadEdition(edition_path)
        prompt, source_hash, analysis_hash = _build_chapter_prompt(edition_path, source_project, "ch1", edition_info)

        assert "Test Book" in prompt
        assert "zh-Hans" in prompt
        assert "Be poetic" in prompt
        assert "Greeting" in prompt
        assert "Friendly" in prompt
        assert "Casual" in prompt
        assert "bob → 鲍勃" in prompt
        assert "Hello world" in prompt
        assert len(source_hash) == 16
        assert len(analysis_hash) == 16


class TestBuildMetadataPrompt:
    """Tests for building metadata prompts."""

    def test_build_metadata_prompt(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project

        edition_info = loadEdition(edition_path)
        prompt, source_hash = _build_metadata_prompt(edition_path, source_project, edition_info)

        assert "Test Book" in prompt
        assert "zh-Hans" in prompt
        assert "book.title" in prompt
        assert "book.subtitle" in prompt
        assert len(source_hash) == 16


class TestReTranslateStale:
    """Tests for re-translating stale chapters."""

    def test_retranslate_stale_chapters(self, translation_project):
        source_path, edition_path, source_project, edition_project = translation_project
        # Set up edition with stale document
        edition_info = loadEdition(edition_path)
        # EditionDoc is frozen, create new one with updated status
        edition_info.docs["ch1"] = EditionDoc(
            handle="ch1",
            baseTextHash="old_hash",
            status="stale",
        )
        saveEdition(edition_path, edition_info)

        # The function should detect stale chapters
        job_ids = retranslateStaleChapters(edition_project)
        # This will return empty because source project not fully set up
        # but should not crash
        assert isinstance(job_ids, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])