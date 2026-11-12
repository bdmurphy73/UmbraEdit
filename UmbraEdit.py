#!/usr/bin/env python3
"""
UmbraEdit - Start Script
==========================
"""  # noqa

# Set process name for macOS menu bar before anything else loads.
# Without this, macOS shows "Python" instead of "UmbraEdit" in the menu bar.
try:
    import setproctitle
    setproctitle.setproctitle("UmbraEdit")
except Exception:
    pass

import os
import sys

# Add tomllib shim for Python < 3.11
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

os.curdir = os.path.abspath(os.path.dirname(__file__))

if __name__ == "__main__":
    import umbraedit

    umbraedit.main(sys.argv[1:])
