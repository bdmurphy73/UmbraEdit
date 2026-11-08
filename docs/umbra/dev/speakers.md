# P09 — Speaker Authoring (Developer Notes)

Status: core logic implemented (Qt-free). GUI pieces (annotate-mode
toggle, gutter chips, picker popup, Speakers dock, editor marking,
underlines, shortcuts) are deferred to GAPS.md (G54–G64).

## Data structures

### SpeakerChip (R1)

```python
@dataclass(frozen=True)
class SpeakerChip:
    kind: str            # "assigned" | "proposed" | "unassigned" |
                         # "needs_review" | "none"
    tag: str | None = None
    label: str = ""      # initials (assigned) or "?" (unassigned)
    color: str = ""      # stable hex per tag (assigned)
    dashed: bool = False # proposed only
```

- `assigned`: solid chip with speaker initials + color stable per tag
  (`tagColor`).
- `proposed`: dashed chip (`src=machine` or alternation guess).
- `unassigned`: amber ring with `?`, only for paragraphs with a
  dialogue span.
- `needs_review`: amber dot, set when an edit adds/removes a quoted
  span in an assigned paragraph (R7).
- `none`: paragraph with no dialogue span shows no chip.

### SpeakerProposal (R4)

```python
@dataclass(frozen=True)
class SpeakerProposal:
    tag: str
    reason: str  # "alternation" or "unclosed_quote"
```

## Public functions

- `umbraedit.umbra.speakers.chipForParagraph(paragraphText, entities,
  dialogueSpans, reviewFlags, handle="", lineNo=0) -> SpeakerChip` (R1)
- `umbraedit.umbra.speakers.enterProposal(previousVoices,
  lastParagraphEndsWithUnclosedQuote) -> SpeakerProposal | None` (R4)
- `umbraedit.umbra.speakers.applySpeaker(paragraphText, tag, entities)
  -> str` (R2): inserts/updates/removes the ``%Voice:`` line above the
  paragraph.
- `umbraedit.umbra.speakers.resolvePick(text, entities)
  -> (list[EntityRow], bool)` (R3): aliasNorm-based matching over tag,
  name parts, aliases, full name.
- `umbraedit.umbra.speakers.splitParagraph(paragraphText, splitIndex)
  -> SplitResult` (R5): first part keeps the voice line.
- `umbraedit.umbra.speakers.mergeParagraphs(firstText, secondText)
  -> MergeResult` (R5): keeps the first voice line; `dropped` names a
  different spk/tone from the second part.
- `umbraedit.umbra.speakers.loadReviewFlags(projectPath)
  -> set[(str, int)]` / `saveReviewFlags` / `toggleReviewFlag` (R7):
  stored in ``<project>/umbra/cache/review.json`` (sorted keys, compact,
  trailing newline).
- `umbraedit.umbra.speakers.unattributedNames(paragraph, entities)
  -> list[UnattributedName]` (R8): attribution names in ``[attr]``
  spans matching no entity.
- `umbraedit.umbra.speakers.speakerSetting(settings, key)` (R10):
  reads ``speakers.addAliasesAutomatically`` (default false) and
  ``speakers.proposeAlternation`` (default true).
- `umbraedit.umbra.speakers.tagColor(tag)` / `tagInitials(tag,
  entities)` — helpers for chip rendering.

## Gate rules (R9)

| Rule | Severity | Operations | Meaning |
|------|----------|------------|---------|
| `speakerUnassigned` | block | audio.chapter | A paragraph with a dialogue span has no speaker, or a `src=machine` proposal. Advisory equivalent used for build.run. |
| `oneoffUnpromoted` | advisory | build.run, audio.chapter | A one-off speaker (``spk=~label``) speaks in more than five dialogue paragraphs. |

Both are registered at the end of ``umbra.gates``. Calling
``requireGates`` before ``audio.chapter``/``build.run`` is deferred
(G62).

## Hook points

No upstream files are modified for the core logic. `umbra.gates.py`
was extended to stamp the running `operation` onto `GateScope` (shared
with P06/P07/P08) and to register `speakergates`.

## Settings (R10)

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `speakers.addAliasesAutomatically` | bool | false | Skip the "add alias" prompt. |
| `speakers.proposeAlternation` | bool | true | Propose alternation on Enter. |

Shortcuts (Alt+Shift+A annotate toggle, Alt+S picker) are deferred
(G63).

## Tests

- `tests/umbra/test_speakers.py` — chips (R1), apply speaker (R2),
  resolve pick (R3), enter proposal (R4), split/merge (R5), review
  flags (R7), unattributed names (R8), settings (R10).
- `tests/umbra/test_speakergates.py` — speakerUnassigned and
  oneoffUnpromoted (R9).
