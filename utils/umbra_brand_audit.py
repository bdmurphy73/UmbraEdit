#!/usr/bin/env python3
"""
UmbraEdit - Brand Audit
=======================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Fails if any image file in the repository has a hash matching a known
upstream brand graphic, or if a visible string or packaging file still
contains the old product name outside the allowed credit lines.

Usage:
    python3 utils/umbra_brand_audit.py
"""  # noqa

from __future__ import annotations

import hashlib
import sys

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
HASHES_FILE = ROOT_DIR / "utils" / "umbra_upstream_brand_hashes.txt"

ALLOWED_OLD_NAME_FILES = [
    "CHANGELOG.md",
    "CREDITS.md",
    "README.md",
    "UMBRAEDIT.md",
    "UMBRAEDIT_UPDATE_PLAN.md",
    "docs/umbra/BASE.md",
    "docs/umbra/BRAND_ASSETS.md",
    "utils/logo_verify.py",
    "utils/umbra_upstream_brand_hashes.txt",
]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".ico", ".icns", ".webp"}


def sha256(data: bytes) -> str:
    """Return the SHA-256 hash of data as lower-case hex."""
    return hashlib.sha256(data).hexdigest()


def loadUpstreamHashes() -> set[str]:
    """Load known upstream brand graphic hashes."""
    hashes = set()
    if HASHES_FILE.is_file():
        for line in HASHES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                hashes.add(line)
    return hashes


def findImageFiles() -> list[Path]:
    """Find all image files in the repository."""
    results = []
    for ext in IMAGE_EXTENSIONS:
        results.extend(ROOT_DIR.rglob(f"*{ext}"))
    return [f for f in results if ".git" not in f.parts and ".venv" not in f.parts]


def checkHashes() -> list[str]:
    """Check if any image file hash matches an upstream brand graphic."""
    upstreamHashes = loadUpstreamHashes()
    if not upstreamHashes:
        return []

    failures = []
    for path in findImageFiles():
        try:
            data = path.read_bytes()
            digest = sha256(data)
            if digest in upstreamHashes:
                failures.append(f"  HASH MATCH: {path.relative_to(ROOT_DIR)} ({digest[:12]}...)")
        except OSError:
            pass
    return failures


def checkOldName() -> list[str]:
    """Check for old product name in visible strings and packaging files."""
    failures = []
    oldName = "novelWriter"
    oldLower = "novelwriter"

    # Check Python files for user-visible strings
    for pyFile in (ROOT_DIR / "umbraedit").rglob("*.py"):
        relPath = str(pyFile.relative_to(ROOT_DIR))
        if any(relPath.endswith(f) or f in relPath for f in ALLOWED_OLD_NAME_FILES):
            continue
        try:
            content = pyFile.read_text(encoding="utf-8")
            for lineNo, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                # Skip comments and license headers
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                # Check for old name in user-visible strings (self.tr, tr, format)
                if oldName in line and ("tr(" in line or "self.tr(" in line or "QCoreApplication" in line):
                    failures.append(
                        f"  OLD NAME: {relPath}:{lineNo}: {stripped[:80]}"
                    )
        except OSError:
            pass

    # Check packaging files
    pkgFiles = [
        ROOT_DIR / "setup" / "data" / "umbraedit.desktop",
        ROOT_DIR / "setup" / "data" / "x-umbraedit-project.xml",
        ROOT_DIR / "pyproject.toml",
    ]
    for pkgFile in pkgFiles:
        if not pkgFile.is_file():
            continue
        try:
            content = pkgFile.read_text(encoding="utf-8")
            if oldLower in content.lower():
                failures.append(f"  OLD NAME in packaging: {pkgFile.relative_to(ROOT_DIR)}")
        except OSError:
            pass

    return failures


def main() -> None:
    """Run the brand audit."""
    hashFailures = checkHashes()
    nameFailures = checkOldName()

    if hashFailures:
        print("Brand graphic hash audit FAILED:")
        for f in hashFailures:
            print(f)
        print()

    if nameFailures:
        print("Product name audit FAILED:")
        for f in nameFailures:
            print(f)
        print()

    if not hashFailures and not nameFailures:
        print("Brand audit PASSED: no upstream graphics or old product name found.")
        sys.exit(0)
    else:
        print(f"Brand audit FAILED: {len(hashFailures)} hash matches, {len(nameFailures)} name matches.")
        sys.exit(1)


if __name__ == "__main__":
    main()
