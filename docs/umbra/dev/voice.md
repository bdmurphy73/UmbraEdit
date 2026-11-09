# P10 — Tone, Narration Voice, Attribution (Developer Notes)

Status: core logic implemented (Qt-free). GUI pieces (tone picker,
attribution picker, editor cues) are deferred to GAPS.md (G66–G76).

## Data structures

### ToneRef

```python
@dataclass(frozen=True)
class ToneRef:
    key: str          # e.g. "happy", "neutral", "tense"
    intensity: int = 2  # 1 light, 2 default, 3 strong
```

Rendered as ``key`` when intensity is 2, else ``key:intensity``.
`parseTone(text) -> ToneRef | None` parses ``key`` or ``key:1|2|3``.

### UnitVoice

```python
@dataclass
class UnitVoice:
    tone: ToneRef | None = None      # dialogue tone on the paragraph
    ntone: ToneRef | None = None     # narration tone on the paragraph
    sceneTone: ToneRef | None = None # scene default narration tone
```

`parseUnitVoice(text) -> UnitVoice` extracts these from a paragraph's
``%Voice:`` line.

### AttrSpan

```python
@dataclass(frozen=True)
class AttrSpan:
    start: int
    end: int
    inner: str
    mode: str  # "inherit" | "drop" | "keep" | "proposal"
```

`parseAttrSpans(text) -> list[AttrSpan]` parses ``[attr]``,
``[attr:drop]``, ``[attr:keep]``, ``[attr:proposal]`` spans.

### UtteranceSpan

```python
@dataclass(frozen=True)
class UtteranceSpan:
    start: int
    end: int
    inner: str
    spk: str | None = None
    tone: ToneRef | None = None
```

`parseUttSpans(text) -> list[UtteranceSpan]` parses
``[utt:spk=...;tone=...]`` spans.

## Public functions

- `umbraedit.umbra.voice.effectiveDialogueTone(unit, sceneVoice)
  -> ToneRef` (R3): unit.tone or neutral:2.
- `umbraedit.umbra.voice.effectiveNarrationTone(unit, sceneVoice)
  -> ToneRef` (R3): unit.ntone or sceneVoice.ntone or neutral:2.
- `umbraedit.umbra.voice.narrationSpeaker(sceneHandle, index) -> str`
  (R3): the scene's @pov tag, else "narrator".
- `umbraedit.umbra.voice.effectiveDrop(span, speaker=None,
  settings=None) -> bool` (R6):
  - span mode drop/keep decides immediately
  - inherit: speaker's ``@attr: drop_attrib`` (yes/no)
  - else project setting ``audio.dropAttributions`` (default false)
- `umbraedit.umbra.voice.effectiveUtteranceSpeaker(paragraphVoice,
  uttSpan) -> str | None` (R8): utt span speaker, then paragraph spk,
  then None.

## Gate rules (R9)

| Rule | Severity | Operations | Meaning |
|------|----------|------------|---------|
| `attribDropSameVoice` | block | audio.chapter | Effective drop is true for a speaker whose voice_matrix equals the scene narration voice's voice_matrix. |
| `attribProposalOpen` | advisory | audio.chapter | An unaccepted ``[attr:proposal]`` span exists. |

Both are registered at the end of ``umbra.gates``.

## Settings (R10)

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `audio.dropAttributions` | bool | false | Project-wide default for inherit-mode attribution drops. |

## Hook points

No upstream files modified for the core logic. `umbra.gates.py`
registers `voicegates` (shared with P06/P07/P08/P09).

## Tone rendering

A ``ToneRef`` renders as ``key`` when intensity is 2 (omitted) and as
``key:1``/``key:3`` otherwise. This matches the ``tone=happy`` (omit
:2) and ``tone=happy:3`` forms from R1.

## Tests

- `tests/umbra/test_voice.py` — tone parsing (R1), effective dialogue/
  narration tone (R3), narration speaker (R3), effective drop (R6),
  attribution span parsing, utterance spans (R8).
- `tests/umbra/test_voicegates.py` — attribDropSameVoice and
  attribProposalOpen (R9).
