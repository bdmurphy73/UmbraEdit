"""
UmbraEdit - Voice Matrix Store
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Stores voice matrix binary assets (P04 asset store, role ``voiceMatrix``)
and maintains the ``umbra/voices.json`` registry. A matrix is immutable:
the same bytes always produce the same code, and importing identical
bytes returns the existing code.
"""  # noqa

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

from umbraedit.umbra.assets import ROLE_VOICE_MATRIX, AssetStore
from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import voicesFile
from umbraedit.umbra.voicematrix import VoiceMatrix, voiceMatrixCode


@dataclass
class VoiceEntry:
    """One entry in the voices.json registry."""

    code: str
    label: str
    kind: str
    engine: str
    languages: list[str]
    assetId: str
    createdAt: str
    retired: bool = False


class VoiceStore:
    """Manages voice matrix assets and the voice registry for a project."""

    def __init__(self, projectPath: Path, bibleVoiceStore: VoiceStore | None = None) -> None:
        self._projectPath = projectPath
        self._assets = AssetStore(projectPath)
        self._registryPath = voicesFile(projectPath)
        self._voices: dict[str, VoiceEntry] = {}
        self._bibleVoiceStore = bibleVoiceStore
        self._loadRegistry()

    ##
    #  Registry
    ##

    def _loadRegistry(self) -> None:
        data = readJson(self._registryPath, default={"voices": []})
        if not isinstance(data, dict):
            data = {"voices": []}
        self._voices = {}
        for entry in data.get("voices", []):
            code = entry.get("code", "")
            if code:
                self._voices[code] = VoiceEntry(
                    code=code,
                    label=entry.get("label", ""),
                    kind=entry.get("kind", ""),
                    engine=entry.get("engine", ""),
                    languages=list(entry.get("languages", [])),
                    assetId=entry.get("assetId", code[3:11] if code else ""),
                    createdAt=entry.get("createdAt", ""),
                    retired=bool(entry.get("retired", False)),
                )

    def _saveRegistry(self) -> None:
        entries = [
            {
                "code": v.code,
                "label": v.label,
                "kind": v.kind,
                "engine": v.engine,
                "languages": v.languages,
                "assetId": v.assetId,
                "createdAt": v.createdAt,
                "retired": v.retired,
            }
            for v in sorted(self._voices.values(), key=lambda v: v.code)
        ]
        writeJson(self._registryPath, {"v": 1, "voices": entries})
        from umbraedit.umbra import hooks as _umbraHooks
        _umbraHooks.call(_umbraHooks.SIDECAR_WRITTEN, self._registryPath)

    def listVoices(self, includeRetired: bool = False) -> list[VoiceEntry]:
        """Return all registered voices, optionally including retired ones."""
        voices = list(self._voices.values())
        if not includeRetired:
            voices = [v for v in voices if not v.retired]
        return sorted(voices, key=lambda v: v.label.lower())

    def getVoiceEntry(self, code: str) -> VoiceEntry | None:
        """Return the registry entry for a code, or None."""
        return self._voices.get(code)

    ##
    #  Import
    ##

    def importVoiceMatrix(
        self,
        data: bytes,
        label: str | None = None,
        kind: str = "character",
    ) -> str:
        """Import a voice matrix byte string.

        Stores the bytes as an immutable voiceMatrix asset and adds a
        registry entry. Importing identical bytes returns the existing
        code (deduplication by content hash).
        """
        code = voiceMatrixCode(data)  # validates

        from umbraedit.umbra.voicematrix import parseVoiceMatrix

        try:
            matrix = parseVoiceMatrix(data)
        except Exception:  # already validated above
            matrix = None

        if label is None and matrix is not None:
            label = matrix.label or f"Voice {code[3:]}"

        existing = self._voices.get(code)
        if existing is not None:
            # Same content already registered: no-op, return existing code
            return code

        # Store the asset (immutable, content-addressed)
        assetId = self._assets.addAsset(
            data,
            ROLE_VOICE_MATRIX,
            attrs={"code": code, "immutable": True},
            name=f"{code}.uvmx",
        )

        from datetime import UTC, datetime

        createdAt = matrix.created if matrix and matrix.created else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        languages = matrix.languages.split(",") if matrix and matrix.languages else []
        engine = matrix.engine if matrix else ""
        entry = VoiceEntry(
            code=code,
            label=label or f"Voice {code[3:]}",
            kind=kind,
            engine=engine,
            languages=languages,
            assetId=assetId,
            createdAt=createdAt,
        )
        self._voices[code] = entry
        self._saveRegistry()
        return code

    def getVoiceMatrix(self, code: str) -> bytes | None:
        """Return the raw UVMX bytes for a registered code, or None."""
        entry = self._voices.get(code)
        if entry is None:
            # Fall back to bible voice store
            if self._bibleVoiceStore is not None:
                return self._bibleVoiceStore.getVoiceMatrix(code)
            return None
        try:
            path = self._assets.assetPath(entry.assetId)
        except KeyError:
            return None
        if not path.is_file():
            return None
        return path.read_bytes()

    ##
    #  Resolution (R3)
    ##

    def getVoice(self, tag: str, editionLang: str | None = None, index: Any = None) -> VoiceMatrix | None:
        """Return the voice matrix for a tag in an edition language.

        Reads the ``voice_matrix`` attribute from the entity sheet and
        looks up the matrix in the registry. `editionLang` is reserved
        for per-edition voices (P24); each note carries its own
        ``voice_matrix`` in an edition project.
        """
        if index is None:
            return None
        row = index.getEntity(tag)
        if row is None:
            return None
        code = row.attrs.get("voice_matrix", "")
        if not code:
            return None
        data = self.getVoiceMatrix(code)
        if data is None:
            return None
        from umbraedit.umbra.voicematrix import parseVoiceMatrix

        try:
            return parseVoiceMatrix(data)
        except Exception:
            return None
