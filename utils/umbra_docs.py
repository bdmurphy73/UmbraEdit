#!/usr/bin/env python3
"""
UmbraEdit - Documentation Build Tool
=====================================

Build targets for the UmbraEdit documentation system.

Usage:
    python3 utils/umbra_docs.py html
    python3 utils/umbra_docs.py pdf [a4|letter]
    python3 utils/umbra_docs.py check
    python3 utils/umbra_docs.py screenshots
"""  # noqa

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs"
SOURCE_DIR = DOCS_DIR / "source"
BUILD_DIR = DOCS_DIR / "build"


def _run(cmd: list[str], cwd: Path | None = None) -> bool:
    """Run a command and return True on success."""
    print(f"  [run] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode == 0


def build_html() -> bool:
    """Build the HTML documentation."""
    print("[html] Building HTML...")
    return _run([sys.executable, "-m", "sphinx", "-b", "html", "-W", "--keep-going",
                 str(SOURCE_DIR), str(BUILD_DIR / "html")])


def build_pdf(paper: str = "a4") -> bool:
    """Build the PDF documentation."""
    print(f"[pdf] Building PDF ({paper})...")
    env = {"PAPER": paper, **{k: v for k, v in __import__("os").environ.items()}}
    return _run([sys.executable, "-m", "sphinx", "-b", "latex", "-W", "--keep-going",
                 str(SOURCE_DIR), str(BUILD_DIR / "latex")], cwd=ROOT_DIR)


def build_check() -> bool:
    """Run the documentation audit."""
    print("[check] Running docs audit...")
    ok = True

    # Check that ownership file exists and is valid JSON
    ownerFile = ROOT_DIR / "docs" / "umbra" / "docs-ownership.json"
    if not ownerFile.is_file():
        print("  MISSING: docs/umbra/docs-ownership.json")
        return False

    # Check that features-done.json exists
    doneFile = ROOT_DIR / "docs" / "umbra" / "features-done.json"
    if not doneFile.is_file():
        doneFile.parent.mkdir(parents=True, exist_ok=True)
        doneFile.write_text("{}", encoding="utf-8")

    # Check all pages referenced in the toctree exist
    import json
    ownership = json.loads(ownerFile.read_text(encoding="utf-8"))
    for page in ownership:
        rstPath = SOURCE_DIR / "umbra" / f"{page}.rst"
        if not rstPath.is_file():
            print(f"  MISSING: {page}.rst")
            ok = False

    # Check for external URLs in HTML output (if built)
    htmlDir = BUILD_DIR / "html"
    if htmlDir.is_dir():
        for htmlFile in htmlDir.rglob("*.html"):
            content = htmlFile.read_text(encoding="utf-8")
            for ext in ["http://", "https://"]:
                # Skip <a href> links (those are fine, they're navigation)
                # Only flag resource URLs (img src, script src, link href)
                for resource in ["src=\"http", "src='http"]:
                    if resource in content:
                        print(f"  EXTERNAL RESOURCE: {htmlFile.name} contains '{resource}'")
                        ok = False

    if ok:
        print("  Docs check PASSED")
    else:
        print("  Docs check FAILED")

    return ok


def main() -> None:
    """Parse arguments and run the target."""
    parser = argparse.ArgumentParser(description="Build UmbraEdit documentation.")
    parser.add_argument("target", choices=["html", "pdf", "check", "clean"])
    parser.add_argument("--paper", default="a4", choices=["a4", "letter"])
    args = parser.parse_args()

    if args.target == "html":
        ok = build_html()
    elif args.target == "pdf":
        ok = build_pdf(args.paper)
    elif args.target == "check":
        ok = build_check()
    elif args.target == "clean":
        if BUILD_DIR.exists():
            shutil.rmtree(BUILD_DIR)
        ok = True
    else:
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
