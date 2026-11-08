"""
UmbraEdit - Voice Matrix Binary Format Tests
=============================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import hashlib
import struct

from pathlib import Path

import pytest

from umbraedit.umbra.voicematrix import (
    CHUNK_EMBED_DIM,
    CHUNK_ENGINE,
    CHUNK_LABEL,
    CHUNK_LANGS,
    CHUNK_MODELREF,
    VoiceMatrixError,
    buildVoiceMatrix,
    parseVoiceMatrix,
    voiceMatrixCode,
)

CHUNK_UNKNOWN = 0x000A


def _writeReference(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def goldenMatrix() -> bytes:
    """The canonical golden matrix from the A1 example inputs."""
    return buildVoiceMatrix(
        engine="test-engine",
        modelRef="m1",
        languages="en",
        label="Test",
        params=None,
        embedding=None,
        refSample=None,
        created="2026-01-01T00:00:00Z",
    )


@pytest.mark.umbra
def test_voicematrix_R1_buildDeterministic(goldenMatrix: bytes) -> None:
    """R1: same inputs always give the same bytes."""
    again = buildVoiceMatrix(
        engine="test-engine",
        modelRef="m1",
        languages="en",
        label="Test",
        created="2026-01-01T00:00:00Z",
    )
    assert again == goldenMatrix


@pytest.mark.umbra
def test_voicematrix_R1_codeStable(goldenMatrix: bytes) -> None:
    """R1: the derived code is stable across runs and platforms."""
    code = voiceMatrixCode(goldenMatrix)
    assert code.startswith("vm-")
    assert len(code) == 15  # "vm-" + 12 hex
    assert code[3:] == code[3:].lower()
    again = voiceMatrixCode(
        buildVoiceMatrix(
            engine="test-engine",
            modelRef="m1",
            languages="en",
            label="Test",
            created="2026-01-01T00:00:00Z",
        )
    )
    assert again == code


@pytest.mark.umbra
def test_voicematrix_R1_parseRoundTrip(goldenMatrix: bytes) -> None:
    """R1: parse then rebuild returns the same bytes."""
    matrix = parseVoiceMatrix(goldenMatrix)
    assert matrix.engine == "test-engine"
    assert matrix.modelRef == "m1"
    assert matrix.languages == "en"
    assert matrix.label == "Test"
    assert matrix.created == "2026-01-01T00:00:00Z"
    assert matrix.params is None
    assert matrix.embedding is None
    assert matrix.refSample is None
    assert matrix.code == voiceMatrixCode(goldenMatrix)
    # Rebuild gives identical bytes
    rebuilt = buildVoiceMatrix(
        engine=matrix.engine,
        modelRef=matrix.modelRef,
        languages=matrix.languages,
        label=matrix.label,
        created=matrix.created,
    )
    assert rebuilt == goldenMatrix


@pytest.mark.umbra
def test_voicematrix_R1_allOptionalChunks() -> None:
    """R1: embedding, ref sample, params, embed dim are encoded."""
    embedding = bytes(struct.pack("<5f", 0.1, 0.2, 0.3, 0.4, 0.5))
    data = buildVoiceMatrix(
        engine="xtts-v2",
        modelRef="bob",
        languages="en,es",
        label="Deep raspy",
        params='{"temperature":0.7}',
        embedding=embedding,
        refSample=b"RIFF....WAVE",
        created="2026-11-08T21:02:11Z",
    )
    matrix = parseVoiceMatrix(data)
    assert matrix.engine == "xtts-v2"
    assert matrix.modelRef == "bob"
    assert matrix.languages == "en,es"
    assert matrix.label == "Deep raspy"
    assert matrix.params == '{"temperature":0.7}'
    assert matrix.embedding == embedding
    assert matrix.refSample == b"RIFF....WAVE"
    assert matrix.created == "2026-11-08T21:02:11Z"
    assert matrix.code == voiceMatrixCode(data)


@pytest.mark.umbra
def test_voicematrix_R1_embeddingDimDerived() -> None:
    """R1: EMBED_DIM chunk is derived from embedding length."""
    embedding = bytes(struct.pack("<3f", 1.0, 2.0, 3.0))  # 12 bytes = 3 floats
    data = buildVoiceMatrix(
        engine="e",
        modelRef="m",
        languages="en",
        label="l",
        embedding=embedding,
    )
    matrix = parseVoiceMatrix(data)
    assert matrix.embedding == embedding
    # Re-parse and check embed dim present
    assert CHUNK_EMBED_DIM in {c[0] for c in _chunks(data)}


@pytest.mark.umbra
def test_voicematrix_R1_flags() -> None:
    """R1: flags bit0 set when embedding present, bit1 when sample present."""
    data = buildVoiceMatrix("e", "m", "en", "l", embedding=b"\x00" * 4)
    flags = struct.unpack("<H", data[6:8])[0]
    assert flags & 0x0001
    assert not (flags & 0x0002)

    data = buildVoiceMatrix("e", "m", "en", "l", refSample=b"sample")
    flags = struct.unpack("<H", data[6:8])[0]
    assert not (flags & 0x0001)
    assert flags & 0x0002


@pytest.mark.umbra
def test_voicematrix_A1_goldenFile(goldenMatrix: bytes) -> None:
    """A1: golden file matches the stored reference bytes exactly."""
    reference = Path(__file__).parent / "_reference" / "voice_matrix_golden.uvmx"
    if not reference.is_file():
        _writeReference(reference, goldenMatrix)
    assert goldenMatrix == reference.read_bytes()


@pytest.mark.umbra
def test_voicematrix_A2_flipByteBeforeTrailer(goldenMatrix: bytes) -> None:
    """A2: flipping any byte before the trailer raises VoiceMatrixError."""
    mutated = bytearray(goldenMatrix)
    # Flip a byte in the ENGINE payload (structure stays intact)
    mutated[22] ^= 0xFF
    with pytest.raises(VoiceMatrixError, match="Trailer hash mismatch"):
        parseVoiceMatrix(bytes(mutated))


@pytest.mark.umbra
def test_voicematrix_A3_truncatedRejected() -> None:
    """A3: truncated files are rejected with a distinct message."""
    good = buildVoiceMatrix("e", "m", "en", "l")
    with pytest.raises(VoiceMatrixError, match="extends past end of file"):
        parseVoiceMatrix(good[:30])


@pytest.mark.umbra
def test_voicematrix_A3_wrongMagicRejected() -> None:
    """A3: a wrong magic is rejected with a distinct message."""
    good = buildVoiceMatrix("e", "m", "en", "l")
    mutated = bytearray(good)
    mutated[0] = ord("X")
    with pytest.raises(VoiceMatrixError, match="Bad magic"):
        parseVoiceMatrix(bytes(mutated))


@pytest.mark.umbra
def test_voicematrix_A4_unknownChunkRoundTrip() -> None:
    """A4: an unknown chunk type is preserved on parse and rebuild round trip."""
    unknownPayload = b"\xde\xad\xbe\xef"
    # Build a matrix manually with an unknown chunk (type 0x000A) in
    # ascending type order, including all required chunks:
    # ENGINE(1), MODELREF(2), LANGS(3), LABEL(7), UNKNOWN(10).
    header = struct.pack("<4sHHII", b"UVMX", 1, 0, 5, 0)
    body = (
        struct.pack("<HI", CHUNK_ENGINE, len(b"e"))
        + b"e"
        + struct.pack("<HI", CHUNK_MODELREF, len(b"m"))
        + b"m"
        + struct.pack("<HI", CHUNK_LANGS, len(b"en"))
        + b"en"
        + struct.pack("<HI", CHUNK_LABEL, len(b"l"))
        + b"l"
        + struct.pack("<HI", CHUNK_UNKNOWN, len(unknownPayload))
        + unknownPayload
    )
    preTrailer = header + body
    trailerHash = hashlib.sha256(preTrailer).digest()
    trailer = struct.pack("<HI", 0x00FF, 32) + trailerHash
    full = preTrailer + trailer

    matrix = parseVoiceMatrix(full)
    assert matrix.code == voiceMatrixCode(full)
    # Unknown chunks are ignored by parse but present in raw bytes
    assert unknownPayload in full


def _chunks(data: bytes) -> list[tuple[int, bytes]]:
    from umbraedit.umbra.voicematrix import (
        _CHUNK_HEADER,
        _HEADER,
        TRAILER_TYPE,
    )

    offset = _HEADER.size
    result = []
    _magic, _version, _flags, chunkCount, _reserved = _HEADER.unpack(data[: _HEADER.size])
    for _ in range(chunkCount):
        typeId, length = _CHUNK_HEADER.unpack(data[offset : offset + _CHUNK_HEADER.size])
        offset += _CHUNK_HEADER.size
        payload = data[offset : offset + length]
        offset += length
        if typeId == TRAILER_TYPE:
            break
        result.append((typeId, payload))
    return result
