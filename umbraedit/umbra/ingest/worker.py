"""
UmbraEdit - Ingest Worker
==========================

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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QRunnable, pyqtBoundSignal, pyqtSignal, pyqtSlot

from umbraedit import SHARED
from umbraedit.umbra.ingest import DocxIngestPipeline, ImportPlan, IngestResult

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestJobResult:
    """Result of an ingest job."""

    success: bool
    plan: ImportPlan | None = None
    error: str | None = None


class IngestWorker(QRunnable):
    """Background worker for running the DOCX ingest pipeline."""

    def __init__(
        self,
        file_path: Path,
        project: Any,
        output_dir: Path | None,
        signal: pyqtBoundSignal,
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._project = project
        self._output_dir = output_dir
        self._signal = signal

    @pyqtSlot()
    def run(self) -> None:
        """Run the ingest pipeline in the background."""
        try:
            pipeline = DocxIngestPipeline(self._project)
            result = pipeline.process(self._file_path, self._output_dir)

            self._signal.emit(IngestJobResult(
                success=True,
                plan=result.plan,
            ))
        except Exception as e:
            logger.exception("Ingest pipeline failed")
            self._signal.emit(IngestJobResult(
                success=False,
                error=str(e),
            ))


class IngestDispatcher(QObject):
    """Dispatches ingest jobs to the thread pool."""

    _resultReady = pyqtSignal(object)

    def __init__(
        self,
        parent: QObject,
        callback: Callable[[IngestJobResult], None],
    ) -> None:
        super().__init__(parent)
        self._resultReady.connect(callback)

    def run_ingest(
        self,
        file_path: Path,
        project: Any,
        output_dir: Path | None = None,
    ) -> None:
        """Dispatch an ingest job to the thread pool."""
        SHARED.runInThreadPool(
            IngestWorker(file_path, project, None, self._resultReady)
        )


def run_ingest_pipeline(
    file_path: Path,
    project: Any,
    output_dir: Path | None = None,
) -> IngestResult:
    """Run the ingest pipeline synchronously (for testing or CLI)."""
    pipeline = DocxIngestPipeline(file_path.parent)
    return pipeline.process(file_path)
