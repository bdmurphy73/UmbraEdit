"""
UmbraEdit - Image Metadata
==========================

This file is a part of UmbraEdit.

Copyright (C) 2026 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import re

from dataclasses import dataclass
from typing import Optional

_IMAGE_KEY = "@Image"
_ASSET_DIR = "assets/img"
_SUPPORTED_SUFFIXES = (".jpg", ".png")
_VALID_POSITIONS = ("left", "center", "right")
_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*,')
_INTEGER_PATTERN = re.compile(r"[0-9]+")
_WINDOWS_DRIVE_PATTERN = re.compile(r"[A-Za-z]:[\\/]")

# Keep metadata dimensions within the same practical range as the GUI
# controls. Besides preventing accidental layout overflow, this avoids
# converting unboundedly large decimal strings on Python versions that
# impose an integer-string conversion limit.
MAX_IMAGE_DIMENSION = 100000
_MAX_DIMENSION_DIGITS = len(str(MAX_IMAGE_DIMENSION))


class ImageMetadataError(ValueError):
    """Raised when image metadata is invalid."""


@dataclass(frozen=True)
class ImageMetadata:
    """Metadata describing an image placed in a project document."""

    relativePath: str
    width: Optional[int] = None
    height: Optional[int] = None
    position: str = "center"


def validateImagePath(relativePath: str) -> str:
    """Validate and return a canonical project-relative image path.

    Image metadata may only refer to a flat JPEG or PNG file directly
    inside the project's ``assets/img`` directory.
    """
    if not isinstance(relativePath, str):
        raise ImageMetadataError("Image path must be a string")
    if not relativePath or not relativePath.strip():
        raise ImageMetadataError("Image path must not be empty")
    if relativePath != relativePath.strip():
        raise ImageMetadataError("Image path must not have leading or trailing whitespace")
    if relativePath.startswith(("/", "\\")) or _WINDOWS_DRIVE_PATTERN.match(relativePath):
        raise ImageMetadataError("Image path must be project-relative")
    if "\\" in relativePath:
        raise ImageMetadataError("Image path must use POSIX separators")
    if "," in relativePath:
        raise ImageMetadataError("Image path must not contain commas")

    parts = relativePath.split("/")
    if any(part in (".", "..") for part in parts):
        raise ImageMetadataError("Image path must not contain path traversal")
    if len(parts) != 3:
        raise ImageMetadataError("Image path must point to a flat file in assets/img")
    if parts[0] != "assets" or parts[1] != "img":
        raise ImageMetadataError("Image path must point to assets/img")

    fileName = parts[2]
    if not fileName or fileName in (".", ".."):
        raise ImageMetadataError("Image path must include a file name")
    if fileName != fileName.strip():
        raise ImageMetadataError("Image file name must not have leading or trailing whitespace")
    if any(not char.isprintable() or char in _INVALID_FILENAME_CHARS for char in fileName):
        raise ImageMetadataError("Image file name contains invalid characters")

    suffix = ""
    for candidate in _SUPPORTED_SUFFIXES:
        if fileName.endswith(candidate):
            suffix = candidate
            break
    if not suffix:
        raise ImageMetadataError("Image path must use a .jpg or .png extension")
    if len(fileName) == len(suffix):
        raise ImageMetadataError("Image path must include a file name")

    return f"{_ASSET_DIR}/{fileName}"


def parseImageMetadata(value: str) -> ImageMetadata:
    """Parse the dedicated pipe-delimited image metadata grammar."""
    if not isinstance(value, str):
        raise ImageMetadataError("Image metadata must be a string")
    if "," in value:
        raise ImageMetadataError("Image metadata must not contain commas")

    segments = value.split("|")
    relativePath = validateImagePath(segments[0].strip())

    width: Optional[int] = None
    height: Optional[int] = None
    position = "center"
    seen: set[str] = set()

    for rawSegment in segments[1:]:
        segment = rawSegment.strip()
        if not segment:
            raise ImageMetadataError("Image metadata contains an empty attribute")

        key, separator, attributeValue = segment.partition("=")
        if not separator or "=" in attributeValue:
            raise ImageMetadataError(f"Malformed image metadata attribute: {segment}")
        if not key or not attributeValue:
            raise ImageMetadataError(f"Malformed image metadata attribute: {segment}")
        if key != key.strip() or attributeValue != attributeValue.strip():
            raise ImageMetadataError(f"Malformed image metadata attribute: {segment}")
        if key not in ("width", "height", "position"):
            raise ImageMetadataError(f"Unknown image metadata attribute: {key}")
        if key in seen:
            raise ImageMetadataError(f"Duplicate image metadata attribute: {key}")
        seen.add(key)

        if key == "position":
            if attributeValue not in _VALID_POSITIONS:
                raise ImageMetadataError(f"Invalid image position: {attributeValue}; expected left, center, or right")
            position = attributeValue
        else:
            if not _INTEGER_PATTERN.fullmatch(attributeValue):
                raise ImageMetadataError(f"Image {key} must be a positive integer")
            if len(attributeValue) > _MAX_DIMENSION_DIGITS:
                raise ImageMetadataError(
                    f"Image {key} must be a positive integer not exceeding {MAX_IMAGE_DIMENSION} pixels"
                )
            dimension = int(attributeValue)
            if dimension <= 0 or dimension > MAX_IMAGE_DIMENSION:
                raise ImageMetadataError(
                    f"Image {key} must be a positive integer not exceeding {MAX_IMAGE_DIMENSION} pixels"
                )
            if key == "width":
                width = dimension
            else:
                height = dimension

    return ImageMetadata(
        relativePath=relativePath,
        width=width,
        height=height,
        position=position,
    )


def formatImageMetadata(metadata: ImageMetadata) -> str:
    """Return the canonical pipe-delimited representation of metadata."""
    if not isinstance(metadata, ImageMetadata):
        raise ImageMetadataError("Image metadata must be an ImageMetadata instance")

    relativePath = validateImagePath(metadata.relativePath)
    width = _validateDimension(metadata.width, "width")
    height = _validateDimension(metadata.height, "height")
    if metadata.position not in _VALID_POSITIONS:
        raise ImageMetadataError(f"Invalid image position: {metadata.position}; expected left, center, or right")

    parts = [relativePath]
    if width is not None:
        parts.append(f"width={width}")
    if height is not None:
        parts.append(f"height={height}")
    parts.append(f"position={metadata.position}")
    return " | ".join(parts)


def parseImageMetadataBits(bits: list[str]) -> ImageMetadata:
    """Parse image metadata from an exact keyword/value pair."""
    if not isinstance(bits, list):
        raise ImageMetadataError("Image metadata must be a keyword/value pair")
    if len(bits) != 2:
        raise ImageMetadataError("Image metadata must have exactly one value")
    if bits[0] != _IMAGE_KEY:
        raise ImageMetadataError(f"Expected the {_IMAGE_KEY} keyword")
    if not isinstance(bits[1], str):
        raise ImageMetadataError("Image metadata value must be a string")
    return parseImageMetadata(bits[1])


def referencedImagePaths(text: str) -> set[str]:
    """Return project image paths referenced by image metadata lines.

    Extraction is deliberately conservative. Every valid path in a
    comma-separated ``@Cover`` or ``@icon`` value is returned. The path in
    an ``@Image`` line is also returned even if a later attribute is invalid.
    """
    if not isinstance(text, str):
        raise ImageMetadataError("Text must be a string")

    paths: set[str] = set()
    for rawLine in text.splitlines():
        line = rawLine.strip()
        if not line.startswith("@"):
            continue

        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        if key not in ("@Image", "@Cover", "@icon"):
            continue

        beforePipe = value.split("|", 1)[0]
        if key == "@Image":
            candidates = (beforePipe,)
        else:
            candidates = beforePipe.split(",")

        for candidate in candidates:
            try:
                relativePath = validateImagePath(candidate.strip())
            except ImageMetadataError:
                continue
            paths.add(relativePath)

    return paths


def _validateDimension(value: Optional[int], name: str) -> Optional[int]:
    """Validate an optional positive image dimension."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_IMAGE_DIMENSION:
        raise ImageMetadataError(f"Image {name} must be a positive integer not exceeding {MAX_IMAGE_DIMENSION} pixels")
    return value
