"""
UmbraEdit - Publish Gate Rules
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for publish package (P32): metadata required, ISBN invalid/duplicate,
cover missing/invalid/size mismatch/edition missing, page variant missing,
edition metadata pending, pronunciation missing, voice matrix missing,
edition stale, review open, sync conflict open, book audio incomplete,
retailer field missing, retailer limit.
"""  # noqa

from __future__ import annotations

import json
import logging
import re

from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.covers import DEFAULT_REQUIREMENTS, loadCovers
from umbraedit.umbra.edition import EditionInfo, loadEdition
from umbraedit.umbra.gates import (
    OP_PUBLISH_HANDOFF,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.metadata import loadMetadata
from umbraedit.umbra.pages import PageManager
from umbraedit.umbra.sheet import SheetManager

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Rule IDs
RULE_PUBLISH_METADATA_REQUIRED = "publishMetadataRequired"
RULE_PUBLISH_ISBN_INVALID = "publishIsbnInvalid"
RULE_PUBLISH_ISBN_DUPLICATE = "publishIsbnDuplicate"
RULE_PUBLISH_COVER_MISSING = "publishCoverMissing"
RULE_PUBLISH_COVER_INVALID = "publishCoverInvalid"
RULE_PUBLISH_COVER_SIZE_MISMATCH = "publishCoverSizeMismatch"
RULE_PUBLISH_COVER_EDITION_MISSING = "publishCoverEditionMissing"
RULE_PUBLISH_PAGE_VARIANT_MISSING = "publishPageVariantMissing"
RULE_PUBLISH_EDITION_METADATA_PENDING = "publishEditionMetadataPending"
RULE_PUBLISH_PRONUNCIATION_MISSING = "publishPronunciationMissing"
RULE_PUBLISH_VOICE_MATRIX_MISSING = "publishVoiceMatrixMissing"
RULE_PUBLISH_EDITION_STALE = "publishEditionStale"
RULE_PUBLISH_REVIEW_OPEN = "publishReviewOpen"
RULE_PUBLISH_SYNC_CONFLICT_OPEN = "publishSyncConflictOpen"
RULE_PUBLISH_BOOK_AUDIO_INCOMPLETE = "publishBookAudioIncomplete"
RULE_PUBLISH_RETAILER_FIELD_MISSING = "publishRetailerFieldMissing"
RULE_PUBLISH_RETAILER_LIMIT = "publishRetailerLimit"

# ISBN-13 regex
ISBN13_RE = re.compile(r"^\d{13}$")
ISBN10_RE = re.compile(r"^\d{9}[\dX]$")


def _load_retailers() -> list[dict[str, Any]]:
    """Load retailer matrix from bundled JSON file."""
    retailers_path = Path(__file__).parent / "retailers.json"
    if retailers_path.is_file():
        try:
            with open(retailers_path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("retailers", [])
        except Exception as exc:
            logger.warning("Failed to load retailers.json: %s", exc)
    return []


def _get_selected_retailer(scope: Any) -> str | None:
    """Get the selected retailer ID from scope options."""
    if scope.options and "retailer" in scope.options:
        return scope.options["retailer"]
    return None


def _get_edition_metadata(scope: Any) -> EditionInfo | None:
    """Load edition metadata from project."""
    project = scope.project
    if not project:
        return None
    edition_id = scope.edition or scope.options.get("edition", "") if scope.options else ""
    if not edition_id:
        return None
    project_path = Path(project.storage.storagePath)
    edition_path = project_path.parent / f"{project_path.name}-ed-{edition_id}"
    if not edition_path.exists():
        return None

    try:
        return loadEdition(edition_path)
    except Exception:
        return None


def _get_source_metadata(scope: Any) -> Any | None:
    """Load source project metadata."""
    project = scope.project
    if not project:
        return None
    try:
        return loadMetadata(project.storage.storagePath)
    except Exception:
        return None


def _get_edition_path(scope: Any) -> Path | None:
    """Get edition project path."""
    project = scope.project
    if not project:
        return None
    edition_id = scope.edition or scope.options.get("edition", "") if scope.options else ""
    if not edition_id:
        return None
    project_path = Path(project.storage.storagePath)
    edition_path = project_path.parent / f"{project_path.name}-ed-{edition_id}"
    if not edition_path.exists():
        return None
    return edition_path


def _validate_isbn(isbn: str) -> bool:
    """Validate ISBN-10 or ISBN-13 format."""
    isbn_clean = isbn.replace("-", "").replace(" ", "")
    return bool(ISBN13_RE.match(isbn_clean) or ISBN10_RE.match(isbn_clean))


def _check_metadata_required(scope: Any) -> Iterable[Finding]:
    """Block: required metadata fields are missing."""
    project = scope.project
    if not project:
        return
    metadata = loadMetadata(project.storage.storagePath)
    if not metadata:
        return

    required = ["book.title", "book.author"]
    for field in required:
        parts = field.split(".")
        if len(parts) == 2:
            section, key = parts
            value = getattr(metadata, section, {}).get(key, "")
            if not value:
                yield Finding(
                    ruleId=RULE_PUBLISH_METADATA_REQUIRED,
                    severity="block",
                    message=f"Required metadata field '{field}' is empty",
                    fix=f"Set '{field}' in Project Settings > Metadata",
                    handle=None,
                    detail={"field": field},
                )


def _check_isbn_invalid(scope: Any) -> Iterable[Finding]:
    """Block: ISBN format is invalid."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    # Check ISBNs in edition metadata
    isbn_fields = ["isbn.paperback", "isbn.hardback", "isbn.ebook", "isbn.audiobook"]
    for field in isbn_fields:
        # Navigate to the ISBN field in edition source
        parts = field.split(".")
        if len(parts) == 2:
            section, key = parts
            source_section = edition.source.get(section)
            if isinstance(source_section, dict):
                value = source_section.get(key, "")
            else:
                value = ""
            if value and not _validate_isbn(value):
                yield Finding(
                    ruleId=RULE_PUBLISH_ISBN_INVALID,
                    severity="block",
                    message=f"ISBN '{value}' for {field} is invalid (must be ISBN-10 or ISBN-13)",
                    fix="Correct the ISBN in Edition settings",
                    handle=None,
                    detail={"field": field, "value": value},
                )


def _check_isbn_duplicate(scope: Any) -> Iterable[Finding]:
    """Block: duplicate ISBN across formats."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    isbns: dict[str, list[str]] = {}
    isbn_fields = ["isbn.paperback", "isbn.hardback", "isbn.ebook", "isbn.audiobook"]
    for field in isbn_fields:
        parts = field.split(".")
        if len(parts) == 2:
            section, key = parts
            source_section = edition.source.get(section)
            if isinstance(source_section, dict):
                value = source_section.get(key, "")
            else:
                value = ""
            if value:
                isbn_clean = value.replace("-", "").replace(" ", "")
                isbns.setdefault(isbn_clean, []).append(field)

    for isbn, fields in isbns.items():
        if len(fields) > 1:
            yield Finding(
                ruleId=RULE_PUBLISH_ISBN_DUPLICATE,
                severity="block",
                message=f"ISBN {isbn} used for multiple formats: {', '.join(fields)}",
                fix="Assign unique ISBNs to each format",
                handle=None,
                detail={"isbn": isbn, "fields": fields},
            )


def _check_cover_missing(scope: Any) -> Iterable[Finding]:
    """Block: cover is missing for a required format."""
    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    covers = loadCovers(edition_path)
    covers = covers

    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    formats = source_meta.formats.get("formats", {}) if source_meta.formats else {}
    for fmt in formats:
        if (fmt in DEFAULT_REQUIREMENTS
                and DEFAULT_REQUIREMENTS[fmt].get("required", False)
                and (fmt not in covers or not covers[fmt].get("file"))):
                yield Finding(
                    ruleId=RULE_PUBLISH_COVER_MISSING,
                    severity="block",
                    message=f"Cover is required for format '{fmt}' but is missing",
                    fix=f"Add a cover for '{fmt}' in Cover Manager",
                    handle=None,
                    detail={"format": fmt},
                )


def _check_cover_invalid(scope: Any) -> Iterable[Finding]:
    """Block: cover file is invalid (corrupt, wrong type)."""
    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    covers = loadCovers(edition_path)
    covers = covers

    for fmt, cover in covers.items():
        if cover.get("file"):
            file_path = edition_path / cover["file"]
            if not file_path.exists():
                yield Finding(
                    ruleId=RULE_PUBLISH_COVER_INVALID,
                    severity="block",
                    message=f"Cover file for '{fmt}' does not exist: {cover['file']}",
                    fix=f"Re-add the cover file for '{fmt}'",
                    handle=None,
                    detail={"format": fmt, "file": cover["file"]},
                )
            else:
                # Check file size
                if file_path.stat().st_size == 0:
                    yield Finding(
                        ruleId=RULE_PUBLISH_COVER_INVALID,
                        severity="block",
                        message=f"Cover file for '{fmt}' is empty",
                        fix=f"Re-add the cover file for '{fmt}'",
                        handle=None,
                        detail={"format": fmt, "file": cover["file"]},
                    )


def _check_cover_size_mismatch(scope: Any) -> Iterable[Finding]:
    """Block: cover dimensions don't match format requirements."""
    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    covers = loadCovers(edition_path)
    covers = covers

    for fmt, cover in covers.items():
        if fmt in DEFAULT_REQUIREMENTS and cover.get("file"):
            req = DEFAULT_REQUIREMENTS[fmt]
            # Detailed dimension check would require PIL
            # For now, check file size limit
            if "maxBytes" in req:
                file_path = edition_path / cover["file"]
                if file_path.exists() and file_path.stat().st_size > req["maxBytes"]:
                    yield Finding(
                        ruleId=RULE_PUBLISH_COVER_SIZE_MISMATCH,
                        severity="block",
                        message=f"Cover for '{fmt}' exceeds maximum file size ({req['maxBytes']} bytes)",
                        fix=f"Reduce cover file size for '{fmt}'",
                        handle=None,
                        detail={"format": fmt, "maxBytes": req["maxBytes"]},
                    )


def _check_cover_edition_missing(scope: Any) -> Iterable[Finding]:
    """Block: edition-specific cover is missing when required."""
    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    # Check if edition has cover requirements that differ from main
    covers = loadCovers(edition_path)
    covers = covers

    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    formats = source_meta.formats.get("formats", {}) if source_meta.formats else {}
    for fmt in formats:
        if fmt in DEFAULT_REQUIREMENTS and DEFAULT_REQUIREMENTS[fmt].get("required", False):
            # Check if there's an edition-specific cover requirement
            edition_cover = covers.get(fmt)
            if not edition_cover or not edition_cover.get("file"):
                # Check main project for fallback
                edition_name = edition_path.name
                base_name = edition_name.replace(f"-ed-{edition_name.split('-ed-')[-1]}", "")
                main_path = edition_path.parent / base_name
                main_covers = loadCovers(main_path)
                if fmt not in main_covers or not main_covers[fmt].get("file"):
                    yield Finding(
                        ruleId=RULE_PUBLISH_COVER_EDITION_MISSING,
                        severity="block",
                        message=f"Edition cover for '{fmt}' is missing and no main project cover exists",
                        fix=f"Add a cover for '{fmt}' in this edition or the main project",
                        handle=None,
                        detail={"format": fmt, "edition": edition_path.name},
                    )


def _check_page_variant_missing(scope: Any) -> Iterable[Finding]:
    """Block: required page variant (spoken) is missing for audio."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    # Check if audiobook format is enabled
    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    formats = source_meta.formats.get("formats", {}) if source_meta.formats else {}
    if "audiobook" in formats:
        # Check for spoken variant pages
        edition_path = _get_edition_path(scope)
        if not edition_path:
            return

        page_manager = PageManager(edition_path)
        all_pages = page_manager.getAllPages()
        spoken_found = False
        for page in all_pages:
            if page.get("variant") == "spoken" and page.get("matter") in ("front", "back"):
                # Check if it's a front/end matter kind
                page_type = page.get("pageType", "")
                if page_type in ("frontMatter", "endMatter", "copyright", "dedication"):
                    spoken_found = True
                    break

        if not spoken_found:
            yield Finding(
                ruleId=RULE_PUBLISH_PAGE_VARIANT_MISSING,
                severity="block",
                message="Audiobook format requires spoken page variants for front/end matter",
                fix="Create page documents with variant 'spoken' for front and end matter",
                handle=None,
                detail={},
            )


def _check_edition_metadata_pending(scope: Any) -> Iterable[Finding]:
    """Block: edition has pending metadata translations."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    if edition.pending:
        yield Finding(
            ruleId=RULE_PUBLISH_EDITION_METADATA_PENDING,
            severity="block",
            message=f"Edition has {len(edition.pending)} pending metadata translation(s)",
            fix="Complete all metadata translations before publishing",
            handle=None,
            detail={"pending": edition.pending},
        )


def _check_pronunciation_missing(scope: Any) -> Iterable[Finding]:
    """Block: pronunciation entries missing for audio."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    formats = source_meta.formats.get("formats", {}) if source_meta.formats else {}
    if "audiobook" not in formats:
        return

    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    sheet = SheetManager(edition_path / "umbra")
    sheet.buildFromProject(str(edition_path))

    # Check characters that need pronunciation
    lang = edition.language or "en"
    for entity in sheet.iterEntities():
        if entity.kind == "character":
            pron_status = entity.attrs.get(f"pron_status_{lang}", "todo")
            if pron_status != "done":
                yield Finding(
                    ruleId=RULE_PUBLISH_PRONUNCIATION_MISSING,
                    severity="block",
                    message=f"Character '{entity.tag}' missing pronunciation for language '{lang}'",
                    fix=f"Set pronunciation for '{entity.tag}' in Entity Editor",
                    handle=entity.handle,
                    detail={"entity": entity.tag, "language": lang},
                )


def _check_voice_matrix_missing(scope: Any) -> Iterable[Finding]:
    """Block: voice matrix missing for speaker in audio."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    formats = source_meta.formats.get("formats", {}) if source_meta.formats else {}
    if "audiobook" not in formats:
        return

    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    sheet = SheetManager(edition_path / "umbra")
    sheet.buildFromProject(str(edition_path))

    # Check characters that have voice_matrix
    for entity in sheet.iterEntities():
        if entity.kind == "character":
            voice_matrix = entity.attrs.get("voice_matrix", "")
            if voice_matrix:
                # Check if voice matrix file exists
                from umbraedit.umbra.voicestore import VoiceStore
                voice_store = VoiceStore(edition_path)
                if not voice_store.getVoiceMatrix(voice_matrix):
                    yield Finding(
                        ruleId=RULE_PUBLISH_VOICE_MATRIX_MISSING,
                        severity="block",
                        message=f"Voice matrix '{voice_matrix}' for character '{entity.tag}' not found",
                        fix=f"Import or create voice matrix '{voice_matrix}' in Voice Manager",
                        handle=entity.handle,
                        detail={"entity": entity.tag, "voice_matrix": voice_matrix},
                    )


def _check_edition_stale(scope: Any) -> Iterable[Finding]:
    """Block: edition documents are stale (source changed)."""
    edition = _get_edition_metadata(scope)
    if not edition:
        return

    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    source_path = edition_path.parent / edition.source.get("path", "")
    if not source_path.exists():
        return

    stale_count = 0
    for doc in edition.docs.values():
        if doc.status == "stale":
            stale_count += 1

    if stale_count > 0:
        yield Finding(
            ruleId=RULE_PUBLISH_EDITION_STALE,
            severity="block",
            message=f"Edition has {stale_count} stale document(s) (source changed since translation)",
            fix="Re-translate stale documents or mark as up to date",
            handle=None,
            detail={"staleCount": stale_count},
        )


def _check_review_open(scope: Any) -> Iterable[Finding]:
    """Block: open review comments exist (if review feature enabled)."""
    project = scope.project
    if not project:
        return

    # Check if review comments exist
    try:
        from umbraedit.umbra.review import loadReviewComments
    except ImportError:
        return  # Review feature not available

    try:
        comments = loadReviewComments(project.storage.storagePath)
        open_count = sum(1 for c in comments if not c.get("resolved", False))
        if open_count > 0:
            yield Finding(
                ruleId=RULE_PUBLISH_REVIEW_OPEN,
                severity="block",
                message=f"{open_count} open review comment(s) found",
                fix="Resolve or dismiss all review comments before publishing",
                handle=None,
                detail={"openCount": open_count},
            )
    except Exception:
        pass  # Review feature may not be available


def _check_sync_conflict_open(scope: Any) -> Iterable[Finding]:
    """Block: open sync conflicts exist."""
    project = scope.project
    if not project:
        return

    from umbraedit.umbra.sync.conflicts import ConflictsStore
    store = ConflictsStore(project.storage.storagePath)
    count = store.open_count()
    if count > 0:
        yield Finding(
            ruleId=RULE_PUBLISH_SYNC_CONFLICT_OPEN,
            severity="block",
            message=f"{count} open sync conflict(s) - resolve before publishing",
            fix="Open the Conflicts panel and resolve all open conflicts",
            handle=None,
            detail={"openConflicts": count},
        )


def _check_book_audio_incomplete(scope: Any) -> Iterable[Finding]:
    """Block: audio package incomplete for audiobook format."""
    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    formats = source_meta.formats.get("formats", {}) if source_meta.formats else {}
    if "audiobook" not in formats:
        return

    edition = _get_edition_metadata(scope)
    if not edition:
        return

    edition_path = _get_edition_path(scope)
    if not edition_path:
        return

    audio_dir = edition_path / "audio" / edition.editionId
    if not audio_dir.exists():
        yield Finding(
            ruleId=RULE_PUBLISH_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message="Audio package not built for this edition",
            fix="Build audio package using 'audio.book' gate",
            handle=None,
            detail={},
        )
        return

    manifest_path = audio_dir / "manifest.json"
    if not manifest_path.exists():
        yield Finding(
            ruleId=RULE_PUBLISH_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message="Audio package manifest not found",
            fix="Rebuild audio package",
            handle=None,
            detail={},
        )
        return

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        yield Finding(
            ruleId=RULE_PUBLISH_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message="Audio package manifest is corrupt",
            fix="Rebuild audio package",
            handle=None,
            detail={},
        )
        return

    incomplete = [
        chapter.get("handle", "")
        for chapter in manifest.get("chapters", [])
        if chapter.get("status") != "ready"
    ]

    if incomplete:
        yield Finding(
            ruleId=RULE_PUBLISH_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message=f"Audio chapters not ready: {', '.join(incomplete)}",
            fix="Build remaining chapters with 'audio.chapter'",
            handle=None,
            detail={"incompleteChapters": incomplete},
        )


def _check_retailer_field_missing(scope: Any) -> Iterable[Finding]:
    """Block: required metadata fields missing for selected retailer."""
    retailer_id = _get_selected_retailer(scope)
    if not retailer_id:
        return  # No retailer selected, skip

    retailers = _load_retailers()
    retailer = next((r for r in retailers if r["id"] == retailer_id), None)
    if not retailer:
        return

    edition = _get_edition_metadata(scope)
    if not edition:
        return

    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    missing = []
    for field_path in retailer.get("requires", []):
        # Parse field path (e.g., "book.title", "edition.isbn.paperback", "edition.trim")
        parts = field_path.split(".")
        if len(parts) == 2:
            section, key = parts
            if section == "book":
                value = source_meta.book.get(key, "")
            elif section == "edition":
                value = edition.source.get("edition", {}).get(key, "")
            else:
                value = ""
            if not value:
                missing.append(field_path)
        elif len(parts) == 3 and parts[0] == "edition" and parts[1] == "isbn":
            # edition.isbn.paperback
            isbn_type = parts[2]
            value = edition.source.get("edition", {}).get("isbn", {}).get(isbn_type, "")
            if not value:
                missing.append(field_path)

    if missing:
        yield Finding(
            ruleId=RULE_PUBLISH_RETAILER_FIELD_MISSING,
            severity="block",
            message=f"Retailer '{retailer['name']}' requires missing fields: {', '.join(missing)}",
            fix="Fill in required metadata in Project Settings and Edition settings",
            handle=None,
            detail={"retailer": retailer_id, "missingFields": missing},
        )


def _check_retailer_limit(scope: Any) -> Iterable[Finding]:
    """Block: metadata exceeds retailer limits."""
    retailer_id = _get_selected_retailer(scope)
    if not retailer_id:
        return

    retailers = _load_retailers()
    retailer = next((r for r in retailers if r["id"] == retailer_id), None)
    if not retailer:
        return

    source_meta = _get_source_metadata(scope)
    if not source_meta:
        return

    limits = retailer.get("limits", {})
    for field, limit in limits.items():
        if field == "book.description":
            value = source_meta.book.get("description", "")
            if len(value) > limit:
                msg = (f"Book description exceeds {limit} character limit "
                       f"for retailer '{retailer['name']}' ({len(value)} chars)")
                yield Finding(
                    ruleId=RULE_PUBLISH_RETAILER_LIMIT,
                    severity="block",
                    message=msg,
                    fix=f"Shorten book description to {limit} characters or fewer",
                    handle=None,
                    detail={"field": field, "limit": limit, "actual": len(value), "retailer": retailer_id},
                )
        elif field == "book.keywords":
            value = source_meta.book.get("keywords", "")
            # Keywords are comma-separated
            count = len([k.strip() for k in value.split(",") if k.strip()])
            if count > limit:
                msg = (f"Book keywords count ({count}) exceeds limit ({limit}) "
                       f"for retailer '{retailer['name']}'")
                yield Finding(
                    ruleId=RULE_PUBLISH_RETAILER_LIMIT,
                    severity="block",
                    message=msg,
                    fix=f"Reduce keywords to {limit} or fewer",
                    handle=None,
                    detail={"field": field, "limit": limit, "actual": count, "retailer": retailer_id},
                )
        elif field == "book.title":
            value = source_meta.book.get("title", "")
            if len(value) > limit:
                msg = (f"Book title exceeds {limit} character limit "
                       f"for retailer '{retailer['name']}'")
                yield Finding(
                    ruleId=RULE_PUBLISH_RETAILER_LIMIT,
                    severity="block",
                    message=msg,
                    fix=f"Shorten book title to {limit} characters or fewer",
                    handle=None,
                    detail={"field": field, "limit": limit, "actual": len(value), "retailer": retailer_id},
                )
        elif field == "book.subtitle":
            value = source_meta.book.get("subtitle", "")
            if len(value) > limit:
                msg = (f"Book subtitle exceeds {limit} character limit "
                       f"for retailer '{retailer['name']}'")
                yield Finding(
                    ruleId=RULE_PUBLISH_RETAILER_LIMIT,
                    severity="block",
                    message=msg,
                    fix=f"Shorten book subtitle to {limit} characters or fewer",
                    handle=None,
                    detail={"field": field, "limit": limit, "actual": len(value), "retailer": retailer_id},
                )


# Register gates for publish.package
registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_METADATA_REQUIRED,
        title="Metadata Required",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_metadata_required,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_ISBN_INVALID,
        title="ISBN Invalid",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_isbn_invalid,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_ISBN_DUPLICATE,
        title="ISBN Duplicate",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_isbn_duplicate,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_COVER_MISSING,
        title="Cover Missing",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_cover_missing,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_COVER_INVALID,
        title="Cover Invalid",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_cover_invalid,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_COVER_SIZE_MISMATCH,
        title="Cover Size Mismatch",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_cover_size_mismatch,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_COVER_EDITION_MISSING,
        title="Cover Edition Missing",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_cover_edition_missing,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_PAGE_VARIANT_MISSING,
        title="Page Variant Missing",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_page_variant_missing,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_EDITION_METADATA_PENDING,
        title="Edition Metadata Pending",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_edition_metadata_pending,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_PRONUNCIATION_MISSING,
        title="Pronunciation Missing",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_pronunciation_missing,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_VOICE_MATRIX_MISSING,
        title="Voice Matrix Missing",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_voice_matrix_missing,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_EDITION_STALE,
        title="Edition Stale",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_edition_stale,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_REVIEW_OPEN,
        title="Review Open",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_review_open,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_SYNC_CONFLICT_OPEN,
        title="Sync Conflict Open",
        operations=frozenset({OP_PUBLISH_PACKAGE, OP_PUBLISH_HANDOFF}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_sync_conflict_open,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_BOOK_AUDIO_INCOMPLETE,
        title="Book Audio Incomplete",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_book_audio_incomplete,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_RETAILER_FIELD_MISSING,
        title="Retailer Field Missing",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_retailer_field_missing,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_PUBLISH_RETAILER_LIMIT,
        title="Retailer Limit Exceeded",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_check_retailer_limit,
    )
)

