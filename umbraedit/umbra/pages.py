"""
UmbraEdit - Page Types
======================

This file is a part of UmbraEdit, a fork of novelWriter.

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

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.metadata import Metadata
from umbraedit.umbra.paths import pagesFile

logger = logging.getLogger(__name__)

# Page type schema for validation
PAGE_TYPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "label", "matter", "order", "fields", "template", "build"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9]*$"},
        "label": {"type": "string", "minLength": 1},
        "matter": {"type": "string", "enum": ["front", "back"]},
        "order": {"type": "integer", "minimum": 0},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label", "type"],
                "properties": {
                    "key": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9]*$"},
                    "label": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "enum": ["text", "textarea", "number", "boolean", "select"]},
                    "from": {"type": "string"},
                    "optional": {"type": "boolean", "default": False},
                    "help": {"type": "string"},
                },
            },
        },
        "template": {"type": "string"},
        "build": {
            "type": "object",
            "properties": {
                "newPageBefore": {"type": "boolean"},
                "headingStyle": {"type": "string", "enum": ["normal", "hidden"]},
                "generated": {"type": "boolean"},
                "spoken": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "requiredFor": {"type": "array", "items": {"type": "string", "enum": ["print", "epub", "audiobook"]}},
        "variants": {
            "type": "object",
            "patternProperties": {
                "^(print|epub|audio)$": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "spoken": {"type": "boolean"},
                        "fields": {"type": "array", "items": {"type": "object"}},
                        "template": {"type": "string"},
                        "build": {"type": "object"},
                        "requiredFor": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class PageField:
    """A field definition for a page type."""

    key: str
    label: str
    type: str
    from_: str = ""
    optional: bool = False
    help: str = ""


@dataclass(frozen=True)
class PageBuildConfig:
    """Build configuration for a page type."""

    newPageBefore: bool = True
    headingStyle: str = "normal"
    generated: bool = False
    spoken: bool = False


@dataclass(frozen=True)
class PageTypeVariant:
    """A format-specific variant of a page type."""

    enabled: bool = True
    spoken: bool = False
    fields: list[PageField] = field(default_factory=list)
    template: str = ""
    build: PageBuildConfig = field(default_factory=PageBuildConfig)
    requiredFor: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PageType:
    """A page type definition."""

    id: str
    label: str
    matter: str
    order: int
    fields: list[PageField]
    template: str
    build: PageBuildConfig
    requiredFor: list[str] = field(default_factory=list)
    variants: dict[str, PageTypeVariant] = field(default_factory=dict)

    def getVariant(self, format_: str) -> PageTypeVariant | None:
        """Get the variant for a specific format."""
        return self.variants.get(format_)

    def isEnabledForFormat(self, format_: str) -> bool:
        """Check if this page type is enabled for a format."""
        variant = self.getVariant(format_)
        if variant is not None:
            return variant.enabled
        return format_ in self.requiredFor

    def getEffectiveFields(self, format_: str) -> list[PageField]:
        """Get the effective fields for a format (variant overrides base)."""
        variant = self.getVariant(format_)
        if variant and variant.fields:
            return variant.fields
        return self.fields

    def getEffectiveTemplate(self, format_: str) -> str:
        """Get the effective template for a format."""
        variant = self.getVariant(format_)
        if variant and variant.template:
            return variant.template
        return self.template

    def getEffectiveBuild(self, format_: str) -> PageBuildConfig:
        """Get the effective build config for a format."""
        variant = self.getVariant(format_)
        if variant and (variant.build.newPageBefore != PageBuildConfig().newPageBefore
                        or variant.build.headingStyle != PageBuildConfig().headingStyle
                        or variant.build.generated != PageBuildConfig().generated
                        or variant.build.spoken != PageBuildConfig().spoken):
            return variant.build
        return self.build

    def getEffectiveRequiredFor(self, format_: str) -> list[str]:
        """Get the effective requiredFor for a format."""
        variant = self.getVariant(format_)
        if variant and variant.requiredFor:
            return variant.requiredFor
        return self.requiredFor


def loadPageTypes(packageDir: Path) -> dict[str, PageType]:
    """Load all page type definitions from the pagetypes package directory."""
    pageTypes: dict[str, PageType] = {}

    for filePath in packageDir.glob("*.json"):
        try:
            data = readJson(filePath)
            if isinstance(data, dict):
                pageType = _parsePageType(data)
                pageTypes[pageType.id] = pageType
        except Exception as e:
            logger.exception("Failed to load page type from %s: %s", filePath, e)

    return pageTypes


def _resolveFrom(data: dict[str, Any], path: str) -> Any:
    """Resolve a value from nested data using dot notation path."""
    parts = path.split(".")
    obj: Any = data
    for part in parts:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def _parsePageType(data: dict[str, Any]) -> PageType:
    """Parse a page type definition from JSON data."""
    # Validate against schema
    jsonschema.validate(data, PAGE_TYPE_SCHEMA)

    fields = [
        PageField(
            key=f["key"],
            label=f["label"],
            type=f["type"],
            from_=f.get("from", ""),
            optional=f.get("optional", False),
            help=f.get("help", ""),
        )
        for f in data["fields"]
    ]

    build = PageBuildConfig(
        newPageBefore=data["build"].get("newPageBefore", True),
        headingStyle=data["build"].get("headingStyle", "normal"),
        generated=data["build"].get("generated", False),
        spoken=data["build"].get("spoken", False),
    )

    variants: dict[str, PageTypeVariant] = {}
    for fmt, variantData in data.get("variants", {}).items():
        variantBuild = PageBuildConfig(
            newPageBefore=variantData.get("build", {}).get("newPageBefore", True),
            headingStyle=variantData.get("build", {}).get("headingStyle", "normal"),
            generated=variantData.get("build", {}).get("generated", False),
            spoken=variantData.get("build", {}).get("spoken", False),
        )
        variantFields = [
            PageField(
                key=f["key"],
                label=f["label"],
                type=f["type"],
                from_=f.get("from", ""),
                optional=f.get("optional", False),
                help=f.get("help", ""),
            )
            for f in variantData.get("fields", [])
        ] if "fields" in variantData else []

        variants[fmt] = PageTypeVariant(
            enabled=variantData.get("enabled", True),
            spoken=variantData.get("spoken", False),
            fields=variantFields,
            template=variantData.get("template", ""),
            build=variantBuild,
            requiredFor=variantData.get("requiredFor", []),
        )

    return PageType(
        id=data["id"],
        label=data["label"],
        matter=data["matter"],
        order=data["order"],
        fields=fields,
        template=data["template"],
        build=build,
        requiredFor=data.get("requiredFor", []),
        variants=variants,
    )


class PageManager:
    """Manages page types and project pages."""

    def __init__(self, projectPath: Path) -> None:
        self._projectPath = projectPath
        self._pageTypes = loadPageTypes(Path(__file__).parent / "pagetypes")
        self._pages = self._loadPages()

    def _loadPages(self) -> dict[str, dict[str, Any]]:
        """Load pages from umbra/pages.json."""
        pages_path = pagesFile(self._projectPath)
        if not pages_path.is_file():
            return {}
        try:
            data = readJson(pages_path)
            if isinstance(data, dict):
                return data.get("pages", {})
        except Exception:
            logger.exception("Failed to load pages from %s", pages_path)
        return {}

    def _savePages(self) -> None:
        """Save pages to umbra/pages.json."""
        path = pagesFile(self._projectPath)
        path.parent.mkdir(parents=True, exist_ok=True)
        writeJson(path, {"pages": self._pages})

    def getPageTypes(self) -> dict[str, PageType]:
        """Get all available page types."""
        return dict(self._pageTypes)

    def getPageType(self, pageTypeId: str) -> PageType | None:
        """Get a page type by ID."""
        return self._pageTypes.get(pageTypeId)

    def getPagesByMatter(self, matter: str) -> list[dict[str, Any]]:
        """Get all pages of a specific matter, sorted by order."""
        pages = []
        for pageData in self._pages.values():
            if pageData.get("matter") == matter:
                pages.append(pageData)
        pages.sort(key=lambda p: p.get("order", 0))
        return pages

    def getAllPages(self) -> list[dict[str, Any]]:
        """Get all pages sorted by matter and order."""
        pages = list(self._pages.values())
        pages.sort(key=lambda p: (0 if p.get("matter") == "front" else 1, p.get("order", 0)))
        return pages

    def createPage(self, pageTypeId: str, handle: str, matter: str, order: int) -> dict[str, Any]:
        """Create a new page from a page type."""
        pageType = self.getPageType(pageTypeId)
        if not pageType:
            raise ValueError(f"Unknown page type: {pageTypeId}")

        pageData = {
            "handle": handle,
            "pageType": pageTypeId,
            "matter": matter,
            "order": pageType.order,
            "fields": {},
            "content": "",
        }
        self._pages[handle] = pageData
        self._savePages()
        return pageData

    def updatePage(self, handle: str, fields: dict[str, str] | None = None, content: str | None = None) -> bool:
        """Update a page's fields and/or content."""
        if handle not in self._pages:
            return False
        page = self._pages[handle]
        if fields is not None:
            page["fields"] = fields
        if content is not None:
            page["content"] = content
        self._savePages()
        return True

    def deletePage(self, handle: str) -> bool:
        """Delete a page."""
        if handle in self._pages:
            del self._pages[handle]
            self._savePages()
            return True
        return False

    def getPage(self, handle: str) -> dict[str, Any] | None:
        """Get a page by handle."""
        return self._pages.get(handle)

    def renderPage(self, handle: str, format_: str, metadata: Metadata | dict[str, Any], edition: str | None = None) -> str:
        """Render a page for a specific format."""
        page = self._pages.get(handle)
        if not page:
            return ""

        pageType = self._pageTypes.get(page.get("pageType", ""))
        if not pageType:
            return page.get("content", "")

        # Check if page is enabled for this format
        if not pageType.isEnabledForFormat(format_):
            return ""

        # Get effective template and fields for format
        template = pageType.getEffectiveTemplate(format_)
        pageType.getEffectiveFields(format_)

        # Build context for template rendering
        context = self._buildTemplateContext(page, pageType, format_, metadata)

        # Simple template rendering (Jinja2-like)
        return self._renderTemplate(template, context)

    def _buildTemplateContext(
        self, page: dict[str, Any], pageType: PageType, format_: str, metadata: Metadata | dict[str, Any]
    ) -> dict[str, Any]:
        """Build context for template rendering."""
        from umbraedit.umbra.metadata import formatValuesForBuild, Metadata

        # Convert dict to Metadata if needed
        if isinstance(metadata, dict):
            metadata = Metadata.fromDict(metadata)

        context = {}

        # Add format-specific values
        fmtValues = formatValuesForBuild(metadata, format_, None)
        context["format"] = {"name": format_, **metadata.formats.get(format_, {})}
        context.update(fmtValues)

        # Add page-specific fields
        for fieldName, fieldValue in page.get("fields", {}).items():
            context[fieldName] = fieldValue

        return context

    def _renderTemplate(self, template: str, context: dict[str, Any]) -> str:
        """Simple template rendering (Jinja2-like syntax)."""
        # This is a simplified implementation
        # In production, would use Jinja2 or similar
        import re

        # Handle {{variable}} substitutions
        def replace_var(match: re.Match) -> str:
            var_path = match.group(1)
            parts = var_path.split(".")
            obj: Any = context
            for part in parts:
                if isinstance(obj, dict) and part in obj:
                    obj = obj[part]
                else:
                    return match.group(0)
            return str(obj) if obj is not None else ""

        return re.sub(r"\{\{(\w+(?:\.\w+)*)\}\}", replace_var, template)

        # Handle {% if condition %}...{% endif %}
        # Simplified - just handle basic if/endif
        # Full implementation would use Jinja2



