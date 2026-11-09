# P11 — Utterance Derivation and Staleness (Developer Notes)

Status: core logic implemented (Qt-free). GUI pieces (export dialog, editor cues, override command) are deferred to GAPS.md (G77-G82).

## Data Structures

### Utterance

```python
@dataclass
class Utterance:
    id: str              # u-<handle>-<para 4 digits>-<k>
    handle: str          # document handle
    para: int            # zero-based paragraph index
    kind: str            # "dialogue", "narration", "attribution", "thought"
    speaker: str         # tag, "narrator", "~label", or "unknown"
    text: str            # utterance text (shortcodes stripped)
    joinAfter: str       # trailing whitespace + next segment's leading whitespace
    tone: str            # tone key ("neutral" if none)
    toneI: int           # intensity (1-3, default 2)
    lang: str            # BCP 47 language code, "" if none
    src: str             # "author" or "machine"
    skip: str | None     # None or "attribution"
    attribution: bool    # True if this is an attribution span
    voice: str | None    # voice matrix code, or None
    pron: list[dict]     # pronunciation spans from P07
    hash: str            # SHA-256 of kind|speaker|text|tone|toneI|lang|voice|pron
```

### Public Functions

- `umbraedit.umbra.utterances.deriveUtterances(handle, text, project, index, settings, store)` — derives utterances for one document
- `umbraedit.umbra.utterances.parseTone(text)` — parses tone key:intensity
- `umbraedit.umbra.utterances.effectiveDrop(span, speaker, settings)` — computes effective drop
- `umbraedit.umbra.utterances.parseAttrSpans(text)` — parses [attr] spans
- `umbraedit.umbra.utterances.parseUttSpans(text)` — parses [utt:...] spans
- `umbraedit.umbra.utterances.narrationSpeaker(handle, index)` — resolves @pov tag
- `umbraedit.umbra.utterances._utteranceHash(...)` — computes SHA-256 hash

## Gate Rules (R9)

| Rule | Severity | Operations | Meaning |
|------|----------|------------|---------|
| `attribDropSameVoice` | block | audio.chapter | Effective drop is true for a speaker whose voice_matrix equals the scene narration voice's voice_matrix |
| `attribProposalOpen` | advisory | audio.chapter | An unaccepted `[attr:proposal]` span exists |

Both are registered at the end of `umbra.gates`.

## Join Invariant (R1)

Concatenating `text + joinAfter` of all utterances in a paragraph rebuilds the paragraph text (shortcodes removed) byte for byte.

- `joinAfter` = trailing whitespace of current segment + leading whitespace of next segment
- For the last segment, `joinAfter` = ""

## Tone Resolution

- Dialogue tone: `utterance.tone` from `%Voice: tone=` or neutral:2
- Narration tone: `utterance.ntone` from `%Voice: ntone=` or scene ntone or neutral:2

## Speaker Resolution (R3)

Order of precedence:
1. Utterance override (`[utt:spk=...]`)
2. Paragraph `%Voice: spk=`
3. Following attribution text ("said Uncle Bob." → resolves "Bob" via entity index)
4. Previous dialogue speaker (carry-forward)
5. "unknown"

## Narration Speaker (R3)

- `@pov` tag of the scene document, or "narrator"

## Tests

- `tests/umbra/test_utterances.py` — utterance derivation (R1-R3, R6), mention detection, split/merge, review flags, unattributed names, settings
