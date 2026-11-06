# UmbraEdit - Linux AMD64 Build Guide

UmbraEdit is developed on macOS but builds natively on Linux AMD64 and ARM64.
This guide covers building Linux install packages from source.

## Source Distribution

The source tarball (`umbraedit-2026.11.1.tar.gz`) includes everything needed to
build Linux packages:

```
umbraedit-2026.11.1/
├── pyproject.toml          # Project metadata & dependencies
├── UmbraEdit.py            # Application entry point
├── pkgutils.py             # Packaging utility
├── run_tests.py            # Test runner
├── setup/                  # Packaging assets
│   ├── data/               # .desktop file, MIME type XML
│   ├── macos/              # macOS-specific packaging
│   └── windows/            # Windows-specific packaging
├── utils/                  # Build scripts
│   ├── build_debian.py     # .deb package builder
│   ├── build_appimage.py   # AppImage builder
│   ├── build_all.py        # Multi-platform build orchestrator
│   └── ...
├── umbraedit/              # Application source code
└── tests/                  # Test suite
```

## Prerequisites on Linux

### Debian/Ubuntu

```bash
sudo apt-get update
sudo apt-get install \
    python3 python3-pip \
    python3-pyqt6 python3-pyqt6.qtsvg \
    python3-enchant \
    qt6-image-formats-plugins qt6-svg-plugins \
    dh-python debhelper python3-build python3-setuptools \
    python3-pytest python3-pytestqt python3-pytest-timeout \
    appimagetool
```

### Fedora/RHEL

```bash
sudo dnf install \
    python3 python3-pip \
    python3-pyqt6 python3-enchant \
    qt6-qtimageformats qt6-qtsvg \
    python3-build python3-setuptools \
    dpkg rpm-build appimagetool
```

### Arch Linux

```bash
sudo pacman -S \
    python python-pip \
    python-pyqt6 python-enchant \
    qt6-imageformats qt6-svg \
    python-build python-setuptools \
    dpkg appimagetool
```

## Build Options

### Option 1: Install via Wheel (Simplest)

The pure Python wheel requires no compilation:

```bash
pip install umbraedit-2026.11.1-py3-none-any.whl
umbraedit
```

### Option 2: Install from Source Tarball

```bash
tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1
pip install .
umbraedit
```

### Option 3: Build .deb Package

```bash
tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1

# Build for Ubuntu Noble (24.04)
python3 utils/build_debian.py --distro noble --build 1

# The .deb will be in dist_deb/
sudo dpkg -i dist_deb/umbraedit_*_amd64.deb
```

Available distro targets: `bookworm`, `trixie`, `noble`, `resolute`, `stonking`, `wilma`

### Option 4: Build AppImage

```bash
pip install python-appimage
sudo apt-get install appimagetool

tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1

python3 utils/build_appimage.py --linux ubuntu --arch amd64 --python 3.12

chmod +x dist_appimage/umbraedit-2026.11-amd64.AppImage
./dist_appimage/umbraedit-2026.11-amd64.AppImage
```

### Option 5: Build All Linux Packages

```bash
tar xzf umbraedit-2026.11.1.tar.gz
cd umbraedit-2026.11.1

python3 utils/build_all.py --platform linux --arch amd64
```

## Project Storage

UmbraEdit projects are stored in plain folders with an `nwProject.nwx` file.
The sample project included in the distribution can be used for testing:

```bash
umbraedit  # Opens the welcome dialog
# Select "Sample Project" from the list, or browse to your .nwx file
```

## Version

Current development version: **2026.11.0004**

## License

GPL-3.0-or-later AND Apache-2.0 AND ISC AND MIT

UmbraEdit is based on novelWrite 2026.02 by Veronica Berglyd Olsen
(novelWriter.io), licenced under the same GPL v3.0 license.