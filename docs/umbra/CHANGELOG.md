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

## P02

### Added

- Gate engine: `umbraedit/umbra/gates.py` with Finding, GateRule, GateScope, GateReport, GateBlockedError
- Hook registry: `registerGate`, `runGates`, `requireGates`, `reportToJson`, `saveReport`
- Built-in rules: `emptyDocumentIncluded` (advisory), `unknownReferenceTag` (block)
- Operations constants: 11 operations defined
- Settings integration: advisory rules relaxable via `gates.relax.<ruleId>`
- JSON report schema v1 written to `umbra/cache/gate-report.json`

### Upstream Files Touched

- None (gate engine is self-contained in `umbraedit/umbra/gates.py`)

### Deferred

- R5: GUI Gates panel (`umbraedit/umbra/gui/gatespanel.py`) — deferred to avoid breaking the existing GUI while the dock system is not yet wired
- R6: Wiring `build.run` into `docbuild.py` via `requireGates` — the hook call is placed via `build.started` but `requireGates` is not yet called at the point of writing output; deferred to avoid breaking existing build flow
