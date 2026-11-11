"""
UmbraEdit - Book Covers
=======================

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

import copy
import logging
import re

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from umbraedit.umbra.assets import AssetStore, _detectMime
from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.metadata import Metadata, loadMetadata
from umbraedit.umbra.paths import coversFile

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Default format requirements
DEFAULT_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "epub": {
        "required": True,
        "types": ["image/jpeg", "image/png"],
        "minLongSide": 2560,
        "minShortSide": 1600,
        "aspect": [1, 1.6],
        "aspectTolerance": 0.02,
        "maxBytes": 10485760,
    },
    "audiobook": {
        "required": True,
        "types": ["image/jpeg", "image/png"],
        "square": True,
        "minSide": 2400,
        "maxSide": 3200,
        "maxBytes": 10485760,
    },
    "paperback": {
        "required": True,
        "types": ["application/pdf", "image/jpeg", "image/png"],
        "minDpi": 300,
        "wraparound": True,
    },
    "hardback": {
        "required": True,
        "types": ["application/pdf", "image/jpeg", "image/png"],
        "minDpi": 300,
        "wraparound": True,
    },
}

# Paper thickness mapping (mm per page)
PAPER_THICKNESS: dict[str, float] = {
    "cream60": 0.0635,
    "white60": 0.0635,
    "cream80": 0.0847,
    "white80": 0.0847,
}

# Board thickness for hardback (mm)
BOARD_THICKNESS = 2.5

# Bleed default (mm)
BLEED_MM = 3.175

# Trim size parsing regex (e.g., "5.5x8.5", "6x9", "139.7x215.9mm")
TRIM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:mm|in)?\s*$", re.IGNORECASE)  # noqa: RUF001

# Note: The regex uses the multiplication sign (×) which is common in trim size notation.  # noqa: RUF003
# The '×' character is intentional and not the letter 'x'.  # noqa: RUF003

# Format keys in canonical order
FORMAT_ORDER = ["paperback", "hardback", "epub", "audiobook"]


@dataclass(frozen=True)
class CoverSlot:
    """A cover slot for a format."""

    assetId: str | None
    requirements: dict[str, Any]


@dataclass(frozen=True)
class Finding:
    """A validation finding."""

    ruleId: str
    severity: str  # "block" | "advisory"
    message: str
    fix: str
    detail: dict[str, Any] | None = None


def coversFilePath(projectPath: Path) -> Path:
    """Return the path to the covers.json file."""
    return coversFile(projectPath)


def loadCovers(projectPath: Path) -> dict[str, Any]:
    """Load covers from project's umbra/covers.json."""
    path = coversFilePath(projectPath)
    if not path.is_file():
        return {"v": SCHEMA_VERSION, "slots": {}, "requirements": copy.deepcopy(DEFAULT_REQUIREMENTS)}
    try:
        data = readJson(path)
        if not isinstance(data, dict):
            logger.warning("covers.json does not contain an object, resetting")
            return {"v": SCHEMA_VERSION, "slots": {}, "requirements": copy.deepcopy(DEFAULT_REQUIREMENTS)}
        # Ensure required keys exist
        data.setdefault("v", SCHEMA_VERSION)
        data.setdefault("slots", {})
        data.setdefault("requirements", copy.deepcopy(DEFAULT_REQUIREMENTS))
        return data
    except Exception:
        logger.exception("Failed to load covers from %s", path)
        return {"v": SCHEMA_VERSION, "slots": {}, "requirements": copy.deepcopy(DEFAULT_REQUIREMENTS)}


def saveCovers(projectPath: Path, covers: dict[str, Any]) -> None:
    """Save covers to project's umbra/covers.json atomically."""
    path = coversFilePath(projectPath)
    path.parent.mkdir(parents=True, exist_ok=True)
    writeJson(path, covers)


def _parseTrimSize(trim: str) -> tuple[float, float] | None:
    """Parse trim size string like '5.5x8.5' or '139.7x215.9mm'.

    Returns (width_mm, height_mm) or None if invalid.
    """
    match = TRIM_RE.match(trim.strip())
    if not match:
        return None
    w = float(match.group(1))
    h = float(match.group(2))
    # If no unit specified, assume inches and convert to mm
    if "mm" not in trim.lower():
        w *= 25.4
        h *= 25.4
    return (w, h)


def _getPaperThickness(paper: str | None) -> float:
    """Get paper thickness in mm per page."""
    if not paper:
        return PAPER_THICKNESS.get("cream60", 0.0635)
    return PAPER_THICKNESS.get(paper, 0.0635)


