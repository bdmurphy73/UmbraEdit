# UmbraEdit Branding

This directory contains the source artwork for all UmbraEdit icons and
graphics. Never edit a generated file by hand — use
`utils/umbra_make_icons.py` to regenerate.

## Files

| File | Description |
|------|-------------|
| `umbraedit-icon-source.svg` | Vector source for the application icon (preferred). |
| `umbraedit-icon-source.png` | Raster fallback, minimum 1024×1024 with transparency. |
| `umbraedit-icon-source.jpg` | JPEG source (as supplied by the author; `UmbraEdit.jpg`). |

## How to Regenerate

```bash
python3 utils/umbra_make_icons.py
python3 utils/umbra_make_icons.py --source branding/my-new-icon.svg
python3 utils/umbra_make_icons.py --source branding/my-icon.png --doc-shape
```

This regenerates:
- `setup/macos/umbraedit.iconset/` (10 PNG sizes) and `umbraedit.icns`
- `setup/data/hicolor/<size>/apps/umbraedit.png` (16–512 px)
- `setup/icons/umbraedit.ico` (multi-size), `umbraedit.png`, `umbraedit.svg`
- `umbraedit/assets/icons/umbraedit.png`
- `docs/source/_static/umbraedit-{dark,light,pdf}.png`

## Icon Sizes

macOS `.icns` requires: 16, 32, 128, 256, 512 px (plus @2x variants).
Windows `.ico` requires: 16, 24, 32, 48, 64, 128, 256 px.
Linux hicolor requires: 16, 24, 32, 48, 64, 128, 256, 512 px (plus scalable SVG).
