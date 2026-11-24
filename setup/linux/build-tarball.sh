#!/usr/bin/env bash
#=============================================================================
# UmbraEdit Linux Source Tarball Build Script
# ============================================================================
# Builds the UmbraEdit source tarball used by build-linux.sh and
# install-linux.sh.
#
# The source tree is first staged with rsync, so that development
# artefacts like the virtual environment, the git data and the build
# output folders are not included. The staged tree is then packed into
# a gzipped tarball with a single top level folder named after the
# release version:
#
#     umbraedit-2026.11.0006/
#
# Usage:
#   bash setup/linux/build-tarball.sh [version]
#=============================================================================

set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
SRC_DIR="$( cd -- "${SCRIPT_DIR}/../.." &> /dev/null && pwd )"
DIST_DIR="${SRC_DIR}/dist"

VERSION="${1:-$( cd -- "${SRC_DIR}" &> /dev/null && python3 pkgutils.py version )}"
RELEASE="umbraedit-${VERSION}"
TARBALL="${RELEASE}.tar.gz"

if ! command -v rsync &> /dev/null; then
    echo "ERROR: rsync is required to build the source tarball."
    exit 1
fi

echo "============================================================"
echo "  UmbraEdit Linux Source Tarball"
echo "============================================================"
echo ""
echo "  Version: ${VERSION}"
echo "  Source:  ${SRC_DIR}"
echo "  Output:  ${DIST_DIR}/${TARBALL}"
echo ""

mkdir -p "${DIST_DIR}"

#-----------------------------------------------------------------------------
# Stage the source tree
#-----------------------------------------------------------------------------
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/umbraedit-tarball-XXXXXX")"
cleanup () {
    rm -rf "$STAGE"
}
trap cleanup EXIT

mkdir -p "${STAGE}/${RELEASE}"

echo "Staging the source tree ..."
rsync -a \
    --delete \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='.pytest_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='.DS_Store' \
    --exclude='__pycache__/' \
    --exclude='*.py[cod]' \
    --exclude='dist/' \
    --exclude='dist_*/' \
    --exclude='umbraedit/assets/manual*.pdf' \
    --exclude='tests/_temp/' \
    --exclude='*.egg-info/' \
    --exclude='build/' \
    "${SRC_DIR}/" "${STAGE}/${RELEASE}/"

# Generated manuals are release artifacts, not source files. They are built
# and validated separately, and must never enter the source tarball.
UNEXPECTED_MANUAL="$(find "${STAGE}/${RELEASE}/umbraedit/assets" -type f -name 'manual*.pdf' -print -quit 2>/dev/null || true)"
if [ -n "${UNEXPECTED_MANUAL}" ]; then
    echo "ERROR: Generated PDF manual entered the source tarball: ${UNEXPECTED_MANUAL}"
    exit 1
fi

# The build scripts are shipped next to the tarball as well
for script in build-linux.sh install-linux.sh; do
    if [ -f "${SRC_DIR}/${script}" ]; then
        cp "${SRC_DIR}/${script}" "${STAGE}/${RELEASE}/${script}"
    fi
done

#-----------------------------------------------------------------------------
# Pack the tarball
#-----------------------------------------------------------------------------
echo "Packing the tarball ..."
cd "$STAGE"
tar -czf "${DIST_DIR}/${TARBALL}" -C "$STAGE" "${RELEASE}"

cd "$SRC_DIR"

#-----------------------------------------------------------------------------
# Report
#-----------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Done"
echo "============================================================"
echo ""
ls -lh "${DIST_DIR}/${TARBALL}"
shasum -a 256 "${DIST_DIR}/${TARBALL}" | tee "${DIST_DIR}/${TARBALL}.sha256"
echo ""

# The build and install scripts are copied next to the tarball, so that
# the user can run them from the same folder
for script in build-linux.sh install-linux.sh; do
    if [ -f "${SRC_DIR}/${script}" ]; then
        cp "${SRC_DIR}/${script}" "${DIST_DIR}/${script}"
        chmod +x "${DIST_DIR}/${script}"
    fi
done

echo "Scripts in ${DIST_DIR}: build-linux.sh, install-linux.sh"
echo ""
