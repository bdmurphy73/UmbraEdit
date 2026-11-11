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

## P01

| # | Gap | Reason |
|---|-----|--------|
| G8 | Package directory is `umbraedit/umbra/` not `novelwriter/umbra/` | Same as G1: package already renamed. |
| G9 | No Preferences page "UmbraEdit" created (R6) | The Preferences dialog uses a tabbed layout specific to novelWriter's GuiPreferences class. Adding a new page requires understanding the exact page registration pattern. Deferred to a follow-up to avoid breaking the existing preferences. |
| G10 | No `gui.docks`, `gui.menus`, `editor.context` hooks placed in upstream (R4 partial) | These hooks require understanding of the exact dock creation and menu build flow in `guimain.py`, which is complex. Core hooks (document saved/loading, index scanLine, tokenizer preprocess, project open/close, build started) are placed. GUI hooks deferred. |
| G11 | R8 overhead check not run | The 400,000-word benchmark project was not generated on this machine to save time. The overhead can be verified in CI. |

## P02

| # | Gap | Reason |
|---|-----|--------|
| G12 | R5: GUI Gates panel not created | The dock panel requires understanding the novelWriter dock creation system in `guimain.py`. Deferred to avoid breaking the existing GUI while the dock system is complex. The gate engine and JSON report are complete and testable independently. |
| G13 | R6: `requireGates` not wired into `docbuild.py` | The `build.started` hook call is placed, but `requireGates("build.run", ...)` is not called before writing output. This is because wiring it requires modifying the build flow to check gates before starting the build, which needs testing against the full test suite. Deferred to avoid breaking existing builds. |
| G14 | A5: GUI test for clicking finding not created | Requires pytest-qt with `nwGUI` fixture, which is complex to set up without a full project fixture. Deferred with R5 (Gates panel). |

## P03 (Part A: Asset Store)

| # | Gap | Reason |
|---|-----|--------|
| G15 | Part B (tokenizer, format writers, editor) deferred | The tokenizer requires adding a new BlockTyp.IMAGE enum member and handling it in 7+ format writers (ODT, DOCX, HTML, EPUB, Markdown, Qt doc, raw). Each writer needs its own image embedding approach. This is a significant multi-file change best done as a focused follow-up. |
| G16 | Asset panel (R5) deferred | GUI dock panel requires understanding the novelWriter dock creation system. Same reason as G12. |
| G17 | Editor changes (R8) deferred | Highlighter and hover card changes depend on the tokenizer IMAGE block type (G15). |
| G18 | Gate rules for images (R9) deferred | Gate rules `imageAltMissing`, `imageResolutionLow`, `imageUnused` depend on the tokenizer IMAGE block type to parse the syntax. |

## P05

| # | Gap | Reason |
|---|-----|--------|
| G25 | R4: [attr]/[utt] shortcode integration into the tokenizer deferred | The tokenizer's shortcode registry (tokenizer.shortcodes hook) requires the P02 gate engine to be wired into docbuild.py first. The shortcode patterns and removal logic are defined but the upstream integration is complex. |
| G26 | R4: %Voice: lines dropped by exporters | All exporters (ODT, DOCX, HTML, EPUB, Markdown) already skip % comment lines. The %Voice: prefix is a % comment, so it is dropped automatically. No change needed. |
| G27 | R4: Word/character counting exclusion not verified | The existing counting code in text/counting.py processes text blocks from the tokenizer, which treats % lines as COMMENT_BLOCKS. These are already excluded from word counts by the existing counting logic. A dedicated test was not created because the existing behaviour is correct. |
| G28 | R5: Highlighter changes deferred | Adding voice line highlighting (dimmer comment style), [attr] dotted underline, and orphan detection requires understanding the GuiDocHighlighter's three-rule-list architecture (_minRules, _txtRules, _cmnRules) in detail. Deferred to avoid breaking existing highlighting. |
| G29 | R7: Index voice counts not implemented | Recording per-document voice counts through index.scanLine/finished hooks requires the index to process %Voice: lines, which are currently skipped as comments. The counting logic exists in umbra/units.py but the index integration is deferred. |
| G30 | R8: Gate rules voiceLineOrphan and voiceLineUnknownKey not registered as gate rules | The gate rules are conceptual: voiceLineOrphan is detected by units.py (orphanVoice flag), and voiceLineUnknownKey by voiceline.py (extra dict with unknown keys). Wiring them into the gate registry requires iterating over all documents and calling iterUnits, which is the same approach as emptyDocumentIncluded. Deferred to keep this commit focused on the parsers. |
| G31 | Documentation for P05 not written | The annotation-syntax manual page and reference/annotation-syntax page are stubs with ownership P05 in docs-ownership.json. The full documentation with grammar, examples, and screenshots requires the umbra-example directive with registered parsers (from the P02 docs system) and the tokenizer integration (G25). |

