"""
UmbraEdit - Test Suite Helpers
================================

This file is a part of UmbraEdit.

Copyright (C) 2019 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import difflib
import gc
import weakref
import xml.etree.ElementTree as ET

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from umbraedit import logger

if TYPE_CHECKING:
    import pytest

    from pytestqt.qtbot import QtBot

    from umbraedit.core.project import NWProject

XML_IGNORE = ("<UmbraEditXML ", "<project ", "<dailyTarget ")
ODT_IGNORE = ("<meta:generator", "<meta:creation-date", "<dc:date", "<meta:editing")
EPUB_IGNORE = ('<meta property="dcterms:date">', '<meta property="dcterms:modified">', "<dc:date>")
NWD_IGNORE = ("createdDate =", "updatedDate =")
DOCX_IGNORE = ("<dcterms:created", "<dcterms:modified", "<ns0:Application")
MOCK_TIME = datetime(2019, 5, 10, 18, 52, 0).timestamp()


class C:
    """Constants from the test project when the random generator is mocked."""

    # Import and status items from test project when random generator is mocked
    sNew = "s000000"
    sNote = "s000001"
    sDraft = "s000002"
    sFinished = "s000003"

    iNew = "i000004"
    iMinor = "i000005"
    iMajor = "i000006"
    iMain = "i000007"

    # Handles from test project when random generator is mocked
    hInvalid = "0000000000000"
    hNovelRoot = "0000000000008"
    hPlotRoot = "0000000000009"
    hTrashRoot = "0000000000010"
    hCharRoot = "000000000000a"
    hWorldRoot = "000000000000b"
    hTitlePage = "000000000000c"
    hChapterDir = "000000000000d"
    hChapterDoc = "000000000000e"
    hSceneDoc = "000000000000f"


@dataclass(frozen=True)
class TstPaths:
    """Paths used by the test suite."""

    testDir: Path
    filesDir: Path
    refDir: Path
    outDir: Path
    tmpDir: Path
    cnfDir: Path


class MockRnd:
    """Mock random generator counting upwards from 0 for predictable handles."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self.reset()

    def _rnd(self, n: int) -> Iterator[int]:
        yield from range(n)

    def reset(self) -> None:
        """Restart the sequence from 0."""
        gen = self._rnd(1000)
        self._monkeypatch.setattr("random.getrandbits", lambda *a: next(gen))


def cmpFiles(
    fromFile: Path,
    toFile: Path,
    ignLines: Sequence[int] | None = None,
    ignStart: Sequence[str] | None = None,
) -> bool:
    """Compare two files, with optional line ignore by line number, or
    by matching the start of a line, ignoring leading whitespace.
    """
    ignLines = ignLines or []
    ignStart = tuple(ignStart or [])

    def loadLines(path: Path) -> list[str] | None:
        """Load a file and return its lines, stripping ignored lines."""
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
        except Exception as exc:
            print(str(exc))
            return None
        return [
            line
            for num, line in enumerate(lines, start=1)
            if not (num in ignLines or line.lstrip().startswith(ignStart))
        ]

    def colourDiffLine(line: str) -> str:
        """Add bright ANSI colours to a line of a unified diff."""
        if line.startswith(("+++", "---")):
            return f"\033[1m{line}\033[0m"
        elif line.startswith("+"):
            return f"\033[92m{line}\033[0m"
        elif line.startswith("-"):
            return f"\033[91m{line}\033[0m"
        elif line.startswith("@@"):
            return f"\033[96m{line}\033[0m"
        return line

    fromText = loadLines(fromFile)
    toText = loadLines(toFile)
    if fromText is None or toText is None:
        return False

    if fromText == toText:
        return True

    diff = difflib.unified_diff(fromText, toText, fromfile=str(fromFile), tofile=str(toFile), lineterm="")
    print("\n".join(colourDiffLine(line) for line in diff))

    return False


def xmlToText(xElem: ET.Element) -> str:
    """Get the text content of an XML element."""
    text = ET.tostring(xElem, encoding="utf-8", xml_declaration=False).decode()
    bits = text.partition(">")
    node = bits[0].partition(" ")
    rest = " ".join(x for x in node[2].split() if not x.startswith("xmlns")).replace("/", " /")
    return f"{node[0]}{rest}{bits[1]}{bits[2]}"


def readFile(file: Path) -> str:
    """Return the content of a file as a string."""
    return file.read_text(encoding="utf-8")


def writeFile(file: Path, data: str) -> None:
    """Write the contents of a string to a file."""
    file.write_text(data, encoding="utf-8")


def clearLogHandlers() -> None:
    """Clear all log handlers."""
    for handler in logger.handlers:
        logger.removeHandler(handler)


