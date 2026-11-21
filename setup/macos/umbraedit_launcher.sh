#!/bin/bash
# UmbraEdit launcher for the macOS application bundle.
# =================================================
#
# The bundle ships a self-contained, relocatable Python runtime in
# Contents/Resources/python together with all of its dependencies.
#
# It is critical that we always exec the *bundled* interpreter and never a
# Python installed somewhere else on the system. macOS LaunchServices derives
# the identity of a running application from the path of the executable that
# was launched. If that executable lives inside another application bundle
# (for instance the Python.app that ships with the Xcode command line tools),
# the running process is registered under that other bundle instead. The
# result is a menu bar that says "Python" and an extra Python rocket icon in
# the Dock next to the UmbraEdit icon.
#
# The "exec -a" call sets argv[0] so that "ps" shows the process as
# "UmbraEdit" rather than "python3".

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RESOURCES_DIR="$DIR/../Resources"
APP_DIR="$RESOURCES_DIR/UmbraEdit"
PYTHON_DIR="$RESOURCES_DIR/python"

# Locate the bundled Python runtime.
PYTHON_CMD=""
for candidate in "$PYTHON_DIR"/bin/python3.*; do
    if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        PYTHON_CMD="$candidate"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    osascript -e 'tell app "System Events" to display dialog "UmbraEdit could not find its bundled Python runtime. The application bundle is incomplete. Please download and install the latest UmbraEdit release." buttons {"OK"} default button "OK" with icon caution' 2>/dev/null
    exit 1
fi

if [ ! -f "$APP_DIR/UmbraEdit.py" ]; then
    osascript -e 'tell app "System Events" to display dialog "UmbraEdit could not find the application files. The application bundle is incomplete. Please download and install the latest UmbraEdit release." buttons {"OK"} default button "OK" with icon caution' 2>/dev/null
    exit 1
fi

# Log any start-up errors to a file in the user's log directory.
ERROR_LOG="$HOME/Library/Logs/UmbraEdit/error.log"
mkdir -p "$(dirname "$ERROR_LOG")" 2>/dev/null
: > "$ERROR_LOG" 2>/dev/null || true

cd "$APP_DIR" || exit 1

# Run UmbraEdit.
#
# The -s flag disables the user site-packages directory and the -E flag makes
# Python ignore PYTHON* environment variables. Together they ensure that the
# bundle only ever uses the packages it ships with.
exec -a "UmbraEdit" "$PYTHON_CMD" -sE "$APP_DIR/UmbraEdit.py" "$@" 2>>"$ERROR_LOG"