def _calculateWraparoundSize(metadata: Metadata, fmt: str) -> tuple[float, float] | None:
    """Calculate expected wraparound cover size in mm.

    Returns (width_mm, height_mm) or None if insufficient data.
    """
    fmt_meta = metadata.formats.get(fmt, {})
    trim = fmt_meta.get("trim")
    page_count = fmt_meta.get("pageCount")
    paper = fmt_meta.get("paper")

    if not trim or not page_count:
        return None

    trim_size = _parseTrimSize(trim)
    if not trim_size:
        return None

    trim_w, trim_h = trim_size
    paper_thickness = _getPaperThickness(paper)

    # Spine width = pageCount * paperThickness
    spine = page_count * paper_thickness

    # Add board thickness for hardback
    if fmt == "hardback":
        spine += 2 * BOARD_THICKNESS

    # Wraparound width = 2 * trimWidth + spine + 2 * bleed
    width = 2 * trim_w + spine + 2 * BLEED_MM
    # Height = trimHeight + 2 * bleed
    height = trim_h + 2 * BLEED_MM

    return (width, height)


def _checkPdfMediaBox(file_path: Path, expected_w: float, expected_h: float, tolerance_mm: float = 1.0) -> bool:
    """Check if PDF MediaBox matches expected size within tolerance."""
    try:
        import fitz  # PyMuPDF  # type: ignore[import-not-found]

        doc = fitz.open(str(file_path))
        if doc.page_count > 0:
            page = doc[0]
            mediabox = page.mediabox
            actual_w = mediabox.width * 25.4 / 72  # points to mm
            actual_h = mediabox.height * 25.4 / 72
            doc.close()
            return abs(actual_w - expected_w) <= tolerance_mm and abs(actual_h - expected_h) <= tolerance_mm
    except Exception:
        pass
    return False


