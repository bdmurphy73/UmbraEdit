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

# Files whose name is allowed to contain the old product name. These are
# documents that explain the rename, and must refer to the old name to do so.
ALLOWED_OLD_NAME_PATHS = [
    "docs/source/umbra/introduction/coming-from-novelwriter.rst",
]

# Binary file types that may carry the old product name in their metadata.
BINARY_EXTENSIONS = {".exe", ".dll", ".msi"}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".ico", ".icns", ".webp"}

# Folders that are never part of the source tree.
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "dist", "dist_macos", "dist_doc", "build"}

OLD_NAME = "novelWriter"


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
    return [f for f in results if not SKIP_DIRS & set(f.parts)]


def findBinaryFiles() -> list[Path]:
    """Find all binary files in the repository."""
    results = []
    for ext in BINARY_EXTENSIONS:
        results.extend(ROOT_DIR.rglob(f"*{ext}"))
    return [f for f in results if not SKIP_DIRS & set(f.parts)]


def findRepoFiles() -> list[Path]:
    """Find all files in the working tree that are part of the source.

    Generated content is skipped. Files that are not tracked by git are
    included, so that a new file is flagged before it is committed.
    """
    results = []
    for item in ROOT_DIR.rglob("*"):
        if not item.is_file():
            continue
        if SKIP_DIRS & set(item.parts):
            continue
        results.append(item)
    return results


def checkFileNames() -> list[str]:
    """Check for files whose name contains the old product name.

    A file with the old name in it is a file a user can see, and it makes
    the package look like it belongs to the upstream project.
    """
    failures = []
    oldLower = OLD_NAME.lower()
    for path in findRepoFiles():
        relPath = str(path.relative_to(ROOT_DIR))
        if relPath in ALLOWED_OLD_NAME_PATHS:
            continue
        if oldLower in path.name.lower():
            failures.append(f"  OLD NAME in file name: {relPath}")
    return failures


def checkBinaryNames() -> list[str]:
    """Check binary files for the old product name in their metadata.

    Windows executables carry the product name in their version resources,
    and the name is also embedded in the file name of the launcher.
    """
    failures = []
    oldLower = OLD_NAME.lower()
    for path in findBinaryFiles():
        relPath = str(path.relative_to(ROOT_DIR))
        try:
            data = path.read_bytes()
        except OSError:
            continue
        text = data.decode("latin-1", errors="ignore") + data.decode("utf-16-le", errors="ignore")
        if oldLower in text.lower():
            failures.append(f"  OLD NAME in binary: {relPath}")
    return failures


def checkHashes() -> list[str]:
    """Check if any file hash matches an upstream brand graphic."""
    upstreamHashes = loadUpstreamHashes()
    if not upstreamHashes:
        return []

    failures = []
    for path in findImageFiles() + findBinaryFiles():
        try:
            data = path.read_bytes()
            digest = sha256(data)
            if digest in upstreamHashes:
                failures.append(f"  HASH MATCH: {path.relative_to(ROOT_DIR)} ({digest[:12]}...)")
        except OSError:  # noqa: PERF203
            pass
    return failures


def checkOldName() -> list[str]:
    """Check for old product name in visible strings and packaging files."""
    failures = []
    oldName = OLD_NAME
    oldLower = oldName.lower()

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
                if stripped.startswith(("#", '"""')):
                    continue
                # Check for old name in user-visible strings (self.tr, tr, format)
                if oldName in line and ("tr(" in line or "self.tr(" in line or "QCoreApplication" in line):
                    failures.append(f"  OLD NAME: {relPath}:{lineNo}: {stripped[:80]}")
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


def main() -> int:
    """Run the brand audit."""
    hashFailures = checkHashes()
    nameFailures = checkOldName()
    fileNameFailures = checkFileNames()
    binaryFailures = checkBinaryNames()

    allFailures = hashFailures + nameFailures + fileNameFailures + binaryFailures

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

    if fileNameFailures:
        print("File name audit FAILED:")
        for f in fileNameFailures:
            print(f)
        print()

    if binaryFailures:
        print("Binary metadata audit FAILED:")
        for f in binaryFailures:
            print(f)
        print()

    if not allFailures:
        print("Brand audit PASSED: no upstream graphics or old product name found.")
        return 0

    print(
        f"Brand audit FAILED: {len(hashFailures)} hash matches, "
        f"{len(nameFailures)} name matches, {len(fileNameFailures)} file names, "
        f"{len(binaryFailures)} binaries."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