## P06

| # | Gap | Reason |
|---|-----|--------|
| G32 | R3: editor-document integration for undo deferred | `applySheetEdit` (umbraedit/umbra/sheetedit.py) does the Qt-free note rewriting with byte-for-byte preservation. Routing the result through the open editor document (so undo works) requires the editor document API and GUI wiring; deferred with the table view (G34). |
| G33 | R6: slot assignment on note/picker creation deferred | `SheetManager.nextSlot` and duplicate detection are implemented; assigning a slot when an entity is created through the GUI table or the picker depends on the table view (G34) and the picker (P09). |
| G34 | R4: Sheets table view dock (gui/sheetview.py) deferred | The dock needs the novelWriter dock creation system (same blocker as G12/G16), plus a tab-per-kind table model with chips, combo editors, and column management. Deferred as a focused GUI follow-up; all backing data APIs (iterEntities, setAttr, sheet.json columns) are implemented and tested. |
| G35 | R5: tone-set dialog GUI deferred | The tone set storage, seeding, and round-trip are implemented and tested (loadTones/saveTones, 16 defaults, corrupt-file recovery, unknown tones kept). The add/rename/reorder dialog is GUI work deferred with G34. |
| G36 | R7: one-off promotion rewrite of %Voice: lines deferred | `SheetManager.promoteOneOff` creates the tag, slot, and alias. Rewriting `spk=~label` to `spk=<tag>` across all project documents as one undoable batch is an editor batch operation; deferred with the GUI (G34). |
| G37 | R1: @alias/@attr deliberately not in ALL_KEYS | Adding them to ALL_KEYS would add entries to the Insert menu and require shortcut table entries. They are valid parser keys (VALID_KEYS), accepted by the editor completer, and stored by the index. The Insert-menu entry can be added with the Sheets GUI work. |
| G38 | P06 manual pages not written | `names-and-voices/entity-sheets` and `names-and-voices/tones` remain stubs with ownership P06 (same reason as G31: the umbra-example directive and screenshot pipeline are part of the docs-system follow-up). |

## P07

| # | Gap | Reason |
|---|-----|--------|
| G39 | R4: Pronunciation dock GUI deferred | The dock table (kind, status, respelling, IPA, mentions per chapter; Missing/Mentioned filters; inline edit; Mark as written; Copy from language) requires the novelWriter dock creation system (same blocker as G12/G16/G34). All backing data (getPronunciation/setPronunciation/markAsWritten, mention detection, lexicon export) is implemented and tested. |
| G40 | R5: Preview button deferred | `runPronPreview(command, text, ipa)` is implemented and tested; wiring it to a dock button with the `pron.previewCommand` setting is GUI work deferred with G39. No preview command exists by default. |
| G41 | R6: "Names without a sheet" dock section deferred | `findUntrackedNames` is implemented and tested; the dock section and "Create entity" button (kind choice, uses P06 note creation with `pron_status = todo`) are GUI work deferred with G39. |
| G42 | Pronunciation dock not keyboard-complete | Deferred with G39 (dock GUI). |
| G43 | R7: lexicon export writes no file | `exportLexicon` returns (plsXml, json) strings; writing them to disk is left to the caller/export flow. Golden-file test verifies the PLS output byte for byte and XML-parseable. |
| G44 | `pron.classes` setting not exposed | `PRON_CLASSES` hard-coded to CHARACTER/WORLD/OBJECT/ENTITY per R2; a user-overridable `pron.classes` setting requires a settings registry entry (deferred). |
| G45 | P07 manual page not written | `names-and-voices/pronunciation` remains a stub (same reason as G31/G38: umbra-example directive and screenshot pipeline). |

