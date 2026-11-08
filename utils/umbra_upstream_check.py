#!/usr/bin/env python3
"""
UmbraEdit - Upstream Changed-File Checker
=========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Lists upstream files changed by the fork against the recorded base.
"""  # noqa

from __future__ import annotations

import subprocess
import sys

BASE_COMMIT = "b80b4b253"


def getChangedFiles(base: str) -> list[str]:
    """Return a sorted list of files that differ between base and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"ERROR: git diff failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return sorted(result.stdout.splitlines())


def main() -> None:
    """List upstream files changed by the fork."""
    files = getChangedFiles(BASE_COMMIT)
    print(f"Upstream files changed since {BASE_COMMIT}: {len(files)}")
    print()
    for f in files:
        print(f"  {f}")


if __name__ == "__main__":
    main()
