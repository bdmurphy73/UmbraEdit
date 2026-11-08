#!/usr/bin/env python3
"""
UmbraEdit - Performance Benchmark
=================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Runs a performance benchmark on a generated project and prints JSON
results to stdout.

Usage:
    python3 utils/umbra_bench.py --project /tmp/bench_project
    python3 utils/umbra_gen_project.py --words 400000 --scenes 2000 \
        --seed 7 --output /tmp/bench_project
    python3 utils/umbra_bench.py --project /tmp/bench_project
"""  # noqa

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def bench(project: Path) -> dict[str, object]:
    """Run the benchmark suite on a project and return results."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(["umbraedit-bench"])

    from umbraedit.core.project import NWProject

    results: dict[str, object] = {}

    # 1. Project open time
    proj = NWProject()
    t0 = time.monotonic()
    proj.openProject(project)
    t1 = time.monotonic()
    results["open_time_s"] = round(t1 - t0, 4)
    openProj = proj

    # 2. Index rebuild time
    t0 = time.monotonic()
    openProj.index.rebuild()
    t1 = time.monotonic()
    results["index_rebuild_s"] = round(t1 - t0, 4)

    # 3. Time to open the largest scene
    largestHandle = None
    largestSize = 0
    for item in openProj.tree:
        if item.isFileType():
            docPath = openProj.storage.contentPath
            if docPath:
                docFile = docPath / f"{item.itemHandle}.md"
                if docFile.is_file():
                    fSize = docFile.stat().st_size
                    if fSize > largestSize:
                        largestSize = fSize
                        largestHandle = item.itemHandle

    if largestHandle:
        from umbraedit.core.document import ProjectDocument

        doc = ProjectDocument(openProj, largestHandle)
        tracemalloc.start()
        t0 = time.monotonic()
        doc.readDocument()
        t1 = time.monotonic()
        _, peakMem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results["largest_scene_open_s"] = round(t1 - t0, 4)
        results["largest_scene_size_bytes"] = largestSize
    else:
        results["largest_scene_open_s"] = None
        results["largest_scene_size_bytes"] = 0

    # 4. Peak memory during open
    tracemalloc.start()
    freshProj = NWProject()
    freshProj.openProject(project)
    _, peakMem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["peak_memory_mb"] = round(peakMem / 1024 / 1024, 2)
    freshProj.closeProject()

    # 5. DOCX build time (if the manuscript module is available)
    try:
        from umbraedit.manuscript.docbuild import DocBuild
        from umbraedit.manuscript.buildsettings import BuildSettings

        t0 = time.monotonic()
        build = DocBuild(openProj)
        settings = BuildSettings(openProj)
        settings.fmtGroup.setFormat("std", True)
        docBuild = build.buildDocument(settings)
        t1 = time.monotonic()
        results["docx_build_s"] = round(t1 - t0, 4)
    except Exception as exc:
        results["docx_build_s"] = None
        results["docx_build_error"] = str(exc)

    openProj.closeProject()
    return results


def main() -> None:
    """Parse arguments and run the benchmark."""
    parser = argparse.ArgumentParser(description="Run UmbraEdit performance benchmark.")
    parser.add_argument("--project", type=str, required=True, help="Path to the project folder.")
    args = parser.parse_args()

    project = Path(args.project)
    if not project.is_dir():
        print(f"ERROR: Project folder not found: {project}", file=sys.stderr)
        sys.exit(1)

    results = bench(project)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
