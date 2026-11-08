"""
UmbraEdit - Voice Matrix Binary Format
=======================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Builds, parses, and validates UVMX version 1 voice matrix files. A voice
matrix is a deterministic binary description of a synthetic voice: its
code is derived from its content hash, so the same code always means
exactly the same voice, in every book and on every machine. Qt-free.
"""  # noqa

from __future__ import annotations

import hashlib
import struct

from dataclasses import dataclass
from typing import Any

MAGIC = b"UVMX"
VERSION = 1
TRAILER_TYPE = 0x00FF

# Chunk types
CHUNK_ENGINE = 0x0001
CHUNK_MODELREF = 0x0002
CHUNK_LANGS = 0x0003
CHUNK_EMBEDDING = 0x0004
CHUNK_EMBED_DIM = 0x0005
CHUNK_REFSAMPLE = 0x0006
CHUNK_LABEL = 0x0007
CHUNK_PARAMS = 0x0008
CHUNK_CREATED = 0x0009

REQUIRED_CHUNKS = frozenset({CHUNK_ENGINE, CHUNK_MODELREF, CHUNK_LANGS, CHUNK_LABEL})

# Little-endian struct formats
_HEADER = struct.Struct("<4sHHII")  # magic, version, flags, chunkCount, reserved
_CHUNK_HEADER = struct.Struct("<HI")  # type, length


class VoiceMatrixError(Exception):
    """Raised when a UVMX file is malformed, corrupt, or invalid."""


@dataclass
class VoiceMatrix:
    """A parsed UVMX voice matrix.

    Attributes:
        engine: Synthesis engine identifier (e.g. ``"xtts-v2"``).
        modelRef: Model id or voice name.
        languages: Comma-separated BCP 47 codes the voice can speak.
        label: Human-readable label.
        params: Canonical JSON string of engine parameters, when present.
        embedding: Float32 array payload bytes, when present.
        refSample: WAV or FLAC reference clip bytes, when present.
        created: UTC ISO 8601 timestamp, when present.
        code: Derived voice matrix code, ``vm-`` plus the first 12
            lower-case hex characters of the trailer hash.

    """

    engine: str = ""
    modelRef: str = ""
    languages: str = ""
    label: str = ""
    params: str | None = None
    embedding: bytes | None = None
    refSample: bytes | None = None
    created: str | None = ""
    code: str = ""

    def toDict(self) -> dict[str, Any]:
        """Return a JSON-serialisable registry entry for this matrix."""
        return {
            "code": self.code,
            "label": self.label,
            "engine": self.engine,
            "languages": self.languages.split(",") if self.languages else [],
            "kind": "",
            "assetId": self.code[3:11] if self.code else "",
            "createdAt": self.created or "",
            "retired": False,
        }


def _chunk(typeId: int, payload: bytes) -> bytes:
    """Encode one UVMX chunk: type (u16 LE), length (u32 LE), payload."""
    return _CHUNK_HEADER.pack(typeId, len(payload)) + payload