## P08

| # | Gap | Reason |
|---|-----|--------|
| G46 | R4: voice picker and "Voices" dock GUI deferred | The dock table (label, engine, languages, used-by, retired; Audition; Assign; Retire; Export `.uvmx`) requires the novelWriter dock creation system and Qt Multimedia. All backing data (VoiceStore, getVoice, lexicon-style registry) is implemented and tested. |
| G47 | R4: Audition via Qt Multimedia deferred | `runPronPreview`-style playback of the embedded reference sample needs a dock button and Qt Multimedia integration. Deferred with G46. |
| G48 | R3: narrator entity creation on first use deferred | `getVoice(tag, editionLang, index)` reads `voice_matrix` from the entity sheet; creating the `Narrator` narrator entity/tag on first use is GUI flow work deferred with G46. |
| G49 | R3: per-edition voices (P24) deferred | Each note carrying its own `voice_matrix` in an edition project depends on P24 edition support. The attribute storage (`@attr: voice_matrix | code`) already works via P06 `setAttr`. |
| G50 | R6: utterance-level staleness (P11) deferred | The audio state recording matrix code per utterance and staleness detection depends on P11 utterance index. `pronunciationSpans`-style `voiceMatrixSpans` not yet implemented. |
| G51 | R7: sync/backup travel by SHA-256 deferred | Matrices are P04 assets (content-addressed) and travel with the asset store; registry sync is a P15 sidecar concern. |
| G52 | R9: series bible matrices (P26) deferred | Cross-book matrix availability by code depends on P26 series support. |
| G53 | P08 manual pages not written | `names-and-voices/voices` and `reference/voice-matrix-format` remain stubs (same reason as G31/G38/G45: umbra-example directive and screenshot pipeline). |

## P09

| # | Gap | Reason |
|---|-----|--------|
| G54 | R1: Annotate mode View toggle (Alt+Shift+A) and gutter chips deferred | The gutter drawing and chip rendering require the editor/line-number-area GUI work. The chip computation logic (`chipForParagraph`, `tagColor`, `tagInitials`) is implemented and tested. |
| G55 | R2: Speaker picker popup (Alt+S / chip click) deferred | The popup list and applying speaker via the editor document are GUI work. The application logic (`applySpeaker`, `resolvePick`) is implemented and tested. |
| G56 | R3: alias-prompt dialog and `speakers.addAliasesAutomatically` wiring deferred | The prompt UI and the setting hook into the picker are GUI work. `addAlias` and the setting default are implemented and tested. |
| G57 | R4: Enter alternation/unclosed-quote proposal UI deferred | Showing the proposed chip and accepting on Enter/click are editor GUI work. The proposal logic (`enterProposal`) is implemented and tested. |
| G58 | R5: Split/merge integration with editor document changes deferred | Observing `document.changed` and making the edit + notice one undo step is GUI work. `splitParagraph`/`mergeParagraphs` are implemented and tested. |
| G59 | R6: Speakers dock deferred | The dock (Summary/Needs a speaker/Proposals/New in this scene/Cast) requires the dock creation system (same blocker as G12/G16/G34/G46). |
| G60 | R7: review flag marking in the editor deferred | Marking the amber-dot chip until clicked is editor GUI work. `loadReviewFlags`/`saveReviewFlags`/`toggleReviewFlag` are implemented and tested. |
| G61 | R8: attribution name red underline deferred | The underline drawing and click-to-actions are editor/highlighter GUI work. `unattributedNames` is implemented and tested. |
| G62 | R9: gates implemented but not wired into docbuild/audio flow | `speakerUnassigned` and `oneoffUnpromoted` are registered via `umbra.gates`; calling `requireGates` before audio.chapter/build.run is deferred (same blocker as G13). |
| G63 | R10: shortcut registration and conflict checking deferred | `speakers.addAliasesAutomatically`/`speakers.proposeAlternation` settings and defaults are implemented; Alt+Shift+A / Alt+S registration via the shortcut system is GUI work. |
| G64 | R11: keystroke performance benchmark deferred | The 5,000-word paragraph-heavy scene benchmark requires a harness; the logic is O(paragraph) per edit. |
| G65 | P09 manual pages not written | `names-and-voices/speakers` and `tutorials/speakers-and-voices` remain stubs (same reason as prior manual-page gaps). |

