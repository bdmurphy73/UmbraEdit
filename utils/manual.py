"""
UmbraEdit - Release Manual Validation
======================================

Utilities for validating generated PDF manuals before they are included in
release artifacts.

Copyright (C) 2026 B.D. Murphy and UmbraEdit contributors.

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

import argparse

from collections.abc import Sequence
from pathlib import Path

MINIMUM_MANUAL_SIZE = 4096
_TRAILER_SIZE = 8192


class InvalidManualError(ValueError):
    """Raised when a generated PDF manual is incomplete or malformed."""


def validate_manual_pdf(path: Path | str) -> None:
    """Validate the basic structure of a generated PDF manual.

    The check deliberately uses only the standard library so it can run in
    packaging environments before the application dependencies are installed.
    A manual must be a non-symlink regular file, contain a PDF header and
    xref/EOF markers, and be large enough to rule out the empty placeholder
    files historically produced by failed documentation builds.
    """
    manualPath = Path(path)
    if manualPath.is_symlink():
        raise InvalidManualError(f"Manual must not be a symbolic link: {manualPath}")
    if not manualPath.exists():
        raise InvalidManualError(f"Manual does not exist: {manualPath}")
    if not manualPath.is_file():
        raise InvalidManualError(f"Manual is not a regular file: {manualPath}")

    try:
        fileSize = manualPath.stat().st_size
    except OSError as exc:
        raise InvalidManualError(f"Could not inspect manual {manualPath}: {exc}") from exc
    if fileSize < MINIMUM_MANUAL_SIZE:
        raise InvalidManualError(f"Manual is too small to be a complete PDF ({fileSize} bytes): {manualPath}")

    try:
        with manualPath.open("rb") as manualFile:
            header = manualFile.read(8)
            manualFile.seek(max(0, fileSize - _TRAILER_SIZE))
            trailer = manualFile.read(_TRAILER_SIZE)
    except OSError as exc:
        raise InvalidManualError(f"Could not read manual {manualPath}: {exc}") from exc

    if not header.startswith(b"%PDF-"):
        raise InvalidManualError(f"Manual does not have a PDF header: {manualPath}")
    if b"startxref" not in trailer:
        raise InvalidManualError(f"Manual does not have a PDF xref marker: {manualPath}")
    if b"%%EOF" not in trailer:
        raise InvalidManualError(f"Manual does not have a PDF EOF marker: {manualPath}")


def _validation_error(path: Path) -> str | None:
    """Return a validation error message, if any."""
    try:
        validate_manual_pdf(path)
    except InvalidManualError as exc:
        return str(exc)
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one or more PDF manuals from the command line."""
    parser = argparse.ArgumentParser(description="Validate generated UmbraEdit PDF manuals.")
    parser.add_argument("paths", nargs="+", type=Path, help="PDF manuals to validate.")
    args = parser.parse_args(argv)

    failed = False
    for path in args.paths:
        if error := _validation_error(path):
            failed = True
            print(f"ERROR: {error}")
        else:
            print(f"Valid PDF manual: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
