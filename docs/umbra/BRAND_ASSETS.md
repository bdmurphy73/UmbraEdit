# Brand Asset Inventory

Last updated: 2026-11-07

This document lists every novelWriter logo, icon, and graphic in the
repository with its replacement rule. Search was performed by file type
(`svg`, `png`, `ico`, `icns`, `webp`, `iconset`) and by name
(`novelwriter`, `x-novelwriter-project`, `nw-`), and by code reference
(`assetPath`, `getIcon("novelwriter")`, `splash`, `welcome`).

## Application and Project-File Icons

| Original Path | Type | Size | Used By | Replacement | Status |
|---|---|---|---|---|---|
| `setup/icons/novelwriter.svg` | SVG | scalable | Linux desktop, packaging | `setup/icons/umbraedit.svg` | ✅ Replaced |
| `setup/icons/novelwriter.png` | PNG | 256×256 | Packaging | `setup/icons/umbraedit.png` | ✅ Replaced |
| `setup/icons/novelwriter.ico` | ICO | multi | Windows | `setup/icons/umbraedit.ico` | ✅ Replaced |
| `setup/icons/x-novelwriter-project.svg` | SVG | scalable | Project file icon (Linux) | `setup/icons/x-umbraedit-project.svg` | ✅ Replaced |
| `setup/icons/x-novelwriter-project.png` | PNG | 256×256 | Packaging | *(deleted, regenerate from source)* | ✅ Removed |
| `setup/icons/x-novelwriter-project.ico` | ICO | multi | Windows project file | `setup/icons/x-umbraedit-project.ico` | ✅ Replaced |
| `setup/data/hicolor/<size>/apps/novelwriter.png` | PNG | 16–512 | Linux desktop icons | `setup/data/hicolor/<size>/apps/umbraedit.png` | ✅ Replaced (8 sizes) |
| `setup/data/hicolor/scalable/apps/novelwriter.svg` | SVG | scalable | Linux desktop | `setup/data/hicolor/scalable/apps/umbraedit.svg` | ✅ Replaced |
| `setup/data/hicolor/<size>/mimetypes/application-x-novelwriter-project.png` | PNG | 16–512 | MIME type icons | `.../application-x-umbraedit-project.png` | ✅ Replaced (8 sizes) |
| `setup/data/hicolor/scalable/mimetypes/application-x-novelwriter-project.svg` | SVG | scalable | MIME type | `.../application-x-umbraedit-project.svg` | ✅ Replaced |
| `setup/macos/novelwriter.iconset/` | PNG set | 10 sizes | macOS .icns source | `setup/macos/umbraedit.iconset/` | ✅ Replaced |
| `setup/macos/novelwriter.icns` | ICNS | multi | macOS app bundle | `setup/macos/umbraedit.icns` | ✅ Replaced |
| `setup/windows/novelWriter.ico` | ICO | multi | Windows installer | `setup/windows/umbraedit.ico` | ✅ Replaced |

## In-App Graphics

| Original Path | Type | Size | Used By | Replacement | Status |
|---|---|---|---|---|---|
| `novelwriter/assets/images/splash.png` | PNG | 600×180 | Splash screen (`splash.py`) | `umbraedit/assets/images/splash.png` (references `NW_Splash.png`) | ⚠️ See note |
| `novelwriter/assets/images/welcome.webp` | WebP | — | Welcome dialog background (`gui/theme.py` IMAGE_MAP `"welcome"`) | `umbraedit/assets/images/welcome.webp` | ✅ Replaced |
| `novelwriter/assets/images/novelwriter-text-light.svg` | SVG | — | Light theme wordmark (`gui/theme.py` IMAGE_MAP `"nw-text"`) | `umbraedit/assets/images/umbraedit-text-light.svg` | ✅ Replaced |
| `novelwriter/assets/images/novelwriter-text-dark.svg` | SVG | — | Dark theme wordmark | `umbraedit/assets/images/umbraedit-text-dark.svg` | ✅ Replaced |
| `novelwriter/assets/icons/novelwriter.svg` | SVG | scalable | App icon (`gui/theme.py` `getIcon("novelwriter")`) | `umbraedit/assets/icons/umbraedit.svg` | ✅ Replaced |
| `novelwriter/assets/icons/x-novelwriter-project.svg` | SVG | scalable | Project file icon | `umbraedit/assets/icons/x-umbraedit-project.svg` | ✅ Replaced |

**Note on splash.png:** The splash screen currently references the
user-supplied `NW_Splash.png` in the project root (via `splash.py`).
The in-tree `splash.png` is a placeholder. The user must supply the
final splash artwork.