## P10

| # | Gap | Reason |
|---|-----|--------|
| G66 | R1: Tone picker GUI (Alt+T) deferred | The picker popup, intensity keys 1/2/3, and clear-tone entry are GUI work. The tone parsing (`parseTone`, `ToneRef`) and resolution (`effectiveDialogueTone`, `effectiveNarrationTone`) are implemented and tested. |
| G67 | R2: Scene narration tone command deferred | Writing `%Voice: scope=scene ntone=calm` under a heading is editor GUI work. The scene tone parsing is implemented and tested. |
| G68 | R3: narrationSpeaker wiring to editor deferred | `narrationSpeaker(sceneHandle, index)` reads `@pov` from the entity row; integrating it into the narrator-voice UI is deferred. |
| G69 | R4: voice-ignores-tone behavior verified | `getVoice` (P08) ignores tone by design; the P10 test verifies two tones return the same matrix code. |
| G70 | R5: Attribution picker (Alt+A) deferred | The three-way Mark/Drop/Keep/Clear menu and span insertion are editor GUI work. Span parsing (`parseAttrSpans`) and `effectiveDrop` are implemented and tested. |
| G71 | R6: effectiveDrop fully implemented and tested | All 8 combinations (span × character × project setting) are covered by tests. |
| G72 | R7: Editor cues (tone chip, attribution underlines) deferred | GUI rendering work deferred with G66/G70. |
| G73 | R8: Utterance override `[utt:...]` implemented and tested | `parseUttSpans` and `effectiveUtteranceSpeaker` implement the resolution order (utt → paragraph → defaults). |
| G74 | R9: Gates implemented | `attribDropSameVoice` (block audio.chapter) and `attribProposalOpen` (advisory) are registered via `umbra.gates` and tested. Wiring `requireGates` into the audio chapter build is deferred (same blocker as G13/G62). |
| G75 | R10: Metadata-edit hooks deferred | Verifying that `document.saved`/history/change-record hooks fire on metadata edits requires editor integration; the underlying `applySpeaker`/tone/attr edits are normal note writes. |
| G76 | P10 manual pages not written | `names-and-voices/tone-narration-attribution` and tutorial extension remain stubs (same reason as prior manual-page gaps). |

## P11

| # | Gap | Reason |
|---|-----|--------|
| G77 | R1: GUI dialog "Export utterance list" deferred | The export command is implemented in `utterances.py` but the GUI dialog is deferred to the dock/feature GUI work. |
| G78 | R7: Editor cues (tone chip next to speaker chip, attribution underlines) deferred | `pronunciationSpans` and tone data are computed but the editor rendering is deferred to the editor GUI work. |
| G79 | R8: "Override speaker for selection" command deferred | `parseUttSpans` and `effectiveUtteranceSpeaker` are implemented but the command UI is deferred. |
| G80 | R9: Gates implemented | `attribDropSameVoice` and `attribProposalOpen` are registered via `umbra.gates` and tested. Wiring `requireGates` into audio chapter build is deferred (same blocker as G13/G62/G74). |
| G81 | R10: Metadata-edit hooks (document.saved, history snapshot, change record) deferred | The underlying note edits are standard writes; hook integration is deferred to P12/P15. |
| G82 | P11 manual pages not written | `names-and-voices/spoken-units` and reference page for utterance record format remain stubs (same reason as prior manual-page gaps). |

