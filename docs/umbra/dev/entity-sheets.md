# P06 — Entity Sheets (Developer Notes)

Status: core implemented (Qt-free logic, index integration, gate rules).
Deferred: Sheets table dock, tone-set dialog, editor undo integration,
manual pages (see GAPS.md G32–G38).

## Data Formats

### Keyword lines in entity notes

```
@tag: <tag> [| <display name>]
@alias: <alias> [| <pronunciation>]     (repeatable, one per line)
@attr: <key> | <value>                  (one line per key)
```

- `@alias` and `@attr` are valid keys in `nwKeyWords.VALID_KEYS` but are
  deliberately **not** in `ALL_KEYS`, so they get no Insert-menu entry
  (G37).
- The index records them on the entity index, **not** as heading
  references, so they do not appear in outline cross-references and are
  not flagged by `unknownReferenceTag`.
- `full_name` is computed from `{title} {fn} {mn} {ln} {suffix}` and is
  never stored.

### Built-in character columns (canonical order)

`kind, slot, fn, mn, ln, nick, title, suffix, full_name, race,
race_detail, age, height, hair, eyes, lang_native, lang_alt,
personality, quirks, mannerisms, biggest_fear, biggest_confidence,
voice, voice_matrix, drop_attrib`

Places, things, and organisations: `kind, description, lang_native`.

Custom columns match `x_[a-z0-9_]{1,30}` and sort after the built-ins
(alphabetically). Column definitions per sheet kind live in
`<project>/umbra/sheet.json` (not yet written by the core; the table
dock owns it).

### Tone set — `<project>/umbra/tones.json`

```json
{"v":1,"tones":[{"key":"happy","label":"Happy","appliesTo":"dialogue","audioHint":"style=cheerful","order":10}]}
```

Seeded with 16 tones on first `loadTones()` when the file is missing,
empty, or corrupt. Hand-edited unknown tones are returned as they are;
`toneNotInSet` flags them at audio build time.

### Entity kinds

`character, place, thing, organisation, narrator, oneoff`. Kind comes
from the root item class: CHARACTER→character, WORLD→place,
OBJECT→thing, ENTITY→organisation. A non-name-root note can declare a
kind with `@attr: kind | narrator`.

## Hook Points (upstream files touched)

| File | Change |
|---|---|
| `core/index.py` `scanText` | Binds the entity index hooks (`ensureBound`) before the scan hooks fire. |
| `core/index.py` `_indexKeyword` | `@alias`/`@attr` values go to `entityindex.recordKeyword`, not `addHeadingRef`. |
| `core/index.py` `clear` | Calls `entityindex.clearEntities()`. |
| `core/index.py` `deleteHandle` | Calls `entityindex.dropEntityHandle(handle)`. |
| `core/index.py` | New public methods `getEntity(tag)` and `iterEntities(kind=None)`. |
| `constants.py` | `nwKeyWords.ALIAS_KEY`/`ATTR_KEY`, extended `VALID_KEYS`, `nwLabels.KEY_NAME`. |

## Public Functions

- `umbraedit.umbra.sheet.SheetManager(projectPath)`:
  `resolveSpeaker(text)`, `addAlias(tag, alias)`, `setAttr(tag, key, value)`,
  `getVoiceCode(tag)`, `nextSlot()`, `promoteOneOff(label)`,
  `buildFromProject(project)`, `iterEntities(kind=None)`,
  `getEntity(tag)`, `loadTones()`, `saveTones(tones)`.
- `umbraedit.umbra.sheet`: `aliasNorm(text)`, `full_name(attrs)`,
  `EntityRow`, `ToneEntry`, `DEFAULT_TONES`, `CHARACTER_COLUMNS`,
  `CUSTOM_KEY_RE`, `ENTITY_KINDS`.
- `umbraedit.umbra.entityindex`: `entityIndex()`, `ensureBound()`,
  `recordKeyword(handle, key, values)`, `clearEntities()`,
  `dropEntityHandle(handle)`.
- `umbraedit.umbra.sheetedit`: `parseSheetNote(text)`,
  `applySheetEdit(text, edit)`, `keywordBlockRange(lines)`, `SheetEdit`.
- `umbraedit.umbra.sheetgates`: registers gate rules on import (imported
  at the end of `umbra.gates`).

## Gate Rules (P06)

| Rule | Severity | Operations | Meaning |
|---|---|---|---|
| `aliasCollision` | advisory | build.run, audio.chapter, audio.book | Two entities share an alias (or tag) after `aliasNorm`. |
| `slotDuplicate` | block | build.run | Two characters share a `slot` value. |
| `toneNotInSet` | block | audio.chapter, audio.book | A tone key in a `%Voice:` line is not in `tones.json`. The value stays in the file. |
| `entityKindMissing` | advisory | build.run | A note in a name root has no `@attr: kind`. |

## Performance

`resolveSpeaker` is O(entities × name-candidates) with `aliasNorm`
cached per comparison call; budget 5 ms for 500 entities / 2,000
aliases, asserted with a 3× CI margin in
`tests/umbra/test_sheet.py::test_sheet_R9_resolveSpeaker_performance`.
