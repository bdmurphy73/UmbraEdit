"""
UmbraEdit - Multi-Platform Build Script
=======================================

Builds install packages for all supported platforms:

  Linux (amd64, arm64)   - .deb, .rpm, AppImage
  macOS (arm64, amd64)   - .dmg, .app
  Windows (amd64, arm64) - .msi, .exe

Usage:
    python utils/build_all.py --platform all
    python utils/build_all.py --platform linux --arch amd64
    python utils/build_all.py --platform macos --arch arm64
    python utils/build_all.py --platform windows --arch amd64

Requirements:
    - Python 3.11+
    - pyqt6, pyenchant
    - Platform-specific tools (see below)

Linux Requirements:
    - dpkg-buildpackage, rpmbuild, appimagetool, python-appimage

macOS Requirements:
    - Xcode command line tools, create-dmg (brew install create-dmg)

Windows Requirements:
    - NSIS (Nullsoft Scriptable Install System) or Inno Setup
    - MinGW-w64 cross-compiler (for cross-compiling from Linux)

iOS / iPadOS:
    NOT SUPPORTED. PyQt6 does not support iOS. UmbraEdit requires a
    full desktop Qt environment. iOS would require a complete rewrite
    using SwiftUI or a different framework entirely.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from umbraedit import __version__

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"[run] {' '.join(cmd)}")
    if cwd:
        print(f"      in {cwd}")
    return subprocess.run(cmd, cwd=cwd, check=check)


def check_tool(tool: str) -> bool:
    """Check if a tool is available on PATH."""
    return shutil.which(tool) is not None


def check_linux_tools() -> list[str]:
    """Check for Linux build tools. Returns list of missing tools."""
    missing: list[str] = []
    for tool in ["dpkg-buildpackage", "rpmbuild", "appimagetool", "python3"]:
        if not check_tool(tool):
            missing.append(tool)
    return missing


def check_macos_tools() -> list[str]:
    """Check for macOS build tools. Returns list of missing tools."""
    missing: list[str] = []
    for tool in ["iconutil", "hdiutil", "codesign", "productbuild"]:
        if not check_tool(tool):
            missing.append(tool)
    return missing


def check_windows_tools() -> list[str]:
    """Check for Windows build tools. Returns list of missing tools."""
    missing: list[str] = []
    for tool in ["makensis", "makepkg", "osslsigncode"]:
        if not check_tool(tool):
            missing.append(tool)
    return missing


def build_linux_amd64() -> None:
    """Build .deb and AppImage for Linux AMD64."""
    print("\n" + "=" * 70)
    print("Building Linux AMD64 packages")
    print("=" * 70)

    missing = check_linux_tools()
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install build dependencies first.")
        return

    # Build .deb via dpkg-buildpackage
    print("\n[1/2] Building .deb package...")
    run(["python3", "utils/build_debian.py", "--distro", "noble", "--build", "1"])

    # Build AppImage
    print("\n[2/2] Building AppImage...")
    run([
        "python3", "utils/build_appimage.py",
        "--linux", "ubuntu", "--arch", "amd64", "--python", "3.12",
    ])

    print("\nLinux AMD64 build complete.")
    print(f"  .deb:   dist_deb/umbraedit_*.deb")
    print(f"  AppImage: dist_appimage/umbraedit-*-amd64.AppImage")


def build_linux_arm64() -> None:
    """Build .deb and AppImage for Linux ARM64."""
    print("\n" + "=" * 70)
    print("Building Linux ARM64 packages")
    print("=" * 70)

    missing = check_linux_tools()
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install build dependencies first.")
        return

    # Build .deb via dpkg-buildpackage (cross-arch or native on ARM64 host)
    print("\n[1/2] Building .deb package (arm64)...")
    run(["python3", "utils/build_debian.py", "--distro", "noble", "--build", "1"])

    # Build AppImage
    print("\n[2/2] Building AppImage (arm64)...")
    run([
        "python3", "utils/build_appimage.py",
        "--linux", "ubuntu", "--arch", "arm64", "--python", "3.12",
    ])

    print("\nLinux ARM64 build complete.")
    print(f"  .deb:   dist_deb/umbraedit_*_arm64.deb")
    print(f"  AppImage: dist_appimage/umbraedit-*-arm64.AppImage")


def build_macos_arm64() -> None:
    """Build .dmg and .app for macOS ARM64 (Apple Silicon)."""
    print("\n" + "=" * 70)
    print("Building macOS ARM64 packages")
    print("=" * 70)

    missing = check_macos_tools()
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install build dependencies first.")
        return

    print("\n[1/1] Building macOS .dmg (arm64)...")
    run(["bash", "setup/macos/build.sh", "3.12", "arm64", "arm64"])

    print("\nmacOS ARM64 build complete.")
    print(f"  .dmg: dist_macos/umbraedit-2026.11-arm64.dmg")


def build_macos_amd64() -> None:
    """Build .dmg and .app for macOS AMD64 (Intel)."""
    print("\n" + "=" * 70)
    print("Building macOS AMD64 packages")
    print("=" * 70)

    missing = check_macos_tools()
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install build dependencies first.")
        return

    print("\n[1/1] Building macOS .dmg (amd64)...")
    run(["bash", "setup/macos/build.sh", "3.12", "amd64", "amd64"])

    print("\nmacOS AMD64 build complete.")
    print(f"  .dmg: dist_macos/umbraedit-2026.11-amd64.dmg")


def build_windows_amd64() -> None:
    """Build .msi and .exe for Windows AMD64."""
    print("\n" + "=" * 70)
    print("Building Windows AMD64 packages")
    print("=" * 70)

    missing = check_windows_tools()
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install build dependencies first.")
        print("Windows builds typically require a Windows host or cross-compilation.")
        return

    print("\n[1/1] Building Windows .exe/.msi (amd64)...")
    run(["python", "utils/build_windows.py", "--arch", "amd64"])

    print("\nWindows AMD64 build complete.")
    print(f"  .exe: dist_win/umbraedit-*.exe")
    print(f"  .msi: dist_win/umbraedit-*.msi")


def build_windows_arm64() -> None:
    """Build .msi and .exe for Windows ARM64."""
    print("\n" + "=" * 70)
    print("Building Windows ARM64 packages")
    print("=" * 70)

    missing = check_windows_tools()
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install build dependencies first.")
        return

    print("\n[1/1] Building Windows .exe/.msi (arm64)...")
    run(["python", "utils/build_windows.py", "--arch", "arm64"])

    print("\nWindows ARM64 build complete.")
    print(f"  .exe: dist_win/umbraedit-*-arm64.exe")
    print(f"  .msi: dist_win/umbraedit-*-arm64.msi")


def build_all_platforms() -> None:
    """Build packages for all supported platforms."""
    print("=" * 70)
    print("UmbraEdit Multi-Platform Build")
    print("=" * 70)
    print(f"Version: {__version__}")
    print(f"Host: {platform.system()} {platform.machine()}")
    print()

    # Build all Linux targets
    build_linux_amd64()
    build_linux_arm64()

    # Build macOS targets (only on macOS host)
    if platform.system() == "Darwin":
        build_macos_arm64()
        build_macos_amd64()
    else:
        print("\n[skip] macOS builds require macOS host")
        print("  Build macOS packages on a Mac with Xcode command line tools")

    # Build Windows targets (only on Windows host or with cross-tools)
    if platform.system() == "Windows":
        build_windows_amd64()
        build_windows_arm64()
    else:
        print("\n[skip] Windows builds require Windows host or cross-compilation toolchain")
        print("  Build Windows packages on Windows with NSIS/Inno Setup")

    print("\n" + "=" * 70)
    print("Multi-platform build complete.")
    print("=" * 70)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Build UmbraEdit install packages for all platforms."
    )
    parser.add_argument(
        "--platform",
        choices=["all", "linux", "macos", "windows"],
        default="all",
        help="Platform to build (default: all)",
    )
    parser.add_argument(
        "--arch",
        choices=["amd64", "arm64"],
        help="Target architecture (default: host architecture)",
    )

    args = parser.parse_args()

    if args.platform == "all":
        build_all_platforms()
    elif args.platform == "linux":
        arch = args.arch or ("arm64" if platform.machine() == "aarch64" else "amd64")
        if arch == "amd64":
            build_linux_amd64()
        else:
            build_linux_arm64()
    elif args.platform == "macos":
        arch = args.arch or ("arm64" if platform.machine() == "arm64" else "amd64")
        if arch == "amd64":
            build_macos_amd64()
        else:
            build_macos_arm64()
    elif args.platform == "windows":
        arch = args.arch or "amd64"
        if arch == "amd64":
            build_windows_amd64()
        else:
            build_windows_arm64()


if __name__ == "__main__":
    main()