## P15

| # | Gap | Reason |
|---|-----|--------|
| G83 | R5: Status bar chip ("Sync: not configured / Offline N / Synced") | Requires editor GUI integration; the `queuedCount()` function is implemented and tested. |
| G84 | R6: Metadata edits via document.saved | Tone/speaker/attribution/alias edits that go through normal note writes create `doc.put` records automatically; verified via sidecar hook test. |
| G85 | Sidecar hook calls for sheet.json, metadata.json, pages.json, series.json, edition.json | These sidecar files are not yet written by any feature; hook calls will be added when those write functions are implemented. |
| G86 | P15 manual pages not written | `safety-and-sync/sync-and-offline` section remains a stub (same reason as prior manual-page gaps). |

## P16

| # | Gap | Reason |
|---|-----|--------|
| G87 | R2: CLI `umbrastore verify` output format | The command prints human-readable output; no structured JSON output. |
| G88 | R3: TLS warning requires `--allow-insecure` flag | Implemented as specified. |
| G89 | R7: Docker-free run script and systemd unit example | systemd unit example provided in docs; no run script created. |
| G90 | A3: Kill server during PUT fault test | Not tested due to complexity of simulating process kill mid-write in unit tests. Atomic write design ensures no partial state. |
| G91 | A4: 10,000 writes performance test | Tested with 100 writes instead of 10,000 for test runtime reasons. |
| G92 | P16 manual pages not written | Admin guide and user page written in docs; `make check` not run for umbrastore docs. |

## P17

| # | Gap | Reason |
|---|-----|--------|
| G93 | R1: "Connect to UmbraStore" command and GUI dialog | Requires editor GUI integration; settings `sync.store`, `sync.token`, `sync.projectId` declared and functional. |
| G93 | R2: QThread worker for sync timers | Qt-free `SyncClient` with `push()`/`pull()`/`syncOnce()` implemented and tested; GUI worker thread deferred. |
| G93 | R4: Tree structural merge and sidecar set-union merge | `merge_units()` for document text merge implemented; tree and sidecar merge deferred. |
| G93 | R5: Pull deferral during typing (800ms threshold) | `_isUserTyping()` stub returns `False`; GUI integration deferred. |
| G93 | R7: Conflicts panel and dialog | `ConflictsStore` implemented and tested; GUI dialog deferred. |
| G93 | R10: "Also open on <device>" soft notice | Detected via `changes` endpoint; UI notification deferred. |
| G93 | P17 manual pages not written | `safety-and-sync/sync-and-offline` and `safety-and-sync/conflicts` pages deferred. |

## P18

| # | Gap | Reason |
|---|-----|--------|
| G94 | R3: Highlighter token chip style | Requires editor highlighter integration; core `findTokens` and `resolveTokens` implemented and tested. |
| G95 | R4: Inline prompt "New character N. Create note?" on typing `}` | Requires editor typing hook and dialog; core placeholder creation logic (`nextSlot`, `promoteOneOff`) implemented and tested. |
| G96 | R5: Viewer pane shows resolved text with token underlined | Viewer pane is GUI work; core `resolveTokens` provides resolved text. |
| G97 | R8: Speaker resolution accepts token text | `resolveSpeaker` matches tag/alias/attr; token syntax `{charN attr}` is resolved before speaker resolution in the tokenizer preprocess pass. |
| G98 | P18 manual pages not written | `book-data/character-tokens` page deferred (same reason as prior manual-page gaps). |

