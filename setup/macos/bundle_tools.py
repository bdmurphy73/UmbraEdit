#!/usr/bin/env python3
"""
UmbraEdit - macOS Bundle Tools
===============================

Helper utilities used by setup/macos/build-app.sh to trim the self-contained
macOS application bundle.

The bundle contains a complete Python runtime and all of its dependencies.
Most of that payload is not needed by UmbraEdit, so this script removes the
unused parts. The set of Qt frameworks that are kept is computed from the
actual link dependencies of the PyQt6 modules and plugins that are shipped,
so the trimming remains correct when Qt is updated.

Copyright (C) 2026 B.D. Murphy and UmbraEdit contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

from collections import deque
from pathlib import Path
from typing import Optional

# The PyQt6 modules that are kept in the bundle. These are the modules
# imported by the UmbraEdit code base, plus the ones needed by the Qt
# plugins that are shipped.
QT_MODULES = (
    "QtCore",
    "QtDBus",
    "QtGui",
    "QtNetwork",
    "QtPrintSupport",
    "QtSvg",
    "QtWidgets",
)

# The Qt plugin categories that are kept in the bundle.
QT_PLUGINS = (
    "generic",
    "iconengines",
    "imageformats",
    "networkinformation",
    "platforms",
    "styles",
    "tls",
)

# The Qt translation catalogues that are kept. These are the translations
# for QtCore and QtBase, which cover the standard dialogs.
QT_TRANSLATION = re.compile(r"^qt(base)?_[a-z]{2,3}(_[A-Za-z]+)?\.qm$")

# Parts of the Python standard library that UmbraEdit never uses.
PYTHON_MODULES = (
    "ensurepip",
    "idlelib",
    "lib2to3",
    "test",
    "tkinter",
    "turtledemo",
)


def remove(path: Path) -> None:
    """Remove a file, a symlink or a directory tree."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def tree_size(path: Path) -> int:
    """Return the size of a directory tree in kibibytes."""
    result = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout:
        return int(result.stdout.split()[0])
    return 0


def linked_libraries(path: Path) -> list[str]:
    """Return the libraries a Mach-O binary links against."""
    try:
        result = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=False)
    except OSError:
        return []
    libraries = []
    for line in result.stdout.splitlines()[1:]:
        name = line.strip().split(" ")[0]
        if name:
            libraries.append(name)
    return libraries


def resolve_rpath(library: str, qt_lib: Path) -> Optional[Path]:
    """Resolve an @rpath library reference to a file in the Qt lib folder."""
    if not library.startswith("@rpath/"):
        return None
    relative = library[len("@rpath/") :]
    if ".framework/" in relative:
        parts = relative.split("/")
        return qt_lib / parts[0] / "Versions" / "A" / parts[-1]
    return qt_lib / relative


def qt_closure(site: Path) -> tuple[set[str], set[Path]]:
    """Compute the Qt frameworks and libraries needed by the bundled app.

    The result is the set of framework names, and the set of all files that
    are reachable from the PyQt6 modules and the shipped Qt plugins.
    """
    pyqt = site / "PyQt6"
    qt_lib = pyqt / "Qt6" / "lib"
    plugins = pyqt / "Qt6" / "plugins"

    seeds: list[Path] = []
    for module in QT_MODULES:
        candidate = pyqt / f"{module}.abi3.so"
        if candidate.is_file():
            seeds.append(candidate)
    for category in QT_PLUGINS:
        folder = plugins / category
        if folder.is_dir():
            seeds.extend(item for item in sorted(folder.iterdir()) if item.is_file())

    frameworks: set[str] = set()
    libraries: set[Path] = set()
    seen: set[Path] = set()
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if current in seen or not current.exists():
            continue
        seen.add(current)
        libraries.add(current)
        for part in current.parts:
            if part.endswith(".framework"):
                frameworks.add(part)
                break
        for library in linked_libraries(current):
            target = resolve_rpath(library, qt_lib)
            if target is not None and target.exists() and target not in seen:
                queue.append(target)

    return frameworks, libraries


