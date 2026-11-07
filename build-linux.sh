#!/usr/bin/env bash
#=============================================================================
# UmbraEdit Linux Build Script
# ============================================================================
# Downloads the UmbraEdit source tarball and builds a .deb package and/or
# AppImage for Linux AMD64/ARM64.
#
# Usage:
#   chmod +x build-linux.sh
#   ./build-linux.sh [--arch amd64|arm64] [--distro ubuntu|debian] [--no-deb]
#
# No git clone required. Downloads the source tarball automatically.
#=============================================================================

set -euo pipefail

#-----------------------------------------------------------------------------
# Configuration
#-----------------------------------------------------------------------------
VERSION="2026.11.5"
RELEASE_VERSION="2026.11.0007"
GITEA_URL="http://192.168.123.18:2222/umbragit/UmbraEdit"
TARBALL_URL="${GITEA_URL}/-/archive/v${RELEASE_VERSION}/umbraedit-${RELEASE_VERSION}.tar.gz"
TARBALL="umbraedit-${RELEASE_VERSION}.tar.gz"
EXTRACTED_DIR="umbraedit-${RELEASE_VERSION}"

ARCH="${1:-amd64}"
DISTRO="${2:-ubuntu}"
BUILD_DEB="${3:-yes}"

echo "============================================================"
echo "  UmbraEdit Linux Build Script"
echo "============================================================"
echo ""
echo "  Version:    ${RELEASE_VERSION}"
echo "  Architecture: ${ARCH}"
echo "  Distro:     ${DISTRO}"
echo "  Build .deb: ${BUILD_DEB}"
echo ""

#--------------------------------------------------------------
# Step 1: Check prerequisites
#--------------------------------------------------------------
echo "[1/5] Checking prerequisites..."

MISSING=0
for cmd in curl tar python3; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "  MISSING: $cmd"
        MISSING=1
    fi
done

if command -v apt-get &> /dev/null; then
    PKG_MGR="apt-get"
elif command -v dnf &> /dev/null; then
    PKG_MGR="dnf"
elif command -v pacman &> /dev/null; then
    PKG_MGR="pacman"
else
    PKG_MGR=""
fi

if [ "$PKG_MGR" = "" ]; then
    echo ""
    echo "ERROR: No supported package manager found (apt-get, dnf, or pacman)"
    echo "Please install: python3, python3-pip, python3-pyqt6, python3-enchant,"
    echo "                dh-python, debhelper, python3-build, appimagetool"
    exit 1
fi

echo "  Package manager: $PKG_MGR"
echo "  Prerequisites OK"

#--------------------------------------------------------------
# Step 2: Install system dependencies
#--------------------------------------------------------------
echo ""
echo "[2/5] Installing system dependencies..."

INSTALL_FAILED=0

if [ "$PKG_MGR" = "apt-get" ]; then
    echo "  Updating package lists..."
    if ! sudo apt-get update 2>&1 | tail -5; then
        echo ""
        echo "============================================================"
        echo "  ERROR: apt-get update failed!"
        echo "============================================================"
        echo ""
        echo "  One of your package repositories is broken (likely a PPA or"
        echo "  third-party repo like NVIDIA's)."
        echo ""
        echo "  To fix:"
        echo "    1. Check /etc/apt/sources.list and /etc/apt/sources.list.d/"
        echo "    2. Remove or disable any repositories that no longer exist"
        echo "    3. Run: sudo apt-get update"
        echo "    4. Then re-run this script: ./build-linux.sh"
        echo ""
        exit 1
    fi
fi

echo ""
echo "Installing packages..."
install_pkg() {
    if [ "$PKG_MGR" = "apt-get" ]; then
        sudo apt-get install -y "$@" 2>&1 | tail -3
    elif [ "$PKG_MGR" = "dnf" ]; then
        sudo dnf install -y "$@" 2>&1 | tail -3
    elif [ "$PKG_MGR" = "pacman" ]; then
        sudo pacman -Sy --noconfirm "$@" 2>&1 | tail -3
    fi
}

