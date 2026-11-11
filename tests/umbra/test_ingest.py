"""
Tests for UmbraEdit DOCX Ingest Engine (P27)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from umbraedit.umbra.ingest import (
    DocxIntake,
    DocxPrepass,
    DocxConvert,
    DocxClassify,
    DocxSplit,
    DocxSyntax,
    DocxPropose,
    DocxOutput,
    DocxIngestPipeline,
    IntakeResult,
    PrepassResult,
    ParagraphRecord,
    ConvertResult,
    ClassifyResult,
    SceneSplitResult,
    SyntaxResult,
    ProposeResult,
    ImportPlan,
)
from umbraedit.umbra.paths import cacheDir


class TestIntakeResult:
    """Tests for IntakeResult dataclass."""

    def test_intake_result_creation(self):
        result = IntakeResult(
            file_path=Path("/test.docx"),
            sha256="abc123",
            file_size=1024,
            pandoc_version="pandoc 3.1.11",
            valid=True,
        )
        assert result.valid
        assert result.sha256 == "abc123"

    def test_intake_result_invalid(self):
        result = IntakeResult(
            file_path=Path("/test.docx"),
            sha256="",
            file_size=0,
            pandoc_version="unknown",
            valid=False,
            error="File not found",
        )
        assert not result.valid
        assert result.error == "File not found"


class TestParagraphRecord:
    """Tests for ParagraphRecord dataclass."""

    def test_paragraph_record_creation(self):
        record = ParagraphRecord(
            index=0,
            text="Hello world",
            style_id="Heading1",
            style_name="Heading 1",
            alignment="center",
            outline_level=1,
            page_break_before=True,
            section_break="nextPage",
            list_membership="list:1",
            image_refs=["rId1"],
            run_formatting=[{"type": "bold", "value": True}],
            footnote_refs=["1"],
            comment_refs=["cmt1"],
            bookmark_starts=["bm1"],
            bookmark_ends=["bm1"],
        )
        assert record.index == 0
        assert record.text == "Hello world"
        assert record.style_id == "Heading1"
        assert record.outline_level == 1


class TestIntake:
    """Tests for DocxIntake."""

    def test_intake_valid_docx(self, tmp_path: Path):
        """Test intake with a valid DOCX file."""
        import zipfile

        # Create a minimal valid DOCX
        docx_path = tmp_path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?>')
            zf.writestr("word/document.xml", """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Test</w:t></w:r></w:p>
  </w:body>
</w:document>""")

        intake = DocxIntake()
        result = intake.process(docx_path)

        assert result.valid
        assert result.sha256
        assert result.file_size > 0
        assert result.pandoc_version

    def test_intake_invalid_not_zip(self, tmp_path: Path):
        """Test intake with invalid file."""
        docx_path = tmp_path / "test.docx"
        docx_path.write_text("not a zip file")

        intake = DocxIntake()
        result = intake.process(docx_path)

        assert not result.valid
        assert result.error

    def test_intake_missing_document_xml(self, tmp_path: Path):
        """Test intake with missing document.xml."""
        import zipfile

        docx_path = tmp_path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?>')
            # Missing word/document.xml

        intake = DocxIntake()
        result = intake.process(docx_path)

        assert not result.valid
        assert "word/document.xml" in result.error

    def test_intake_rejects_docm(self, tmp_path: Path):
        """Test intake rejects macro-enabled files."""
        import zipfile

        docx_path = tmp_path / "test.docm"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?>')
            zf.writestr("word/document.xml", """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body>
</w:document>""")
            zf.writestr("vbaProject.bin", "macro data")

        intake = DocxIntake()
        result = intake.process(docx_path)

        assert not result.valid
        assert "Macro-enabled" in result.error


class TestPrepass:
    """Tests for DocxPrepass."""

    def test_prepass_basic(self, tmp_path: Path):
        """Test pre-pass on a simple DOCX."""
        import zipfile

        docx_path = tmp_path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?>')
            zf.writestr("word/document.xml", """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Chapter 1</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Hello world.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>""")
            zf.writestr("word/styles.xml", """<?xml version="1.0"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="Heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Normal">
    <w:name w:val="Normal"/>
  </w:style>
</w:styles>""")
            zf.writestr("word/_rels/document.xml.rels", """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>""")
            zf.writestr("docProps/core.xml", """<?xml version="1.0"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">
  <dc:title>Test Book</dc:title>
  <dc:creator>Author Name</dc:creator>
