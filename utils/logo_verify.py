#!/usr/bin/env python3
"""
UmbraEdit Logo Verification Tool
================================
Analyzes the UmbraEdit.jpg reference logo and compares it against all other
logo/icon images in the project. Shows a GUI for the user to confirm or
flag images that don't match the UmbraEdit branding.
"""

from __future__ import annotations

import os
import sys

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "UmbraEdit.jpg"

# Files to check (logo/icon files that should be UmbraEdit branded)
LOGO_FILES = [
    "setup/macos/umbraedit.icns",
    "setup/icons/umbraedit.ico",
    "setup/icons/umbraedit.png",
    "setup/icons/x-umbraedit-project.ico",
    "setup/icons/x-umbraedit-project.png",
    "setup/icons/x-umbraedit-project.svg",
    "setup/data/umbraedit.png",
    "setup/data/hicolor/16x16/apps/umbraedit.png",
    "setup/data/hicolor/24x24/apps/umbraedit.png",
    "setup/data/hicolor/32x32/apps/umbraedit.png",
    "setup/data/hicolor/48x48/apps/umbraedit.png",
    "setup/data/hicolor/64x64/apps/umbraedit.png",
    "setup/data/hicolor/128x128/apps/umbraedit.png",
    "setup/data/hicolor/256x256/apps/umbraedit.png",
    "setup/data/hicolor/512x512/apps/umbraedit.png",
    "setup/data/hicolor/scalable/apps/umbraedit.svg",
    "setup/data/hicolor/16x16/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/24x24/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/32x32/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/48x48/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/64x64/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/128x128/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/256x256/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/512x512/mimetypes/application-x-umbraedit-project.png",
    "setup/data/hicolor/scalable/mimetypes/application-x-umbraedit-project.svg",
    "setup/umbraedit_readme.png",
    "setup/umbraedit_text.png",
    "umbraedit/assets/icons/umbraedit.ico",
    "umbraedit/assets/icons/umbraedit.png",
    "umbraedit/assets/icons/umbraedit.svg",
    "umbraedit/assets/icons/UmbraEdit.jpg",
    "umbraedit/assets/icons/x-umbraedit-project.ico",
    "umbraedit/assets/icons/x-umbraedit-project.svg",
    "umbraedit/assets/images/umbraedit-text-dark.svg",
    "umbraedit/assets/images/umbraedit-text-light.svg",
    "umbraedit/assets/images/splash.png",
    "setup/macos/umbraedit.iconset/icon_16x16.png",
    "setup/macos/umbraedit.iconset/icon_32x32.png",
    "setup/macos/umbraedit.iconset/icon_128x128.png",
    "setup/macos/umbraedit.iconset/icon_256x256.png",
    "setup/macos/umbraedit.iconset/icon_512x512.png",
    "NW_Splash.png",
    "setup/icons/x-novelwriter-project.png",
    "setup/windows/novelWriter.ico",
    "docs/source/_static/umbraedit-dark.png",
    "docs/source/_static/umbraedit-light.png",
    "docs/source/_static/umbraedit-pdf.png",
]


@dataclass
class ImageSignature:
    """Color signature of an image."""

    avg_r: float
    avg_g: float
    avg_b: float
    dominant: tuple[int, int, int]
    size: tuple[int, int]
    similarity: float  # 0.0 to 1.0, 1.0 = identical to reference


def getSignature(path: Path) -> ImageSignature | None:
    """Get the color signature of an image file."""
    try:
        if path.suffix.lower() == ".svg":
            return None  # SVG files can't be opened directly by PIL

        with Image.open(path) as img:
            img = img.convert("RGB")
            # Downsample to 8x8 grid for color comparison
            small = img.resize((8, 8))
            pixels = list(small.getdata())
            avgR = sum(p[0] for p in pixels) / len(pixels)
            avgG = sum(p[1] for p in pixels) / len(pixels)
            avgB = sum(p[2] for p in pixels) / len(pixels)

            # Get dominant color
            colors = img.getcolors(maxcolors=256 * 256 * 256)
            if colors:
                dominant = max(colors, key=lambda x: x[0])[1]
            else:
                dominant = (0, 0, 0)

            return ImageSignature(
                avg_r=avgR,
                avg_g=avgG,
                avg_b=avgB,
                dominant=dominant,
                size=img.size,
                similarity=0.0,  # Will be calculated
            )
    except Exception as exc:
        print(f"Warning: Could not analyze {path}: {exc}")
        return None


def compareSignatures(ref: ImageSignature, other: ImageSignature) -> float:
    """Compare two image signatures, returning 0.0 (different) to 1.0 (same)."""
    # Compare average colors (0-255 scale)
    diffR = abs(ref.avg_r - other.avg_r)
    diffG = abs(ref.avg_g - other.avg_g)
    diffB = abs(ref.avg_b - other.avg_b)
    avgDiff = (diffR + diffG + diffB) / 3.0
    # Normalize to 0-1, 255 is max possible diff
    return max(0.0, 1.0 - avgDiff / 128.0)


