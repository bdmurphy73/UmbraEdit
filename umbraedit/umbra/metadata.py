"""
UmbraEdit - Book Metadata
=========================

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

import copy
import logging
import re

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import metadataFile

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ISBN-13 regex
ISBN13_RE = re.compile(
    r"^(?:ISBN[-\s]?)?(?=[0-9]{13}$|(?=(?:[0-9]+[-\s]?){4})"
    r"[-\s]?97[89][-\s]?[0-9]{1,5}[-\s]?[0-9]+[-\s]?[0-9]+[-\s]?[0-9])"
    r"(?:[0-9]{1,5}[-\s]?){3}[0-9]$"
)
# ISBN-10 regex
ISBN10_RE = re.compile(
    r"^(?:ISBN[-\s]?)?(?=[0-9]{10}$|(?=(?:[0-9]+[-\s]?){3})"
    r"[-\s]?[0-9]{1,5}[-\s]?[0-9]+[-\s]?[0-9]+[-\s]?[0-9X])"
    r"(?:[0-9]+[-\s]?){3}[0-9X]$"
)

# Default format configurations
DEFAULT_FORMATS = {
    "paperback": {
        "enabled": True,
        "isbn": "",
        "publisher": "",
        "publicationDate": "",
        "price": {"USD": None},
        "trim": "5.5x8.5",
        "pageCount": None,
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
        "isbn": "",
        "publisher": "",
        "publicationDate": "",
        "price": {},
    },
    "audiobook": {
        "enabled": True,
        "isbn": "",
        "publisher": "",
        "publicationDate": "",
        "price": {},
        "narrator": "",
        "durationSeconds": None,
    },
}

# Book fields that are required for each enabled format
REQUIRED_BOOK_FIELDS = [
    "title",
    "author",
    "language",
    "copyrightYear",
    "copyrightHolder",
]

FORMAT_REQUIRED_FIELDS = {
    "paperback": ["isbn"],
    "hardback": ["isbn"],
    "epub": ["isbn"],
    "audiobook": ["isbn", "narrator"],
}


@dataclass
class Metadata:
    """Book metadata container."""

    v: int = 1
    book: dict[str, Any] = field(default_factory=dict)
    formats: dict[str, dict[str, Any]] = field(default_factory=dict)
    custom: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize default values for book and formats."""
        # Ensure book has all required fields with defaults
        default_book = {
            "title": "",
            "subtitle": "",
            "author": "",
            "penName": "",
            "series": "",
            "seriesNumber": None,
            "language": "en",
            "copyrightYear": datetime.now().year,
            "copyrightHolder": "",
            "description": "",
            "keywords": [],
            "bisac": [],
            "audience": "",
            "contentWarnings": [],
        }
        for key, value in default_book.items():
            if key not in self.book:
                self.book[key] = value

        # Ensure formats have all required fields with defaults
        for fmt_key, fmt_defaults in DEFAULT_FORMATS.items():
            if fmt_key not in self.formats:
                self.formats[fmt_key] = copy.deepcopy(fmt_defaults)
            else:
                # Fill in missing keys
                for k, v in fmt_defaults.items():
                    if k not in self.formats[fmt_key]:
                        self.formats[fmt_key][k] = copy.deepcopy(v)

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "v": self.v,
            "book": self.book,
            "formats": self.formats,
            "custom": self.custom,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> Metadata:
        """Create Metadata from dictionary."""
        return cls(
            v=data.get("v", 1),
            book=data.get("book", {}),
            formats=data.get("formats", {}),
            custom=data.get("custom", {}),
        )


def loadMetadata(projectPath: Path) -> Metadata:
    """Load metadata from project's umbra/metadata.json."""
    metaFile = metadataFile(projectPath)
    if not metaFile.is_file():
        return Metadata()
    try:
        data = readJson(metaFile)
        if isinstance(data, dict):
            return Metadata.fromDict(data)
        logger.warning("Metadata file %s does not contain a JSON object", metaFile)
        return Metadata()
    except Exception:
        logger.exception("Failed to load metadata from %s", metaFile)
        return Metadata()


def saveMetadata(projectPath: Path, metadata: Metadata) -> None:
    """Save metadata to project's umbra/metadata.json atomically."""
    metaFile = metadataFile(projectPath)
    metaFile.parent.mkdir(parents=True, exist_ok=True)
    writeJson(metaFile, metadata.toDict())


def getValue(metadata: Metadata, path: str) -> Any:
    """Get a value from metadata using dot notation path.

    Examples: "book.title", "formats.paperback.isbn", "custom.dedicationName"
    """
    parts = path.split(".")
    if not parts:
        return None

    obj: Any = metadata
    if parts[0] == "book":
        obj = metadata.book
    elif parts[0] == "formats":
        obj = metadata.formats
    elif parts[0] == "custom":
        obj = metadata.custom
    else:
        return None

    for part in parts[1:]:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def setValue(metadata: Metadata, path: str, value: Any) -> bool:
    """Set a value in metadata using dot notation path.

    Returns True if successful, False if path is invalid.
    Unknown keys under 'custom' are always allowed.
    """
    parts = path.split(".")
    if len(parts) < 2:
        return False

    obj: Any = None
    if parts[0] == "book":
        obj = metadata.book
    elif parts[0] == "formats":
        obj = metadata.formats
    elif parts[0] == "custom":
        obj = metadata.custom
    else:
        return False

    # Navigate to parent of target key
    for part in parts[1:-1]:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return False

    # Set the value
    target = parts[-1]
    if isinstance(obj, dict):
        obj[target] = value
        return True
    return False


