#!/usr/bin/env bash
#=============================================================================
# UmbraEdit Linux Build Script
# ============================================================================
# Builds a .deb package and/or AppImage for Linux AMD64/ARM64 from the
# UmbraEdit source tarball.
#
# The script assumes that the source tarball is in the same directory as
# the script itself:
#
#     umbraedit-2026.11.0006.tar.gz
#     build-linux.sh
#
# Usage:
#   chmod +x build-linux.sh
#   ./build-linux.sh [amd64|arm64] [ubuntu|debian] [yes|no]
#=============================================================================

set -euo pipefail

#-----------------------------------------------------------------------------
# Configuration
#-----------------------------------------------------------------------------
VERSION="2026.11.0006"
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

#-----------------------------------------------------------------------------
# Step 1: Check prerequisites
#-----------------------------------------------------------------------------
echo "[1/5] Checking prerequisites..."

MISSING=0
for cmd in curl tar python3; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "  MISSING: $cmd"
        MISSING=1
    fi
done

if [ "$MISSING" -ne 0 ]; then
    echo ""
    echo "ERROR: Missing required tools"
    exit 1
fi

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

#-----------------------------------------------------------------------------
# Step 2: Install system dependencies
#-----------------------------------------------------------------------------
echo ""
echo "[2/5] Installing system dependencies..."

install_pkg() {
    if [ "$PKG_MGR" = "apt-get" ]; then
        sudo apt-get install -y "$@" 2>&1 | tail -3
    elif [ "$PKG_MGR" = "dnf" ]; then
        sudo dnf install -y "$@" 2>&1 | tail -3
    elif [ "$PKG_MGR" = "pacman" ]; then
        sudo pacman -S --noconfirm "$@" 2>&1 | tail -3
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

#-----------------------------------------------------------------------------
# Step 3: Fetch and extract the source tarball
#-----------------------------------------------------------------------------
echo ""
echo "[3/5] Extracting the source tarball..."

if [ -n "${TARBALL_PATH:-}" ]; then
    cp "$TARBALL_PATH" "${TARBALL}"
else
    curl -L -o "${TARBALL}" "$TARBALL_URL"
fi

# The tarball holds a single top level folder with the source code. It
# is extracted into a staging folder first, so that the source always
# ends up in a predictable place, no matter what the folder in the
# tarball is called.
STAGE_DIR="$(mktemp -d "${PWD}/.umbraedit-stage-XXXXXX")"
tar xzf "${TARBALL}" -C "$STAGE_DIR"

SRC_DIR=""
for candidate in "$STAGE_DIR"/*/; do
    if [ -f "${candidate}UmbraEdit.py" ]; then
        SRC_DIR="${candidate%/}"
        break
    fi
done

if [ -z "$SRC_DIR" ]; then
    echo "ERROR: Could not locate the extracted UmbraEdit source folder"
    rm -rf "$STAGE_DIR"
    exit 1
fi

rm -rf "${EXTRACTED_DIR}"
mv "$SRC_DIR" "${EXTRACTED_DIR}"
rm -rf "$STAGE_DIR"

cd "$EXTRACTED_DIR"
echo "  Extracted to: $(pwd)"

#-----------------------------------------------------------------------------
# Step 4: Install Python dependencies
#-----------------------------------------------------------------------------
echo ""
echo "[4/5] Installing Python dependencies..."

python3 -m pip install --user --upgrade pip setuptools wheel 2>&1 | tail -1
python3 -m pip install --user pyqt6 pyenchant 2>&1 | tail -1

echo "  Python dependencies installed"

#-----------------------------------------------------------------------------
# Step 5: Build packages and install the start menu shortcut
#-----------------------------------------------------------------------------
echo ""
echo "[5/5] Building packages..."

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

# Install the start menu shortcut and the UmbraEdit icon for the current
# user. The .deb package does this system wide, but the AppImage and the
# source install do not, so it is done here as well.
echo ""
echo "Installing the start menu shortcut..."

DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

ICON_SRC="setup/icons/umbraedit.png"
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
Exec=$(pwd)/UmbraEdit.py %f
Icon=umbraedit
Categories=Qt;Office;WordProcessor;
Terminal=false
MimeType=application/x-umbraedit-project;
EOF

chmod +x "${DESKTOP_DIR}/umbraedit.desktop"
echo "  Installed shortcut: ${DESKTOP_DIR}/umbraedit.desktop"

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$DESKTOP_DIR" &> /dev/null || true
fi
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" &> /dev/null || true
fi

#-----------------------------------------------------------------------------
# Done
#-----------------------------------------------------------------------------
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
echo "  From source:    python3 UmbraEdit.py"
echo ""
echo "Source directory: $(pwd)"
