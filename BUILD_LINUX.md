# UmbraEdit - Linux AMD64 Build Guide

UmbraEdit is built on macOS (darwin/aarch64), so native Linux packages (.deb, .rpm, AppImage)
cannot be built directly from this machine. This document describes how to build
Linux AMD64 install packages from the source artifacts provided here.

## Build Artifacts

The following files are in `dist/`:

| File | Description | Purpose |
|------|-------------|---------|
| `umbraedit-2026.11.1.tar.gz` | Source distribution (sdist) | Source tarball for building on Linux |
| `umbraedit-2026.11.1-py3-none-any.whl` | Pure Python wheel | Installable via pip on any platform |

## Prerequisites on Linux AMD64

Before building, install the required system packages:

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install python3 python3-pip python3-pyqt6 python3-pyqt6.qtsvg \
    python3-enchant qt6-image-formats-plugins qt6-svg-plugins \
    dh-python debhelper python3-build python3-setuptools

# Fedora/RHEL
sudo dnf install python3 python3-pip python3-pyqt6 python3-enchant \
    qt6-qtimageformats qt6-qtsvg python3-build python3-setuptools

# Arch Linux
sudo pacman -S python python-pip python-pyqt6 python-enchant qt6-imageformats qt6-svg \
    python-build python-setuptools
```

## Option 1: Install via Wheel (Simplest)

The pure Python wheel can be installed directly on Linux AMD64 with pip:

```bash
# Copy the wheel to your Linux AMD64 machine
scp umbraedit-2026.11.1-py3-none-any.whl user@linux-machine:~/

# On the Linux machine
pip install umbraedit-2026.11.1-py3-none-any.whl

# Run UmbraEdit
umbraedit
```

This installs the application as a Python package with the `umbraedit` console script
entry point. No compilation is required.

## Option 2: Build from Source Distribution

The source tarball contains all source files needed to build native Linux packages:

```bash
# Copy the source tarball to your Linux AMD64 machine
scp umbraedit-2026.11.1.tar.gz user@linux-machine:~/

# On the Linux machine
tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1

# Build and install locally
pip install .
```

## Option 3: Build Debian (.deb) Package

On a Debian/Ubuntu-based Linux AMD64 system:

```bash
# Install build dependencies
sudo apt-get install dh-python pybuild-plugin-pyproject python3-build \
    python3-setuptools python3-all debhelper \
    python3-pytest python3-pytestqt python3-pytest-timeout

# Extract and build
tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1

# Build .deb package
python3 utils/build_debian.py --distro noble  # or trixie, resolute, stonking

# The .deb will be in dist_deb/
sudo dpkg -i dist_deb/umbraedit_*.deb
```

Available distro targets: `bookworm`, `trixie`, `noble`, `resolute`, `stonking`, `wilma`

## Option 4: Build AppImage

On any Linux AMD64 system:

```bash
# Install AppImage build tools
pip install python-appimage
sudo apt-get install appimagetool  # or download from GitHub

# Extract and build
tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1

# Build AppImage
python3 utils/build_appimage.py --linux ubuntu --arch amd64 --python 3.12

# The AppImage will be in dist_appimage/
chmod +x dist_appimage/umbraedit-2026.11-amd64.AppImage
./dist_appimage/umbraedit-2026.11-amd64.AppImage
```

## Project Storage

UmbraEdit projects are stored in plain folders with an `nwProject.nwx` file.
The sample project included in the distribution can be used for testing:

```bash
umbraedit  # Opens the welcome dialog
# Select "Sample Project" from the list, or browse to your .nwx file
```

## Version

Current development version: **2026.11.0003**

## License

GPL-3.0-or-later AND Apache-2.0 AND ISC AND MIT

UmbraEdit is based on novelWrite 2026.02 by Veronica Berglyd Olsen
(novelWriter.io), licenced under the same GPL v3.0 license.