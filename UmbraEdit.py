#!/usr/bin/env python3
"""
UmbraEdit - Start Script
==========================
"""  # noqa

import os
import sys

os.curdir = os.path.abspath(os.path.dirname(__file__))

if __name__ == "__main__":
    import umbraedit

    umbraedit.main(sys.argv[1:])
