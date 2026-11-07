#!/usr/bin/env bash
# UmbraEdit Linux Build Script
# Builds .deb package and AppImage from source tarball
#
# Usage:
#   chmod +x build-linux.sh
#   ./build-linux.sh
#
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "UmbraEdit Linux Build Script"
echo "=========================================="

# Detect architecture
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

if [[ "$ARCH" != "x86_64" && "$ARCH" != "aarch64" ]]; then
    echo -e "${RED}Error: Unsupported architecture: $ARCH${NC}"
    echo "Supported architectures: x86_64, aarch64"
    exit 1
fi

# Detect Linux distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    VERSION=$VERSION_ID
else
    echo -e "${RED}Error: Cannot detect Linux distribution${NC}"
    exit 1
fi

echo "Detected distribution: $DISTRO $VERSION"

# ---------------------------------------------------------
# Step 1: Install build dependencies
# ---------------------------------------------------------
echo ""
echo "=========================================="
echo "Step 1: Installing build dependencies"
echo "=========================================="

if command -v apt-get &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y \
        python3 \
        python3-pip \
        python3-pyqt6 \
        python3-pyqt6.qtsvg \
        python3-enchant \
        qt6-image-formats-plugins \
        qt6-svg-plugins \
        dh-python \
        debhelper \
        python3-build \
        python3-setuptools \
        appimagetool \
        file
elif command -v dnf &> /dev/null; then
    sudo dnf install -y \
        python3 \
        python3-pip \
        python3-pyqt6 \
        python3-enchant \
        qt6-qtimageformats \
        qt6-qtsvg \
        python3-build \
        python3-setuptools \
        appimagetool
elif command -v pacman &> /dev/null; then
    sudo pacman -Sy --noconfirm \
        python \
        python-pip \
        python-pyqt6 \
        python-enchant \
        qt6-imageformats \
        qt6-qtsvg \
        python-build \
        python3-setuptools \
        appimagetool
else
    echo -e "${RED}Error: Unsupported package manager${NC}"
    echo "Please install manually: python3, pyqt6, pyenchant, dpkg-buildpackage, appimagetool"
    exit 1
fi

# ---------------------------------------------------------
# Step 2: Extract source tarball
# ---------------------------------------------------------
echo ""
echo "=========================================="
echo "Step 2: Extracting source tarball"
echo "=========================================="

TARBALL="umbraedit-2026.11.5.tar.gz"

if [ ! -f "$TARBALL" ]; then
    echo -e "${RED}Error: $TARBALL not found in current directory${NC}"
    echo "Download it from: https://git.umbratools.com/umbragit/UmbraEdit/-/releases/v2026.11.0006"
    exit 1
fi

echo "Extracting $TARBALL..."
tar xzf "$TARBALL"
cd umbraedit-2026.11.5

echo "Extracted to: $(pwd)"

# ---------------------------------------------------------
# Step 3: Install Python dependencies
# ---------------------------------------------------------
echo ""
echo "=========================================="
echo "Step 3: Installing Python dependencies"
echo "=========================================="

python3 -m pip install --user --upgrade pip setuptools wheel
python3 -m pip install --user -r <(python3 utils/main.py gen-req --groups app)

# ---------------------------------------------------------
# Step 4: Build .deb package (Debian/Ubuntu only)
# ---------------------------------------------------------
if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
    echo ""
    echo "=========================================="
    echo "Step 4: Building .deb package"
    echo "=========================================="

    python3 utils/build_debian.py --distro "$DISTRO" --build 1

    echo ""
    echo -e "${GREEN}Build complete!${NC}"
    echo "Debian package: dist_deb/umbraedit_*.deb"
    echo ""
    echo "To install:"
    echo "  sudo dpkg -i dist_deb/umbraedit_*_${ARCH}.deb"
else
    echo ""
    echo "=========================================="
    echo "Step 4: Skipping .deb build (not Debian/Ubuntu)"
    echo "=========================================="
fi

# ---------------------------------------------------------
# Step 5: Build AppImage
# ---------------------------------------------------------
echo ""
echo "=========================================="
echo "Step 5: Building AppImage"
echo "=========================================="

python3 utils/build_appimage.py --linux manylinux_2_28 --arch "$ARCH" --python 3.12

echo ""
echo -e "${GREEN}Build complete!${NC}"
echo "AppImage: dist_appimage/umbraedit-2026.11-${ARCH}.AppImage"
echo ""
echo "To run:"
echo "  chmod +x dist_appimage/umbraedit-2026.11-${ARCH}.AppImage"
echo "  ./dist_appimage/umbraedit-2026.11-${ARCH}.AppImage"

# ---------------------------------------------------------
# Step 6: Build Python wheel (optional, for pip install)
# ---------------------------------------------------------
echo ""
echo "=========================================="
echo "Step 6: Building Python wheel"
echo "=========================================="

python3 -m pip install --user build
python3 -m build --wheel

echo ""
echo -e "${GREEN}Wheel built:${NC}"
echo "  dist/umbraedit-2026.11.1-py3-none-any.whl"
echo ""
echo "To install:"
echo "  pip install dist/umbraedit-2026.11.1-py3-none-any.whl"

# ---------------------------------------------------------
# Done
# ---------------------------------------------------------
echo ""
echo "=========================================="
echo "Build complete!"
echo "=========================================="
echo ""
echo "Build artifacts:"
ls -la dist_deb/ 2>/dev/null || true
ls -la dist_appimage/ 2>/dev/null || true
ls -la dist/ 2>/dev/null || true
echo ""
echo "To run UmbraEdit:"
echo "  From AppImage: ./dist_appimage/umbraedit-2026.11-${ARCH}.AppImage"
echo "  From .deb:     sudo dpkg -i dist_deb/umbraedit_*_${ARCH}.deb && umbraedit"
echo "  From wheel:    pip install dist/umbraedit-2026.11.1-py3-none-any.whl && umbraedit"