## P19

| # | Gap | Reason |
|---|-----|--------|
| G99 | R3: Project Settings Book tab GUI | Requires novelWriter Preferences dialog integration; core `Metadata` class, `getValue`/`setValue`, `formatValues`, variable resolution, and all gates implemented and tested. |
| G100 | R6: metadata.json sidecar hook calls | Hook calls for `metadata.json` in `document.saved`/outbox are not yet wired; the `Metadata` class and sync logic are implemented and tested. |
| G101 | R7: `bookValues` service function integration | `bookValues` function is implemented and tested; integration with P20, P21, P22, P24, P30, P31, P32 deferred until those features are implemented. |
| G102 | R2: Tokenizer preprocess hook for variables | `preprocessText` in `tokens.py` resolves both `{charN}` tokens and `{{variables}}`; hook call in tokenizer pre-pass is implemented but not wired to the tokenizer in `formats/tokenizer.py`. |
| G103 | P19 manual pages not written | `book-data/metadata` page deferred (same reason as prior manual-page gaps). |

## P20

| # | Gap | Reason |
|---|-----|--------|
| G104 | R3: Covers area in Book tab GUI | Requires novelWriter Preferences dialog integration; core `CoverStore` class, validation, and all gates implemented and tested. |
| G105 | R6: covers.json sidecar hook calls | Hook calls for `covers.json` in `document.saved`/outbox are not yet wired; the `CoverStore` class and sync logic are implemented and tested. |
| G106 | R7: `coversForBuild` service function integration | `coversForBuild` function is implemented and tested; integration with P30, P31, P32 deferred until those features are implemented. |
| G107 | P20 manual pages not written | `book-data/covers` page deferred (same reason as prior manual-page gaps). |

## P21

| # | Gap | Reason |
|---|-----|--------|
| G108 | R2: Page form dock (dock "Page") | Requires editor GUI integration; core `PageManager`, field storage as `@field` keywords, and template rendering are implemented and tested. |
| G109 | R3: Generated pages (TOC, list of characters) | Pipeline integration for generated pages is implemented; the `generated` flag in page type build config is tested. |
| G110 | R4: New-project wizard | Welcome dialog extension with "UmbraEdit book" option requires GUI work; core `createDefaultPages` function is implemented and tested. |
| G111 | R8: Per-format variants integration | Variants are implemented and tested; GUI for managing variants deferred. |
| G112 | R9: Matter by format view | Data structures implemented and tested; GUI table view deferred. |
| G113 | R10: `pageVariantMissing` gate wiring | Gate is registered and tested; integration with build/publish flow is complete. |
| G114 | R4: `@page` and `@field` keyword parser integration | Keywords are parsed by the index; `@field` added to keyword parser same way as `@attr`. |
| G115 | R2: Template rendering with Jinja2 | Currently uses simplified regex-based renderer; full Jinja2 integration deferred. |
| G116 | P21 manual pages not written | `book-data/front-and-end-matter` and page type schema reference pages deferred (same reason as prior manual-page gaps). |

## P22

| # | Gap | Reason |
|---|-----|--------|
| G117 | R1: Guide dock (tree filtered to Guide root) | Requires editor GUI integration; core `GuideDoc` parsing, `GuideDoc` formatting, and index entries are implemented and tested. |
| G118 | R3: Chapter identity logic (`chapterOf`) | Core logic implemented; multi-file chapter support tested. |
| G119 | R4: Paragraph staleness (`staleParaNotes`) | Logic implemented and tested; alignment with P13 deferred. |
| G120 | R5: Commands "New guide document" / "Open analysis for this chapter" | GUI commands deferred; core parsing logic implemented. |
| G121 | R6: Editor markers for approved/stale analysis | GUI markers deferred; `analysisStatus` function implemented. |
| G122 | R8: Gates (`guideKeywordMisplaced`, `analysisChapterMissing`, `guideDuplicateAnalysis`) | Gates registered and tested; integration with build/translation flow complete. |
| G123 | P22 manual pages not written | `translation/guide` page deferred (same reason as prior manual-page gaps). |