echo "  Installing: python3 python3-pip python3-pyqt6 python3-enchant"
install_pkg python3 python3-pip python3-pyqt6 python3-enchant 2>&1 | tail -3 || {
    echo ""
    echo "============================================================"
    echo "  ERROR: Failed to install core dependencies"
    echo "============================================================"
    echo ""
    echo "  Please install manually and re-run:"
    echo "    sudo apt-get install python3 python3-pip python3-pyqt6 python3-enchant"
    echo ""
    exit 1
}

echo ""
echo "  Installing: dh-python debhelper python3-build appimagetool"
install_pkg dh-python debhelper python3-build appimagetool 2>&1 | tail -3 || {
    echo ""
    echo "============================================================"
    echo "  WARNING: Some build tools failed to install"
    echo "============================================================"
    echo ""
    echo "  You may need to install these manually:"
    echo "    sudo apt-get install dh-python debhelper python3-build appimagetool"
    echo ""
    echo "  Continuing anyway..."
}

echo "  System dependencies installed"

#--------------------------------------------------------------
# Step 3: Download source tarball
#--------------------------------------------------------------
echo ""
echo "[3/5] Downloading source tarball..."
echo "  URL: ${TARBALL_URL}"

if [ -f "$TARBALL" ]; then
    echo "  Archive already exists, skipping download"
else
    curl -L -o "$TARBALL" "$TARBALL_URL"
    echo "  Downloaded: $(ls -lh "$TARBALL" | awk '{print $5}')"
fi

#--------------------------------------------------------------
# Step 4: Extract source
#--------------------------------------------------------------
echo ""
echo "[4/5] Extracting source..."

rm -rf "$EXTRACTED_DIR"
tar xzf "$TARBALL"
cd "$EXTRACTED_DIR"

echo "  Extracted to: $(pwd)"

#--------------------------------------------------------------
# Step 5: Install Python dependencies
#--------------------------------------------------------------
echo ""
echo "[5/5] Installing Python dependencies..."

python3 -m pip install --user --upgrade pip setuptools wheel 2>&1 | tail -1
python3 -m pip install --user pyqt6 pyenchant 2>&1 | tail -1

echo "  Python dependencies installed"

#--------------------------------------------------------------
# Step 6: Build packages
#--------------------------------------------------------------
echo ""
echo "[6/6] Building packages..."

# Build .deb (Debian/Ubuntu only)
if [ "$BUILD_DEB" = "yes" ] && [ "$PKG_MGR" = "apt-get" ]; then
    echo ""
    echo "Building .deb package..."
    python3 utils/build_debian.py --distro "$DISTRO" --build 1
    echo ""
    echo "  .deb package: dist_deb/umbraedit_*_${ARCH}.deb"
fi

# Build AppImage
echo ""
echo "Building AppImage..."
python3 utils/build_appimage.py --linux manylinux_2_28 --arch "$ARCH" --python 3.12
echo ""
echo "  AppImage: dist_appimage/umbraedit-${RELEASE_VERSION}-${ARCH}.AppImage"

#--------------------------------------------------------------
# Done
#--------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Build Complete!"
echo "============================================================"
echo ""
echo "Artifacts:"
ls -la dist_deb/ 2>/dev/null || true
ls -la dist_appimage/ 2>/dev/null || true
echo ""
echo "To run UmbraEdit:"
echo "  From AppImage:  chmod +x dist_appimage/umbraedit-${RELEASE_VERSION}-${ARCH}.AppImage"
echo "                  ./dist_appimage/umbraedit-${RELEASE_VERSION}-${ARCH}.AppImage"
echo "  From .deb:      sudo dpkg -i dist_deb/umbraedit_*_${ARCH}.deb && umbraedit"
echo ""
echo "Source directory: $(pwd)"
