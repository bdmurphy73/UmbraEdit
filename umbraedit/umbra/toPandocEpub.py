"""
UmbraEdit - Pandoc EPUB Validator
==================================

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

This module is an alias for :mod:`umbraedit.formats.toPandocEpub`,
which holds the actual implementation.
"""  # noqa

from umbraedit.formats.toPandocEpub import (
    EpubValidationResult,
    build_epub_validated,
    build_epub_with_pandoc,
    validate_epub,
)

__all__ = [
    "EpubValidationResult",
    "build_epub_validated",
    "build_epub_with_pandoc",
    "validate_epub",
]