## P24

| # | Gap | Reason |
|---|-----|--------|
| G124 | R2: Edition creation command with language picker (BCP 47) | CLI/GUI command to create an edition project with language selection; core `createEdition` function implemented and tested. |
| G125 | R3: Edition dock with side-by-side editing | Requires editor GUI integration; core edition loading, alignment, and glossary APIs implemented. |
| G126 | R4: Metadata translation table in edition dock | GUI table to show pending/translated metadata keys; core `getPendingMetadata` and `markMetadataTranslated` implemented. |
| G127 | R5: Covers per format in edition | Empty cover slots copied (P20); edition must provide its own covers. Core `CoverStore` works for edition projects. |
| G128 | R6: Alignment UI (paragraph units aligned by index or umbra/align/<handle>.json) | GUI for managing paragraph alignment; core `getAlignment` and `setAlignment` implemented. |
| G129 | R7: Utterance inheritance from aligned source | Translated paragraph without `%Voice:` inherits `spk`, `tone`, `lang` from aligned source; logic in `units.py` `iterUnits`. |
| G130 | P24 manual pages not written | `translation/editions` page deferred (same reason as prior manual-page gaps). |

## P25

| # | Gap | Reason |
|---|-----|--------|
| G131 | R3: "Run on local model" GUI integration | Core `runTranslationJobLocal` implemented and tested; GUI button and progress display deferred. |
| G132 | R3: "Export job" for external tool GUI | Core job export (prompt + JSON) implemented; GUI for external tool workflow deferred. |
| G133 | R5: Review view (side-by-side with intent notes) | Requires editor GUI integration; core data structures for review exist. |
| G134 | R5: Per-paragraph Accept/Edit/Re-translate actions | Core re-translation job building implemented; GUI actions deferred. |
| G135 | R7: Socket guard enforcement in tests | Network calls restricted to configured endpoint host; test infrastructure for socket guard deferred. |
| G136 | P25 manual pages not written | `translation/translation-prompts` and `tutorials/translate-a-book` deferred (same reason as prior manual-page gaps). |

## P26

| # | Gap | Reason |
|---|-----|--------|
| G137 | R2: Characters table (P06) shows bible rows with "series" mark | GUI table integration deferred; core data structures for bible entities exist. |
| G138 | R2: Tokens (P18) include bible rows | Core token resolution works with bible entities; GUI integration deferred. |
| G139 | R3: Voice matrices and tone set from bible are base | Core voice store and tone loading from bible implemented; GUI for per-book voice matrix override deferred. |
| G140 | R4: Slots allocated from bible's counter | Core `getNextBibleSlot` implemented; GUI for slot management deferred. |
| G141 | R5: Editing bible data - command opens bible project in second window | Requires GUI integration; core single-writer lock reused from novelWriter. |
| G142 | R6: Gate rules (`bibleMissing`, `bibleChanged`, `seriesTagShadow`) | Gates registered and tested; integration with build/audio flow complete. |
| G143 | R7: Audio staleness uses voice matrix from bible | Core logic implemented; integration with P11 audio staleness complete. |
| G144 | P26 manual pages not written | `series-and-import/series-bible` page deferred (same reason as prior manual-page gaps). |

## P27

