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

## P07

### Added

- `umbraedit/umbra/pronunciation.py` — Pronunciation model and store
  - `Pron`, `EntityPron`, `PronSpan`, `Pronunciations` class
  - `getPronunciation(tag, lang)`, `setPronunciation(tag, lang, respelling, ipa)`, `markAsWritten(tag)`
  - `validateIpa(text)`: validates allowed IPA codepoints, balanced `/` and `[ ]` delimiters, with positions
  - `parsePronNote(body)`: reads `@tag`, `@alias` respelling, `@pron`, `pron_status`
  - `runPronPreview(command, text, ipa)`: runs a user-configured preview command without a shell (R5)
  - `pronunciationSpans(text, lang, project)`: pronounced name spans for the utterance index (P11) (R8)
  - `PRON_CLASSES` = CHARACTER, WORLD, OBJECT, ENTITY (PLOT/TIMELINE excluded) (R2)
  - `updatePronSeen()` / `staleEntities()` staleness cache in `umbra/cache/pron-seen.json`
  - 16 default tones are seeded once; a missing tones.json is recreated; a hand-edited unknown tone is flagged, never removed
- `umbraedit/umbra/mentions.py` — Name mention detection (R3/R6/R10)
  - `findMentions(text, entities)`: tag, display name, fn, mn, ln, nick, title, full_name, aliases; longest match wins; word boundaries; possessives and hyphenated forms; CJK without boundaries; cached per document via `textHash` (MentionCache)
  - `findUntrackedNames(texts, entities, stoplist)`: capitalised words occurring >= 3 times matching no entity, excluding sentence-initial-only words
- `umbraedit/umbra/lexicon.py` — Lexicon export (R7)
  - `exportLexicon(project, lang)`: deterministic W3C PLS 1.0 XML + JSON copy; `<phoneme>` for IPA entries, `<alias>` for respelling-only; asWritten omitted; sorted by grapheme then tag
- `umbraedit/umbra/prongates.py` — gate rules: pronunciationMissing, pronunciationLanguageMissing, pronunciationInvalidIpa, nameUntracked, pronunciationStale; registered via `umbra.gates`

### Changed

- `umbraedit/constants.py`: nwKeyWords.PRON_KEY (`@pron`) added to VALID_KEYS; nwLabels.KEY_NAME entry added
- `umbraedit/core/index.py`: `_indexKeyword` records `@pron` on the entity index; `Index` owns an `EntityIndex` instance; public `getEntity(tag)`, `iterEntities(kind=None)`, `entityHandle(tag)`; `__slots__` extended
- `umbraedit/umbra/sheet.py`: EntityRow gains displayName, prons, aliasPron fields
- `umbraedit/umbra/entityindex.py`: records @pron values; EntityRow carries pron data
- `umbraedit/umbra/sheetedit.py`: @pron rendering/parsing; header (`+++`) aware keyword block; IPA delimiter stripping

### Upstream Files Touched

- `umbraedit/constants.py`: PRON_KEY, VALID_KEYS, KEY_NAME (P07 requirement R1)
- `umbraedit/core/index.py`: entity keyword recording, Index-owned EntityIndex, entity query methods (P07 R1, P06 R1)

## P08

### Added

- `umbraedit/umbra/voicematrix.py` — UVMX version 1 voice matrix format
  - `buildVoiceMatrix(...) -> bytes` (deterministic), `parseVoiceMatrix(data) -> VoiceMatrix`, `voiceMatrixCode(data) -> str`
  - `VoiceMatrix` dataclass (engine, modelRef, languages, label, params, embedding, refSample, created, code) and `VoiceMatrixError`
  - Header: magic "UVMX", version u16, flags u16, chunkCount u32, reserved u32; chunks u16 type / u32 length / payload in ascending type order; trailer type 0x00FF with SHA-256 of all preceding bytes
  - Required chunks: ENGINE(0001), MODELREF(0002), LANGS(0003), LABEL(0007); optional EMBEDDING, EMBED_DIM, REFSAMPLE, PARAMS, CREATED; unknown chunks preserved
  - Code = `vm-` + first 12 hex of trailer hash
- `umbraedit/umbra/voicestore.py` — VoiceStore + VoiceEntry
  - Import stores the matrix as an immutable `voiceMatrix` P04 asset and adds a `umbra/voices.json` registry entry
  - Importing identical bytes returns the existing code (deduplication)
  - `getVoiceMatrix(code)`, `getVoiceEntry(code)`, `listVoices()`, `getVoice(tag, editionLang, index)`
- `umbraedit/umbra/voicematrixgates.py` — gate rules:
  voiceMatrixMissing, voiceMatrixUnknown, voiceMatrixCorrupt,
  voiceMatrixLanguage, voiceMatrixRetired; registered via `umbra.gates`