def formatValues(metadata: Metadata, fmt: str) -> dict[str, Any]:
    """Merge book and format-specific values.

    Format values override book values. Returns a flat dict suitable for
    template variable resolution.
    """
    result = {"book": copy.deepcopy(metadata.book)}
    if fmt in metadata.formats:
        result.update(metadata.formats[fmt])
    result["format"] = {"name": fmt, **metadata.formats.get(fmt, {})}
    if metadata.custom:
        result["custom"] = metadata.custom
    return result


def validateIsbn(isbn: str) -> tuple[bool, str]:
    """Validate ISBN-13 or ISBN-10 check digit.

    Returns (is_valid, normalized_isbn). Normalized ISBN has no spaces/hyphens.
    """
    # Normalize: remove spaces, hyphens, "ISBN" prefix
    normalized = re.sub(r"[\s\-]|^ISBN", "", isbn, flags=re.IGNORECASE)

    if len(normalized) == 13 and normalized.isdigit():
        # ISBN-13 check digit
        total = sum(int(normalized[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
        check = (10 - (total % 10)) % 10
        return check == int(normalized[12]), normalized
    elif len(normalized) == 10:
        # ISBN-10 check digit
        total = 0
        for i, ch in enumerate(normalized[:9]):
            if not ch.isdigit():
                return False, normalized
            total += int(ch) * (10 - i)
        check_char = normalized[9].upper()
        check = (11 - (total % 11)) % 11
        expected = "X" if check == 10 else str(check)
        return check_char == expected, normalized
    return False, normalized


def formatValuesForBuild(metadata: Metadata, fmt: str, edition: str | None = None) -> dict[str, Any]:
    """Get format values for a build, with edition awareness.

    Used by P24 and other features that need edition-specific values.
    """
    values = formatValues(metadata, fmt)
    values["format"]["name"] = fmt
    values["format"]["edition"] = edition or "main"
    # Add current date
    values["date"] = datetime.now().strftime("%Y-%m-%d")
    return values


def bookValues(edition: str | None, fmt: str, projectPath: Path) -> dict[str, Any]:
    """Service function used by P20, P21, P22, P24, P30, P31, P32.

    Returns merged book + format values for the given edition and format.
    """
    metadata = loadMetadata(projectPath)
    return formatValuesForBuild(metadata, fmt, edition)


# Variable resolution for {{...}} templates
VARIABLE_RE = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

VARIABLE_PREFIXES = {
    "book": lambda m, f, e: getValue(m, f"book.{f}"),
    "format": lambda m, f, e: getValue(m, f"formats.{f}.{f}") or getValue(m, f"formats.{f}.{e}"),
    "custom": lambda m, f, e: getValue(m, f"custom.{e}"),
    "date": lambda m, f, e: datetime.now().strftime("%Y-%m-%d"),
}


def resolveVariables(
    text: str, project: Any, edition: str | None = None, fmt: str = "paperback"
) -> tuple[str, list[str]]:
    """Resolve {{...}} variables in text.

    Args:
        text: The source text containing variables.
        project: The project object with storage.path.
        edition: Optional edition identifier.
        fmt: The format being built (paperback, hardback, epub, audiobook).

    Returns:
        A tuple of ``(resolved_text, unresolved_list)`` where
        ``resolved_text`` has all resolvable variables replaced and
        ``unresolved_list`` lists each variable that could not be resolved.

    """
    storagePath = project.storage.storagePath
    if not storagePath:
        return text, []

    metadata = loadMetadata(storagePath)
    values = formatValuesForBuild(metadata, fmt, edition)

    unresolved: list[str] = []

    def replace(match: re.Match) -> str:
        var_path = match.group(1)
        parts = var_path.split(".")
        if not parts:
            unresolved.append(var_path)
            return match.group(0)

        # Navigate the values dict
        obj: Any = values
        for part in parts:
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                unresolved.append(var_path)
                return match.group(0)

        if obj is None:
            unresolved.append(var_path)
            return match.group(0)

        return str(obj)

    result = VARIABLE_RE.sub(replace, text)
    return result, unresolved


def getEnabledFormats(metadata: Metadata) -> list[str]:
    """Return list of enabled format keys."""
    return [fmt for fmt, config in metadata.formats.items() if config.get("enabled", False)]


def getRequiredFieldsForFormat(fmt: str) -> list[str]:
    """Get required fields for a specific format."""
    return FORMAT_REQUIRED_FIELDS.get(fmt, [])


def checkMetadataRequired(metadata: Metadata) -> list[tuple[str, str]]:
    """Check required metadata fields for enabled formats.

    Returns list of (field_path, format) tuples for missing required fields.
    """
    missing: list[tuple[str, str]] = []
    enabled = getEnabledFormats(metadata)

    for fmt in enabled:
        # Check book fields
        missing.extend((f"book.{fld}", fmt) for fld in REQUIRED_BOOK_FIELDS if not metadata.book.get(fld))

        # Check format-specific fields
        missing.extend(
            (f"formats.{fmt}.{fld}", fmt)
            for fld in getRequiredFieldsForFormat(fmt)
            if not metadata.formats[fmt].get(fld)
        )

    return missing
