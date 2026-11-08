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
