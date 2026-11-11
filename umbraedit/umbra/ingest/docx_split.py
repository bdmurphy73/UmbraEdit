"""
UmbraEdit - DOCX Split Stage
=============================

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

from dataclasses import dataclass, field
from typing import Any

from umbraedit.umbra.ingest.docx_classify import BlockKind, ClassifyResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SceneSplitResult:
    """Result of the scene split stage."""

    documents: list[dict[str, Any]]  # Each document has planId, kind, parentPlanId, title, level, text, sourceParagraphs, pageType
    chapter_count: int = 0
    scene_count: int = 0
    warnings: list[str] = field(default_factory=list)


class DocxSplit:
    """Split stage: split chapters into scenes based on scene breaks."""

    def process(self, classify: ClassifyResult) -> SceneSplitResult:
        """Split chapters into scenes."""
        logger.info("Split: processing %d blocks", len(classify.blocks))

        documents: list[dict[str, Any]] = []
        chapter_count = 0
        scene_count = 0
        warnings: list[str] = []

        current_chapter_id: str | None = None
        chapter_number = 0

        for block in classify.blocks:
            if block.kind == BlockKind.CHAPTER:
                # New chapter
                chapter_count += 1
                chapter_number += 1
                plan_id = f"ch{chapter_number}"
                current_chapter_id = plan_id

                documents.append({
                    "planId": plan_id,
                    "kind": "chapter",
                    "parentPlanId": None,
                    "title": block.title,
                    "level": block.level,
                    "text": block.text,
                    "sourceParagraphs": block.source_paragraphs,
                    "pageType": None,
                })

            elif block.kind == BlockKind.SCENE:
                # Scene within current chapter
                scene_count += 1
                scene_num = scene_count
                if current_chapter_id:
                    plan_id = f"{current_chapter_id}-sc{scene_num}"
                else:
                    plan_id = f"sc{scene_num}"

                documents.append({
                    "planId": plan_id,
                    "kind": "scene",
                    "parentPlanId": current_chapter_id,
                    "title": block.title,
                    "level": block.level,
                    "text": block.text,
                    "sourceParagraphs": block.source_paragraphs,
                    "pageType": None,
                })

            elif block.kind == BlockKind.FRONT_MATTER:
                # Front matter page
                plan_id = f"front-{len([d for d in documents if d['kind'] == 'front']) + 1}"
                documents.append({
                    "planId": plan_id,
                    "kind": "front",
                    "parentPlanId": None,
                    "title": block.title,
                    "level": block.level,
                    "text": block.text,
                    "sourceParagraphs": block.source_paragraphs,
                    "pageType": block.page_type,
                })

            elif block.kind == BlockKind.BACK_MATTER:
                # Back matter page
                plan_id = f"back-{len([d for d in documents if d['kind'] == 'back']) + 1}"
                documents.append({
                    "planId": plan_id,
                    "kind": "back",
                    "parentPlanId": None,
                    "title": block.title,
                    "level": block.level,
                    "text": block.text,
                    "sourceParagraphs": block.source_paragraphs,
                    "pageType": block.page_type,
                })

            elif block.kind in (BlockKind.BODY, BlockKind.NOTE):
                # Regular body content or notes - attach to current chapter/scene
                if current_chapter_id:
                    # Append to last document if it's a scene/chapter
                    if documents and documents[-1]["kind"] in ("chapter", "scene"):
                        documents[-1]["text"] += "\n\n" + block.text
                        documents[-1]["sourceParagraphs"].extend(block.source_paragraphs)
                    else:
                        # Create a scene for orphaned body text
                        scene_count += 1
                        plan_id = f"{current_chapter_id}-sc{scene_count}"
                        documents.append({
                            "planId": plan_id,
                            "kind": "scene",
                            "parentPlanId": current_chapter_id,
                            "title": f"Scene {scene_count}",
                            "level": 0,
                            "text": block.text,
                            "sourceParagraphs": block.source_paragraphs,
                            "pageType": None,
                        })
                else:
                    # No chapter yet - create a standalone scene
                    scene_count += 1
                    plan_id = f"sc{scene_count}"
                    documents.append({
                        "planId": plan_id,
                        "kind": "scene",
                        "parentPlanId": None,
                        "title": f"Scene {scene_count}",
                        "level": 0,
                        "text": block.text,
                        "sourceParagraphs": block.source_paragraphs,
                        "pageType": None,
                    })

        # Check for empty scenes
        for doc in documents:
            if doc["kind"] == "scene" and not doc["text"].strip():
                warnings.append(f"Empty scene: {doc['planId']} (ingestEmptyScene)")

        # Check for no chapters
        if chapter_count == 0:
            warnings.append("No chapters found (ingestNoHeadings)")

        return SceneSplitResult(
            documents=documents,
            chapter_count=chapter_count,
            scene_count=scene_count,
            warnings=warnings,
        )
