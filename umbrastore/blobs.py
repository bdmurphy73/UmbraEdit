"""
UmbraStore - Blob storage
=========================

Content-addressed blob storage under blobs/<sha256[0:2]>/<sha256>.
All writes are atomic (temp file in same directory, fsync, rename).
"""  # noqa

from __future__ import annotations

import hashlib
import os
import tempfile

from pathlib import Path


class BlobStore:
    """Content-addressed blob storage.

    Blobs are stored at <root>/blobs/<sha256[0:2]>/<sha256>.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._blobsDir = root / "blobs"

    @property
    def blobsDir(self) -> Path:
        return self._blobsDir

    def _blobPath(self, sha256: str) -> Path:
        return self._blobsDir / sha256[:2] / sha256

    def _sha256File(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def _sha256Bytes(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def store(self, data: bytes) -> str:
        """Store bytes and return their SHA-256 hex digest.

        The blob is written atomically: temp file in the same
        directory, fsync, then rename. If the blob already exists,
        it is not rewritten.
        """
        sha256 = self._sha256Bytes(data)
        blobPath = self._blobPath(sha256)

        if blobPath.is_file():
            # Verify existing blob matches
            existingSha = self._sha256File(blobPath)
            if existingSha == sha256:
                return sha256
            # Corrupted existing blob - overwrite
        else:
            blobPath.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write
        fd, tempPath = tempfile.mkstemp(dir=str(blobPath.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tempPath, str(blobPath))
        except Exception:
            try:
                os.unlink(tempPath)
            except OSError:
                pass
            raise

        return sha256

    def storeFromFile(self, filePath: Path) -> str:
        """Store the contents of a file and return its SHA-256."""
        data = filePath.read_bytes()
        return self.store(data)

    def retrieve(self, sha256: str) -> bytes | None:
        """Retrieve blob bytes by SHA-256, or None if not found."""
        blobPath = self._blobPath(sha256)
        if not blobPath.is_file():
            return None
        return blobPath.read_bytes()

    def exists(self, sha256: str) -> bool:
        """Check if a blob exists."""
        return self._blobPath(sha256).is_file()

    def verify(self, sha256: str) -> bool:
        """Verify that a blob's content matches its SHA-256."""
        blobPath = self._blobPath(sha256)
        if not blobPath.is_file():
            return False
        actualSha = self._sha256File(blobPath)
        return actualSha == sha256
