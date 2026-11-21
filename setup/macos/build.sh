#! /bin/bash

# UmbraEdit macOS Application Bundle Build Script
# ===============================================
#
# Compatibility wrapper around setup/macos/build-app.sh.
#
# The bundle used to be built from a Miniconda environment. It is now built
# from a relocatable, standalone Python runtime instead. The conda build had
# a number of problems: it was slow, it needed a network download of the
# whole Miniconda installer, and the version of Python it shipped was not
# pinned to the versions the project is tested against.
#
# The standalone runtime has one important property that the conda build
# also had: the interpreter lives inside the application bundle. macOS
# derives the identity of a running application from the path of the
# executable that was launched, so an interpreter that lives inside another
# application bundle would make UmbraEdit register itself as "Python" in
# the menu bar and add a second rocket icon to the Dock.
#
# Usage:
#   ./setup/macos/build.sh <python-version> <arch> <miniconda-arch>
#
# The third argument is ignored and only kept so that the existing release
# workflows keep working.

set -euo pipefail

PYTHON_VERSION="${1:-3.12}"
ARCH="${2:-arm64}"

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

exec bash "$SCRIPT_DIR/build-app.sh" "$ARCH" "$PYTHON_VERSION"
