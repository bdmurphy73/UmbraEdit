# UmbraEdit macOS Menu Bar Issue - Fix Specification

## Issue Analysis

When UmbraEdit starts on macOS, the top menu bar shows "Python" instead of "UmbraEdit", and a Python icon appears in the Dock/tray. This is a well-known macOS Python application branding issue.

### Root Cause

On macOS, Python applications without an explicit process title will display "Python" in the menu bar and Dock. The UmbraEdit source code already includes a fix for this in `UmbraEdit.py`:

```python
# Set process name for macOS menu bar before anything else loads.
# Without this, macOS shows "Python" instead of "UmbraEdit" in the menu bar.
try:
    import setproctitle
    setproctitle.setproctitle("UmbraEdit")
except Exception:
    pass
```

However, the `setproctitle` package is **not** installed when building the macOS application using the provided build script.

### Build Process Failure

The macOS build process (`setup/macos/build.sh`) installs Python dependencies from `requirements.txt`:

```bash
pip install -r "$SRC_DIR/requirements.txt"
```

The `requirements.txt` file contains:
```
pyqt6>=6.4
pyenchant>=3.3.0
pyobjc-framework-Cocoa; sys_platform == 'darwin'
```

**Notably, `setproctitle` is missing from `requirements.txt`.**

Interestingly, `setproctitle` **is** correctly listed as a conditional dependency in `pyproject.toml`:
```toml
dependencies = [
    ...
    "setproctitle; sys_platform == 'darwin'",
]
```

However, the build script uses `requirements.txt` (via pip), not `pyproject.toml`, so this dependency is never installed during the macOS build.

## Fix Specification

To fix this issue without modifying application code, the build process must ensure `setproctitle` is installed when building for macOS. Here are the required changes:

### Option 1: Update `requirements.txt` (Recommended)

Add `setproctitle` to `requirements.txt` with the macOS conditional:

```
pyqt6>=6.4
pyenchant>=3.3.0
pyobjc-framework-Cocoa; sys_platform == 'darwin'
setproctitle; sys_platform == 'darwin'
```

This ensures that when `pip install -r requirements.txt` runs during the macOS build, `setproctitle` will be installed on macOS systems.

### Option 2: Modify Build Script

Add an explicit installation step in `setup/macos/build.sh` after the pip install:

```bash
# Install setproctitle for macOS menu bar branding
if [ "$(uname)" == "Darwin" ]; then
    pip install setproctitle
fi
```

### Option 3: Use pyproject.toml Dependencies

Modify the build script to use `pyproject.toml` dependencies instead of `requirements.txt`, or parse the conditional dependencies from `pyproject.toml`. This would be a more comprehensive solution but requires more extensive changes to the build process.

## Recommended Approach

**Option 1** is the simplest and most targeted fix. Add `setproctitle; sys_platform == 'darwin'` to `/Volumes/1TB_APL_Storage/UmbraEdit/requirements.txt`.

This single-line change ensures that:
1. The `setproctitle` package is installed on macOS during the build process
2. The `UmbraEdit.py` startup code can successfully set the process title
3. macOS will display "UmbraEdit" in the menu bar instead of "Python"
4. No application code needs to be modified

## Verification

After implementing the fix, verify by:
1. Building the macOS app using `setup/macos/build.sh`
2. Launching the UmbraEdit.app bundle
3. Checking that the menu bar shows "UmbraEdit" (not "Python")
4. Checking that the Dock displays the UmbraEdit icon (not a Python icon)
5. Confirming the process title is set correctly via `ps -o comm -p <pid>`