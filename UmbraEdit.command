#!/bin/zsh
# UmbraEdit Launcher for macOS
# Double-click to launch, or run: ./UmbraEdit.command

cd "$(dirname "$0")"

# Use the project's uv-managed Python 3.12 virtual environment
export UV_PYTHON_PREFERENCE="only-managed"
exec uv run python UmbraEdit.py "$@"