def buildTestProject(project: NWProject, path: Path) -> None:
    """Build a standard test project in path using the given project
    object.
    """
    from umbraedit.enum import nwItemClass

    project.storage.createNewProject(path)
    project.setDefaultStatusImport()

    project.data.setUuid("d0f3fe10-c6e6-4310-8bfd-181eb4224eed")
    project.data.setName("New Project")
    project.data.setAuthor("Jane Doe")

    # Creating a minimal project with a few root folders and a
    # single chapter folder with a single file.
    nrHandle = project.newRoot(nwItemClass.NOVEL)
    project.newRoot(nwItemClass.PLOT)
    project.newRoot(nwItemClass.CHARACTER)
    project.newRoot(nwItemClass.WORLD)

    tdHandle = project.newFile("Title Page", nrHandle)
    cfHandle = project.newFolder("New Folder", nrHandle) or ""
    cdHandle = project.newFile("New Chapter", cfHandle)
    sdHandle = project.newFile("New Scene", cfHandle)

    aDoc = project.storage.getDocument(tdHandle)
    aDoc.writeDocument("#! New Novel\n\n>> By Jane Doe <<\n")
    project.index.reIndexHandle(tdHandle)

    aDoc = project.storage.getDocument(cdHandle)
    aDoc.writeDocument("## {0}\n\n".format(project.tr("New Chapter")))
    project.index.reIndexHandle(cdHandle)

    aDoc = project.storage.getDocument(sdHandle)
    aDoc.writeDocument("### {0}\n\n".format(project.tr("New Scene")))
    project.index.reIndexHandle(sdHandle)

    project.session.startSession()
    project.setProjectChanged(True)
    project.saveProject()
    project._valid = True
    project._tree._ready = True


def checkDialogFreedOnClose(qtbot: QtBot, factory: Callable[[], QDialog]) -> None:
    """Check that a dialog is freed by reference count alone when it is
    closed. This guards against PyQt6 reference loops where a closure
    connected to a signal captures the dialog that owns the sender, in
    which case the dialog lingers until the cyclic garbage collector
    runs. The dialog must be created by the factory so that the check
    holds the only reference to it.
    """
    dialog = factory()
    dialog.show()
    qtbot.wait(20)
    ref = weakref.ref(dialog)
    gc.disable()
    try:
        dialog.close()
        qtbot.wait(20)
        del dialog
        assert ref() is None, "Dialog was not freed by reference count on close"
    finally:
        gc.enable()


def checkWidgetFreedOnRelease(factory: Callable[[], QWidget]) -> None:
    """Check that a transient widget, like a context menu, is freed by
    reference count alone when its parent is cleared and the last
    reference is dropped. The widget must be created by the factory so
    that the check holds the only reference to it.
    """
    widget = factory()
    ref = weakref.ref(widget)
    gc.disable()
    try:
        widget.setParent(None)  # type: ignore
        del widget
        assert ref() is None, "Widget was not freed by reference count on release"
    finally:
        gc.enable()


class SimpleDialog(QDialog):
    """Dialog for showing a single widget in tests."""

    def __init__(self, widget: QWidget | None = None) -> None:
        super().__init__()
        self._widget = widget
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        self.setLayout(layout)
        if widget:
            layout.addWidget(widget)

    @property
    def widget(self) -> QWidget | None:
        return self._widget

    def addWidget(self, widget: QWidget) -> None:
        """Add a widget to the dialog."""
        self._widget = widget
        layout = self.layout()
        assert layout is not None
        layout.addWidget(widget)


DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

DOCX_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOCX_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""


def makeDocxParagraph(text: str, style: str | None = None) -> str:
    """Return a WordprocessingML paragraph with optional style."""
    from xml.sax.saxutils import escape

    props = f'<w:pPr><w:pStyle w:val="{style}" /></w:pPr>' if style else ""
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def makeDocx(
    path: Path,
    paragraphs: Sequence[tuple[str, str | None]] | None = None,
    title: str = "",
    author: str = "",
) -> Path:
    """Create a minimal Word document at the given path.

    The paragraphs are a sequence of (text, style) tuples, where the
    style is the Word style id, like "Heading1".
    """
    import zipfile

    body = "".join(makeDocxParagraph(text, style) for text, style in paragraphs or [])
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<cp:coreProperties "
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>"
        "</cp:coreProperties>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, mode="w") as inFile:
        inFile.writestr("[Content_Types].xml", DOCX_CONTENT_TYPES)
        inFile.writestr("_rels/.rels", DOCX_ROOT_RELS)
        inFile.writestr("word/_rels/document.xml.rels", DOCX_DOC_RELS)
        inFile.writestr("word/document.xml", document)
        inFile.writestr("docProps/core.xml", core)
    return path
