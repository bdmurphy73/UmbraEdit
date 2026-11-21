"""
UmbraEdit - JSON I/O
====================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Canonical JSON read/write with atomic writes and schema versioning.
Data is UTF-8, NFC, LF line endings, no BOM, sorted keys, compact
separators, trailing newline. Timestamps are UTC ISO 8601 with Z.
Hashes are SHA-256 lower-case hex.
"""  # noqa

from __future__ import annotations

import contextlib
import json
import os
import tempfile

from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA_VERSION = 1


class UmbraSchemaNewerError(Exception):
    """The file's schema version is newer than this code supports."""


def readJson(path: Path, default: Union[dict, Optional[list]] = None) -> Union[dict, list]:
    """Read a JSON file. Returns `default` if the file doesn't exist.

    Raises `UmbraSchemaNewerError` if the schema version is newer than
    this code supports.
    """
    if not path.is_file():
        return default if default is not None else {}

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict) and "v" in data:
        fileVersion = data["v"]
        if isinstance(fileVersion, int) and fileVersion > SCHEMA_VERSION:
            raise UmbraSchemaNewerError(
                f"Schema version {fileVersion} is newer than supported version {SCHEMA_VERSION}"
            )
        # Strip the version key so callers get their original data back
        data = {k: v for k, v in data.items() if k != "v"}

    return data


def writeJson(path: Path, data: Union[dict, list]) -> None:
    """Write a JSON file atomically with canonical formatting.

    Uses a temp file in the same folder, then renames. Adds the schema
    version key `"v"` if data is a dict and doesn't already have one.
    """
    if isinstance(data, dict) and "v" not in data:
        data = {"v": SCHEMA_VERSION, **data}

    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: temp file in same folder, fsync, rename
    fd, tempPath = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fObj:
            fObj.write(text)
            fObj.flush()
            os.fsync(fObj.fileno())
        os.rename(tempPath, str(path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tempPath)
        raise