def buildVoiceMatrix(
    engine: str,
    modelRef: str,
    languages: str,
    label: str,
    params: str | None = None,
    embedding: bytes | None = None,
    refSample: bytes | None = None,
    created: str | None = None,
) -> bytes:
    """Build a deterministic UVMX version 1 voice matrix byte string.

    Chunks are written in ascending type order. The trailer hash covers
    all bytes before the trailer chunk (header plus body chunks).
    """
    bodyChunks: list[tuple[int, bytes]] = [
        (CHUNK_ENGINE, engine.encode("utf-8")),
        (CHUNK_MODELREF, modelRef.encode("utf-8")),
        (CHUNK_LANGS, languages.encode("utf-8")),
        (CHUNK_LABEL, label.encode("utf-8")),
    ]

    flags = 0
    if embedding is not None:
        flags |= 0x0001
        bodyChunks.append((CHUNK_EMBEDDING, embedding))
        bodyChunks.append((CHUNK_EMBED_DIM, struct.pack("<I", len(embedding) // 4)))
    if refSample is not None:
        flags |= 0x0002
        bodyChunks.append((CHUNK_REFSAMPLE, refSample))
    if params is not None:
        bodyChunks.append((CHUNK_PARAMS, params.encode("utf-8")))
    if created is not None:
        bodyChunks.append((CHUNK_CREATED, created.encode("utf-8")))

    bodyChunks.sort(key=lambda item: item[0])
    body = b"".join(_chunk(typeId, payload) for typeId, payload in bodyChunks)

    header = _HEADER.pack(MAGIC, VERSION, flags, len(bodyChunks), 0)
    preTrailer = header + body
    trailerHash = hashlib.sha256(preTrailer).digest()
    trailer = _chunk(TRAILER_TYPE, trailerHash)

    return preTrailer + trailer


def voiceMatrixCode(data: bytes) -> str:
    """Return the voice matrix code for a UVMX byte string.

    The code is ``vm-`` plus the first 12 lower-case hex characters of
    the trailer payload hash. Raises VoiceMatrixError if the matrix
    cannot be validated.
    """
    _matrix = parseVoiceMatrix(data)
    return _matrix.code


def parseVoiceMatrix(data: bytes) -> VoiceMatrix:
    """Parse and validate a UVMX voice matrix byte string.

    Verifies the magic, version, chunk bounds, required chunks, and the
    trailer hash. Raises VoiceMatrixError with a message naming the
    problem on any invalid input.
    """
    if len(data) < _HEADER.size:
        raise VoiceMatrixError("File is too small to contain a UVMX header")

    magic, version, _flags, chunkCount, _reserved = _HEADER.unpack(data[: _HEADER.size])
    if magic != MAGIC:
        raise VoiceMatrixError(f"Bad magic: expected 'UVMX', got {magic!r}")
    if version != VERSION:
        raise VoiceMatrixError(f"Unsupported UVMX version {version} (expected {VERSION})")

    offset = _HEADER.size
    chunks: dict[int, bytes] = {}
    typesSeen: list[int] = []

    for index in range(chunkCount):
        if offset + _CHUNK_HEADER.size > len(data):
            raise VoiceMatrixError(f"Chunk {index} header extends past end of file")
        typeId, length = _CHUNK_HEADER.unpack(data[offset : offset + _CHUNK_HEADER.size])
        offset += _CHUNK_HEADER.size
        if offset + length > len(data):
            raise VoiceMatrixError(f"Chunk {index} (type 0x{typeId:04X}) length extends past end of file")
        payload = data[offset : offset + length]
        offset += length
        chunks[typeId] = payload
        typesSeen.append(typeId)

    # Trailer chunk must follow all body chunks.
    if offset + _CHUNK_HEADER.size > len(data):
        raise VoiceMatrixError("Trailer chunk header missing")
    trailerType, trailerLength = _CHUNK_HEADER.unpack(data[offset : offset + _CHUNK_HEADER.size])
    offset += _CHUNK_HEADER.size
    if trailerType != TRAILER_TYPE:
        raise VoiceMatrixError(f"Expected trailer chunk type 0x{TRAILER_TYPE:04X}, got 0x{trailerType:04X}")
    if trailerLength != 32:
        raise VoiceMatrixError(f"Trailer chunk length must be 32 (SHA-256), got {trailerLength}")
    if offset + trailerLength > len(data):
        raise VoiceMatrixError("Trailer payload extends past end of file")
    trailerPayload = data[offset : offset + trailerLength]
    offset += trailerLength

    if offset != len(data):
        raise VoiceMatrixError("Trailing bytes after trailer chunk")

    expectedHash = hashlib.sha256(data[: offset - trailerLength - _CHUNK_HEADER.size]).digest()
    if trailerPayload != expectedHash:
        raise VoiceMatrixError("Trailer hash mismatch: voice matrix may be corrupt")

    missing = REQUIRED_CHUNKS - set(chunks)
    if missing:
        missingHex = ", ".join(f"0x{t:04X}" for t in sorted(missing))
        raise VoiceMatrixError(f"Missing required chunks: {missingHex}")

    def _text(typeId: int) -> str:
        return chunks.get(typeId, b"").decode("utf-8")

    matrix = VoiceMatrix(
        engine=_text(CHUNK_ENGINE),
        modelRef=_text(CHUNK_MODELREF),
        languages=_text(CHUNK_LANGS),
        label=_text(CHUNK_LABEL),
    )

    if CHUNK_PARAMS in chunks:
        matrix.params = chunks[CHUNK_PARAMS].decode("utf-8")
    if CHUNK_EMBEDDING in chunks:
        matrix.embedding = chunks[CHUNK_EMBEDDING]
    if CHUNK_REFSAMPLE in chunks:
        matrix.refSample = chunks[CHUNK_REFSAMPLE]
    if CHUNK_CREATED in chunks:
        matrix.created = chunks[CHUNK_CREATED].decode("utf-8")

    matrix.code = "vm-" + trailerPayload.hex()[:12]
    return matrix
