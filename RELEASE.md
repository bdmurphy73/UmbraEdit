# UmbraEdit - Release Process

This document describes the release process for UmbraEdit, including versioning,
platform support, build workflows, and publishing.

## Versioning

UmbraEdit uses a **YYYY/MM.P####** versioning scheme:

| Component | Meaning |
|-----------|---------|
| `YYYY`    | Release year (e.g., 2026) |
| `MM`      | Release month (e.g., 11) |
| `####`    | Patch/build sequence (e.g., 0001) |

Examples:
- `2026.11`     - Major monthly release (November 2026)
- `2026.11.0001` - First development build of November 2026
- `2026.11.0002` - Second development build (e.g., new feature)

Git tags follow the format: `v2026.11`, `v2026.11.0001`, etc.

## Supported Platforms

| Platform | Architecture | Package Format | Build Host |
|----------|-------------|----------------|------------|
| Linux    | amd64       | .deb, .rpm, AppImage | Linux |
| Linux    | arm64       | .deb, .rpm, AppImage | Linux (ARM64) |
| macOS    | arm64       | .dmg, .app | macOS (Apple Silicon) |
| macOS    | amd64       | .dmg, .app | macOS (Intel) |
| Windows  | amd64       | .msi, .exe | Windows |
| Windows  | arm64       | .msi, .exe | Windows (ARM64) |
| iOS/iPadOS | arm64     | **NOT SUPPORTED** | N/A |

### iOS/iPadOS Support

UmbraEdit is **not available for iOS/iPadOS**. PyQt6 does not support iOS,
and UmbraEdit requires a full desktop Qt environment with keyboard, mouse,
and file system access. Porting to iOS would require a complete rewrite
using SwiftUI or a different cross-platform framework.

Users on iPad should use UmbraEdit via a VNC/remote desktop connection to a
desktop machine running UmbraEdit, or use a compatible web-based alternative.

## Release Workflow

### 1. Prepare Release

```bash
# Ensure working tree is clean
git status

# Update version in umbraedit/__init__.py
# __version__ = "2026.12.0001"

# Update CHANGELOG.md with new release entry

# Commit and tag
git add -A
git commit -m "release: prepare v2026.12"
git tag -a v2026.12 -m "Release v2026.12"
git push origin main --tags
```

### 2. Build All Platforms

On each target platform, run:

```bash
# Clone the tagged release
git clone https://git.umbratools.com/umbragit/UmbraEdit.git
cd UmbraEdit
git checkout v2026.12

# Build all packages for this platform
python utils/build_all.py --platform <platform> --arch <arch>
```

Available platforms: `linux`, `macos`, `windows`
Available architectures: `amd64`, `arm64`

### 3. Publish

Upload all build artifacts to the release server:

```bash
# Example: upload to Gitea releases
# Files to upload:
#   Linux:   dist_deb/umbraedit_*.deb, dist_appimage/*.AppImage
#   macOS:   dist_macos/umbraedit-*.dmg
#   Windows: dist_win/umbraedit-*.exe, dist_win/umbraedit-*.msi
#   Source:  dist/umbraedit-*.tar.gz, dist/umbraedit-*.whl
```

Create a release on Gitea/GitHub and attach all artifacts.

## Build Artifacts

Each platform produces the following artifacts:

### Linux (.deb + AppImage)

| File | Location | Description |
|------|----------|-------------|
| `umbraedit_<version>_amd64.deb` | `dist_deb/` | Debian package |
| `umbraedit-<version>-amd64.AppImage` | `dist_appimage/` | Portable AppImage |

### macOS (.dmg + .app)

| File | Location | Description |
|------|----------|-------------|
| `umbraedit-<version>-arm64.dmg` | `dist_macos/` | macOS disk image |
| `UmbraEdit.app` | inside .dmg | macOS application bundle |

### Windows (.exe + .msi)

| File | Location | Description |
|------|----------|-------------|
| `umbraedit-<version>-amd64.exe` | `dist_win/` | Windows installer |
| `umbraedit-<version>-amd64.msi` | `dist_win/` | Windows MSI installer |

### Source

| File | Location | Description |
|------|----------|-------------|
| `umbraedit-<version>.tar.gz` | `dist/` | Source tarball |
| `umbraedit-<version>-py3-none-any.whl` | `dist/` | Pure Python wheel |

## Build Scripts

| Script | Purpose |
|--------|---------|
| `utils/build_all.py` | Unified build orchestrator for all platforms |
| `utils/build_debian.py` | Debian/Ubuntu .deb package builder |
| `utils/build_appimage.py` | AppImage builder |
| `utils/build_windows.py` | Windows installer builder |
| `setup/macos/build.sh` | macOS .dmg builder |

## Release Checklist

- [ ] Update version in `umbraedit/__init__.py`
- [ ] Update `CHANGELOG.md` with release notes
- [ ] Tag release: `git tag -a vYYYY.MM -m "Release vYYYY.MM"`
- [ ] Push tag: `git push origin vYYYY.MM`
- [ ] Build packages for all platforms
- [ ] Test installation on each platform
- [ ] Create release on Gitea/GitHub
- [ ] Attach all build artifacts
- [ ] Publish release notes
- [ ] Announce release

## Credits

UmbraEdit is based on novelWrite 2026.02 by Veronica Berglyd Olsen
(novelWriter.io), licenced under the same GPL v3.0 license.

Current development lead: B.D. Murphy