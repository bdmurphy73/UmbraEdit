#!/bin/zsh
# UmbraEdit Launcher for macOS
# Double-click to launch, or run: ./UmbraEdit.command
#
# Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
# Created: macOS launcher script for UmbraEdit (renamed from novelWriter).

cd "$(dirname "$0")"

# Use the project's uv-managed Python 3.12 virtual environment
export UV_PYTHON_PREFERENCE="only-managed"
exec uv run python UmbraEdit.py "$@"
