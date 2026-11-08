#!/usr/bin/env python3
"""
UmbraEdit - Icon Generator
==========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Regenerates every derived icon file from the source image
`branding/umbraedit-icon-source.svg` (or a PNG fallback of at least
1024x1024). Never edit a generated file by hand.

Usage:
    python3 utils/umbra_make_icons.py
    python3 utils/umbra_make_icons.py --source branding/my-icon.svg
"""  # noqa

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BRANDING_DIR = ROOT_DIR / "branding"
ICONSET_DIR = ROOT_DIR / "setup" / "macos" / "umbraedit.iconset"
HICOLOR_DIR = ROOT_DIR / "setup" / "data" / "hicolor"
ICONS_DIR = ROOT_DIR / "setup" / "icons"
ASSETS_ICONS_DIR = ROOT_DIR / "umbraedit" / "assets" / "icons"
DOCS_STATIC_DIR = ROOT_DIR / "docs" / "source" / "_static"

# macOS iconset sizes: (basename, size, scale)
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

HICOLOR_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def renderPng(source: Path, size: int, output: Path) -> None:
    """Render the source image to a PNG at the given size."""
    if source.suffix.lower() == ".svg":
        # Try QSvgRenderer via Qt
        try:
            from PyQt6.QtCore import QByteArray, QSize
            from PyQt6.QtGui import QImage, QPainter
            from PyQt6.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(str(source))
            if not renderer.isValid():
                raise ValueError(f"Invalid SVG: {source}")
            image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            image.save(str(output), "PNG")
            return
        except ImportError:
            pass

    # Fall back to ImageMagick
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        subprocess.run(
            [magick, "-background", "none", "-resize", f"{size}x{size}", str(source), str(output)],
            check=True,
        )
        return

    # Fall back to Pillow for PNG sources
    try:
        from PIL import Image

        with Image.open(source) as img:
            img = img.convert("RGBA")
            img = img.resize((size, size), Image.LANCZOS)
            img.save(output, "PNG")
        return
    except ImportError:
        pass

    print(f"ERROR: Cannot render {source} to {output}. No suitable tool found.", file=sys.stderr)
    sys.exit(1)


def writeIco(source: Path, output: Path, sizes: list[int]) -> None:
    """Write a multi-size .ico file using Pillow."""
    try:
        from PIL import Image

        images = []
        for size in sizes:
            with Image.open(source) as img:
                img = img.convert("RGBA")
                img = img.resize((size, size), Image.LANCZOS)
                images.append(img)
        images[0].save(str(output), format="ICO", sizes=[(s, s) for s in sizes])
    except ImportError:
        print("WARNING: Pillow not available, skipping .ico generation.", file=sys.stderr)


def writeIcns(iconsetDir: Path, output: Path) -> None:
    """Write a .icns file from the iconset directory."""
    if sys.platform == "darwin":
        iconutil = shutil.which("iconutil")
        if iconutil:
            subprocess.run(
                [iconutil, "-c", "icns", str(iconsetDir), "-o", str(output)],
                check=True,
            )
            return

    # Pure-Python .icns writer (simplified: writes PNG-based icons)
    icnsTypes = {
        16: "is32", 32: "il32", 128: "it32", 256: "ic10", 512: "ic14",
    }
    pngTypes = {
        16: b"icp4", 32: b"icp5", 128: b"ic07", 256: b"ic08",
        512: b"ic09", 1024: b"ic10",
    }

    entries = b""
    iconCount = 0

    sizeMap = {
        16: "icon_16x16.png",
        32: "icon_16x16@2x.png",
        128: "icon_128x128.png",
        256: "icon_256x256.png",
        512: "icon_512x512.png",
        1024: "icon_512x512@2x.png",
    }

    for size, filename in sizeMap.items():
        pngPath = iconsetDir / filename
        if not pngPath.is_file():
            continue
        pngData = pngPath.read_bytes()
        osType = pngTypes.get(size)
        if osType is None:
            continue
        entry = osType + struct.pack(">I", len(pngData) + 8) + pngData
        entries += entry
        iconCount += 1

    if iconCount == 0:
        print("ERROR: No icon PNGs found in iconset.", file=sys.stderr)
        sys.exit(1)

    icnsData = b"icns" + struct.pack(">I", len(entries) + 8) + entries
    output.write_bytes(icnsData)


def main() -> None:
    """Generate all icon files from the source image."""
    parser = argparse.ArgumentParser(description="Generate all UmbraEdit icons from the source.")
    parser.add_argument(
        "--source", type=str, default=None,
        help="Path to the source SVG or PNG (default: branding/umbraedit-icon-source.svg)",
    )
    parser.add_argument(
        "--doc-shape", action="store_true",
        help="Also generate the project-file document icon variant.",
    )
    args = parser.parse_args()

    if args.source:
        source = Path(args.source)
    else:
        source = BRANDING_DIR / "umbraedit-icon-source.svg"
        if not source.is_file():
            source = BRANDING_DIR / "umbraedit-icon-source.png"
        if not source.is_file():
            # Fall back to UmbraEdit.jpg
            source = ROOT_DIR / "UmbraEdit.jpg"

    if not source.is_file():
        print(f"ERROR: Source image not found: {source}", file=sys.stderr)
        sys.exit(1)

    print(f"Source image: {source}")
    print(f"Type: {source.suffix.upper()}")

    # 1. macOS iconset
    print("\nGenerating macOS iconset...")
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in ICONSET_SIZES:
        output = ICONSET_DIR / name
        renderPng(source, size, output)
        print(f"  {output.name}: {size}x{size}")

    # 2. macOS .icns
    print("\nGenerating macOS .icns...")
    icnsOutput = ROOT_DIR / "setup" / "macos" / "umbraedit.icns"
    writeIcns(ICONSET_DIR, icnsOutput)
    print(f"  {icnsOutput}")

    # 3. Hicolor PNG icons
    print("\nGenerating hicolor PNG icons...")
    for size in HICOLOR_SIZES:
        appsDir = HICOLOR_DIR / f"{size}x{size}" / "apps"
        appsDir.mkdir(parents=True, exist_ok=True)
        output = appsDir / "umbraedit.png"
        renderPng(source, size, output)
        print(f"  {output}")

    # 4. Windows .ico
    print("\nGenerating Windows .ico...")
    icoOutput = ICONS_DIR / "umbraedit.ico"
    writeIco(source, icoOutput, ICO_SIZES)
    print(f"  {icoOutput}")

    # 5. PNG for setup/icons
    print("\nGenerating setup/icons PNG...")
    pngOutput = ICONS_DIR / "umbraedit.png"
    renderPng(source, 256, pngOutput)
    print(f"  {pngOutput}")

    # 6. In-app icons
    print("\nGenerating in-app icons...")
    appPng = ASSETS_ICONS_DIR / "umbraedit.png"
    renderPng(source, 256, appPng)
    print(f"  {appPng}")

    # 7. Docs logos
    print("\nGenerating docs logos...")
    for name in ["umbraedit-dark.png", "umbraedit-light.png", "umbraedit-pdf.png"]:
        output = DOCS_STATIC_DIR / name
        renderPng(source, 256, output)
        print(f"  {output}")

    # 8. Copy source to setup/icons/
    svgTarget = ICONS_DIR / "umbraedit.svg"
    if source.suffix.lower() == ".svg":
        shutil.copyfile(source, svgTarget)
        print(f"\n  Copied SVG: {svgTarget}")

    print("\nDone. All icons regenerated.")


if __name__ == "__main__":
    main()