def loadImageThumbnail(path: Path, size: tuple[int, int] = (128, 128)) -> ImageTk.PhotoImage | None:
    """Load an image as a thumbnail for GUI display."""
    try:
        if path.suffix.lower() == ".svg":
            return None
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail(size)
            return ImageTk.PhotoImage(img)
    except Exception:
        return None


def main() -> None:
    """Run the GUI verification tool."""
    root = tk.Tk()
    root.title("UmbraEdit Logo Verification")
    root.geometry("1000x700")

    # Header
    headerFrame = ttk.Frame(root, padding=10)
    headerFrame.pack(fill=tk.X)
    ttk.Label(
        headerFrame,
        text="UmbraEdit Logo Verification Tool",
        font=("Helvetica", 16, "bold"),
    ).pack()
    ttk.Label(
        headerFrame,
        text=f"Reference: {REFERENCE.name}",
        font=("Helvetica", 10),
    ).pack()

    # Get reference signature
    refSig = getSignature(REFERENCE)
    if refSig is None:
        print("ERROR: Could not analyze reference image")
        sys.exit(1)

    print(f"Reference: {REFERENCE}")
    print(f"  Average RGB: ({refSig.avg_r:.0f}, {refSig.avg_g:.0f}, {refSig.avg_b:.0f})")
    print(f"  Dominant RGB: {refSig.dominant}")
    print(f"  Size: {refSig.size}")
    print()

    # Analyze all files
    results: list[tuple[Path, ImageSignature | None, float]] = []

    for relPath in LOGO_FILES:
        absPath = ROOT / relPath
        if not absPath.exists():
            results.append((absPath, None, 0.0))
            continue

        sig = getSignature(absPath)
        if sig is None:
            results.append((absPath, None, 0.0))
            continue

        similarity = compareSignatures(refSig, sig)
        sig.similarity = similarity
        results.append((absPath, sig, similarity))

    # Sort by similarity (ascending - most different first)
    results.sort(key=lambda x: x[2])

    # Create the main scrollable frame
    mainFrame = ttk.Frame(root, padding=5)
    mainFrame.pack(fill=tk.BOTH, expand=True)

    canvas = tk.Canvas(mainFrame)
    scrollbar = ttk.Scrollbar(mainFrame, orient=tk.VERTICAL, command=canvas.yview)
    scrollFrame = ttk.Frame(canvas)

    scrollFrame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas.create_window((0, 0), window=scrollFrame, anchor=tk.NW)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Column headers
    header = ttk.Frame(scrollFrame, padding=5)
    header.pack(fill=tk.X)
    for col, text in enumerate(["File", "Preview", "Avg RGB", "Size", "Similarity", "Action"]):
        ttk.Label(header, text=text, font=("Helvetica", 10, "bold")).grid(
            row=0, column=col, padx=5, sticky=tk.W
        )

    # Results
    row = 1
    flaggedCount = 0
    for path, sig, similarity in results:
        relPath = str(path.relative_to(ROOT)) if str(path).startswith(str(ROOT)) else str(path)
        itemFrame = ttk.Frame(scrollFrame, padding=2)
        itemFrame.pack(fill=tk.X, pady=2)

        # File name
        nameLabel = ttk.Label(itemFrame, text=relPath, width=55)
        nameLabel.grid(row=0, column=0, padx=5, sticky=tk.W)

        # Preview thumbnail
        thumb = loadImageThumbnail(path, (48, 48))
        if thumb:
            previewLabel = ttk.Label(itemFrame, image=thumb)
            previewLabel.image = thumb  # Keep reference
            previewLabel.grid(row=0, column=1, padx=5)
        else:
            previewLabel = ttk.Label(itemFrame, text="(SVG)", width=8)
            previewLabel.grid(row=0, column=1, padx=5)

        # Color info
        if sig:
            colorText = f"({sig.avg_r:.0f}, {sig.avg_g:.0f}, {sig.avg_b:.0f})"
            sizeText = f"{sig.size[0]}x{sig.size[1]}"
            simText = f"{similarity:.1%}"
        else:
            colorText = "N/A"
            sizeText = "N/A"
            simText = "N/A"

        ttk.Label(itemFrame, text=colorText, width=18).grid(row=0, column=2, padx=5)
        ttk.Label(itemFrame, text=sizeText, width=12).grid(row=0, column=3, padx=5)
        ttk.Label(itemFrame, text=simText, width=12).grid(row=0, column=4, padx=5)

        # Action label (PASS or FLAG)
        if similarity >= 0.80:
            actionText = "PASS"
            actionColor = "green"
        else:
            actionText = "FLAG"
            actionColor = "red"
            flaggedCount += 1
        actionLabel = ttk.Label(itemFrame, text=actionText, foreground=actionColor)
        actionLabel.grid(row=0, column=5, padx=5)

        row += 1

    # Footer with summary
    footerFrame = ttk.Frame(root, padding=10)
    footerFrame.pack(fill=tk.X)
    ttk.Label(
        footerFrame,
        text=f"Total: {len(results)} files, {flaggedCount} flagged for review",
        font=("Helvetica", 12, "bold"),
    ).pack()

    def closeApp() -> None:
        root.destroy()

    ttk.Button(footerFrame, text="Close", command=closeApp).pack(pady=5)

    root.mainloop()


if __name__ == "__main__":
    main()
