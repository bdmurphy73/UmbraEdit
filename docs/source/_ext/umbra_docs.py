"""UmbraEdit Sphinx Extension.

Custom directives for the UmbraEdit documentation system.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from sphinx.application import Sphinx

_EXT_DIR = Path(__file__).parent
_DOC_SRC = _EXT_DIR.parent


def _loadFeaturesDone() -> dict:
    """Load docs/umbra/features-done.json."""
    doneFile = _DOC_SRC.parent / "umbra" / "features-done.json"
    if doneFile.is_file():
        return json.loads(doneFile.read_text(encoding="utf-8"))
    return {}


def _loadOwnership() -> dict:
    """Load docs/umbra/docs-ownership.json."""
    ownerFile = _DOC_SRC.parent / "umbra" / "docs-ownership.json"
    if ownerFile.is_file():
        return json.loads(ownerFile.read_text(encoding="utf-8"))
    return {}


class UmbraOwnerDirective(Directive):
    """Mark a page as owned by a feature prompt (e.g. P09).

    Usage: .. umbra-owner:: P09
    """

    required_arguments = 1
    optional_arguments = 0

    def run(self) -> list[nodes.Node]:
        ownerId = self.arguments[0].strip()
        node = nodes.comment()
        node["umbra-owner"] = ownerId
        return [node]


class UmbraExampleDirective(Directive):
    """Render a code block and optionally verify it against a parser.

    Usage:
        .. umbra-example:: voiceline
            :expect: ok

            [voice: alice] Hello world.

    During `make check`, the content is fed to the named parser and
    compared with the expected result. A failing example fails the
    docs build.
    """

    required_arguments = 1
    optional_arguments = 0
    has_content = True
    option_spec = {"expect": directives.unchanged, "lang": directives.unchanged}

    def run(self) -> list[nodes.Node]:
        parserName = self.arguments[0].strip()
        lang = self.options.get("lang", "text")
        expect = self.options.get("expect", None)
        content = "\n".join(self.content)

        # Create a literal block
        literal = nodes.literal_block(content, content)
        literal["language"] = lang
        literal["umbra-example"] = parserName
        if expect:
            literal["umbra-expect"] = expect

        return [literal]


class UmbraShotDirective(Directive):
    """Insert a screenshot with light/dark variants.

    Usage: .. umbra-shot:: editor-main
        :alt: The main editor window

    Requires docs/source/_static/shots/editor-main-{light,dark}.png.
    """

    required_arguments = 1
    optional_arguments = 0
    option_spec = {"alt": directives.unchanged_required, "width": directives.unchanged}

    def run(self) -> list[nodes.Node]:
        shotName = self.arguments[0].strip()
        altText = self.options.get("alt", f"Screenshot: {shotName}")
        width = self.options.get("width", "80%")

        shotsDir = _DOC_SRC / "_static" / "shots"

        image = nodes.image(
            uri=f"_static/shots/{shotName}-light.png",
            alt=altText,
            width=width,
        )
        image["classes"].append("umbra-shot")
        image["umbra-shot"] = shotName
        return [image]


class UmbraCatalogDirective(Directive):
    """Render a generated catalog (checks, settings, commands, etc.).

    Usage: .. umbra-catalog:: checks
    """

    required_arguments = 1
    optional_arguments = 0

    def run(self) -> list[nodes.Node]:
        catalogName = self.arguments[0].strip()
        node = nodes.section()
        node["umbra-catalog"] = catalogName
        node += nodes.title("", f"Generated {catalogName.title()} Catalog")
        node += nodes.paragraph(
            "", f"This catalog is generated at build time from the code. "
            f"Run `make {catalogName}` to regenerate."
        )
        return [node]


def setup(app: Sphinx) -> dict[str, Any]:
    """Register directives with Sphinx."""
    app.add_directive("umbra-owner", UmbraOwnerDirective)
    app.add_directive("umbra-example", UmbraExampleDirective)
    app.add_directive("umbra-shot", UmbraShotDirective)
    app.add_directive("umbra-catalog", UmbraCatalogDirective)
    return {"version": "0.1", "parallel_read_safe": True}