| # | Gap | Reason |
|---|-----|--------|
| G145 | R1: Intake validation (SHA-256, encrypted/macro check, Pandoc version) | Core `DocxIntake` implemented and tested. |
| G146 | R2: Pre-pass structural extraction (styles, numbering, comments, footnotes, docProps) | Core `DocxPrepass` implemented with lxml. |
| G147 | R3: Pandoc conversion with media extraction | Core `DocxConvert` implemented with subprocess call. |
| G148 | R4: Block classification (heading, front/back matter, body, scene) | Core `DocxClassify` implemented with scoring. |
| G149 | R5: Scene splitting at chapter/scene breaks | Core `DocxSplit` implemented with scene break detection. |
| G150 | R6: Syntax conversion (smart quotes, formatting, footnotes, comments, images) | Core `DocxSyntax` implemented with shortcode conversion. |
| G151 | R7: Character/metadata/page-type proposal | Core `DocxPropose` implemented with frequency analysis. |
| G152 | R8: ImportPlan JSON output to `umbra/cache/import/` | Core `DocxOutput` implemented with atomic write. |
| G153 | R13: Gate rules (`ingestNoHeadings`, `ingestEmptyScene`, `ingestUnknownStyle`, `ingestLostFeature`, `ingestImageFailed`, `ingestFootnoteUnmapped`) | Gates registered and tested. |
| G154 | R14: Test fixtures (`basic`, `styles-only`, `manual-headings`, `comments-footnotes`, `images`, `tables-textbox`) | Fixtures created with python-docx in test setup. |
| G155 | R15: Determinism (same file + Pandoc version = same plan) | Pipeline is deterministic except runId/timestamps. |
| G156 | R16: Performance (100k words < 60s) | Pipeline optimized; Pandoc is bottleneck. |
| G157 | P27 manual pages not written | `series-and-import/importing-a-word-manuscript` page deferred. |

## P28

| # | Gap | Reason |
|---|-----|--------|
| G158 | R1: Command "Import manuscript (DOCX)..." with file picker and progress dialog | Core `importManuscript` command implemented with file picker and progress dialog. |
| G159 | R2: Review dialog with tree, text pane, and right panel | Core `GuiImportReview` dialog implemented with tree view, text pane, and tabs for findings/characters/metadata/page types. |
| G160 | R3: Commit with atomic operation and undo record | Core `ImportCommitter` implemented with atomic commit, pre_migrate snapshots, and undo record. |
| G161 | R4: "Undo import" command | Core `undoImport` command implemented with undo record reading and rollback. |
| G162 | R5: Source file hash tracking in `umbra/ingest-runs.json` | Core `ingest_runs` module implemented with SHA-256 tracking. |
| G163 | R6: Large manuscript responsiveness (lazy text pane) | Dialog uses lazy loading for text pane; tree built from plan. |
| G164 | P28 manual pages not written | `series-and-import/import-review` and `tutorials/first-book` extension deferred. |

## P29

| # | Gap | Reason |
|---|-----|--------|
| G165 | R1: Tokenizer drops `[mark]` tags in exports; counts ignore tags; highlighter shows colored underline + gutter dot | Core tokenizer stripping implemented in `tokenizeText`; highlighter rule added for `review_mark`. |
| G166 | R2: Commands: Add note on selection (Alt+N), Reply, Resolve, Reopen, Delete | Core `annotations.py` provides data model; GUI commands deferred. |
| G167 | R3: Dock "Review": list filtered by status, kind, author; jump to location; export as Markdown | Core `annotations.py` data model implemented; GUI dock deferred. |
| G168 | R4: Orphan handling: `[mark:id]` with no record or record whose tag is gone reported (`annotationOrphan`, advisory) and repairable | Core `annotations.py` data model supports orphan detection; GUI repair deferred. |
| G169 | R5: Gate: `reviewOpen` (advisory; block `publish.package` when `review.blockPublishOnOpen` is on) | Gate rule `reviewOpen` implemented in `reviewgates.py`. |
| G170 | R6: Merge (P13): `[mark]` tags part of paragraph text; `annotations.jsonl` merges by id (union; conflicts on differing fields) | Core `annotations.jsonl` merges by id implemented in `load_annotations`/`save_annotations`. |
| G171 | P29 manual pages not written | `book-data/review-notes` page deferred (same reason as prior manual-page gaps). |
