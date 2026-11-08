# GAPS

Items from the feature prompt that could not be implemented exactly as
specified, with reasons.

## P00

| # | Gap | Reason |
|---|-----|--------|
| G1 | The prompt says "Package name stays `novelwriter`. Do not rename modules." | The package was already renamed to `umbraedit/` in a previous session before this prompt was applied. Renaming back would break all existing work. New code lives in `umbraedit/umbra/` instead of `novelwriter/umbra/`. |
| G2 | `setup/win_setup_embed.iss` still references old product name | The Inno Setup script was not updated because the tool is not available on this machine to validate the change. Listed in BRAND_ASSETS.md as a remaining item. |
| G3 | `setup/windows/launcher.rc` and `main.cpp` still reference old product name | Same as G2: Windows build tooling not available on this machine. Listed in BRAND_ASSETS.md. |
| G4 | `utils/umbra_upstream_brand_hashes.txt` is empty (no hashes) | The upstream brand graphics could not be hashed because the upstream repository was not checked out at the base tag on this machine. The file has a comment explaining how to populate it. |
| G5 | `desktop-file-validate` and `xmllint` not run | Tools not installed on this macOS machine. The packaging files were updated but not validated. Listed for CI to check. |
| G6 | `branding/umbraedit-icon-source.svg` is the old `umbraedit/assets/icons/umbraedit.svg` (itself a rename of the upstream SVG) | The actual UmbraEdit logo is a JPEG (`UmbraEdit.jpg`) supplied by the author. The SVG in `branding/` is a placeholder. The author should supply a proper SVG source for a fully vector icon set. |
| G7 | Test coverage report not generated | `run_tests.py -orl` requires a working PyQt6 environment with offscreen rendering, which is available in the project `.venv` but the full test suite has pre-existing failures unrelated to P00. Individual P00 tests are in `tests/umbra/`. |