</cp:coreProperties>""")

        intake = DocxIntake()
        intake_result = DocxIntake().process(Path(docx_path))

        prepass = DocxPrepass()
        result = prepass.process(intake_result)

        assert isinstance(result, PrepassResult)
        assert len(result.paragraphs) == 2
        assert result.paragraphs[0].style_id == "Heading1"
        assert result.paragraphs[0].outline_level == 0
        assert "Chapter 1" in result.paragraphs[0].text
        assert "Hello world" in result.paragraphs[1].text

    def test_prepass_styles(self, tmp_path: Path):
        """Test pre-pass extracts styles correctly."""
        import zipfile

        docx_path = tmp_path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?>')
            zf.writestr("word/document.xml", """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="CustomStyle"/></w:pPr><w:r><w:t>Test</w:t></w:r></w:p>
  </w:body>
</w:document>""")
            zf.writestr("word/styles.xml", """<?xml version="1.0"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="CustomStyle">
    <w:name w:val="My Custom Style"/>
    <w:basedOn w:val="Normal"/>
    <w:next w:val="CustomStyle"/>
    <w:uiPriority w:val="1"/>
    <w:hidden w:val="true"/>
    <w:locked w:val="true"/>
    <w:pPr><w:jc w:val="center"/><w:outlineLvl w:val="2"/></w:pPr>
    <w:rPr><w:b/><w:i/><w:sz w:val="28"/></w:rPr>
  </w:style>
</w:styles>""")
            zf.writestr("word/_rels/document.xml.rels", """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>""")
            zf.writestr("docProps/core.xml", "<cp:coreProperties/>")

        intake = DocxIntake().process(tmp_path / "test.docx")
        result = DocxPrepass().process(intake)

        style = result.styles.get("CustomStyle")
        assert style is not None
        assert style["name"] == "My Custom Style"
        assert style["based_on"] == "Normal"
        assert style["next"] == "CustomStyle"
        assert style["ui_priority"] == "1"
        assert style["hidden"] is True
        assert style["locked"] is True
        assert style["pPr"]["alignment"] == "center"
        assert style["pPr"]["outline_level"] == 2
        assert style["rPr"]["bold"] is True
        assert style["rPr"]["italic"] is True
        assert style["rPr"]["font_size"] == "28"


class TestClassify:
    """Tests for DocxClassify."""

    def test_classify_chapter_heading(self, tmp_path: Path):
        """Test chapter heading classification."""
        import zipfile

        docx_path = tmp_path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?>')
            zf.writestr("word/document.xml", """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Chapter 1</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>Content here.</w:t></w:r></w:p>
  </w:body>
</w:document>""")
            zf.writestr("word/styles.xml", """<?xml version="1.0"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="Heading 1"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
