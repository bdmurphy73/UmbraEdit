"""
UmbraEdit - DOCX Ingest Pipeline
=================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

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
"""  # noqa

from __future__ import annotations

import logging

from dataclasses import dataclass
from pathlib import Path

from umbraedit.umbra.ingest.docx_classify import ClassifyResult, DocxClassify
from umbraedit.umbra.ingest.docx_convert import ConvertResult, DocxConvert
from umbraedit.umbra.ingest.docx_intake import DocxIntake, IntakeResult
from umbraedit.umbra.ingest.docx_output import DocxOutput, ImportPlan
from umbraedit.umbra.ingest.docx_prepass import DocxPrepass, PrepassResult
from umbraedit.umbra.ingest.docx_propose import DocxPropose, ProposeResult
from umbraedit.umbra.ingest.docx_split import DocxSplit, SceneSplitResult
from umbraedit.umbra.ingest.docx_syntax import DocxSyntax, SyntaxResult

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Complete result of the ingest pipeline."""

    intake: IntakeResult
    prepass: PrepassResult
    convert: ConvertResult
    classify: ClassifyResult
    split: SceneSplitResult
    syntax: SyntaxResult
    propose: ProposeResult
    plan: ImportPlan
    plan_file: Path


class DocxIngestPipeline:
    """Main pipeline for DOCX ingest."""

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path
        self._intake = DocxIntake()
        self._prepass = DocxPrepass()
        self._convert = DocxConvert()
        self._classify = DocxClassify()
        self._split = DocxSplit()
        self._syntax = DocxSyntax()
        self._propose = DocxPropose()
        self._output = DocxOutput(project_path)

    def process(
        self,
        file_path: Path,
        output_dir: Path | None = None,
    ) -> IngestResult:
        """Run the full ingest pipeline on a DOCX file."""
        logger.info("Starting ingest pipeline for %s", file_path)

        # Stage 1: Intake
        intake = self._intake.process(file_path)
        if not intake.valid:
            raise ValueError(f"Intake failed: {intake.error}")

        # Stage 2: Pre-pass
        prepass = self._prepass.process(intake)

        # Stage 3: Convert (Pandoc)
        convert = self._convert.process(intake, prepass, output_dir)

        # Stage 4: Classify
        classify = self._classify.process(prepass, convert)

        # Stage 5: Split scenes
        split = self._split.process(classify)

        # Stage 6: Syntax conversion
        syntax = self._syntax.process(
            split,
            prepass.paragraphs,
            prepass.footnotes,
            prepass.comments,
            [{"rid": img["rid"], "filename": img["filename"], "alt": img["filename"]}
             for img in prepass.images],
        )

        # Stage 7: Propose
        propose = self._propose.process(
            split,
            syntax,
            prepass.doc_props,
        )

        # Stage 8: Output
        plan_file = self._output.write(intake, split, syntax, propose)
        plan = self._output.load(plan_file.stem)

        if plan is None:
            raise RuntimeError("Failed to load generated import plan")

        logger.info("Ingest pipeline completed successfully")
        return IngestResult(
            intake=intake,
            prepass=prepass,
            convert=convert,
            classify=classify,
            split=split,
            syntax=syntax,
            propose=propose,
            plan=plan,
            plan_file=plan_file,
        )
