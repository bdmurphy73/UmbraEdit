#!/usr/bin/env bash
#=============================================================================
# UmbraEdit Linux Install Script
# ============================================================================
# Installs UmbraEdit on Linux AMD64/ARM64 from the source tarball.
# No compilation required.
#
# The script assumes that the source tarball is in the same directory as
# the script itself:
#
#     umbraedit-2026.11.0006.tar.gz
#     install-linux.sh
#
# Usage:
#   chmod +x install-linux.sh
#   ./install-linux.sh [amd64|arm64]
#=============================================================================

set -euo pipefail

ARCH="${1:-amd64}"
RELEASE_VERSION="2026.11.0006"

# The tarball is expected in the same directory as this script. If it is
# not there, a GITEA_URL can be provided to download it instead.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
GITEA_URL="${GITEA_URL:-}"

TARBALL="umbraedit-${RELEASE_VERSION}.tar.gz"
if [ -f "${SCRIPT_DIR}/${TARBALL}" ]; then
    TARBALL_PATH="${SCRIPT_DIR}/${TARBALL}"
    echo "Using local tarball: ${TARBALL_PATH}"
elif [ -n "$GITEA_URL" ]; then
    TARBALL_URL="${GITEA_URL}/-/archive/v${RELEASE_VERSION}/${TARBALL}"
else
    echo "ERROR: No source tarball found."
    echo "Place ${TARBALL} in the same directory as this script, or set GITEA_URL."
    exit 1
fi

echo "============================================================"
echo "  UmbraEdit Linux Installer"
echo "============================================================"
echo ""
echo "  Version:    ${RELEASE_VERSION}"
echo "  Architecture: ${ARCH}"
echo ""

#-----------------------------------------------------------------------------
# Step 1: Check prerequisites
#-----------------------------------------------------------------------------
echo "[1/4] Checking prerequisites..."

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

#-----------------------------------------------------------------------------
# Step 2: Fetch the source tarball
#-----------------------------------------------------------------------------
echo ""
echo "[2/4] Fetching the source tarball..."

INSTALL_DIR="${HOME}/Downloads/umbraedit-${RELEASE_VERSION}"
mkdir -p "$INSTALL_DIR"

if [ -n "${TARBALL_PATH:-}" ]; then
    cp "$TARBALL_PATH" "${INSTALL_DIR}/${TARBALL}"
else
    curl -L -o "${INSTALL_DIR}/${TARBALL}" "$TARBALL_URL"
fi

echo "  Ready: $(ls -lh "${INSTALL_DIR}/${TARBALL}" | awk '{print $5}')"

#-----------------------------------------------------------------------------
# Step 3: Extract the source
#-----------------------------------------------------------------------------
echo ""
echo "[3/4] Extracting the source..."

cd "$INSTALL_DIR"
rm -rf "umbraedit-${RELEASE_VERSION}"
tar xzf "${TARBALL}"

SRC_DIR="${INSTALL_DIR}/umbraedit-${RELEASE_VERSION}"
if [ ! -d "$SRC_DIR" ]; then
    # The tarball may contain a single top level folder with another name
    SRC_DIR="$(find "$INSTALL_DIR" -maxdepth 1 -type d -name 'umbraedit-*' | head -1)"
fi

if [ -z "$SRC_DIR" ] || [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: Could not locate the extracted UmbraEdit source folder"
    exit 1
fi

echo "  Extracted to: ${SRC_DIR}"

#-----------------------------------------------------------------------------
# Step 4: Install the start menu shortcut and the UmbraEdit icon
#-----------------------------------------------------------------------------
echo ""
echo "[4/4] Installing the start menu shortcut..."

DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

ICON_SRC="${SRC_DIR}/setup/icons/umbraedit.png"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "${ICON_DIR}/umbraedit.png"
    echo "  Installed icon: ${ICON_DIR}/umbraedit.png"
else
    echo "  WARNING: Could not find the UmbraEdit icon at ${ICON_SRC}"
fi

cat > "${DESKTOP_DIR}/umbraedit.desktop" << EOF
[Desktop Entry]
Type=Application
Name=UmbraEdit
Comment=A plain text editor for planning and writing novels
Exec=${SRC_DIR}/UmbraEdit.py %f
Icon=umbraedit
Categories=Qt;Office;WordProcessor;
Terminal=false
MimeType=application/x-umbraedit-project;
EOF

chmod +x "${DESKTOP_DIR}/umbraedit.desktop"
echo "  Installed shortcut: ${DESKTOP_DIR}/umbraedit.desktop"

# Refresh the desktop and icon caches if the tools are available
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$DESKTOP_DIR" &> /dev/null || true
fi
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" &> /dev/null || true
fi

echo ""
echo "============================================================"
echo "  Installation Complete!"
echo "============================================================"
echo ""
echo "To run UmbraEdit:"
echo "  cd ${SRC_DIR}"
echo "  python3 UmbraEdit.py"
echo ""
echo "Or install as a system application:"
echo "  sudo pip install ."
echo "  umbraedit"
echo ""
echo "The UmbraEdit shortcut has been added to your application menu."
echo ""
