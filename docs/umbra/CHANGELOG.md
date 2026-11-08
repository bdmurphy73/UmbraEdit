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

## P03 (Part A: Asset Store)

### Added

- `umbraedit/umbra/assets.py` — content-addressed binary asset store
  - `addAsset(path_or_bytes, role, attrs, name) -> assetId` (streamed, content-hashed)
  - `assetPath(id)`, `iterAssets(role)`, `usedBy(id)`, `unusedAssets()`
  - `removeAsset(id)` (refused while used or immutable), `replaceAsset(id, source)`
  - `verifyAssets()` — integrity check returning gate finding dicts
- MIME type detection by content magic bytes (not extension)
- SVG security validation (rejects script, on* handlers, javascript: URLs, external refs)
- Pillow for image dimension detection
- 17 tests in tests/umbra/test_assets.py

### Upstream Files Touched

- None (asset store is self-contained in `umbraedit/umbra/assets.py`)

## P05

### Added

- `umbraedit/umbra/voiceline.py` — parseVoiceLine, formatVoiceLine, VoiceData, isVoiceLine
  - Canonical key order: spk, src, tone, ntone, lang, scope
  - Unknown keys preserved for round-trip in extra dict
  - Round-trip verified for 200 generated lines (A1)
- `umbraedit/umbra/units.py` — iterUnits for document unit splitting
  - Detects headings, paragraphs, comments, keywords, blank lines
  - Attaches VoiceData to paragraphs, detects orphan %Voice: lines
- `umbraedit/umbra/dialogue.py` — findDialogueSpans with DialogueConfig
  - Supports curly, straight, German, French, and dash-style quotes
  - Handles unclosed quotes, alternate symbols, line-start dashes
- `umbraedit/umbra/canonical.py` — canonicalTextHash (SHA-256)
  - Strips %Voice: lines, [attr]/[utt] tags, trailing whitespace
  - Changing annotations does not change the hash; changing text does (A5)

### Upstream Files Touched

- None (all parsers are self-contained in `umbraedit/umbra/`)

## P06

### Added

- `umbraedit/umbra/sheet.py` — SheetManager (resolveSpeaker, addAlias, setAttr,
  getVoiceCode, nextSlot, promoteOneOff, buildFromProject, iterEntities,
  getEntity, loadTones, saveTones), EntityRow, ToneEntry, DEFAULT_TONES
  (16 seeded tones), aliasNorm, full_name, CHARACTER_COLUMNS
- `umbraedit/umbra/entityindex.py` — EntityIndex: collects `@tag`, `@alias`,
  `@attr` data during index scans; exposes getEntity and iterEntities with
  kind resolution from the item class; module singleton bound to the index
  hooks (index.scanLine, project.closing)
- `umbraedit/umbra/sheetedit.py` — SheetEdit, applySheetEdit, parseSheetNote:
  rewrites the keyword block of a note (canonical @tag/@alias/@attr order)
  preserving everything outside the block byte for byte
- `umbraedit/umbra/sheetgates.py` — gate rules aliasCollision (advisory),
  slotDuplicate (blocks build.run), toneNotInSet (blocks audio.chapter),
  entityKindMissing (advisory); registered via umbra.gates import
- `nwKeyWords.ALIAS_KEY`/`ATTR_KEY` (`@alias`, `@attr`) added to VALID_KEYS;
  nwLabels.KEY_NAME entries added; `core/index.py` records alias/attr data
  on the entity index instead of heading references, and exposes
  `getEntity(tag)`/`iterEntities(kind)`

### Changed

- `core/index.py`: `scanText` binds the entity index hooks before the scan
  hooks fire; `clear` and `deleteHandle` keep the entity index in sync
- `tests/core/test_indexdata.py`: reference key sets now include `@alias`
  and `@attr` (consequence of the new valid keys)

### Upgrade notes

- Notes in Character/World/Object/Entity roots can now carry `@alias:` and
  `@attr: key | value` lines; they are indexed and checked by gates, and
  excluded from heading references and outline cross-references.

### Upstream Files Touched

- `umbraedit/constants.py`: nwKeyWords.ALIAS_KEY/ATTR_KEY, VALID_KEYS,
  nwLabels.KEY_NAME (P06 requirement R1)
- `umbraedit/core/index.py`: entity recording in `_indexKeyword`, sync in
  `clear`/`deleteHandle`, hook binding in `scanText`, entity query methods
  (P06 requirement R1)
