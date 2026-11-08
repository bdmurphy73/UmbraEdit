"""UmbraEdit - Asset Store.

This file is a part of UmbraEdit, a fork of novelWriter.
Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
Content-addressed store for binary project assets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile

from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1

ROLE_FIGURE = "figure"
ROLE_COVER = "cover"
ROLE_VOICE_MATRIX = "voiceMatrix"
ROLE_AUDIO_SAMPLE = "audioSample"
ROLE_OTHER = "other"
VALID_ROLES = frozenset({ROLE_FIGURE, ROLE_COVER, ROLE_VOICE_MATRIX, ROLE_AUDIO_SAMPLE, ROLE_OTHER})

ALLOWED_TYPES: dict[str, set[str]] = {
    ROLE_FIGURE: {"image/png", "image/jpeg", "image/svg+xml", "image/webp"},
    ROLE_COVER: {"image/jpeg", "image/png", "application/pdf"},
    ROLE_VOICE_MATRIX: {"application/x-uvmx"},
    ROLE_AUDIO_SAMPLE: {"audio/wav", "audio/x-wav", "audio/flac", "audio/mpeg"},
    ROLE_OTHER: set(),
}

_SVG_SCRIPT_RE = re.compile(r"<script[\s>]", re.IGNORECASE)
_SVG_ONATTR_RE = re.compile(r"\son\w+\s*=", re.IGNORECASE)
_SVG_JSURL_RE = re.compile(r"javascript\s*:", re.IGNORECASE)
_SVG_EXTREF_RE = re.compile(r"(xlink:href|href)\s*=\s*[\"']https?://", re.IGNORECASE)


def _sha256File(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _detectMime(data: bytes, fileName: str = "") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if data[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return "image/webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE": return "audio/x-wav"
    if data[:4] == b"fLaC": return "audio/flac"
    if data[:3] == b"ID3" or (len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0): return "audio/mpeg"
    if data[:5] == b"<?xml" or data[:4] == b"<svg": return "image/svg+xml"
    if data[:4] == b"%PDF": return "application/pdf"
    if data[:4] == b"UVMX": return "application/x-uvmx"
    mime, _ = mimetypes.guess_type(fileName)
    return mime or "application/octet-stream"


def _imageDims(data: bytes, mime: str) -> dict[str, int]:
    if not mime.startswith("image/") or mime == "image/svg+xml": return {}
    try:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(data))
        return {"width": img.width, "height": img.height}
    except Exception: return {}


def _validateSvg(data: bytes) -> None:
    try: text = data.decode("utf-8")
    except UnicodeDecodeError: raise ValueError("SVG is not valid UTF-8")
    if _SVG_SCRIPT_RE.search(text): raise ValueError("SVG contains <script> tag")
    if _SVG_ONATTR_RE.search(text): raise ValueError("SVG contains on* handler")
    if _SVG_JSURL_RE.search(text): raise ValueError("SVG contains javascript: URL")
    if _SVG_EXTREF_RE.search(text): raise ValueError("SVG contains external reference")


def _extFromMime(mime: str, fileName: str = "") -> str:
    extMap = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg",
              "image/webp": ".webp", "application/pdf": ".pdf", "application/x-uvmx": ".uvmx",
              "audio/x-wav": ".wav", "audio/wav": ".wav", "audio/flac": ".flac", "audio/mpeg": ".mp3"}
    return extMap.get(mime) or Path(fileName).suffix or ".bin"


class AssetStore:
    def __init__(self, projectPath: Path) -> None:
        self._projectPath = projectPath
        self._assetsDir = projectPath / "umbra" / "assets"
        self._indexPath = self._assetsDir / "index.json"
        self._index: dict[str, dict[str, Any]] = {}
        self._loadIndex()

    @property
    def index(self) -> dict[str, dict[str, Any]]:
        return dict(self._index)

    def addAsset(self, source: Path | bytes, role: str, attrs: dict[str, Any] | None = None, name: str | None = None) -> str:
        if isinstance(source, Path):
            if not source.is_file(): raise FileNotFoundError(f"Asset file not found: {source}")
            fileName = source.name
            sha256 = _sha256File(source)
            with open(source, "rb") as f: header = f.read(1024)
            mime = _detectMime(header, fileName)
        else:
            data = source
            sha256 = hashlib.sha256(data).hexdigest()
            fileName = name or "asset"
            mime = _detectMime(data, fileName)

        if role not in VALID_ROLES: raise ValueError(f"Invalid role: {role}")
        allowed = ALLOWED_TYPES.get(role, set())
        if allowed and mime not in allowed:
            raise ValueError(f"MIME type '{mime}' not allowed for role '{role}'")

        if mime == "image/svg+xml":
            svgData = source.read_bytes() if isinstance(source, Path) else source
            _validateSvg(svgData)

        assetId = sha256[:8]
        if assetId in self._index:
            existing = self._index[assetId]
            if existing["sha256"] == sha256:
                # Same content, deduplicate: return existing ID
                self._saveIndex()
                return assetId
            # Different content with same 8-char prefix, extend to 12
            assetId = sha256[:12]

        ext = _extFromMime(mime, fileName)
        relFile = f"{sha256[:2]}/{sha256}{ext}"
        absFile = self._assetsDir / relFile

        dims = {}
        if isinstance(source, bytes): dims = _imageDims(source, mime)
        elif source.stat().st_size < 50 * 1024 * 1024: dims = _imageDims(source.read_bytes(), mime)

        entry = {"sha256": sha256, "file": relFile, "name": name or fileName,
                 "type": mime, "size": source.stat().st_size if isinstance(source, Path) else len(source),
                 "role": role, "attrs": {**(attrs or {}), **dims}}

        absFile.parent.mkdir(parents=True, exist_ok=True)
        if not absFile.is_file():
            if isinstance(source, Path):
                with open(source, "rb") as src:
                    fd, tmp = tempfile.mkstemp(dir=str(absFile.parent), suffix=".tmp")
                    try:
                        with os.fdopen(fd, "wb") as dst:
                            while chunk := src.read(65536): dst.write(chunk)
                            dst.flush(); os.fsync(dst.fileno())
                        os.rename(tmp, str(absFile))
                    except Exception:
                        try: os.unlink(tmp)
                        except OSError: pass
                        raise
            else:
                fd, tmp = tempfile.mkstemp(dir=str(absFile.parent), suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as dst:
                        dst.write(source); dst.flush(); os.fsync(dst.fileno())
                    os.rename(tmp, str(absFile))
                except Exception:
                    try: os.unlink(tmp)
                    except OSError: pass
                    raise

        self._index[assetId] = entry
        self._saveIndex()
        logger.info("Added asset %s: %s (%s, %d bytes)", assetId, entry["name"], mime, entry["size"])
        return assetId

    def assetPath(self, assetId: str) -> Path:
        entry = self._index.get(assetId)
        if not entry: raise KeyError(f"Asset not found: {assetId}")
        return self._assetsDir / entry["file"]

    def getAsset(self, assetId: str) -> dict[str, Any] | None:
        entry = self._index.get(assetId)
        return dict(entry) if entry else None

    def iterAssets(self, role: str | None = None) -> list[tuple[str, dict[str, Any]]]:
        return [(aid, dict(e)) for aid, e in sorted(self._index.items()) if role is None or e.get("role") == role]

    def usedBy(self, assetId: str) -> list[str]:
        results = []
        contentPath = self._projectPath / "content"
        if not contentPath.is_dir(): return results
        pattern = re.compile(r"\[image:" + re.escape(assetId) + r"\|")
        for docFile in sorted(contentPath.glob("*.md")):
            try:
                if pattern.search(docFile.read_text(encoding="utf-8")): results.append(docFile.stem)
            except OSError: pass
        return results

    def unusedAssets(self) -> list[str]:
        allIds = set(self._index.keys())
        usedIds = set()
        for aid in allIds: usedIds.update(self.usedBy(aid))
        return sorted(allIds - usedIds)

    def removeAsset(self, assetId: str) -> bool:
        entry = self._index.get(assetId)
        if not entry: raise KeyError(f"Asset not found: {assetId}")
        if entry.get("immutable"): raise PermissionError(f"Asset '{assetId}' is immutable")
        if self.usedBy(assetId): raise PermissionError(f"Asset '{assetId}' is in use")
        absFile = self._assetsDir / entry["file"]
        if absFile.is_file(): absFile.unlink()
        del self._index[assetId]
        self._saveIndex()
        return True

    def replaceAsset(self, assetId: str, source: Path | bytes) -> bool:
        entry = self._index.get(assetId)
        if not entry: raise KeyError(f"Asset not found: {assetId}")
        if entry.get("immutable"): raise PermissionError(f"Asset '{assetId}' is immutable")
        newHash = _sha256File(source) if isinstance(source, Path) else hashlib.sha256(source).hexdigest()
        if newHash == entry["sha256"]: return True
        if entry["role"] == ROLE_VOICE_MATRIX:
            newId = newHash[:8]
            entry["sha256"] = newHash
            entry["file"] = f"{newHash[:2]}/{newHash}{Path(entry['file']).suffix}"
            entry["size"] = source.stat().st_size if isinstance(source, Path) else len(source)
            absFile = self._assetsDir / entry["file"]
            absFile.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path): shutil.copy2(source, absFile)
            else: absFile.write_bytes(source)
            del self._index[assetId]
            self._index[newId] = entry
            self._saveIndex()
            return True
        ext = _extFromMime(entry["type"], entry["name"])
        entry["sha256"] = newHash
        entry["file"] = f"{newHash[:2]}/{newHash}{ext}"
        entry["size"] = source.stat().st_size if isinstance(source, Path) else len(source)
        absFile = self._assetsDir / entry["file"]
        absFile.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, Path): shutil.copy2(source, absFile)
        else: absFile.write_bytes(source)
        self._saveIndex()
        return True

    def verifyAssets(self) -> list[dict[str, str]]:
        issues = []
        for assetId, entry in sorted(self._index.items()):
            absFile = self._assetsDir / entry["file"]
            if not absFile.is_file():
                issues.append({"ruleId": "assetMissing", "severity": "block",
                               "message": f"Asset file missing: {entry['name']} ({assetId})",
                               "fix": "Re-add the asset.", "handle": None, "line": None,
                               "detail": {"assetId": assetId}})
                continue
            actual = _sha256File(absFile)
            if actual != entry["sha256"]:
                issues.append({"ruleId": "assetCorrupt", "severity": "block",
                               "message": f"Asset corrupted: {entry['name']} ({assetId})",
                               "fix": "Re-add the asset.", "handle": None, "line": None,
                               "detail": {"assetId": assetId, "expected": entry["sha256"], "actual": actual}})
        return issues

    def _loadIndex(self) -> None:
        if self._indexPath.is_file():
            try:
                data = json.loads(self._indexPath.read_text(encoding="utf-8"))
                self._index = data.get("assets", {})
            except (json.JSONDecodeError, OSError):
                self._index = {}

    def _saveIndex(self) -> None:
        self._assetsDir.mkdir(parents=True, exist_ok=True)
        data = {"v": SCHEMA_VERSION, "assets": self._index}
        text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(self._assetsDir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text); f.flush(); os.fsync(f.fileno())
            os.rename(tmp, str(self._indexPath))
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
