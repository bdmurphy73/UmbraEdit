#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RESOURCES_DIR="$DIR/../Resources/UmbraEdit"

# Find Python
PYTHON_CMD=""
for cmd in python3 python3.12 python3.11 python3.10 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    osascript -e 'tell app "System Events" to display dialog "UmbraEdit requires Python 3.10 or newer but Python was not found. Please install Python from python.org or via Homebrew: brew install python" buttons {"OK"} default button "OK" with icon caution'
    exit 1
fi

# Install required components if missing
"$PYTHON_CMD" -m pip install --no-deps "tomli==1.2.3" jsonschema attrs "referencing==0.35.1" rpds-py uri-template "idna==2.10" jsonschema_specifications httpx httpcore anyio sniffio lxml setproctitle 2>/dev/null || true

if ! "$PYTHON_CMD" -c "import PyQt6.QtWidgets" 2>/dev/null; then
    osascript -e 'tell app "System Events" to display dialog "UmbraEdit is installing required components (PyQt6). This may take a few minutes..." buttons {"OK"} default button "OK" with icon note'
    if ! "$PYTHON_CMD" -m pip install PyQt6 PyEnchant tomli jsonschema attrs "referencing==0.35.1" rpds-py uri-template "idna==2.10" jsonschema_specifications httpx httpcore anyio sniffio lxml setproctitle 2>/dev/null; then
        osascript -e 'tell app "System Events" to display dialog "UmbraEdit failed to install PyQt6. Please install it manually: pip3 install PyQt6 PyEnchant" buttons {"OK"} default button "OK" with icon caution'
        exit 1
    fi
fi

cd "$RESOURCES_DIR"

# Run UmbraEdit with error capture
ERROR_LOG="$HOME/Library/Logs/UmbraEdit/error.log"
mkdir -p "$(dirname "$ERROR_LOG")"

exec -a "UmbraEdit" "$PYTHON_CMD" UmbraEdit.py "$@" 2>"$ERROR_LOG"

# If we get here, the app crashed - show the error
ERROR_CONTENT=$(cat "$ERROR_LOG" 2>/dev/null || echo "Unknown error")
osascript -e "tell app \"System Events\" to display dialog \"UmbraEdit crashed:\\n\\n$ERROR_CONTENT\" buttons {\"OK\"} default button \"OK\" with icon caution"
exit 1
