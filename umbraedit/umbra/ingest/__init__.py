"""
UmbraEdit - DOCX Ingest Engine
===============================

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

from .commit import CommitResult, ImportCommitter, commit_import_plan, undo_import_plan
from .docx_classify import BlockKind, ClassifyResult, DocumentBlock, DocxClassify
from .docx_convert import ConvertResult, DocxConvert
from .docx_intake import DocxIntake, IntakeResult
from .docx_output import DocxOutput, ImportPlan
from .docx_prepass import DocxPrepass, ParagraphRecord, PrepassResult
from .docx_propose import DocxPropose, ProposeResult
from .docx_split import DocxSplit, SceneSplitResult
from .docx_syntax import DocxSyntax, SyntaxResult
from .ingest_runs import IngestRun, find_existing_import, record_ingest_run
from .pipeline import DocxIngestPipeline, IngestResult

__all__ = [
    "BlockKind",
    "ClassifyResult",
    "CommitResult",
    "ConvertResult",
    "DocumentBlock",
    "DocxClassify",
    "DocxConvert",
    "DocxIngestPipeline",
    "DocxIntake",
    "DocxOutput",
    "DocxPrepass",
    "DocxPropose",
    "DocxSplit",
    "DocxSyntax",
    "ImportCommitter",
    "ImportPlan",
    "IngestResult",
    "IngestRun",
    "IntakeResult",
    "ParagraphRecord",
    "PrepassResult",
    "ProposeResult",
    "SceneSplitResult",
    "SyntaxResult",
    "commit_import_plan",
    "find_existing_import",
    "record_ingest_run",
    "undo_import_plan",
]