def createDefaultPages(projectPath: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Create the default page set for a new project."""
    manager = PageManager(projectPath)

    # Default page types in Chicago order
    defaultPages = [
        ("halfTitle", "front"),
        ("titlePage", "front"),
        ("copyrightPage", "front"),
        ("dedication", "front"),
        ("epigraph", "front"),
        ("tableOfContents", "front"),
        ("foreword", "front"),
        ("acknowledgments", "back"),
        ("aboutAuthor", "back"),
        ("alsoBy", "back"),
    ]

    pageTypes = loadPageTypes(Path(__file__).parent / "pagetypes")

    for pageTypeId, matter in defaultPages:
        pageType = pageTypes.get(pageTypeId)
        if not pageType:
            continue


        # Create page with default field values
        fields = {}
        for field in pageType.getEffectiveFields("print"):
            if field.from_:
                # Resolve from metadata
                value = _resolveFrom(metadata, field.from_)
                if value:
                    fields[field.key] = value

        pageData = {
            "handle": f"page-{pageTypeId}",
            "pageType": pageType.id,
            "matter": matter,
            "order": pageType.order,
            "fields": fields,
            "content": "",
        }
        manager._pages[f"page-{pageTypeId}"] = pageData

    manager._savePages()
    return {"handles": [f"page-{pt}" for pt, _ in defaultPages if pt in pageTypes]}