</w:styles>""")
            zf.writestr("word/_rels/document.xml.rels", """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>""")
            zf.writestr("docProps/core.xml", "<cp:coreProperties/>")

        intake = DocxIntake().process(tmp_path / "test.docx")
        prepass = DocxPrepass().process(intake)
        classify = DocxClassify().process(prepass, None)

        chapter_blocks = [b for b in classify.blocks if b.kind.name == "CHAPTER"]
        assert len(chapter_blocks) == 1
        assert chapter_blocks[0].title == "Chapter 1"
        assert chapter_blocks[0].level == 1


class TestSplit:
    """Tests for DocxSplit."""

    def test_split_chapters_and_scenes(self):
        """Test splitting chapters into scenes."""
        from umbraedit.umbra.ingest.docx_classify import BlockKind, ClassifyResult, DocumentBlock

        blocks = [
            DocumentBlock(kind=BlockKind.CHAPTER, level=1, title="Chapter 1", text="Chapter 1", source_paragraphs=[0]),
            DocumentBlock(kind=BlockKind.BODY, level=0, title="", text="Scene 1 content", source_paragraphs=[1]),
            DocumentBlock(kind=BlockKind.SCENE, level=0, title="Scene 1", text="***", source_paragraphs=[2]),
            DocumentBlock(kind=BlockKind.BODY, level=0, title="", text="Scene 2 content", source_paragraphs=[3]),
            DocumentBlock(kind=BlockKind.CHAPTER, level=1, title="Chapter 2", text="Chapter 2", source_paragraphs=[4]),
            DocumentBlock(kind=BlockKind.BODY, level=0, title="", text="Chapter 2 scene", source_paragraphs=[5]),
        ]

        classify_result = ClassifyResult(blocks=blocks)
        split_result = DocxSplit().process(classify_result)

        assert split_result.chapter_count == 2
        assert split_result.scene_count == 1  # Only explicit SCENE blocks counted (body merged into scene)
        assert len(split_result.documents) == 3  # 2 chapters + 1 scene (body content merged)


class TestSyntax:
    """Tests for DocxSyntax."""

    def test_smart_quote_conversion(self):
        """Test smart quote normalization."""
        from umbraedit.umbra.ingest.docx_syntax import _normalize_smart_quotes

        text = "He said \u201cHello\u201d and \u2018Hi\u2019."
        result = _normalize_smart_quotes(text)
        assert '"' in result
        assert "'" in result
        assert "\u201c" not in result
        assert "\u201d" not in result

    def test_special_chars(self):
        """Test non-breaking space and soft hyphen handling."""
        from umbraedit.umbra.ingest.docx_syntax import _handle_special_chars

        text = "Word\u00a0break\u00adsoft"
        result = _handle_special_chars(text)
        assert "\u00a0" not in result
        assert "\u00ad" not in result
        assert " " in result


class TestPropose:
    """Tests for DocxPropose."""

    def test_propose_characters(self):
        """Test character name proposal."""
        from umbraedit.umbra.ingest.docx_propose import DocxPropose

        text = "John said \"Hello\". Mary replied \"Hi\". John smiled. Mary laughed. John nodded. Mary waved. John left. Mary stayed. John returned."
        # John appears 5 times, Mary appears 4 times
        # Both should be proposed if they appear near quotes

        propose = DocxPropose()
        # We can't easily test the full process without full pipeline
        # But we can test the helper
        from umbraedit.umbra.ingest.docx_propose import _extract_potential_names, _is_likely_name

        words = _extract_potential_names(text)
        names = [w for w in words if _is_likely_name(w, text)]
        counts = {}
        for name in names:
            counts[name] = counts.get(name, 0) + 1

        # Both John and Mary should appear multiple times
        assert "John" in counts
        assert "Mary" in counts


class TestOutput:
    """Tests for DocxOutput."""

    def test_write_and_load_plan(self, tmp_path: Path):
        """Test writing and loading an import plan."""
        import tempfile

        # Create a temp project
        project_path = tmp_path / "project"
        project_path.mkdir()
        (project_path / "umbra").mkdir()

        output = DocxOutput(project_path)

        # Create a minimal plan
        from umbraedit.umbra.ingest.docx_intake import IntakeResult
        from umbraedit.umbra.ingest.docx_split import SceneSplitResult
        from umbraedit.umbra.ingest.docx_syntax import SyntaxResult
        from umbraedit.umbra.ingest.docx_propose import ProposeResult

        intake = IntakeResult(
            file_path=Path("test.docx"),
            sha256="abc123",
            file_size=1024,
            pandoc_version="pandoc 3.1.11",
            valid=True,
        )

        split = SceneSplitResult(documents=[{"planId": "ch1", "kind": "chapter", "title": "Chapter 1", "text": "Content"}])
        syntax = SyntaxResult(documents=[{"planId": "ch1", "kind": "chapter", "title": "Chapter 1", "text": "Converted content"}])
        propose = ProposeResult(characters=[], metadata={}, page_types={})

        plan_file = DocxOutput(project_path).write(
            IntakeResult(file_path=Path("test.docx"), sha256="abc", file_size=100, pandoc_version="3.1", valid=True),
            SceneSplitResult(documents=[{"planId": "ch1", "kind": "chapter", "title": "Ch1", "text": "Content"}]),
            SyntaxResult(documents=[{"planId": "ch1", "kind": "chapter", "title": "Ch1", "text": "Content"}]),
            ProposeResult(characters=[], metadata={}, page_types={})
        )

        assert plan_file.exists()
        assert plan_file.suffix == ".json"

        # Load it back
        plan = DocxOutput(project_path).load(plan_file.stem)
        assert plan is not None
        assert plan.run_id
        assert plan.source["sha256"] == "abc"


class TestPipeline:
    """Tests for DocxIngestPipeline."""

    def test_pipeline_creation(self, tmp_path: Path):
        """Test pipeline can be created."""
        pipeline = DocxIngestPipeline(tmp_path)
        assert pipeline is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])