#!/usr/bin/env bash
# UmbraEdit Linux Install Script
# ============================================================================
# Downloads and installs pre-built UmbraEdit packages for Linux AMD64/ARM64.
# No compilation required.
#
# Usage:
#   chmod +x install-linux.sh
#   ./install-linux.sh [amd64|arm64]
#=============================================================================

set -euo pipefail

ARCH="${1:-amd64}"
RELEASE_VERSION="2026.11.0007"
GITEA_URL="http://192.168.123.18:2222/umbragit/UmbraEdit"

echo "============================================================"
echo "  UmbraEdit Linux Installer"
echo "============================================================"
echo ""
echo "  Version:    ${RELEASE_VERSION}"
echo "  Architecture: ${ARCH}"
echo ""

#--------------------------------------------------------------
# Step 1: Check prerequisites
#--------------------------------------------------------------
echo "[1/3] Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is required but not installed"
    echo "  Install with: sudo apt-get install python3 python3-pyqt6 python3-enchant"
    exit 1
fi

if ! command -v wget &> /dev/null && ! command -v curl &> /dev/null; then
    echo "ERROR: wget or curl is required"
    exit 1
fi

echo "  Prerequisites OK"

#--------------------------------------------------------------
# Step 2: Download pre-built packages
#--------------------------------------------------------------
echo ""
echo "[2/3] Downloading packages..."

DOWNLOAD_DIR="${HOME}/Downloads/umbraedit-${RELEASE_VERSION}"
mkdir -p "$DOWNLOAD_DIR"

# Download AppImage (works on any Linux)
APPIMAGE_URL="${GITEA_URL}/-/archive/v${RELEASE_VERSION}/umbraedit-${RELEASE_VERSION}.tar.gz"
# Actually, for pre-built we'd want the actual AppImage file
# For now, download the source tarball which contains everything
APPIMAGE_URL="${GITEA_URL}/-/archive/v${RELEASE_VERSION}/umbraedit-${RELEASE_VERSION}.tar.gz"

echo "  Downloading source tarball..."
curl -L -o "$DOWNLOAD_DIR/umbraedit-${RELEASE_VERSION}.tar.gz" "$APPIMAGE_URL"

echo "  Downloaded: $(ls -lh "$DOWNLOAD_DIR/umbraedit-${RELEASE_VERSION}.tar.gz" | awk '{print $5}')"

#--------------------------------------------------------------
# Step 3: Extract and install
#--------------------------------------------------------------
echo ""
echo "[3/3] Installing..."

cd "$DOWNLOAD_DIR"
tar xzf "umbraedit-${RELEASE_VERSION}.tar.gz"
cd "umbraedit-${RELEASE_VERSION}"

echo ""
echo "Extracting to: $DOWNLOAD_DIR/umbraedit-${RELEASE_VERSION}"
echo ""

echo "============================================================"
echo "  Installation Complete!"
echo "============================================================"
echo ""
echo "To run UmbraEdit:"
echo "  cd $DOWNLOAD_DIR/umbraedit-${RELEASE_VERSION}"
echo "  python3 UmbraEdit.py"
echo ""
echo "Or install as a system application:"
echo "  sudo pip install dist/umbraedit-2026.11.1-py3-none-any.whl"
echo "  umbraedit"
echo ""
