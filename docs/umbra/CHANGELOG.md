# UmbraEdit Changelog

All notable changes to UmbraEdit are documented here.

## [Unreleased]

### Added

- P00: `umbraedit/umbra/brand.py` — single source of truth for product name
- P00: `utils/umbra_gen_project.py` — deterministic benchmark project generator
- P00: `utils/umbra_bench.py` — performance benchmark tool
- P00: `utils/umbra_upstream_check.py` — upstream changed-file lister
- P00: `utils/umbra_brand_audit.py` — brand graphic hash audit
- P00: `utils/umbra_make_icons.py` — icon regeneration from source
- P00: `utils/umbra_upstream_brand_hashes.txt` — known upstream brand hashes
- P00: `branding/` — source artwork directory
- P00: CI workflow for ruff, pyright, tests (offscreen)
- P00: `docs/umbra/BASE.md`, `BRAND_ASSETS.md`, `UPSTREAM_SYNC.md`, `BENCHMARK.md`
- P00: `GAPS.md`
- P00: Entry point `umbraedit` in `pyproject.toml`

### Changed

- P00: All novelWriter icons and graphics renamed/replaced with UmbraEdit assets
- P00: Website URLs updated to umbratools.com/umbraedit
- P00: Version format changed to YYYY/MM.#### (e.g., 2026.11.0005)

### Upstream Files Touched

See `docs/umbra/BASE.md` for the full list. Key upstream files touched:
- `umbraedit/__init__.py` (branding, single instance)
- `umbraedit/gui/theme.py` (icon references)
- `umbraedit/gui/mainmenu.py` (Save As menu)
- `umbraedit/core/project.py` (saveProjectAs)
- `umbraedit/splash.py` (splash image path)
- `pyproject.toml` (project name, entry points)