def trim_qt(site: Path) -> None:
    """Remove the Qt components that UmbraEdit does not need."""
    pyqt = site / "PyQt6"
    qt6 = pyqt / "Qt6"
    qt_lib = qt6 / "lib"
    plugins = qt6 / "plugins"
    bindings = pyqt / "bindings"

    frameworks, libraries = qt_closure(site)
    print(f"Qt frameworks kept: {', '.join(sorted(frameworks))}")

    for framework in sorted(qt_lib.glob("*.framework")):
        if framework.name not in frameworks:
            remove(framework)

    for library in sorted(qt_lib.glob("*.dylib")):
        if library not in libraries:
            remove(library)

    for category in sorted(plugins.iterdir()):
        if category.name not in QT_PLUGINS:
            remove(category)

    for module in sorted(pyqt.glob("Qt*.abi3.so")):
        if module.name.split(".")[0] not in QT_MODULES:
            remove(module)

    for stub in sorted(pyqt.glob("Qt*.pyi")):
        if stub.stem not in QT_MODULES:
            remove(stub)

    if bindings.is_dir():
        for binding in sorted(bindings.iterdir()):
            if binding.name not in QT_MODULES:
                remove(binding)

    translations = qt6 / "translations"
    if translations.is_dir():
        for item in sorted(translations.iterdir()):
            if not QT_TRANSLATION.match(item.name):
                remove(item)

    remove(qt6 / "qml")
    remove(qt6 / "qsci")
    remove(pyqt / "lupdate")
    remove(pyqt / "uic")


def clean_bytecode(folder: Path) -> None:
    """Remove cached bytecode files that no longer have a source file."""
    for cache in sorted(folder.rglob("__pycache__")):
        for item in sorted(cache.iterdir()):
            if not item.is_file() or not item.name.endswith(".pyc"):
                continue
            stem = item.name.split(".")[0]
            if not (cache.parent / f"{stem}.py").exists():
                remove(item)


def trim_python(root: Path) -> None:
    """Remove the parts of a standalone Python runtime that aren't needed."""
    remove(root / "include")
    remove(root / "share")
    remove(root / "lib" / "pkgconfig")

    # Tcl/Tk is only needed for the interactive interpreter
    for pattern in ("tcl*", "tk*", "thread*", "itcl*", "libtcl*", "libtk*"):
        for item in sorted((root / "lib").glob(pattern)):
            remove(item)

    # Scripts that are not needed to run the app
    for pattern in ("2to3*", "idle3*", "pydoc3*", "pip*"):
        for item in sorted((root / "bin").glob(pattern)):
            remove(item)

    for folder in sorted((root / "lib").glob("python3.*")):
        for name in PYTHON_MODULES:
            remove(folder / name)
        clean_bytecode(folder)


def trim_site(site: Path) -> None:
    """Remove the parts of the installed packages that aren't needed."""
    for cache in sorted(site.rglob("__pycache__")):
        remove(cache)
    for item in sorted(site.glob("*.dist-info")):
        for record in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json"):
            remove(item / record)


def find_python(version: str) -> Optional[Path]:
    """Find a managed Python interpreter that can be bundled with the app.

    An interpreter that lives inside another application bundle must never
    be used. macOS derives the identity of a running application from the
    path of the executable that was launched, so an interpreter inside, for
    instance, Xcode's Python.app would make UmbraEdit register itself as
    "Python" in the menu bar and the Dock.
    """
    result = subprocess.run(
        ["uv", "python", "list", "--only-installed", "--output-format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    candidates: list[tuple[bool, Path]] = []
    for entry in entries:
        entryVersion = str(entry.get("version", ""))
        if entryVersion != version and not entryVersion.startswith(f"{version}."):
            continue
        path = Path(str(entry.get("path", "")))
        if not path.is_file():
            continue
        candidates.append((bool(entry.get("symlink")), path))

    # Prefer an interpreter that is installed directly over a symlink
    candidates.sort(key=lambda item: item[0])
    for _, path in candidates:
        resolved = path.resolve()
        if not resolved.is_file() or not resolved.name.startswith("python"):
            continue
        if ".app" in resolved.parts:
            continue
        if str(resolved).startswith(("/usr/bin/", "/bin/")):
            continue
        root = resolved.parent.parent
        if not (root / "lib").is_dir():
            continue
        return resolved

    return None


def main() -> int:
    """Run the bundle tools."""
    parser = argparse.ArgumentParser(description="Tools for the UmbraEdit macOS bundle")
    sub = parser.add_subparsers(dest="command", required=True)

    cmdFind = sub.add_parser("find-python", help="Find a Python interpreter to bundle")
    cmdFind.add_argument("--version", required=True, help="Python version, for instance 3.12")

    cmdTrim = sub.add_parser("trim", help="Trim the bundle")
    cmdTrim.add_argument("--python", required=True, help="Path to the bundled Python runtime")
    cmdTrim.add_argument("--site", required=True, help="Path to the bundled site-packages folder")

    args = parser.parse_args()

    if args.command == "find-python":
        path = find_python(args.version)
        if path is None:
            return 1
        print(path)
        return 0

    root = Path(args.python)
    site = Path(args.site)

    print(f"Trimming the Python runtime at {root}")
    trim_python(root)
    trim_site(site)
    print(f"Trimming Qt at {site}")
    trim_qt(site)

    print(f"Bundle size: {tree_size(root) // 1024} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
