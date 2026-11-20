#! /bin/bash

# UmbraEdit macOS Application Bundle Build Script
# ===============================================
#
# Builds the UmbraEdit.app bundle and packages it as a DMG.
#
# The bundle uses the launcher in setup/macos/umbraedit_launcher.sh, which
# runs UmbraEdit with the system Python and installs the required packages
# on first run. This keeps the download small and makes sure the app works
# with the Python version installed on the user's machine.
#
# Usage:
#   bash setup/macos/build-app.sh [arch]
#
# The arch argument is only used for the file name of the DMG. It must
# match the architecture of the machine running the build.

set -euo pipefail

ARCH="${1:-arm64}"
TIMESTAMP=$(date "+%s")

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SRC_DIR="$SCRIPT_DIR/../.."
RLS_DIR="$SRC_DIR/dist_macos"

if [ -d /dev/shm ]; then
    TEMP_BASE=/dev/shm
else
    TEMP_BASE=/private/var/folders/y8/cbvhds297918lrxt2wd3btsr0000gn/T/opencode
fi

BUILD_DIR=$(mktemp -d "$TEMP_BASE/UmbraEdit-build-XXXXXX")

cleanup () {
    if [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
}
trap cleanup EXIT

pushd "$SRC_DIR" || exit 1

VERSION="$(python3 pkgutils.py version)"
echo "UmbraEdit Version: $VERSION"
echo "Architecture: $ARCH"
echo "Build Dir: $BUILD_DIR"

# --- Prepare Files ----------------------------------------------------------------------------- #

echo "Generating Info.plist"
python3 pkgutils.py gen-plist
if [ -f "$SRC_DIR/setup/macos/Info.plist" ]; then
    echo "Found: setup/macos/Info.plist"
else
    echo "Missing: setup/macos/Info.plist"
    exit 1
fi

echo "Generating requirements.txt"
python3 pkgutils.py gen-req

# Check that other assets are present
echo "Checking assets"
for asset in "umbraedit/assets/sample.zip" "umbraedit/assets/manual.pdf" \
    "umbraedit/assets/i18n/project_en_US.json" "setup/icons/umbraedit.png" \
    "setup/macos/umbraedit.icns" "setup/macos/umbraedit_launcher.sh"; do
    if [ -f "$SRC_DIR/$asset" ]; then
        echo "Found: $asset"
    else
        echo "Missing: $asset"
        exit 1
    fi
done

# --- Build App --------------------------------------------------------------------------------- #

echo "Building App bundle ..."

popd || exit 1
pushd "$BUILD_DIR" || exit 1

mkdir -p UmbraEdit.app/Contents/MacOS
mkdir -p UmbraEdit.app/Contents/Resources/UmbraEdit

cp "$SRC_DIR/setup/macos/Info.plist" UmbraEdit.app/Contents/Info.plist
cp "$SRC_DIR/setup/macos/umbraedit.icns" UmbraEdit.app/Contents/Resources/

# Copy the application source
FILES_COPY=(
    "CHANGELOG.md" "CREDITS.md" "LICENSE.md"
    "CONTRIBUTING.md" "CODE_OF_CONDUCT.md" "umbraedit"
    "UmbraEdit.py"
)

for file in "${FILES_COPY[@]}"; do
    echo "Copying $SRC_DIR/$file ..."
    cp -R "$SRC_DIR/$file" UmbraEdit.app/Contents/Resources/UmbraEdit/
done

# Clean up the copied source
find UmbraEdit.app/Contents/Resources/UmbraEdit -type d -name '__pycache__' -print0 \
    | xargs -0 rm -r 2>/dev/null || true
find UmbraEdit.app/Contents/Resources/UmbraEdit -type f -name '*.pyc' -delete 2>/dev/null || true
find UmbraEdit.app/Contents/Resources/UmbraEdit -type f -name '.DS_Store' -delete 2>/dev/null || true

# Create the entry script
echo "Creating entry script ..."
cp "$SRC_DIR/setup/macos/umbraedit_launcher.sh" UmbraEdit.app/Contents/MacOS/UmbraEdit
chmod a+x UmbraEdit.app/Contents/MacOS/UmbraEdit

# Do codesigning
# echo "Signing bundle ..."
# sudo codesign --sign - --deep --force --entitlements "$SCRIPT_DIR/../macos/App.entitlements" --options runtime "UmbraEdit.app/Contents/MacOS/UmbraEdit"

# --- Create DMG -------------------------------------------------------------------------------- #

echo "Packaging DMG ..."
if ! command -v create-dmg &> /dev/null; then
    echo "Installing create-dmg ..."
    brew install create-dmg
fi

mkdir -p "$RLS_DIR"

# Remove any previous build of the same version
rm -f "$RLS_DIR/umbraedit-${VERSION}-${ARCH}.dmg" "$RLS_DIR/umbraedit-${VERSION}-${ARCH}.dmg.sha256"

create-dmg --volname "UmbraEdit $VERSION" --volicon "$SRC_DIR/setup/macos/umbraedit.icns" \
    --window-pos 200 120 --window-size 800 400 --icon-size 100 \
    --icon UmbraEdit.app 200 190 --hide-extension UmbraEdit.app \
    --app-drop-link 600 185 "$RLS_DIR/umbraedit-${VERSION}-${ARCH}.dmg" "$BUILD_DIR/"

popd || exit 1
pushd "$RLS_DIR" || exit 1
shasum -a 256 "umbraedit-${VERSION}-${ARCH}.dmg" | tee "umbraedit-${VERSION}-${ARCH}.dmg.sha256"
popd || exit 1

echo ""
echo "Done: $RLS_DIR/umbraedit-${VERSION}-${ARCH}.dmg"
