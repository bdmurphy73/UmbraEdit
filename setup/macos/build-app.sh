#! /bin/bash

# UmbraEdit macOS Application Bundle Build Script
# ===============================================
#
# Builds a self-contained UmbraEdit.app bundle and packages it as a DMG.
#
# The bundle ships its own relocatable Python runtime together with all of
# the Python packages UmbraEdit needs. This is a requirement on macOS. If
# the app instead launches a Python installed somewhere else on the system,
# the operating system may register the process under a different
# application bundle. The visible result is a menu bar that says "Python"
# and a second rocket icon in the Dock next to the UmbraEdit icon.
#
# Usage:
#   bash setup/macos/build-app.sh [arch] [python-version]
#
# The arch argument is the architecture to build for. It must match the
# architecture of the machine running the build, and is used for the file
# name of the DMG.

set -euo pipefail

ARCH="${1:-arm64}"
PYTHON_VERSION="${2:-3.12}"

# Normalise the architecture names
case "$ARCH" in
    arm64|aarch64) ARCH="arm64" ;;
    x86_64|amd64) ARCH="x86_64" ;;
esac

# The bundle must match the architecture of the machine that builds it.
HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
    arm64) HOST_ARCH="arm64" ;;
    x86_64) HOST_ARCH="x86_64" ;;
esac

if [ "$ARCH" != "$HOST_ARCH" ]; then
    echo "WARNING: This is a $HOST_ARCH machine, so the bundle is built for $HOST_ARCH." >&2
    ARCH="$HOST_ARCH"
fi

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SRC_DIR="$SCRIPT_DIR/../.."
RLS_DIR="$SRC_DIR/dist_macos"

if [ -d /dev/shm ]; then
    TEMP_BASE=/dev/shm
else
    TEMP_BASE="${TMPDIR:-/tmp}"
fi

BUILD_DIR=$(mktemp -d "$TEMP_BASE/UmbraEdit-build-XXXXXX")
REQ_DIR=$(mktemp -d "$TEMP_BASE/UmbraEdit-req-XXXXXX")