## Packaging and Data Files

| Original Path | Type | Used By | Replacement | Status |
|---|---|---|---|---|
| `setup/data/novelwriter.png` | PNG | Packaging | `setup/data/umbraedit.png` | ✅ Replaced |
| `setup/data/novelwriter.desktop` | Desktop | Linux | `setup/data/umbraedit.desktop` | ✅ Replaced |
| `setup/data/x-novelwriter-project.xml` | XML | MIME type | `setup/data/x-umbraedit-project.xml` | ✅ Replaced |
| `setup/novelwriter.appdata.xml` | XML | AppStream | `setup/umbraedit.appdata.xml` | ✅ Replaced |
| `setup/novelwriter_readme.png` | PNG | README | `setup/umbraedit_readme.png` | ✅ Replaced |
| `setup/novelwriter_text.png` | PNG | README | `setup/umbraedit_text.png` | ✅ Replaced |
| `setup/flatpak/io.novelwriter.novelwriter.yml` | YAML | Flatpak | `setup/flatpak/io.umbraedit.umbraedit.yml` | ✅ Replaced |

## Windows-Specific

| Original Path | Type | Used By | Replacement | Status |
|---|---|---|---|---|
| `setup/windows/novelWriter.exe` | Binary | Launcher | *(rebuild required)* | ⚠️ Still present |
| `setup/windows/novelWriter.ico` | ICO | Resource | `setup/windows/umbraedit.ico` | ✅ Replaced |
| `setup/windows/launcher.rc` | RC | Resource | *(references old icon name)* | ⚠️ See R11 |
| `setup/windows/main.cpp` | C++ | Launcher | *(product name string)* | ⚠️ See R11 |
| `setup/win_setup_embed.iss` | ISS | Installer | *(app name, icon paths)* | ⚠️ See R11 |

## Documentation

| Original Path | Type | Used By | Replacement | Status |
|---|---|---|---|---|
| `docs/source/_static/novelwriter-light.png` | PNG | Sphinx light theme | `docs/source/_static/umbraedit-light.png` | ✅ Replaced |
| `docs/source/_static/novelwriter-dark.png` | PNG | Sphinx dark theme | `docs/source/_static/umbraedit-dark.png` | ✅ Replaced |
| `docs/source/_static/novelwriter-pdf.png` | PNG | PDF cover | `docs/source/_static/umbraedit-pdf.png` | ✅ Replaced |
| `docs/source/conf.py` logo settings | Python | Sphinx | *(already updated)* | ✅ Updated |

## Non-Brand Graphics (unchanged)

The following are generic UI icon themes and are NOT brand graphics.
They stay unchanged:

- `umbraedit/assets/icons/*.icons` (Fluent UI, Lucide, Material Symbols)
- `umbraedit/assets/icons/none.svg`
- `setup/screenshot.png` (application screenshot — needs update after UI changes)
- `setup/signpath_logo.png` (third-party logo)
- `setup/cloudsmith_logo.png` (third-party logo)

## Code References Updated

| File | Line | Old Reference | New Reference |
|---|---|---|---|
| `umbraedit/gui/theme.py` | L855 | `nw-text` IMAGE_MAP key | Key unchanged; values now point to `umbraedit-text-{light,dark}.svg` |
| `umbraedit/gui/theme.py` | L1058 | `IMAGE_MAP[name]` | Values updated to umbraedit filenames |
| `umbraedit/gui/theme.py` | L1114 | `getIcon("umbraedit")` | Loads `UmbraEdit.jpg` (user-supplied) |
| `umbraedit/gui/theme.py` | L1116 | `x-novelwriter-project.svg` | `x-umbraedit-project.svg` |
| `umbraedit/splash.py` | SPLASH_IMG | `assets/images/splash.png` | Root-level `NW_Splash.png` |

## Remaining Items

| Item | Status | Action Required |
|---|---|---|
| `setup/windows/novelWriter.exe` | ⚠️ Present | Rebuild Windows launcher binary |
| `setup/windows/launcher.rc` | ⚠️ Present | Update icon reference and product strings |
| `setup/windows/main.cpp` | ⚠️ Present | Update product name string |
| `setup/win_setup_embed.iss` | ⚠️ Present | Update app name, icon paths, file associations |
| `setup/data/x-umbraedit-project.xml` | ⚠️ Glob still `*.nwx` | Keep reading novelWriter projects (intentional) |
| `splash.png` (in-tree) | ⚠️ Placeholder | User to supply final splash artwork as `NW_Splash.png` |
