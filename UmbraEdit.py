#!/usr/bin/env python3
"""
UmbraEdit - Start Script
==========================
"""  # noqa

import os
import sys

# Set the process name so that the operating system shows "UmbraEdit" in
# task lists and process monitors.
#
# On macOS this is skipped when the app runs from an application bundle.
# The setproctitle call rewrites the process arguments, and the operating
# system then loses track of the application bundle the process belongs to.
# The app is then registered as an unnamed application, which means a menu
# bar without an application name and no icon in the Dock. The macOS
# launcher sets the process title itself instead.
if not (sys.platform == "darwin" and any(part.endswith(".app") for part in sys.executable.split("/"))):
    try:
        import setproctitle

        setproctitle.setproctitle("UmbraEdit")
    except Exception:
        pass

os.curdir = os.path.abspath(os.path.dirname(__file__))

if __name__ == "__main__":
    import umbraedit

    umbraedit.main(sys.argv[1:])
