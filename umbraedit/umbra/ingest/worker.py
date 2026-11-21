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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from umbraedit import SHARED
from umbraedit.umbra.ingest import DocxIngestPipeline, ImportPlan, IngestResult

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestJobResult:
    """Result of an ingest job."""

    success: bool
    plan: Optional[ImportPlan] = None
    error: Optional[str] = None


class IngestWorker(QRunnable):
    """Background worker for running the DOCX ingest pipeline."""

    def __init__(
        self,
        file_path: Path,
        project: Any,
        output_dir: Optional[Path],
        dispatcher: Optional[IngestDispatcher],
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._project = project
        self._output_dir = output_dir
        self._dispatcher = dispatcher

    @pyqtSlot()
    def run(self) -> None:
        """Run the ingest pipeline in the background."""
        try:
            pipeline = DocxIngestPipeline(self._projectPath())
            result = pipeline.process(self._file_path, self._output_dir)

            self._emit(
                IngestJobResult(
                    success=True,
                    plan=result.plan,
                )
            )
        except Exception as e:
            logger.exception("Ingest pipeline failed")
            self._emit(
                IngestJobResult(
                    success=False,
                    error=str(e),
                )
            )

    def _projectPath(self) -> Path:
        """Return the project folder path.

        The project can be given either as a project object, or as the
        path to a project folder.
        """
        if isinstance(self._project, Path):
            return self._project
        storage = getattr(self._project, "storage", None)
        if storage is not None and getattr(storage, "storagePath", None):
            return Path(storage.storagePath)
        return Path(str(self._project))

    def _emit(self, result: IngestJobResult) -> None:
        """Send the result to the receiver.

        The receiver is a QObject that may have been deleted while the
        job was running, for instance if the main window was closed.
        Emitting a signal on a deleted QObject crashes the process, so
        the object is checked before the signal is emitted.
        """
        dispatcher = self._dispatcher
        if dispatcher is None:
            return
        try:
            if sip.isdeleted(dispatcher):
                logger.warning("The ingest dispatcher was deleted, dropping result")
                return
            dispatcher._resultReady.emit(result)
        except RuntimeError:
            logger.warning("Could not deliver the ingest result: the receiver was deleted")
        except Exception:
            logger.warning("Could not deliver the ingest result", exc_info=True)


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
        output_dir: Optional[Path] = None,
    ) -> None:
        """Dispatch an ingest job to the thread pool."""
        SHARED.runInThreadPool(IngestWorker(file_path, project, None, self))


def run_ingest_pipeline(
    file_path: Path,
    project: Any,
    output_dir: Optional[Path] = None,
) -> IngestResult:
    """Run the ingest pipeline synchronously (for testing or CLI)."""
    pipeline = DocxIngestPipeline(file_path.parent)
    return pipeline.process(file_path)