cleanup () {
    if [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
    if [ -d "$REQ_DIR" ]; then
        rm -rf "$REQ_DIR"
    fi
}
trap cleanup EXIT

APP_DIR="$BUILD_DIR/UmbraEdit.app"
RES_DIR="$APP_DIR/Contents/Resources"

echo "UmbraEdit macOS Bundle Builder"
echo "=============================="
echo "Architecture:   $ARCH"
echo "Python version: $PYTHON_VERSION"
echo "Build folder:   $BUILD_DIR"
echo ""

die () {
    echo "ERROR: $1" >&2
    exit 1
}

# --- Locate Python ---------------------------------------------------------------------------- #

# Find a managed Python interpreter that can be bundled with the app.
#
# The interpreter must not live inside another application bundle. macOS
# derives the identity of a running application from the path of the
# executable that was launched, so an interpreter inside, for instance,
# Xcode's Python.app would make UmbraEdit register itself as "Python".
find_python () {
    local version="$1"
    local path=""
    path="$(python3 "$SCRIPT_DIR/bundle_tools.py" find-python --version "$version" 2>/dev/null || true)"
    if [ -n "$path" ]; then
        echo "$path"
        return 0
    fi
    echo "Downloading Python $version ..." >&2
    uv python install "$version" >/dev/null 2>&1 || return 1
    path="$(python3 "$SCRIPT_DIR/bundle_tools.py" find-python --version "$version" 2>/dev/null || true)"
    if [ -n "$path" ]; then
        echo "$path"
        return 0
    fi
    return 1
}

command -v uv >/dev/null 2>&1 || die "uv is required to build the bundle. See https://docs.astral.sh/uv/"
command -v python3 >/dev/null 2>&1 || die "python3 is required to build the bundle."

echo "Locating Python $PYTHON_VERSION ..."
PYTHON_BIN="$(find_python "$PYTHON_VERSION")" || die "Could not find a usable Python $PYTHON_VERSION"
PYTHON_ROOT="$(dirname "$(dirname "$PYTHON_BIN")")"
PY_TAG="$("$PYTHON_BIN" -c 'import sys; print("python%d.%d" % sys.version_info[:2])')"

echo "Python binary: $PYTHON_BIN"
echo "Python root:   $PYTHON_ROOT"
echo ""

# --- Prepare Files ----------------------------------------------------------------------------- #

pushd "$SRC_DIR" || die "Could not enter $SRC_DIR"

VERSION="$(python3 pkgutils.py version)"
echo "UmbraEdit version: $VERSION"

echo "Generating Info.plist ..."
python3 pkgutils.py gen-plist || die "Could not generate Info.plist"

echo "Exporting requirements from uv.lock ..."
uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt \
    -o "$REQ_DIR/requirements.txt" || die "Could not export the requirements"

# Check that all assets are present
echo "Checking assets"
for asset in "umbraedit/assets/sample.zip" "umbraedit/assets/manual.pdf" \
    "umbraedit/assets/manual_fr.pdf" "umbraedit/assets/i18n/project_en_US.json" \
    "setup/icons/umbraedit.png" \
    "setup/macos/umbraedit.icns" "setup/macos/umbraedit_launcher.sh"; do
    if [ -f "$SRC_DIR/$asset" ]; then
        echo "Found: $asset"
    else
        echo "Missing: $asset"
        die "Missing asset: $asset"
    fi
done

# Reject empty or malformed manuals before copying the source tree into the
# application bundle. Validate every manual so stale placeholders for other
# languages cannot slip into the release either.
MANUAL_FILES=("$SRC_DIR"/umbraedit/assets/manual*.pdf)
if [ "${#MANUAL_FILES[@]}" -lt 2 ]; then
    die "Both English and French PDF manuals are required"
fi
python3 -m utils.manual "${MANUAL_FILES[@]}" || die "Invalid PDF manual asset"

popd || die "Could not leave $SRC_DIR"

# --- Build App --------------------------------------------------------------------------------- #

echo ""
echo "Building app bundle ..."

mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$RES_DIR/UmbraEdit"
mkdir -p "$RES_DIR/python"

echo "Copying the Python runtime ..."
cp -a "$PYTHON_ROOT/." "$RES_DIR/python/"

BUNDLED_PYTHON="$RES_DIR/python/bin/$PY_TAG"
[ -x "$BUNDLED_PYTHON" ] || die "The bundled Python runtime is incomplete"

SITE_DIR="$RES_DIR/python/lib/$PY_TAG/site-packages"
mkdir -p "$SITE_DIR"

echo "Installing the Python packages ..."
uv pip install --python "$BUNDLED_PYTHON" --target "$SITE_DIR" \
    -r "$REQ_DIR/requirements.txt" || die "Could not install the Python packages"

echo "Copying the application source ..."
FILES_COPY=(
    "CHANGELOG.md" "CREDITS.md" "LICENSE.md"
    "CONTRIBUTING.md" "CODE_OF_CONDUCT.md" "umbraedit"
    "UmbraEdit.py"
)

for file in "${FILES_COPY[@]}"; do
    echo "Copying $file ..."
    cp -a "$SRC_DIR/$file" "$RES_DIR/UmbraEdit/"
done

# Clean up the copied source
find "$RES_DIR/UmbraEdit" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$RES_DIR/UmbraEdit" -type f -name '*.pyc' -delete 2>/dev/null || true
find "$RES_DIR/UmbraEdit" -type f -name '.DS_Store' -delete 2>/dev/null || true

cp "$SRC_DIR/setup/macos/Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$SRC_DIR/setup/macos/umbraedit.icns" "$RES_DIR/"

# Create the entry script
echo "Creating entry script ..."
cp "$SRC_DIR/setup/macos/umbraedit_launcher.sh" "$APP_DIR/Contents/MacOS/UmbraEdit"
chmod a+x "$APP_DIR/Contents/MacOS/UmbraEdit"

echo "Trimming the bundle ..."
python3 "$SCRIPT_DIR/bundle_tools.py" trim --python "$RES_DIR/python" --site "$SITE_DIR"

# Verify that the bundle is complete and can start
echo "Verifying the bundle ..."
"$BUNDLED_PYTHON" -sE -c "
import sys
sys.path.insert(0, '$RES_DIR/UmbraEdit')
import umbraedit
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
print('UmbraEdit', umbraedit.__version__)
print('PyQt6', PYQT_VERSION_STR, 'Qt', QT_VERSION_STR)
" || die "The bundled application could not be loaded"

# --- Create DMG -------------------------------------------------------------------------------- #

echo ""
echo "Packaging DMG ..."
if ! command -v create-dmg &> /dev/null; then
    echo "Installing create-dmg ..."
    brew install create-dmg
fi

mkdir -p "$RLS_DIR"

DMG_NAME="umbraedit-${VERSION}-${ARCH}.dmg"
DMG_PATH="$RLS_DIR/$DMG_NAME"

# Remove any previous build of the same version
rm -f "$DMG_PATH" "$DMG_PATH.sha256" "$RLS_DIR"/rw.*."$DMG_NAME"

DMG_ARGS=(
    --volname "UmbraEdit $VERSION"
    --volicon "$SRC_DIR/setup/macos/umbraedit.icns"
    --window-pos 200 120
    --window-size 800 400
    --icon-size 100
    --icon UmbraEdit.app 200 190
    --hide-extension UmbraEdit.app
    --app-drop-link 600 185
)

# Run a command with a time limit. The command is killed if it has not
# completed within the given number of seconds.
run_with_timeout () {
    local seconds="$1"
    shift
    "$@" &
    local pid=$!
    local waited=0
    while kill -0 "$pid" 2> /dev/null; do
        if [ "$waited" -ge "$seconds" ]; then
            echo "WARNING: Timed out after ${seconds}s: $*" >&2
            kill -9 "$pid" 2> /dev/null || true
            wait "$pid" 2> /dev/null || true
            return 124
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "$pid"
}

# Unmount any disk image left behind by a failed packaging attempt. The
# image is not usable when it is still mounted, and a stale mount also
# keeps the disk arbitration service busy. The detach is given a time
# limit because a busy volume can make it hang indefinitely.
cleanup_mounts () {
    for mountPoint in /Volumes/dmg.*; do
        [ -e "${mountPoint}" ] || continue
        echo "Unmounting stale disk image: ${mountPoint}"
        run_with_timeout 30 hdiutil detach -force "${mountPoint}" > /dev/null 2>&1 || true
    done
}

# Build the disk image with hdiutil alone. This is the fallback for
# systems where create-dmg cannot unmount the image it just mounted. The
# image is functional, but it does not have the custom Finder layout.
make_dmg_hdiutil () {
    local staging
    staging="$(mktemp -d "${TMPDIR:-/tmp}/umbraedit-dmg-XXXXXX")"
    cp -a "$BUILD_DIR/UmbraEdit.app" "${staging}/"
    ln -s /Applications "${staging}/Applications"
    cp "$SRC_DIR/setup/macos/umbraedit.icns" "${staging}/.VolumeIcon.icns"
    hdiutil create -volname "UmbraEdit $VERSION" -srcfolder "${staging}" \
        -fs HFS+ -format UDZO -ov "$DMG_PATH"
    rm -rf "${staging}"
}

# create-dmg normally asks Finder to polish the mounted window. Recent
# macOS releases can reject that cosmetic AppleScript even though the disk
# image itself was created correctly. Retry without the Finder step so a
# functional DMG is still produced on those systems.
if ! create-dmg "${DMG_ARGS[@]}" "$DMG_PATH" "$BUILD_DIR/"; then
    echo "WARNING: create-dmg could not apply the Finder layout; retrying without it." >&2
    rm -f "$DMG_PATH" "$RLS_DIR"/rw.*."$DMG_NAME"
    cleanup_mounts
    if ! create-dmg --skip-jenkins "${DMG_ARGS[@]}" "$DMG_PATH" "$BUILD_DIR/"; then
        echo "WARNING: create-dmg could not package the disk image." >&2
        echo "WARNING: Falling back to a plain hdiutil disk image." >&2
        rm -f "$DMG_PATH" "$RLS_DIR"/rw.*."$DMG_NAME"
        cleanup_mounts
        make_dmg_hdiutil || die "Could not package the disk image"
    fi
fi

# Intermediate images are not release artifacts
rm -f "$RLS_DIR"/rw.*."$DMG_NAME"

[ -f "$DMG_PATH" ] || die "The disk image was not created"

pushd "$RLS_DIR" || die "Could not enter $RLS_DIR"
shasum -a 256 "umbraedit-${VERSION}-${ARCH}.dmg" | tee "umbraedit-${VERSION}-${ARCH}.dmg.sha256"
popd || die "Could not leave $RLS_DIR"

echo ""
echo "Done: $RLS_DIR/umbraedit-${VERSION}-${ARCH}.dmg"