class CoverStore:
    """Manages book covers for all formats."""

    def __init__(self, projectPath: Path) -> None:
        self._projectPath = projectPath
        self._assetStore = AssetStore(projectPath)
        self._covers = loadCovers(projectPath)

    @property
    def covers(self) -> dict[str, Any]:
        return dict(self._covers)

    def getEnabledFormats(self) -> list[str]:
        """Return list of enabled formats from metadata."""
        metadata = loadMetadata(self._projectPath)
        return [fmt for fmt in FORMAT_ORDER if metadata.formats.get(fmt, {}).get("enabled", False)]

    def getCover(self, fmt: str) -> dict[str, Any] | None:
        """Get cover info for a format.

        Returns dict with assetId and asset details, or None if no cover set.
        """
        slots = self._covers.get("slots", {})
        asset_id = slots.get(fmt, {}).get("assetId")
        if not asset_id:
            return None
        asset = self._assetStore.getAsset(asset_id)
        if not asset:
            return None
        return {"assetId": asset_id, **asset}

    def setCover(self, fmt: str, path: Path | str) -> str:
        """Set cover for a format.

        Adds the file as an asset with role 'cover', validates it,
        and stores the assetId in the covers slot table.
        Returns the assetId.
        """
        file_path = Path(path) if isinstance(path, str) else path

        # Validate format
        if fmt not in FORMAT_ORDER:
            raise ValueError(f"Unknown format: {fmt}")

        # Read file and detect mime
        if not file_path.is_file():
            raise FileNotFoundError(f"Cover file not found: {file_path}")

        # Validate using asset store's type detection
        with open(file_path, "rb") as f:
            header = f.read(1024)
        mime = _detectMime(header, file_path.name)

        # Check against format requirements
        reqs = self._covers.get("requirements", {}).get(fmt, DEFAULT_REQUIREMENTS[fmt])
        allowed_types = reqs.get("types", [])
        if allowed_types and mime not in allowed_types:
            raise ValueError(f"MIME type '{mime}' not allowed for format '{fmt}'. Allowed: {allowed_types}")

        # Check file size
        max_bytes = reqs.get("maxBytes", 10485760)
        if file_path.stat().st_size > max_bytes:
            raise ValueError(f"File size exceeds maximum {max_bytes} bytes for format '{fmt}'")

        # Validate image dimensions
        dims = {}
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                dims = {"width": img.width, "height": img.height}
        except Exception:
            pass

        # Add as asset with role "cover"
        asset_id = self._assetStore.addAsset(
            file_path,
            role="cover",
            attrs={"format": fmt, "edition": "main", **dims},
            name=file_path.name,
        )

        # Update covers slot table
        self._covers.setdefault("slots", {})[fmt] = {"assetId": asset_id}
        saveCovers(self._projectPath, self._covers)

        logger.info("Set cover for format %s: asset %s", fmt, asset_id)
        return asset_id

    def clearCover(self, fmt: str) -> bool:
        """Clear cover for a format. Returns True if a cover was removed."""
        slots = self._covers.get("slots", {})
        if fmt in slots:
            del slots[fmt]
            saveCovers(self._projectPath, self._covers)
            return True
        return False

    def getRequirements(self, fmt: str) -> dict[str, Any]:
        """Get the requirements for a format."""
        return self._covers.get("requirements", {}).get(fmt, DEFAULT_REQUIREMENTS[fmt])

    def validateCover(self, fmt: str) -> list[Finding]:
        """Validate cover for a format.

        Returns list of findings (empty if valid).
        """
        findings: list[Finding] = []

        # Check if format is enabled
        metadata = loadMetadata(self._projectPath)
        fmt_meta = metadata.formats.get(fmt, {})
        if not fmt_meta.get("enabled", False):
            return findings

        reqs = self._covers.get("requirements", {}).get(fmt, DEFAULT_REQUIREMENTS[fmt])
        slots = self._covers.get("slots", {})
        slot = slots.get(fmt, {})
        asset_id = slot.get("assetId")

        # Check if cover exists
        if not asset_id:
            if reqs.get("required", False):
                findings.append(
                    Finding(
                        ruleId="coverMissing",
                        severity="block",
                        message=f"Cover missing for format '{fmt}'",
                        fix=f"Add a cover image for format '{fmt}' in the Book tab",
                        detail={"format": fmt},
                    )
                )
            return findings

        # Get asset
        asset = self._assetStore.getAsset(asset_id)
        if not asset:
            findings.append(
                Finding(
                    ruleId="coverMissing",
                    severity="block",
                    message=f"Cover asset not found for format '{fmt}'",
                    fix=f"Re-add the cover image for format '{fmt}'",
                    detail={"format": fmt, "assetId": asset_id},
                )
            )
            return findings

        # Check MIME type
        mime = asset.get("type", "")
        allowed_types = reqs.get("types", [])
        if allowed_types and mime not in allowed_types:
            findings.append(
                Finding(
                    ruleId="coverInvalid",
                    severity="block",
                    message=f"Cover for format '{fmt}' has invalid type '{mime}'",
                    fix=f"Use an allowed type: {', '.join(allowed_types)}",
                    detail={"format": fmt, "mime": mime, "allowed": allowed_types},
                )
            )

        # Check file size
        max_bytes = reqs.get("maxBytes", 10485760)
        size = asset.get("size", 0)
        if size > max_bytes:
            findings.append(
                Finding(
                    ruleId="coverInvalid",
                    severity="block",
                    message=f"Cover for format '{fmt}' exceeds maximum size ({max_bytes} bytes)",
                    fix=f"Use a smaller file (max {max_bytes} bytes)",
                    detail={"format": fmt, "size": size, "maxBytes": max_bytes},
                )
            )

        # Check dimensions for image formats
        attrs = asset.get("attrs", {})
        width = attrs.get("width")
        height = attrs.get("height")

        if width is not None and height is not None:
            # EPUB: check aspect ratio and minimum sides
            if fmt == "epub":
                min_long = reqs.get("minLongSide", 2560)
                min_short = reqs.get("minShortSide", 1600)
                aspect_ratio = reqs.get("aspect", [1, 1.6])
                aspect_tolerance = reqs.get("aspectTolerance", 0.02)

                long_side = max(width, height)
                short_side = min(width, height)

                if long_side < min_long or short_side < min_short:
                    findings.append(
                        Finding(
                            ruleId="coverInvalid",
                            severity="block",
                            message=(f"EPUB cover too small: {width}x{height} (minimum {min_long}x{min_short})"),
                            fix=f"Use an image at least {min_long}x{min_short} pixels",
                            detail={
                                "format": "epub",
                                "width": width,
                                "height": height,
                                "minLongSide": min_long,
                                "minShortSide": min_short,
                            },
                        )
                    )

                expected_ratio = aspect_ratio[1] / aspect_ratio[0]
                actual_ratio = long_side / short_side
                if abs(actual_ratio - expected_ratio) > aspect_tolerance:
                    findings.append(
                        Finding(
                            ruleId="coverInvalid",
                            severity="block",
                            message=(
                                f"EPUB cover aspect ratio {actual_ratio:.3f} "
                                f"differs from expected {expected_ratio:.3f} "
                                f"(tolerance ±{aspect_tolerance})"
                            ),
                            fix=f"Use an image with aspect ratio close to {aspect_ratio[0]}:{aspect_ratio[1]}",
                            detail={
                                "format": "epub",
                                "actualRatio": actual_ratio,
                                "expectedRatio": expected_ratio,
                                "tolerance": aspect_tolerance,
                            },
                        )
                    )

            # Audiobook: must be square, within size range
            elif fmt == "audiobook":
                if reqs.get("square", False) and width != height:
                    findings.append(
                        Finding(
                            ruleId="coverInvalid",
                            severity="block",
                            message=f"Audiobook cover must be square (got {width}x{height})",
                            fix="Use a square image (e.g., 3000x3000)",
                            detail={"format": "audiobook", "width": width, "height": height},
                        )
                    )

                min_side = reqs.get("minSide", 2400)
                max_side = reqs.get("maxSide", 3200)
                if width < min_side or height < min_side:
                    findings.append(
                        Finding(
                            ruleId="coverInvalid",
                            severity="block",
                            message=f"Audiobook cover too small: {width}x{height} (minimum {min_side}x{min_side})",
                            fix=f"Use an image at least {min_side}x{min_side} pixels",
                            detail={"format": "audiobook", "width": width, "height": height, "minSide": min_side},
                        )
                    )
                if width > max_side or height > max_side:
                    findings.append(
                        Finding(
                            ruleId="coverInvalid",
                            severity="block",
                            message=f"Audiobook cover too large: {width}x{height} (maximum {max_side}x{max_side})",
                            fix=f"Use an image no larger than {max_side}x{max_side} pixels",
                            detail={"format": "audiobook", "width": width, "height": height, "maxSide": max_side},
                        )
                    )

        # Print covers: check wraparound size
        if fmt in ("paperback", "hardback"):
            expected = _calculateWraparoundSize(metadata, fmt)
            if expected:
                expected_w, expected_h = expected
                mime = asset.get("type", "")
                if mime == "application/pdf":
                    # Check PDF MediaBox
                    asset_path = self._assetStore.assetPath(asset_id)
                    if asset_path.is_file() and not _checkPdfMediaBox(asset_path, expected_w, expected_h):
                        findings.append(
                            Finding(
                                ruleId="coverSizeMismatch",
                                severity="block",
                                message=(
                                    f"Print cover PDF MediaBox does not match expected "
                                    f"wraparound size: expected {expected_w:.1f}x{expected_h:.1f}mm"
                                ),
                                fix=(
                                    f"Regenerate cover PDF with correct wraparound dimensions "
                                    f"({expected_w:.1f}x{expected_h:.1f}mm)"
                                ),
                                detail={"format": fmt, "expectedWidth": expected_w, "expectedHeight": expected_h},
                            )
                        )
                else:
                    # For image covers, check pixel dimensions match DPI
                    min_dpi = reqs.get("minDpi", 300)
                    if width and height:
                        # Calculate DPI from expected mm size
                        dpi_w = (width / expected_w) * 25.4
                        dpi_h = (height / expected_h) * 25.4
                        if dpi_w < min_dpi or dpi_h < min_dpi:
                            findings.append(
                                Finding(
                                    ruleId="coverSizeMismatch",
                                    severity="block",
                                    message=(
                                        f"Print cover image DPI too low: "
                                        f"{dpi_w:.0f}x{dpi_h:.0f} (minimum {min_dpi} DPI)"
                                    ),
                                    fix=f"Use an image with at least {min_dpi} DPI at the wraparound size",
                                    detail={"format": fmt, "dpiW": dpi_w, "dpiH": dpi_h, "minDpi": min_dpi},
                                )
                            )

        return findings

    def useSourceCover(self, fmt: str, sourceProjectPath: Path) -> bool:
        """Copy cover from source project (for edition projects).

        Returns True if successful.
        """
        source_store = CoverStore(sourceProjectPath)
        source_cover = source_store.getCover(fmt)
        if not source_cover:
            return False

        asset_id = source_cover["assetId"]
        asset = source_store._assetStore.getAsset(asset_id)
        if not asset:
            return False

        # Copy asset file to this project's asset store
        source_asset_path = source_store._assetStore.assetPath(asset_id)
        if not source_asset_path.is_file():
            return False

        # Add to this project's asset store
        new_asset_id = self._assetStore.addAsset(
            source_asset_path,
            role="cover",
            attrs={"format": fmt, "edition": "main", "source": "main", **source_cover.get("attrs", {})},
            name=asset["name"],
        )

        # Update covers slot table with source info
        self._covers.setdefault("slots", {})[fmt] = {
            "assetId": new_asset_id,
            "source": "main",
        }
        saveCovers(self._projectPath, self._covers)
        return True

    def validateAllCovers(self) -> list[Finding]:
        """Validate covers for all enabled formats."""
        all_findings: list[Finding] = []
        enabled = self.getEnabledFormats()
        for fmt in enabled:
            all_findings.extend(self.validateCover(fmt))
        return all_findings


def coversForBuild(metadata: Metadata, fmt: str, edition: str | None = None) -> dict[str, Any]:
    """Get cover asset IDs for a build.

    Returns dict with assetId for the format's cover.
    Used by P30, P31, P32.
    """
    project_path = Path(".")  # This would be passed in real usage
    covers = loadCovers(project_path)
    slots = covers.get("slots", {})
    slot = slots.get(fmt, {})
    asset_id = slot.get("assetId")
    return {"coverAssetId": asset_id}
