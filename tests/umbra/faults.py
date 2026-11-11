"""
UmbraEdit - Fault Injection Tests
==================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import random

from pathlib import Path


class FaultInjector:
    """Damages document files in various ways for testing verification and repair.

    Fault types:
        truncate   - Cut the file at a random byte
        flip_byte  - Flip a random byte
        remove_header_terminator - Remove the closing +++ of the header
        insert_null - Insert a NUL byte at a random position
        change_encoding - Write the file as Latin-1 instead of UTF-8
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def damage(self, docFile: Path, faultType: str) -> None:
        """Apply a fault to a document file in place."""
        if faultType == "truncate":
            self._truncate(docFile)
        elif faultType == "flip_byte":
            self._flipByte(docFile)
        elif faultType == "remove_header_terminator":
            self._removeHeaderTerminator(docFile)
        elif faultType == "insert_null":
            self._insertNull(docFile)
        elif faultType == "change_encoding":
            self._changeEncoding(docFile)
        else:
            raise ValueError(f"Unknown fault type: {faultType}")

    def _truncate(self, docFile: Path) -> None:
        """Truncate the file at a random byte (not the first byte)."""
        data = docFile.read_bytes()
        if len(data) <= 2:
            return
        cut = self.rng.randint(1, len(data) - 1)
        docFile.write_bytes(data[:cut])

    def _flipByte(self, docFile: Path) -> None:
        """Flip a random bit in a random byte."""
        data = bytearray(docFile.read_bytes())
        if len(data) == 0:
            return
        pos = self.rng.randint(0, len(data) - 1)
        data[pos] ^= 0x01
        docFile.write_bytes(bytes(data))

    def _removeHeaderTerminator(self, docFile: Path) -> None:
        """Remove the closing +++ of the header block."""
        text = docFile.read_text(encoding="utf-8")
        if not text.startswith("+++\n"):
            return
        lines = text.split("\n")
        # Find the closing +++ (second occurrence)
        close_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "+++":
                close_idx = i
                break
        if close_idx < 0:
            return
        # Remove the closing +++ line
        del lines[close_idx]
        docFile.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    def _insertNull(self, docFile: Path) -> None:
        """Insert a NUL byte at a random position."""
        data = bytearray(docFile.read_bytes())
        pos = self.rng.randint(0, len(data))
        data.insert(pos, 0x00)
        docFile.write_bytes(bytes(data))

    def _changeEncoding(self, docFile: Path) -> None:
        """Rewrite the file as Latin-1 with a character that's invalid UTF-8."""
        text = docFile.read_text(encoding="utf-8")
        # Add a byte that's invalid in UTF-8 context
        docFile.write_bytes(text.encode("latin-1") + bytes([0xFF]))


FAULT_TYPES = ("truncate", "flip_byte", "remove_header_terminator", "insert_null", "change_encoding")

__all__ = ["FAULT_TYPES", "FaultInjector"]
