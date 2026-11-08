.. _umbra-installation:

Installation
============

Overview
========

What it is
    Instructions for installing UmbraEdit on Linux, macOS, and Windows.

What it does
    Installs the application and its dependencies.

Before you start
================

You need Python 3.11 or later. PyQt6 and PyEnchant are installed
automatically when you use ``pip``.

Quick start
===========

1. Install from the source distribution::

       pip install umbraedit-2026.11.1-py3-none-any.whl

2. Run the application::

       umbraedit

3. A Welcome dialog opens. Create a new project or open an existing one.

Linux packages
==============

On Debian and Ubuntu, install the ``.deb`` package::

    sudo dpkg -i umbraedit_*_amd64.deb

On any Linux distribution, run the AppImage::

    chmod +x UmbraEdit-*.AppImage
    ./UmbraEdit-*.AppImage

macOS
=====

Mount the ``.dmg`` file and drag ``UmbraEdit.app`` to ``/Applications``.

Windows
=======

Run the ``.exe`` installer.

See also
========

* :doc:`first-book` — Create your first project.
