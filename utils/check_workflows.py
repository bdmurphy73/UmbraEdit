"""
UmbraEdit - Workflow Checks
============================

This file is a part of UmbraEdit.

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
"""  # noqa

from __future__ import annotations

import sys

from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT_DIR / ".github" / "workflows"


class StrictLoader(yaml.SafeLoader):
    """A YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: StrictLoader, node: yaml.MappingNode) -> dict:
    """Construct a mapping and fail on duplicate keys."""
    mapping: dict = {}
    for keyNode, valueNode in node.value:
        key = loader.construct_object(keyNode, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                keyNode.start_mark,
            )
        mapping[key] = loader.construct_object(valueNode, deep=True)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def checkFile(path: Path) -> list[str]:
    """Check a single workflow file and return a list of problems."""
    problems = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path.name}: could not read file: {exc}"]

    try:
        yaml.load(text, Loader=StrictLoader)
    except yaml.YAMLError as exc:
        problems.append(f"{path.name}: {exc}")

    return problems


def main(paths: list[str] | None = None) -> int:
    """Run the workflow checks."""
    if paths:
        files = [Path(p).resolve() for p in paths]
    else:
        files = sorted(WORKFLOW_DIR.glob("*.yml"))

    problems = []
    for file in files:
        problems.extend(checkFile(file))

    if problems:
        for problem in problems:
            print(f"[er]{problem}")
        return 1

    print(f"Checked {len(files)} workflow files, no problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
