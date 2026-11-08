# P08 — Voice Matrix Format (Developer Notes)

Status: core implemented (binary format, parser, store, gates).
Deferred: voice picker GUI, "Voices" dock, audition, retire/export UI,
per-edition voice assignment UI, manual pages (see GAPS.md).

## Binary format — UVMX version 1

All integers are little-endian. A file is:

```
offset  size  field
0       4     magic "UVMX" = 55 56 4d 58
4       2     version = 01 00
6       2     flags: bit0 embedding present, bit1 reference sample present
8       4     chunkCount (chunks before the trailer chunk)
12      4     reserved = 00 00 00 00
16      ...   chunks, in ascending type order
              chunk = u16 type, u32 length, <length> bytes payload
trailer chunk: type 00 FF, length 20 00 00 00, payload = SHA-256 of
                all bytes before the trailer chunk
```

Note: the trailer length field `20 00 00 00` is little-endian u32 = 32,
the size of a SHA-256 digest.

### Chunk types

| Type | Name | Payload | Required |
|------|------|---------|----------|
| 0001 | ENGINE | UTF-8 engine id (e.g. `xtts-v2`) | yes |
| 0002 | MODELREF | UTF-8 model id or voice name | yes |
| 0003 | LANGS | UTF-8 comma-separated BCP 47 codes | yes |
| 0004 | EMBEDDING | float32 array bytes | no |
| 0005 | EMBED_DIM | u32 = embedding length / 4 | no |
| 0006 | REFSAMPLE | WAV or FLAC reference clip bytes | no |
| 0007 | LABEL | UTF-8 human label | yes |
| 0008 | PARAMS | canonical JSON of engine parameters | no |
| 0009 | CREATED | UTF-8 UTC ISO 8601 timestamp | no |

Unknown chunk types are preserved on a parse/rebuild round trip and
ignored semantically (forward compatible).

### Voice matrix code

`vm-` + the first 12 lower-case hex characters of the trailer payload
(SHA-256 digest). Example: `vm-bf7bbe800d63`.

### Golden example (A1)

Inputs: engine=`test-engine`, modelRef=`m1`, languages=`en`, label=`Test`,
no embedding, no reference sample, created=`2026-01-01T00:00:00Z`.

Full file bytes (96 bytes total):

```
00000000: 5556 4d58 0100 0000 0500 0000 0000 0000  UVMX............
00000010: 0100 0b00 0000 7465 7374 2d65 6e67 696e  ......test-engin
00000020: 6502 0002 0000 006d 3103 0002 0000 0065  e......m1......e
00000030: 6e07 0004 0000 0054 6573 7409 0014 0000  n......Test.....
00000040: 0032 3032 362d 3031 2d30 3154 3030 3a30  .2026-01-01T00:0
00000050: 303a 3030 5aff 0020 0000 00bf 7bbe 800d  0:00Z.. ....{...
00000060: 6360 43da 77c6 538d 96d0 6967 2acf 3b8c  c`C.w.S...ig*.;.
00000070: 095d 20da aac5 9651 559c aa              .] ....QU..
```

Breakdown:
- Header: `55564d58` ("UVMX"), `0100` (v1), `0000` (flags), `05000000` (5 chunks), `00000000` (reserved)
- Chunk 0001 ENGINE: `0100 0b000000` + `test-engine` (11 bytes)
- Chunk 0002 MODELREF: `0200 02000000` + `m1`
- Chunk 0003 LANGS: `0300 02000000` + `en`
- Chunk 0007 LABEL: `0700 04000000` + `Test`
- Chunk 0009 CREATED: `0900 14000000` + `2026-01-01T00:00:00Z` (20 bytes)
- Trailer 00FF: `ff00 20000000` + 32-byte SHA-256

The derived code is `vm-bf7bbe800d63` and is stable across runs and
platforms for identical inputs.

## Registry — `umbra/voices.json`

```json
{"v":1,"voices":[{"code":"vm-9f3a1c20d7e4","label":"Deep raspy male, Bob","kind":"character","engine":"xtts-v2","languages":["en"],"assetId":"9f3a1c20","createdAt":"2026-11-06T21:02:11Z","retired":false}]}
```

A matrix is immutable: changing a voice means a new matrix and a new
code. The old one can be retired (kept, hidden from pickers, flagged in
books that still use it).

## Hook points (upstream files touched)

| File | Change |
|------|--------|
| `umbraedit/umbra/assets.py` | Added `UVMX` magic detection to `_detectMime` so voice matrix files are recognised as `application/x-uvmx`. |
| `umbraedit/umbra/gates.py` | `runGates` stamps `operation` onto `GateScope`; registers `voicematrixgates`. |

## Public functions

- `umbraedit.umbra.voicematrix.buildVoiceMatrix(engine, modelRef, languages, label, params=None, embedding=None, refSample=None, created=None) -> bytes`
- `umbraedit.umbra.voicematrix.parseVoiceMatrix(data) -> VoiceMatrix` (raises `VoiceMatrixError`)
- `umbraedit.umbra.voicematrix.voiceMatrixCode(data) -> str`
- `umbraedit.umbra.voicematrix.VoiceMatrix`, `VoiceMatrixError`
- `umbraedit.umbra.voicestore.VoiceStore(projectPath)`:
  `importVoiceMatrix(data, label, kind)`, `getVoiceMatrix(code)`,
  `getVoiceEntry(code)`, `listVoices(includeRetired=False)`,
  `getVoice(tag, editionLang, index)`.
- `umbraedit.umbra.voicestore.VoiceEntry`.

## Gate rules (P08)

| Rule | Severity | Operations | Meaning |
|------|----------|------------|---------|
| `voiceMatrixMissing` | block | audio.chapter | A speaker with dialogue in the chapter, or the narration voice, has no `voice_matrix` code. |
| `voiceMatrixUnknown` | block | audio.chapter, sync.push | The code is not in the registry or its asset is missing. |
| `voiceMatrixCorrupt` | block | audio.chapter, sync.push | Trailer hash mismatch on verify. |
| `voiceMatrixLanguage` | block | audio.chapter | The matrix's languages do not include the utterance language. |
| `voiceMatrixRetired` | advisory | audio.chapter, audio.book | A retired code is still in use. |

## Tests

- `tests/umbra/test_voicematrix.py` — format build/parse/round trip,
  golden file (A1), flip-byte (A2), truncated/wrong magic (A3),
  unknown chunk round trip (A4).
- `tests/umbra/test_voicestore.py` — import, dedup, immutability,
  asset round-trip, `getVoice` resolution (R2/R3).
- `tests/umbra/test_voicematrixgates.py` — all five gate rules (R8).