### Changed

- `umbraedit/umbra/assets.py`: `_detectMime` recognises `UVMX` magic as `application/x-uvmx`
- `umbraedit/umbra/gates.py`: `runGates` stamps `operation` onto `GateScope`

### Upstream Files Touched

- `umbraedit/umbra/assets.py`: MIME detection for UVMX (P08 import)
- `umbraedit/umbra/gates.py`: operation stamping on GateScope (gate rule context)

## P09

### Added

- `umbraedit/umbra/speakers.py` — speaker authoring logic (Qt-free)
  - `SpeakerChip`, `SpeakerProposal`, `SplitResult`, `MergeResult`
  - `chipForParagraph` (R1): assigned/proposed/unassigned/needs_review/none
  - `applySpeaker` (R2): insert/update/remove the ``%Voice:`` line above a paragraph
  - `resolvePick` (R3): aliasNorm matching over tag, name parts, aliases, full name
  - `enterProposal` (R4): alternation / unclosed-quote proposals
  - `splitParagraph` / `mergeParagraphs` (R5): voice-line preservation and drop notice
  - `loadReviewFlags` / `saveReviewFlags` / `toggleReviewFlag` (R7): ``umbra/cache/review.json``
  - `unattributedNames` (R8): attribution names matching no entity
  - `speakerSetting` (R10): ``speakers.addAliasesAutomatically`` / ``speakers.proposeAlternation``
  - `tagColor` / `tagInitials` — chip rendering helpers
- `umbraedit/umbra/speakergates.py` — gate rules `speakerUnassigned` (block audio.chapter) and `oneoffUnpromoted` (advisory), registered via `umbra.gates`

### Upstream Files Touched

- `umbraedit/umbra/gates.py`: registers `speakergates` (P09 gate rules);
  operation stamping on `GateScope` was added earlier (P07/P08). All
  P09 logic is otherwise self-contained in `umbraedit/umbra/`; GUI
  pieces are deferred to GAPS.md G54–G64.

## P10

### Added

- `umbraedit/umbra/voice.py` — tone, narration voice and attribution
  resolution (Qt-free)
  - `ToneRef`, `parseTone`, `toneNeutral` — tone key + intensity (1-3,
    default 2), rendered as ``key`` or ``key:intensity``
  - `UnitVoice`, `parseUnitVoice` — extracts tone/ntone/scene tone from
    a paragraph's ``%Voice:`` line
  - `effectiveDialogueTone` (R3): unit tone or neutral:2
  - `effectiveNarrationTone` (R3): unit ntone or scene ntone or neutral:2
  - `narrationSpeaker` (R3): @pov tag of the scene, else "narrator"
  - `AttrSpan`, `parseAttrSpans` (R5): [attr], [attr:drop], [attr:keep],
    [attr:proposal] parsing
  - `effectiveDrop` (R6): span drop/keep, else speaker drop_attrib, else
    project setting audio.dropAttributions (default false)
  - `UtteranceSpan`, `parseUttSpans`, `effectiveUtteranceSpeaker` (R8):
    [utt:spk=...;tone=...] override spans, resolution order utt →
    paragraph → defaults
- `umbraedit/umbra/voicegates.py` — gate rules
  `attribDropSameVoice` (block audio.chapter) and
  `attribProposalOpen` (advisory), registered via `umbra.gates` (R9)

### Upstream Files Touched

- `umbraedit/umbra/gates.py`: registers `voicegates` (P10 gate rules)

## P11

### Added

- `umbraedit/umbra/utterances.py` — utterance derivation (Qt-free)
  - `Utterance` dataclass with id, handle, para, kind, speaker, text, joinAfter, tone, toneI, lang, src, skip, attribution, voice, pron, hash
  - `deriveUtterances(handle, text, project, index, settings, store)` — derives utterances from document text
  - `parseTone`, `toneNeutral`, `effectiveDrop`, `parseAttrSpans`, `parseUttSpans` — re-exported from voice.py
  - `narrationSpeaker` — resolves @pov tag or narrator
  - `_speakerFromFollowingText` — resolves speaker from "said X." text following dialogue
  - `_utteranceHash` — SHA-256 of kind|speaker|text|tone|toneI|lang|voice|pron
  - `_stripShortcodes` / `_restoreShortcodes` — keyword shortcode stripping/restoration for join invariant
  - `_splitParagraphIntoSegments` — splits text into dialogue/attribution/narration segments
- `umbraedit/umbra/voicegates.py` — gate rules `attribDropSameVoice` (block audio.chapter) and `attribProposalOpen` (advisory), registered via `umbra.gates`

### Upstream Files Touched

- `umbraedit/umbra/gates.py`: registers `voicegates` (P10 gate rules)
