"""
UmbraEdit - Safe File Operations
================================

This file is a part of UmbraEdit.

Copyright (C) 2026 Veronica Berglyd Olsen and UmbraEdit contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import logging
import ntpath
import os
import platform
import shutil
import stat
import sys
import uuid
import weakref

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple, Optional, cast

# Windows marks symbolic links, junctions, and other reparse points with
# this file attribute. Path.is_symlink() does not identify every kind of
# reparse point on Python 3.9.
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# POSIX cleanup is quarantine-only because supported systems do not provide
# an inode-bound unlink or rmdir operation. The quarantine directory keeps
# retained objects out of direct-child project scans and backup archives.
QUARANTINE_DIRECTORY_NAME = ".umbraedit-quarantine"

# Darwin and Linux use different values for AT_FDCWD. The Darwin value is
# required by renameatx_np(); using the Linux value there makes descriptor-
# relative calls with one descriptor-less side fail or resolve incorrectly.
_DARWIN_AT_FDCWD = -2
_LINUX_AT_FDCWD = -100

# Linux statx() flags and mask bits used to obtain a fallback file birth
# time. The value remains unchanged when a file is renamed or hard linked.
# Some filesystems expose only coarse timestamp granularity, so Linux file
# handles are preferred when they are available.
_LINUX_AT_SYMLINK_NOFOLLOW = 0x00000100
_LINUX_STATX_BTIME = 0x00000800
_LINUX_AT_EMPTY_PATH = 0x00001000
_LINUX_MAX_HANDLE_SIZE = 128

# Linux renameat2() syscall numbers. The libc wrapper is not available on
# glibc versions older than 2.28, so the raw syscall is used as a fallback.
_LINUX_RENAMEAT2_SYSCALL = {
    "aarch64": 276,
    "alpha": 276,
    "armv7l": 382,
    "armv8l": 382,
    "i386": 353,
    "i686": 353,
    "ppc64": 357,
    "ppc64le": 357,
    "riscv64": 276,
    "s390x": 347,
    "x86_64": 316,
}


class _StatxTimestamp(ctypes.Structure):
    """Linux statx timestamp structure."""

    _fields_ = [
        ("seconds", ctypes.c_int64),
        ("nanoseconds", ctypes.c_uint32),
        ("reserved", ctypes.c_int32),
    ]


class _LinuxFileHandle(ctypes.Structure):
    """Linux name_to_handle_at() result buffer."""

    _fields_ = [
        ("handle_bytes", ctypes.c_uint),
        ("handle_type", ctypes.c_int),
        ("file_handle", ctypes.c_ubyte * _LINUX_MAX_HANDLE_SIZE),
    ]


class _StatxBuffer(ctypes.Structure):
    """Linux statx result structure."""

    _fields_ = [
        ("mask", ctypes.c_uint32),
        ("blockSize", ctypes.c_uint32),
        ("attributes", ctypes.c_uint64),
        ("linkCount", ctypes.c_uint32),
        ("userId", ctypes.c_uint32),
        ("groupId", ctypes.c_uint32),
        ("mode", ctypes.c_uint16),
        ("reserved0", ctypes.c_uint16 * 1),
        ("inode", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
        ("blocks", ctypes.c_uint64),
        ("attributesMask", ctypes.c_uint64),
        ("accessTime", _StatxTimestamp),
        ("birthTime", _StatxTimestamp),
        ("changeTime", _StatxTimestamp),
        ("modifyTime", _StatxTimestamp),
        ("deviceMajor", ctypes.c_uint32),
        ("deviceMinor", ctypes.c_uint32),
        ("reserved1", ctypes.c_uint32 * 2),
        ("reserved2", ctypes.c_uint64 * 14),
    ]


_GENERATION_UNKNOWN = 0
_GENERATION_BIRTH = 1
_GENERATION_CHANGE = 2
_GENERATION_FILE_HANDLE = 3
_GENERATION_WINDOWS_FILE_ID = 4
_GENERATION_WINDOWS_LEGACY = 5
_GENERATION_WITNESS = 6


class _WindowsFileId128(ctypes.Structure):
    """Windows 128-bit filesystem object identifier."""

    _fields_ = [("identifier", ctypes.c_ubyte * 16)]


class _WindowsFileIdInfo(ctypes.Structure):
    """Windows FILE_ID_INFO structure."""

    _fields_ = [
        ("volumeSerialNumber", ctypes.c_uint64),
        ("fileId", _WindowsFileId128),
    ]


class _WindowsFileRenameInfo(ctypes.Structure):
    """Windows FILE_RENAME_INFO structure.

    The first member is a union containing either ``ReplaceIfExists`` or
    ``Flags``. A zero DWORD therefore requests the classic FileRenameInfo
    behaviour without replacing an existing target.
    """

    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("rootDirectory", ctypes.c_void_p),
        ("fileNameLength", ctypes.c_uint32),
        ("fileName", ctypes.c_wchar * 1),
    ]


class _WindowsIoStatusBlock(ctypes.Structure):
    """Windows IO_STATUS_BLOCK structure.

    The native structure contains a pointer-sized status union followed by a
    pointer-sized information value. Expressing the status as a signed
    32-bit field preserves the native padding on 64-bit Windows.
    """

    _fields_ = [
        ("status", ctypes.c_int32),
        ("information", ctypes.c_size_t),
    ]


# Relevant Win32 error codes. These are stable values from the Windows API
# and are not the same as every POSIX errno value.
_WINDOWS_ERROR_ACCESS_DENIED = 5
_WINDOWS_ERROR_FILE_EXISTS = 80
_WINDOWS_ERROR_INVALID_PARAMETER = 87
_WINDOWS_ERROR_ALREADY_EXISTS = 183

# Relevant NTSTATUS values used by the native rename fallback.
_WINDOWS_STATUS_SUCCESS = 0
_WINDOWS_STATUS_OBJECT_NAME_EXISTS = 0x40000000
_WINDOWS_STATUS_OBJECT_NAME_COLLISION = 0xC0000035


class _IdentityWitness:
    """Keep a Linux inode allocated while an identity is in use.

    Some Linux filesystems expose neither file handles nor a unique birth
    time. An inode number can then be recycled within one filesystem clock
    tick, making a pathname replacement indistinguishable by ``stat`` data
    alone. An ``O_PATH`` descriptor pins the original inode, preventing that
    reuse until every identity referring to it has been released.
    """

    __slots__ = ("__weakref__", "fileDescriptor")

    def __init__(self, fileDescriptor: int) -> None:
        self.fileDescriptor = fileDescriptor

    def _close(self) -> None:
        """Release the descriptor, if it is still open."""
        fileDescriptor = self.fileDescriptor
        self.fileDescriptor = -1
        if fileDescriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(fileDescriptor)

    def __del__(self) -> None:
        self._close()


_IDENTITY_WITNESSES: weakref.WeakValueDictionary[tuple[int, int], _IdentityWitness] = weakref.WeakValueDictionary()


@dataclass(frozen=True)
class FileIdentity:
    """Identify a filesystem object across pathname replacements.

    Device and inode numbers alone are not sufficient on Linux, where an
    inode can be reused immediately after a file is unlinked. The generation
    field is derived from a stable filesystem identifier when one is
    available: a Linux file handle, a Windows file ID, a Windows creation
    time, or a macOS birth time. It is unchanged by rename and hard-link
    operations, but differs for a new object that reuses the same device
    and inode numbers. Windows file IDs include their volume serial number
    so objects on different volumes can never compare equal.

    On Linux filesystems without file handles, a private descriptor witness
    is retained with the identity. The witness prevents inode-number reuse
    while the identity is live. It is deliberately excluded from equality
    and hashing because it is an implementation detail, not object data.
    Witness-backed identities use a dedicated generation source so normal
    metadata changes, such as a directory ctime update after publishing a
    child, do not invalidate the identity.
    """

    device: int
    inode: int
    generation: int
    generationSource: int
    _witness: Optional[_IdentityWitness] = field(default=None, compare=False, repr=False)


class PublishedFileError(OSError):
    """Raised when a published file cannot be verified after publication.

    The staged file's identity is retained so callers that own the
    publication can clean up or retry the exact object without touching a
    concurrent replacement.
    """

    def __init__(self, message: str, path: Path, publishedIdentity: FileIdentity) -> None:
        super().__init__(errno.EINVAL, message, str(path))
        self.publishedIdentity = publishedIdentity


class _WindowsHandleInformation(NamedTuple):
    """Identity and attributes of an object opened with a Windows handle."""

    identity: FileIdentity
    attributes: int
    legacyIdentity: Optional[FileIdentity] = None


logger = logging.getLogger(__name__)


def supportsDirectoryDescriptors() -> bool:
    """Return whether the platform supports descriptor-relative directory I/O."""
    return os.name != "nt" and os.open in os.supports_dir_fd


@dataclass(frozen=True)
class DirectorySnapshot:
    """A verified snapshot of regular files in a directory."""

    path: Path
    identity: FileIdentity
    files: tuple[Path, ...]
    fileIdentities: dict[str, FileIdentity]


def _linuxBirthTime(
    path: Optional[Path] = None,
    *,
    dirFd: Optional[int] = None,
    fileDescriptor: Optional[int] = None,
) -> tuple[int, int]:
    """Return a Linux statx birth time and inode, when available.

    The inode is returned so the caller can reject a birth time observed
    for a different object during a concurrent pathname replacement.
    """
    if not sys.platform.startswith("linux"):
        return 0, 0
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        statxFunction = getattr(libc, "statx", None)
    except (AttributeError, OSError):
        return 0, 0
    if statxFunction is None:
        return 0, 0

    statxFunction.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_StatxBuffer),
    ]
    statxFunction.restype = ctypes.c_int

    effectiveFd = _LINUX_AT_FDCWD
    flags = _LINUX_AT_SYMLINK_NOFOLLOW
    if dirFd is not None and path is not None:
        effectiveFd = dirFd
        pathBytes = os.fsencode(path.name)
    elif fileDescriptor is not None:
        # /proc/self/fd keeps the stat bound to the object held open by the
        # descriptor, including after the original pathname is unlinked.
        effectiveFd = _LINUX_AT_FDCWD
        flags = 0
        pathBytes = os.fsencode(f"/proc/self/fd/{fileDescriptor}")
    elif path is not None:
        pathBytes = os.fsencode(path)
    else:
        return 0, 0

    result = _StatxBuffer()
    status = statxFunction(
        effectiveFd,
        pathBytes,
        flags,
        _LINUX_STATX_BTIME,
        ctypes.byref(result),
    )
    if status != 0 or not result.mask & _LINUX_STATX_BTIME:
        return 0, 0
    birthTime = result.birthTime.seconds * 1_000_000_000 + result.birthTime.nanoseconds
    return birthTime, result.inode


def _linuxFileHandleBytes(fileDescriptor: int) -> Optional[bytes]:
    """Return an opaque Linux file handle for an open descriptor.

    Linux file handles include the filesystem's generation identifier where
    one is available. Unlike a birth timestamp, they remain distinct when
    an inode number is reused within the filesystem's timestamp granularity.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        handleFunction = getattr(libc, "name_to_handle_at", None)
    except (AttributeError, OSError):
        return None
    if handleFunction is None:
        return None

    handleFunction.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.POINTER(_LinuxFileHandle),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
    ]
    handleFunction.restype = ctypes.c_int

    resultBuffer = _LinuxFileHandle()
    mountId = ctypes.c_int()
    ctypes.set_errno(0)
    result = handleFunction(
        fileDescriptor,
        b"",
        ctypes.byref(resultBuffer),
        ctypes.byref(mountId),
        _LINUX_AT_EMPTY_PATH,
    )
    if result != 0:
        errorNumber = ctypes.get_errno()
        requiredBytes = int(resultBuffer.handle_bytes)
        if errorNumber != errno.EOVERFLOW or requiredBytes <= 0:
            return None
        if requiredBytes > _LINUX_MAX_HANDLE_SIZE:
            return None
        resultBuffer.handle_bytes = requiredBytes
        ctypes.set_errno(0)
        result = handleFunction(
            fileDescriptor,
            b"",
            ctypes.byref(resultBuffer),
            ctypes.byref(mountId),
            _LINUX_AT_EMPTY_PATH,
        )
    if result != 0:
        return None

    handleBytes = bytes(resultBuffer.file_handle[: resultBuffer.handle_bytes])
    if not handleBytes:
        return None
    return bytes([resultBuffer.handle_type & 0xFF]) + handleBytes


def _linuxFileHandleGeneration(
    pathStat: os.stat_result,
    path: Optional[Path] = None,
    *,
    dirFd: Optional[int] = None,
    fileDescriptor: Optional[int] = None,
) -> tuple[int, os.stat_result, Optional[_IdentityWitness]]:
    """Return a stable generation derived from a Linux file handle.

    A file handle is the preferred generation source, but not every
    filesystem supports one. When it is unavailable, an ``O_PATH`` witness
    is retained so the inode cannot be recycled while the identity is live.
    """
    if not sys.platform.startswith("linux"):
        return 0, pathStat, None

    ownDescriptor = False
    descriptor = fileDescriptor
    if descriptor is None:
        if path is None:
            return 0, pathStat, None
        flags = getattr(os, "O_PATH", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        if not flags:
            return 0, pathStat, None
        try:
            if dirFd is not None and os.open in os.supports_dir_fd:
                descriptor = os.open(path.name, flags, dir_fd=dirFd)
            else:
                descriptor = os.open(path, flags)
        except OSError:
            return 0, pathStat, None
        ownDescriptor = True

    try:
        openedStat = os.fstat(descriptor)
        if (
            openedStat.st_dev != pathStat.st_dev
            or openedStat.st_ino != pathStat.st_ino
            or stat.S_IFMT(openedStat.st_mode) != stat.S_IFMT(pathStat.st_mode)
        ):
            raise OSError(errno.ESTALE, "The path changed while its identity was being captured")

        handleBytes = _linuxFileHandleBytes(descriptor)
        if handleBytes is None:
            witness = _IDENTITY_WITNESSES.get((openedStat.st_dev, openedStat.st_ino))
            if witness is None:
                try:
                    witness = _IdentityWitness(os.dup(descriptor))
                except OSError:
                    witness = None
                else:
                    _IDENTITY_WITNESSES[(openedStat.st_dev, openedStat.st_ino)] = witness
            return 0, openedStat, witness
        digest = hashlib.blake2b(handleBytes, digest_size=8, person=b"UmbraEditID").digest()
        return int.from_bytes(digest, byteorder="little", signed=False), openedStat, None
    finally:
        if ownDescriptor and descriptor is not None:
            os.close(descriptor)


def fileIdentity(
    pathStat: os.stat_result,
    path: Optional[Path] = None,
    *,
    dirFd: Optional[int] = None,
    fileDescriptor: Optional[int] = None,
    generationSource: Optional[int] = None,
) -> FileIdentity:
    """Return a replacement-resistant identity for a stat result.

    ``path`` should be supplied whenever possible so Linux can obtain a
    stable file handle. A descriptor may be supplied for fstat results.
    Birth and change times are used as fallbacks on platforms without a
    stronger filesystem identifier.
    """
    if os.name == "nt":
        return _windowsFileIdentity(
            pathStat,
            path,
            fileDescriptor=fileDescriptor,
            generationSource=generationSource,
        )

    device = pathStat.st_dev
    witness: Optional[_IdentityWitness] = None
    if sys.platform.startswith("linux"):
        handleGeneration, openedStat, witness = _linuxFileHandleGeneration(
            pathStat,
            path,
            dirFd=dirFd,
            fileDescriptor=fileDescriptor,
        )
        if generationSource in (None, _GENERATION_FILE_HANDLE) and handleGeneration:
            return FileIdentity(
                0 if os.name == "nt" else openedStat.st_dev,
                openedStat.st_ino,
                handleGeneration,
                _GENERATION_FILE_HANDLE,
            )
        if generationSource == _GENERATION_FILE_HANDLE:
            return FileIdentity(
                device,
                pathStat.st_ino,
                0,
                _GENERATION_FILE_HANDLE,
                _witness=witness,
            )
        if generationSource is None and witness is not None:
            # Without a native file handle, the descriptor witness is the
            # only reliable way to prevent inode-number reuse. In
            # particular, overlayfs can repeat a statx birth time for
            # different objects, so birth time alone is not sufficient.
            return FileIdentity(
                device,
                pathStat.st_ino,
                0,
                _GENERATION_WITNESS,
                _witness=witness,
            )

    birthTime = getattr(pathStat, "st_birthtime_ns", None)
    if birthTime is None:
        birthSeconds = getattr(pathStat, "st_birthtime", None)
        if birthSeconds is not None:
            birthTime = int(birthSeconds * 1_000_000_000)

    if sys.platform.startswith("linux") and generationSource in (None, _GENERATION_BIRTH):
        statxBirthTime, statxInode = _linuxBirthTime(
            path,
            dirFd=dirFd,
            fileDescriptor=fileDescriptor,
        )
        if statxBirthTime and statxInode == pathStat.st_ino:
            return FileIdentity(
                device,
                pathStat.st_ino,
                statxBirthTime,
                _GENERATION_BIRTH,
                _witness=witness,
            )

    if generationSource is None:
        if birthTime is not None:
            generationSource = _GENERATION_BIRTH
        elif os.name == "nt":
            # On Windows, ctime is the stable creation time.
            generationSource = _GENERATION_BIRTH
            birthTime = pathStat.st_ctime_ns
        elif witness is not None:
            # The descriptor keeps the inode allocated. Device and inode
            # therefore identify the object without relying on its ctime,
            # which can legitimately change when a child is published.
            generationSource = _GENERATION_WITNESS
        else:
            generationSource = _GENERATION_CHANGE

    if generationSource == _GENERATION_BIRTH:
        generation = birthTime or 0
    elif generationSource == _GENERATION_CHANGE:
        generation = pathStat.st_ctime_ns
    elif generationSource == _GENERATION_WITNESS and witness is None:
        # A witness-backed identity cannot be verified without a fresh
        # descriptor. Fall back to the stricter change-time identity so
        # the comparison fails closed instead of accepting an unverified
        # inode number.
        generationSource = _GENERATION_CHANGE
        generation = pathStat.st_ctime_ns
    else:
        generation = 0
    return FileIdentity(device, pathStat.st_ino, generation, generationSource, _witness=witness)


def identityMatches(
    expectedIdentity: FileIdentity,
    pathStat: os.stat_result,
    path: Optional[Path] = None,
    *,
    dirFd: Optional[int] = None,
    fileDescriptor: Optional[int] = None,
) -> bool:
    """Return whether a stat result matches an expected file identity.

    The generation source recorded with the expected identity is reused so
    identities captured through the legacy stat-only helper remain
    comparable with later observations of the same object.
    """
    currentIdentity = fileIdentity(
        pathStat,
        path,
        dirFd=dirFd,
        fileDescriptor=fileDescriptor,
        generationSource=expectedIdentity.generationSource,
    )
    return currentIdentity == expectedIdentity


def verifyPathIdentity(
    path: Path,
    expectedIdentity: FileIdentity,
    *,
    expectedParent: Optional[FileIdentity] = None,
    requireDirectory: bool = False,
) -> os.stat_result:
    """Verify that a path still refers to the expected real object."""
    pathStat = os.lstat(path)
    if stat.S_ISLNK(pathStat.st_mode) or (getattr(pathStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError(errno.ELOOP, "The path cannot be a link", str(path))
    if requireDirectory and not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.ENOTDIR, "The path is not a directory", str(path))
    if not identityMatches(expectedIdentity, pathStat, path):
        raise OSError(errno.EINVAL, "The path changed while it was being used", str(path))
    if expectedParent is not None:
        parentStat = os.lstat(path.parent)
        if not _identityMatchesObject(expectedParent, parentStat, path.parent):
            raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(path.parent))
    return pathStat


def isPathWithin(path: Path, ancestor: Path) -> bool:
    """Return whether a path is the ancestor directory or below it.

    The check uses file identities rather than path spelling. This is
    important on case-insensitive file systems, where a differently
    cased path can refer to the same directory without comparing equal
    as a ``Path`` object.
    """
    ancestorStat = os.stat(ancestor)
    ancestorIdentity = fileIdentity(ancestorStat, ancestor)
    current = path
    while True:
        try:
            currentStat = os.stat(current)
        except FileNotFoundError:
            pass
        else:
            if _identityMatchesObject(ancestorIdentity, currentStat, current):
                return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def directoryHasNonQuarantineEntries(directory: Path) -> bool:
    """Return whether a directory contains anything besides retained quarantine.

    The application-owned quarantine directory is excluded from direct-child
    project scans. A link or non-directory using the reserved quarantine name
    is treated as a real entry so it cannot silently make a target appear
    empty.
    """
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name != QUARANTINE_DIRECTORY_NAME:
                    return True
                entryStat = os.lstat(entry.path)
                if (
                    stat.S_ISLNK(entryStat.st_mode)
                    or getattr(entryStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
                    or not stat.S_ISDIR(entryStat.st_mode)
                ):
                    return True
    except OSError:
        return True
    return False


def isLinkLike(path: Path) -> bool:
    """Return whether a path is a symbolic link or another link type.

    On Windows, this includes junctions and other reparse points. A path
    that does not exist is not considered a link.
    """
    try:
        pathStat = os.lstat(path)
    except FileNotFoundError:
        return False
    return bool(
        stat.S_ISLNK(pathStat.st_mode) or getattr(pathStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def ensureDirectory(path: Path) -> Path:
    """Create a directory and verify that it is a real directory.

    Symbolic links, junctions, and other reparse points are rejected.
    """
    if isLinkLike(path):
        raise OSError(errno.ELOOP, "The directory cannot be a link", str(path))
    path.mkdir(exist_ok=True)
    if isLinkLike(path):
        raise OSError(errno.ELOOP, "The directory cannot be a link", str(path))
    try:
        pathStat = os.stat(path, follow_symlinks=False)
    except OSError:
        raise
    if not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.ENOTDIR, "The path is not a directory", str(path))
    return path


def openDirectory(path: Path) -> int:
    """Open a real directory and return its file descriptor."""
    beforeStat = os.lstat(path)
    if stat.S_ISLNK(beforeStat.st_mode) or (
        getattr(beforeStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The directory cannot be a link", str(path))
    if not stat.S_ISDIR(beforeStat.st_mode):
        raise OSError(errno.ENOTDIR, "The path is not a directory", str(path))

    beforeIdentity = fileIdentity(beforeStat, path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fileDesc = os.open(path, flags)
    try:
        afterStat = os.fstat(fileDesc)
        if not stat.S_ISDIR(afterStat.st_mode) or not _identityMatchesObject(
            beforeIdentity,
            afterStat,
            path,
            fileDescriptor=fileDesc,
        ):
            raise OSError(errno.EINVAL, "The directory changed while it was being opened", str(path))
        return fileDesc
    except Exception:
        os.close(fileDesc)
        raise


def openDirectoryAt(parentFd: int, name: str) -> int:
    """Open a real child directory relative to an open parent directory."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fileDesc = os.open(name, flags, dir_fd=parentFd)
    try:
        childStat = os.fstat(fileDesc)
        if not stat.S_ISDIR(childStat.st_mode):
            raise OSError(errno.ENOTDIR, "The directory entry is not a directory", name)
        return fileDesc
    except Exception:
        os.close(fileDesc)
        raise


def _verifyParent(path: Path, expectedParent: Optional[FileIdentity]) -> None:
    """Verify that a file still has the expected parent directory."""
    if expectedParent is None:
        return
    parentStat = os.lstat(path.parent)
    if not _identityMatchesObject(expectedParent, parentStat, path.parent):
        raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(path.parent))


def openRegularFile(
    path: Path,
    *,
    expectedParent: Optional[FileIdentity] = None,
    expectedIdentity: Optional[FileIdentity] = None,
) -> BinaryIO:
    """Open a regular file without following symbolic links.

    The file identity is checked before and after opening it so a link
    cannot silently redirect the operation to another file. When an
    expected parent identity is provided, the parent is checked both
    before and after the file is opened. The optional expected identity
    binds the operation to a specific file observed by an earlier scan.
    """
    _verifyParent(path, expectedParent)
    beforeStat = os.lstat(path)
    if stat.S_ISLNK(beforeStat.st_mode) or (
        getattr(beforeStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The file cannot be a link", str(path))
    if not stat.S_ISREG(beforeStat.st_mode):
        raise OSError(errno.EINVAL, "The path is not a regular file", str(path))
    if expectedIdentity is not None and not identityMatches(expectedIdentity, beforeStat, path):
        raise OSError(errno.EINVAL, "The file changed before it could be opened", str(path))

    beforeIdentity = fileIdentity(beforeStat, path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fileDesc = os.open(path, flags)
    try:
        afterStat = os.fstat(fileDesc)
        if not stat.S_ISREG(afterStat.st_mode) or not _identityMatchesObject(
            beforeIdentity,
            afterStat,
            path,
            fileDescriptor=fileDesc,
        ):
            raise OSError(errno.EINVAL, "The file changed while it was being opened", str(path))
        if expectedIdentity is not None and not identityMatches(
            expectedIdentity,
            afterStat,
            fileDescriptor=fileDesc,
        ):
            raise OSError(errno.EINVAL, "The file changed while it was being opened", str(path))
        _verifyParent(path, expectedParent)
        return os.fdopen(fileDesc, mode="rb")
    except Exception:
        os.close(fileDesc)
        raise


def captureRegularFileIdentity(path: Path) -> Optional[FileIdentity]:
    """Return the identity of a regular file, or ``None`` if it is absent.

    Link-like and non-regular entries are rejected. The result can be
    passed to :func:`writeFileAtomic` to bind a later replacement to the
    file that was observed by the caller.
    """
    try:
        pathStat = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(pathStat.st_mode) or (getattr(pathStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError(errno.ELOOP, "The file cannot be a link", str(path))
    if not stat.S_ISREG(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The path is not a regular file", str(path))
    return fileIdentity(pathStat, path)


def openExclusiveFile(
    path: Path,
    dirFd: Optional[int] = None,
    mode: int = 0o000,
    *,
    readable: bool = False,
) -> int:
    """Create a new regular file exclusively and return its descriptor.

    On Windows, the file is opened with exclusive sharing so another
    process cannot read the partially written contents. On POSIX, the
    descriptor is created with the requested mode. The default mode 000
    keeps a staging file inaccessible until its contents are complete.
    Set ``readable`` when the completed descriptor must be decoded before
    it is closed.
    """
    if os.name == "nt":
        if dirFd is not None:
            raise OSError(errno.ENOTSUP, "Directory descriptors are not supported on Windows")

        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        createFile = kernel32.CreateFileW
        createFile.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        createFile.restype = ctypes.c_void_p
        handle = createFile(
            os.fspath(path),
            0xC0000000 if readable else 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0,  # No sharing while the copy is in progress
            None,
            1,  # CREATE_NEW
            0x80,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        invalidHandle = ctypes.c_void_p(-1).value
        if handle == invalidHandle:
            errorNumber = ctypes.get_last_error()
            if errorNumber in (80, 183):  # ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS
                raise FileExistsError(errorNumber, os.strerror(errorNumber), str(path))
            if errorNumber == 5:  # ERROR_ACCESS_DENIED
                # Some Windows filesystems report access denied rather than
                # file exists when CREATE_NEW collides with an existing
                # directory or reparse point. Classify that case as a
                # namespace collision, but preserve genuine ACL failures.
                try:
                    os.lstat(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                else:
                    raise FileExistsError(errno.EEXIST, "The target already exists", str(path))
            raise OSError(errorNumber, ctypes.FormatError(errorNumber), str(path))
        try:
            descriptorFlags = os.O_RDWR if readable else os.O_WRONLY
            return msvcrt.open_osfhandle(handle, descriptorFlags | getattr(os, "O_BINARY", 0))
        except Exception:
            try:
                _closeWindowsHandle(handle)
            except OSError:
                logger.warning("Could not close a Windows file handle after descriptor conversion failed")
            raise

    accessFlags = os.O_RDWR if readable else os.O_WRONLY
    flags = accessFlags | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if dirFd is not None and os.open in os.supports_dir_fd:
        return os.open(path, flags, mode, dir_fd=dirFd)
    return os.open(path, flags, mode)


def scanRegularFiles(directory: Path, *, expectedPath: Optional[Path] = None) -> DirectorySnapshot:
    """Return a verified snapshot of the regular files in a directory.

    Link-like entries are rejected rather than followed. The directory
    identity and resolved location are checked again after enumeration so
    a directory replacement is detected before its contents are copied.
    """
    beforeStat = os.lstat(directory)
    if stat.S_ISLNK(beforeStat.st_mode) or (
        getattr(beforeStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The directory cannot be a link", str(directory))
    if not stat.S_ISDIR(beforeStat.st_mode):
        raise OSError(errno.ENOTDIR, "The path is not a directory", str(directory))
    expectedLocation = Path(os.path.abspath(expectedPath)) if expectedPath is not None else None
    if expectedLocation is not None and directory.resolve() != expectedLocation:
        raise OSError(errno.EINVAL, "The directory resolves outside the expected location", str(directory))

    beforeIdentity = fileIdentity(beforeStat, directory)
    files: list[Path] = []
    fileIdentities: dict[str, FileIdentity] = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            entryPath = Path(entry.path)
            if isLinkLike(entryPath):
                raise OSError(errno.ELOOP, "The file cannot be a link", str(entryPath))
            entryStat = os.lstat(entryPath)
            if stat.S_ISLNK(entryStat.st_mode) or (
                getattr(entryStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise OSError(errno.ELOOP, "The file cannot be a link", str(entryPath))
            if stat.S_ISREG(entryStat.st_mode):
                files.append(entryPath)
                fileIdentities[entryPath.name] = fileIdentity(entryStat, entryPath)

    afterStat = os.lstat(directory)
    if not _identityMatchesObject(beforeIdentity, afterStat, directory):
        raise OSError(errno.EINVAL, "The directory changed while it was being scanned", str(directory))
    expectedLocation = Path(os.path.abspath(expectedPath)) if expectedPath is not None else None
    if expectedLocation is not None and directory.resolve() != expectedLocation:
        raise OSError(errno.EINVAL, "The directory resolves outside the expected location", str(directory))

    return DirectorySnapshot(
        path=directory,
        identity=beforeIdentity,
        files=tuple(files),
        fileIdentities=fileIdentities,
    )


def _entryStat(path: Path, dirFd: Optional[int]) -> os.stat_result:
    """Return a no-follow stat result for a directory entry."""
    if dirFd is not None and os.stat in os.supports_dir_fd:
        return os.stat(path.name, dir_fd=dirFd, follow_symlinks=False)
    return os.lstat(path)


def _entryIdentity(path: Path, dirFd: Optional[int], pathStat: os.stat_result) -> FileIdentity:
    """Return an identity for a directory entry observed through a descriptor."""
    if dirFd is not None:
        return fileIdentity(pathStat, path, dirFd=dirFd)
    return fileIdentity(pathStat, path)


def _entryIdentityMatches(
    expectedIdentity: FileIdentity,
    path: Path,
    dirFd: Optional[int],
    pathStat: os.stat_result,
) -> bool:
    """Return whether a directory entry still matches its expected identity."""
    return _identityMatchesObject(
        expectedIdentity,
        pathStat,
        path,
        dirFd=dirFd,
    )


def _windowsKernel32() -> Any:
    """Return the Windows kernel32 DLL without importing it on POSIX."""
    return cast("Any", ctypes).WinDLL("kernel32", use_last_error=True)


def _windowsNtdll() -> Any:
    """Return the Windows ntdll DLL without importing it on POSIX."""
    return cast("Any", ctypes).WinDLL("ntdll")


def _windowsNtStatusToDosError(status: int) -> int:
    """Translate an NTSTATUS value to a Win32 error number."""
    ntdll = _windowsNtdll()
    translate = ntdll.RtlNtStatusToDosError
    translate.argtypes = [ctypes.c_int32]
    translate.restype = ctypes.c_uint32
    signedStatus = status if status < 0x80000000 else status - 0x100000000
    return int(translate(signedStatus))


def _windowsLastError() -> int:
    """Return the last Windows error code."""
    ctypesModule = cast("Any", ctypes)
    getLastError = getattr(ctypesModule, "get_last_error", None)
    if getLastError is None:
        return ctypes.get_errno()
    return int(getLastError())


def _windowsError(errorNumber: int, path: Path) -> OSError:
    """Return an OSError with a Windows-formatted error message."""
    ctypesModule = cast("Any", ctypes)
    formatError = getattr(ctypesModule, "FormatError", None)
    message = formatError(errorNumber) if formatError is not None else os.strerror(errorNumber)
    return OSError(errorNumber, message, str(path))


def _openWindowsDeleteHandle(path: Path, *, directory: bool) -> int:
    """Open a Windows path with delete access and return a native handle."""
    kernel32 = _windowsKernel32()
    createFile = kernel32.CreateFileW
    createFile.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    createFile.restype = ctypes.c_void_p

    flags = 0x00200000  # FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= 0x02000000  # FILE_FLAG_BACKUP_SEMANTICS
    handle = createFile(
        os.fspath(path),
        0x00010000 | 0x00000080,  # DELETE | FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002 | 0x00000004,  # Share read, write, and delete
        None,
        3,  # OPEN_EXISTING
        flags,
        None,
    )
    invalidHandle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalidHandle:
        raise _windowsError(_windowsLastError(), path)
    return int(handle)


def _closeWindowsHandle(handle: int) -> None:
    """Close a native Windows handle and report a failed close."""
    kernel32 = _windowsKernel32()
    closeHandle = kernel32.CloseHandle
    closeHandle.argtypes = [ctypes.c_void_p]
    closeHandle.restype = ctypes.c_int
    if not closeHandle(handle):
        raise _windowsError(_windowsLastError(), Path("."))


def _windowsLegacyHandleInformation(handle: int) -> _WindowsHandleInformation:
    """Return legacy Windows identity and attributes for a handle."""

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", ctypes.c_uint32),
            ("creationTime", FileTime),
            ("accessTime", FileTime),
            ("writeTime", FileTime),
            ("volumeSerial", ctypes.c_uint32),
            ("sizeHigh", ctypes.c_uint32),
            ("sizeLow", ctypes.c_uint32),
            ("links", ctypes.c_uint32),
            ("indexHigh", ctypes.c_uint32),
            ("indexLow", ctypes.c_uint32),
        ]

    kernel32 = _windowsKernel32()
    getInformation = kernel32.GetFileInformationByHandle
    getInformation.argtypes = [ctypes.c_void_p, ctypes.POINTER(FileInformation)]
    getInformation.restype = ctypes.c_int

    information = FileInformation()
    if not getInformation(handle, ctypes.byref(information)):
        raise _windowsError(_windowsLastError(), Path("."))
    fileIndex = (int(information.indexHigh) << 32) | int(information.indexLow)
    # Some filesystems, notably ReFS, can expose a zero legacy file index
    # while still providing a valid 128-bit FILE_ID_INFO identifier. Keep the
    # legacy value available so the caller can prefer FILE_ID_INFO before
    # deciding that no stable identifier exists.
    creationValue = (int(information.creationTime.high) << 32) | int(information.creationTime.low)
    creationNanoseconds = (creationValue - 116444736000000000) * 100
    identity = FileIdentity(
        int(information.volumeSerial),
        fileIndex,
        creationNanoseconds,
        _GENERATION_WINDOWS_LEGACY,
    )
    return _WindowsHandleInformation(
        identity=identity,
        attributes=int(information.attributes),
        legacyIdentity=identity,
    )


def _windowsFileId(handle: int) -> Optional[tuple[int, int]]:
    """Return the volume serial and 128-bit file ID for a handle."""
    kernel32 = _windowsKernel32()
    getInformation = kernel32.GetFileInformationByHandleEx
    getInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    getInformation.restype = ctypes.c_int

    information = _WindowsFileIdInfo()
    if not getInformation(handle, 18, ctypes.byref(information), ctypes.sizeof(information)):  # FileIdInfo
        errorNumber = _windowsLastError()
        if errorNumber in (1, 50, 87):  # ERROR_INVALID_FUNCTION, NOT_SUPPORTED, INVALID_PARAMETER
            return None
        raise _windowsError(errorNumber, Path("."))
    fileId = int.from_bytes(bytes(information.fileId.identifier), byteorder="little")
    if fileId == 0:
        return None
    return int(information.volumeSerialNumber), fileId


def _windowsHandleInformation(
    handle: int,
    *,
    identitySource: Optional[int] = None,
) -> _WindowsHandleInformation:
    """Return the identity and attributes of a Windows handle.

    ``FILE_ID_INFO`` is preferred because its 128-bit identifier also works
    on filesystems such as ReFS. The legacy 64-bit identifier remains a
    fallback for older filesystems, but it is always combined with the
    volume serial number and creation time.
    """
    legacyInformation = _windowsLegacyHandleInformation(handle)
    if identitySource == _GENERATION_WINDOWS_LEGACY:
        if legacyInformation.identity.inode == 0:
            raise OSError(errno.EIO, "Windows returned an unusable legacy file identifier", str(Path(".")))
        return legacyInformation

    fileId = _windowsFileId(handle)
    if fileId is not None:
        identity = FileIdentity(
            fileId[0],
            fileId[1],
            legacyInformation.identity.generation,
            _GENERATION_WINDOWS_FILE_ID,
        )
        return _WindowsHandleInformation(
            identity=identity,
            attributes=legacyInformation.attributes,
            legacyIdentity=legacyInformation.identity,
        )
    if identitySource == _GENERATION_WINDOWS_FILE_ID:
        raise OSError(errno.EIO, "Windows did not return a 128-bit file identifier", str(Path(".")))
    if legacyInformation.identity.inode == 0:
        raise OSError(errno.EIO, "Windows returned an unusable file identifier", str(Path(".")))
    return legacyInformation


def _windowsHandleIdentity(handle: int) -> FileIdentity:
    """Return the stable identity of the object held by a Windows handle."""
    return _windowsHandleInformation(handle).identity


def _openWindowsIdentityHandle(path: Path) -> int:
    """Open a path for authoritative Windows identity observation."""
    kernel32 = _windowsKernel32()
    createFile = kernel32.CreateFileW
    createFile.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    createFile.restype = ctypes.c_void_p

    handle = createFile(
        os.fspath(path),
        0x00000080,  # FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002 | 0x00000004,  # Share read, write, and delete
        None,
        3,  # OPEN_EXISTING
        0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
        None,
    )
    invalidHandle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalidHandle:
        raise _windowsError(_windowsLastError(), path)
    return int(handle)


def _openWindowsRenameParentHandle(path: Path) -> int:
    """Open a Windows directory for use as a rename root handle.

    The handle is opened on the directory object itself and remains valid
    if the directory's pathname is concurrently replaced. ``FILE_TRAVERSE``
    is requested in addition to attribute access so the handle can be used
    as the ``RootDirectory`` of ``FILE_RENAME_INFO``.
    """
    kernel32 = _windowsKernel32()
    createFile = kernel32.CreateFileW
    createFile.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    createFile.restype = ctypes.c_void_p

    handle = createFile(
        os.fspath(path),
        0x00000020 | 0x00000080,  # FILE_TRAVERSE | FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002 | 0x00000004,  # Share read, write, and delete
        None,
        3,  # OPEN_EXISTING
        0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
        None,
    )
    invalidHandle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalidHandle:
        raise _windowsError(_windowsLastError(), path)
    return int(handle)


def _windowsDescriptorHandle(fileDescriptor: int) -> Optional[int]:
    """Return the native handle associated with a Windows file descriptor."""
    try:
        import msvcrt

        getOsfHandle = getattr(msvcrt, "get_osfhandle", None)
        if getOsfHandle is None:
            return None
        handle = getOsfHandle(fileDescriptor)
    except (ImportError, OSError, ValueError):
        return None
    if handle is None or handle < 0:
        return None
    return int(handle)


def _windowsFileIdentity(
    pathStat: os.stat_result,
    path: Optional[Path],
    *,
    fileDescriptor: Optional[int],
    generationSource: Optional[int],
) -> FileIdentity:
    """Return an identity observed through an authoritative Windows handle.

    A pathname observation and a later handle observation must describe the
    same object. The stat snapshot is therefore bound to the native handle
    before its identity is accepted. If the native handle cannot be opened,
    or the snapshot cannot be bound safely, this function fails closed
    instead of silently weakening the identity to stat metadata.
    """
    if generationSource == _GENERATION_BIRTH:
        # Preserve the stat-only fallback only for identities explicitly
        # created through the legacy compatibility path.
        return FileIdentity(
            int(getattr(pathStat, "st_dev", 0)),
            int(pathStat.st_ino),
            int(pathStat.st_ctime_ns),
            _GENERATION_BIRTH,
        )

    handle: Optional[int] = None
    ownHandle = False
    try:
        if fileDescriptor is not None:
            handle = _windowsDescriptorHandle(fileDescriptor)
        elif path is not None:
            handle = _openWindowsIdentityHandle(path)
            ownHandle = True
        if handle is None:
            raise OSError(errno.EIO, "The Windows object identity is unavailable", str(path or Path(".")))

        requestedSource = generationSource
        if requestedSource not in (_GENERATION_WINDOWS_FILE_ID, _GENERATION_WINDOWS_LEGACY):
            requestedSource = None
        information = _windowsHandleInformation(handle, identitySource=requestedSource)
        if path is not None and fileDescriptor is None and not _windowsStatMatchesHandle(pathStat, information):
            raise OSError(
                errno.ESTALE,
                "The path changed while its Windows identity was being captured",
                str(path),
            )
        identity = information.identity
    finally:
        if ownHandle and handle is not None:
            try:
                _closeWindowsHandle(handle)
            except OSError:
                if sys.exc_info()[0] is None:
                    raise
                logger.warning("Could not close a Windows identity handle", exc_info=True)

    return identity


def _windowsHandleFinalPath(handle: int) -> Path:
    """Return the current path of the object held by a Windows handle."""
    kernel32 = _windowsKernel32()
    getFinalPath = kernel32.GetFinalPathNameByHandleW
    getFinalPath.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    getFinalPath.restype = ctypes.c_uint32

    bufferSize = 32768
    while True:
        buffer = ctypes.create_unicode_buffer(bufferSize)
        length = getFinalPath(handle, buffer, bufferSize, 0)
        if length == 0:
            raise _windowsError(_windowsLastError(), Path("."))
        if length < bufferSize:
            pathText = buffer.value
            break
        bufferSize = length + 1

    if pathText.startswith("\\\\?\\UNC\\"):
        pathText = "\\\\" + pathText[8:]
    elif pathText.startswith("\\\\?\\"):
        pathText = pathText[4:]
    return Path(pathText)


def _windowsPathKey(path: Path) -> str:
    """Return a normalised, case-insensitive Windows path key."""
    pathText = os.fspath(path)
    if pathText.startswith("\\\\?\\UNC\\"):
        pathText = "\\\\" + pathText[8:]
    elif pathText.startswith("\\\\?\\"):
        pathText = pathText[4:]
    return ntpath.normcase(ntpath.normpath(ntpath.abspath(pathText)))


def _windowsPathsEqual(left: Path, right: Path) -> bool:
    """Return whether two Windows paths identify the same namespace entry."""
    return _windowsPathKey(left) == _windowsPathKey(right)


def _windowsPathParentKey(path: Path) -> str:
    """Return the normalised parent key of a Windows path."""
    return ntpath.dirname(_windowsPathKey(path))


def _windowsPathIsDirectChild(parent: Path, child: Path) -> bool:
    """Return whether a Windows path is a direct child of another path."""
    return _windowsPathParentKey(child) == _windowsPathKey(parent)


def _setWindowsDeleteDisposition(handle: int, path: Path) -> None:
    """Mark the object held by a Windows handle for deletion."""

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("deleteFile", ctypes.c_ubyte)]

    kernel32 = _windowsKernel32()
    setFileInformation = kernel32.SetFileInformationByHandle
    setFileInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    setFileInformation.restype = ctypes.c_int

    disposition = FileDispositionInfo(deleteFile=1)
    if not setFileInformation(
        handle,
        4,  # FileDispositionInfo
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise _windowsError(_windowsLastError(), path)


def _deleteWindowsEntryByHandle(path: Path, expectedIdentity: FileIdentity) -> None:
    """Delete the exact Windows object referenced by an open handle."""
    pathStat = os.lstat(path)
    if not identityMatches(expectedIdentity, pathStat, path):
        raise OSError(errno.EINVAL, "The file changed before it could be removed", str(path))
    # Backup semantics are also used for regular files. This permits a
    # directory symlink or junction to be opened as the reparse point
    # itself instead of following it to its target.
    handle = _openWindowsDeleteHandle(path, directory=True)
    try:
        identitySource = (
            expectedIdentity.generationSource
            if expectedIdentity.generationSource in (_GENERATION_WINDOWS_FILE_ID, _GENERATION_WINDOWS_LEGACY)
            else None
        )
        handleInformation = (
            _windowsHandleInformation(handle)
            if identitySource is None
            else _windowsHandleInformation(handle, identitySource=identitySource)
        )
        if handleInformation.identity != expectedIdentity:
            raise OSError(errno.EINVAL, "The file changed before it could be removed", str(path))
        _setWindowsDeleteDisposition(handle, path)
    except BaseException:
        try:
            _closeWindowsHandle(handle)
        except OSError:
            logger.warning("Could not close a Windows deletion handle", exc_info=True)
        raise
    else:
        _closeWindowsHandle(handle)


def _windowsStatMatchesHandle(
    pathStat: os.stat_result,
    information: _WindowsHandleInformation,
) -> bool:
    """Return whether a stat snapshot describes the object held by a handle.

    Python 3.9 exposes the legacy 64-bit Windows file index through
    ``st_ino``. Python 3.12 and later may expose the full 128-bit file ID
    instead. A snapshot may therefore be bound through either identifier,
    provided the native handle exposes a matching value.

    Python's Windows ``st_dev`` is a drive number, not the filesystem
    volume serial returned by ``GetFileInformationByHandle``. The two
    values cannot be compared. The validated parent final path establishes
    that the entry is on the expected volume, while the file identifier
    and creation time bind the stat snapshot to the opened object.
    """
    try:
        statInode = int(pathStat.st_ino)
    except (AttributeError, TypeError, ValueError):
        return False

    legacyIdentity = information.legacyIdentity
    inodeMatches = statInode != 0 and statInode == information.identity.inode
    if not inodeMatches and legacyIdentity is not None:
        inodeMatches = statInode != 0 and statInode == legacyIdentity.inode
    if not inodeMatches:
        # A Python 3.9 snapshot can expose only the legacy 64-bit index.
        # If the filesystem also suppresses that value, the snapshot
        # cannot be bound safely to the native handle and callers must
        # fail closed.
        return False

    creationTime = getattr(pathStat, "st_birthtime_ns", None)
    if creationTime is None:
        creationTime = getattr(pathStat, "st_ctime_ns", None)
    expectedCreationTime = legacyIdentity.generation if legacyIdentity is not None else information.identity.generation
    if creationTime is None or int(creationTime) != expectedCreationTime:
        return False

    statAttributes = int(getattr(pathStat, "st_file_attributes", 0))
    handleAttributes = int(information.attributes)
    statIsReparse = bool(statAttributes & _FILE_ATTRIBUTE_REPARSE_POINT)
    handleIsReparse = bool(handleAttributes & _FILE_ATTRIBUTE_REPARSE_POINT)
    if statIsReparse != handleIsReparse:
        return False
    if not statIsReparse:
        statIsDirectory = stat.S_ISDIR(pathStat.st_mode)
        handleIsDirectory = bool(handleAttributes & _FILE_ATTRIBUTE_DIRECTORY)
        if statIsDirectory != handleIsDirectory:
            return False
    return True


def _removeWindowsDirectoryContents(
    directoryHandle: int,
    directoryPath: Path,
    expectedIdentity: FileIdentity,
    expectedFinalPath: Path,
) -> None:
    """Remove the contents of one validated Windows directory handle.

    The expected final path is captured while the directory is still known
    to be below the validated root. A directory renamed out of that root
    must be rejected before its new location is scanned or any child is
    deleted.
    """
    directoryFinalPath = _windowsHandleFinalPath(directoryHandle)
    if not _windowsPathsEqual(directoryFinalPath, expectedFinalPath):
        raise OSError(errno.EINVAL, "The cleanup directory moved outside the validated root", str(directoryPath))
    identitySource = (
        expectedIdentity.generationSource
        if expectedIdentity.generationSource in (_GENERATION_WINDOWS_FILE_ID, _GENERATION_WINDOWS_LEGACY)
        else None
    )
    directoryInformation = (
        _windowsHandleInformation(directoryHandle)
        if identitySource is None
        else _windowsHandleInformation(directoryHandle, identitySource=identitySource)
    )
    if directoryInformation.identity != expectedIdentity:
        raise OSError(errno.EINVAL, "The cleanup directory changed before it was scanned", str(directoryPath))
    children: list[tuple[Path, os.stat_result]] = []

    # os.scandir cannot consume a Windows HANDLE. The directory handle is
    # therefore used as the authority: the scanned pathname must continue
    # to resolve to that exact handle, and every opened child must resolve
    # to the same direct-child pathname below it. The stat snapshot is kept
    # so that a replacement between enumeration and handle opening can be
    # detected before the replacement is marked for deletion.
    with os.scandir(directoryFinalPath) as entries:
        for entry in entries:
            entryPath = Path(entry.path)
            # On Windows, DirEntry.stat(follow_symlinks=False) is built from
            # the cached FindFirstFile data on both Python 3.9 and 3.12.
            # That data does not contain a file index or FILE_ID_INFO, so it
            # cannot safely bind the entry to a later native handle. A
            # path-based lstat opens the object and supplies the legacy file
            # index on Python 3.9 or the full 128-bit ID on Python 3.12+.
            entryStat = os.lstat(entryPath)
            children.append((entryPath, entryStat))

    if not _windowsPathsEqual(expectedFinalPath, _windowsHandleFinalPath(directoryHandle)):
        raise OSError(errno.EINVAL, "The cleanup directory changed before it was scanned", str(directoryPath))

    for childPath, childStat in children:
        if not _windowsPathsEqual(expectedFinalPath, _windowsHandleFinalPath(directoryHandle)):
            raise OSError(errno.EINVAL, "The cleanup directory changed while it was being cleaned", str(directoryPath))

        # Always request backup semantics so a reparse point is opened as
        # the link object itself. Its target is never traversed or deleted.
        childHandle = _openWindowsDeleteHandle(childPath, directory=True)
        try:
            childInformation = _windowsHandleInformation(childHandle)
            if not _windowsStatMatchesHandle(childStat, childInformation):
                raise OSError(errno.EINVAL, "The cleanup entry changed before it could be removed", str(childPath))
            childIdentity = childInformation.identity

            childFinalPath = _windowsHandleFinalPath(childHandle)
            if not _windowsPathsEqual(childFinalPath, childPath):
                raise OSError(errno.EINVAL, "The cleanup entry changed before it could be removed", str(childPath))
            if not _windowsPathIsDirectChild(directoryFinalPath, childFinalPath):
                raise OSError(errno.EINVAL, "The cleanup entry is outside the validated directory", str(childPath))

            if childInformation.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                # Reparse points are leaves. Delete the link object through
                # its handle without following it to another directory.
                _setWindowsDeleteDisposition(childHandle, childPath)
            else:
                if childInformation.attributes & _FILE_ATTRIBUTE_DIRECTORY:
                    _removeWindowsDirectoryContents(
                        childHandle,
                        childPath,
                        childIdentity,
                        childFinalPath,
                    )
                    if not _windowsPathsEqual(childFinalPath, _windowsHandleFinalPath(childHandle)):
                        raise OSError(
                            errno.EINVAL, "The cleanup directory changed while it was being cleaned", str(childPath)
                        )

                _setWindowsDeleteDisposition(childHandle, childPath)
        except BaseException:
            try:
                _closeWindowsHandle(childHandle)
            except OSError:
                logger.warning("Could not close a Windows cleanup handle", exc_info=True)
            raise
        else:
            _closeWindowsHandle(childHandle)

    if not _windowsPathsEqual(expectedFinalPath, _windowsHandleFinalPath(directoryHandle)):
        raise OSError(errno.EINVAL, "The cleanup directory changed while it was being cleaned", str(directoryPath))


def _removeWindowsTreeByHandle(
    path: Path,
    expectedIdentity: FileIdentity,
    expectedParent: Optional[FileIdentity] = None,
) -> None:
    """Remove a Windows tree through handles bound to the observed objects."""
    pathStat = os.lstat(path)
    if isLinkLike(path) or not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The cleanup path is not a real directory", str(path))
    if not identityMatches(expectedIdentity, pathStat, path):
        raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

    if expectedParent is not None:
        parentStat = os.lstat(path.parent)
        if isLinkLike(path.parent) or not stat.S_ISDIR(parentStat.st_mode):
            raise OSError(errno.EINVAL, "The cleanup parent is not a real directory", str(path.parent))
        parentIdentity = fileIdentity(parentStat, path.parent)
        if parentIdentity != expectedParent:
            raise OSError(errno.EINVAL, "The cleanup parent changed before it could be removed", str(path.parent))

    rootHandle: Optional[int] = None
    primaryFailure = False
    try:
        rootHandle = _openWindowsDeleteHandle(path, directory=True)

        identitySource = (
            expectedIdentity.generationSource
            if expectedIdentity.generationSource in (_GENERATION_WINDOWS_FILE_ID, _GENERATION_WINDOWS_LEGACY)
            else None
        )
        rootInformation = (
            _windowsHandleInformation(rootHandle)
            if identitySource is None
            else _windowsHandleInformation(rootHandle, identitySource=identitySource)
        )
        if rootInformation.identity != expectedIdentity:
            raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))
        if rootInformation.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(errno.ELOOP, "The cleanup path cannot be a link", str(path))
        if not rootInformation.attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError(errno.ENOTDIR, "The cleanup path is not a directory", str(path))

        rootFinalPath = _windowsHandleFinalPath(rootHandle)
        if not _windowsPathsEqual(rootFinalPath, path):
            raise OSError(errno.EINVAL, "The cleanup path moved before it could be removed", str(path))
        if _windowsPathParentKey(rootFinalPath) != _windowsPathParentKey(path):
            raise OSError(errno.EINVAL, "The cleanup path moved outside its validated parent", str(path))
        _removeWindowsDirectoryContents(
            rootHandle,
            path,
            expectedIdentity,
            rootFinalPath,
        )
        finalRootInformation = (
            _windowsHandleInformation(rootHandle)
            if identitySource is None
            else _windowsHandleInformation(rootHandle, identitySource=identitySource)
        )
        if finalRootInformation.identity != expectedIdentity:
            raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))
        _setWindowsDeleteDisposition(rootHandle, path)
    except BaseException:
        primaryFailure = True
        raise
    finally:
        closeError: Optional[OSError] = None
        for handle, description in ((rootHandle, "cleanup"),):
            if handle is None:
                continue
            try:
                _closeWindowsHandle(handle)
            except OSError as exc:
                if closeError is None:
                    closeError = exc
                logger.warning("Could not close a Windows %s handle", description, exc_info=True)
        if closeError is not None and not primaryFailure:
            raise closeError


def _sameFileObject(leftIdentity: FileIdentity, rightIdentity: FileIdentity) -> bool:
    """Return whether two identities refer to the same device and inode."""
    return leftIdentity.device == rightIdentity.device and leftIdentity.inode == rightIdentity.inode


def _identityMatchesObject(
    expectedIdentity: FileIdentity,
    pathStat: os.stat_result,
    path: Optional[Path] = None,
    *,
    dirFd: Optional[int] = None,
    fileDescriptor: Optional[int] = None,
) -> bool:
    """Match an object while allowing rename-induced change-time updates."""
    if expectedIdentity.generationSource == _GENERATION_CHANGE:
        currentIdentity = fileIdentity(
            pathStat,
            path,
            dirFd=dirFd,
            fileDescriptor=fileDescriptor,
            generationSource=_GENERATION_CHANGE,
        )
        return _sameFileObject(expectedIdentity, currentIdentity)
    return identityMatches(
        expectedIdentity,
        pathStat,
        path,
        dirFd=dirFd,
        fileDescriptor=fileDescriptor,
    )


def _descriptorHasEntries(directoryFd: int) -> bool:
    """Return whether an open directory contains any entries.

    Cleanup uses one validated project-level quarantine, so even a nested
    quarantine-looking directory is significant. Treating it as ordinary
    content prevents legacy cleanup from silently absorbing an object that
    was not created by the current cleanup operation.
    """
    return bool(os.listdir(directoryFd))


def _openQuarantineDirectory(parentPath: Path, parentFd: int) -> tuple[int, Path]:
    """Open or create the application quarantine directory in a parent."""
    with contextlib.suppress(FileExistsError):
        os.mkdir(QUARANTINE_DIRECTORY_NAME, 0o700, dir_fd=parentFd)

    quarantineStat = os.stat(
        QUARANTINE_DIRECTORY_NAME,
        dir_fd=parentFd,
        follow_symlinks=False,
    )
    if stat.S_ISLNK(quarantineStat.st_mode) or (
        getattr(quarantineStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The cleanup quarantine cannot be a link", str(parentPath))
    if not stat.S_ISDIR(quarantineStat.st_mode):
        raise OSError(errno.ENOTDIR, "The cleanup quarantine is not a directory", str(parentPath))

    quarantineIdentity = fileIdentity(
        quarantineStat,
        Path(QUARANTINE_DIRECTORY_NAME),
        dirFd=parentFd,
    )
    quarantineFd = openDirectoryAt(parentFd, QUARANTINE_DIRECTORY_NAME)
    try:
        openedStat = os.fstat(quarantineFd)
        if not stat.S_ISDIR(openedStat.st_mode) or not _identityMatchesObject(
            quarantineIdentity,
            openedStat,
            Path(QUARANTINE_DIRECTORY_NAME),
            fileDescriptor=quarantineFd,
        ):
            raise OSError(errno.EINVAL, "The cleanup quarantine changed while it was being opened", str(parentPath))
        if hasattr(os, "fchmod"):
            os.fchmod(quarantineFd, 0o700)
    except Exception:
        os.close(quarantineFd)
        raise
    return quarantineFd, parentPath / QUARANTINE_DIRECTORY_NAME


def _restoreQuarantinedEntry(
    quarantineName: str,
    quarantineFd: int,
    sourceName: str,
    parentFd: int,
    expectedIdentity: FileIdentity,
) -> bool:
    """Restore a quarantined entry without replacing a new source entry."""
    try:
        quarantineStat = os.stat(quarantineName, dir_fd=quarantineFd, follow_symlinks=False)
    except OSError:
        return False
    quarantineIdentity = fileIdentity(quarantineStat, Path(quarantineName), dirFd=quarantineFd)
    if not _identityMatchesObject(
        expectedIdentity,
        quarantineStat,
        Path(quarantineName),
        dirFd=quarantineFd,
    ):
        return False
    try:
        moved = renameNoReplaceBetween(
            Path(quarantineName),
            Path(sourceName),
            sourceDirFd=quarantineFd,
            targetDirFd=parentFd,
        )
    except OSError:
        return False
    if not moved:
        return False
    try:
        restoredStat = os.stat(sourceName, dir_fd=parentFd, follow_symlinks=False)
    except OSError:
        return False
    restoredIdentity = fileIdentity(restoredStat, Path(sourceName), dirFd=parentFd)
    return _identityMatchesObject(
        expectedIdentity,
        restoredStat,
        Path(sourceName),
        dirFd=parentFd,
    )


def _quarantineOwnedEntry(
    path: Path,
    expectedIdentity: Optional[FileIdentity] = None,
    *,
    dirFd: Optional[int] = None,
    requireEmpty: bool = False,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> Path:
    """Move an owned entry into a retained POSIX quarantine directory.

    POSIX does not expose an inode-bound unlink operation. The entry is
    therefore moved to a private quarantine directory and retained. The
    source pathname is never deleted, so a concurrent replacement cannot
    be destroyed by the cleanup operation.
    """
    if quarantineParent is not None and expectedQuarantineParent is None:
        raise ValueError("A central cleanup quarantine requires a validated parent identity")

    ownParentFd = False
    parentFd = dirFd
    if parentFd is None:
        parentFd = openDirectory(path.parent)
        ownParentFd = True

    ownQuarantineParentFd = False
    quarantineParentFd = parentFd
    quarantineParentPath = path.parent
    try:
        if quarantineParent is not None:
            quarantineParentFd = openDirectory(quarantineParent)
            ownQuarantineParentFd = True
            quarantineParentPath = quarantineParent
            quarantineParentStat = os.fstat(quarantineParentFd)
            quarantineParentIdentity = fileIdentity(
                quarantineParentStat,
                fileDescriptor=quarantineParentFd,
            )
            if expectedQuarantineParent is not None and not _identityMatchesObject(
                expectedQuarantineParent,
                quarantineParentStat,
                quarantineParent,
                fileDescriptor=quarantineParentFd,
            ):
                raise OSError(
                    errno.EINVAL,
                    "The cleanup quarantine parent changed while it was being opened",
                    str(quarantineParent),
                )
            if os.fstat(parentFd).st_dev != quarantineParentStat.st_dev:
                raise OSError(
                    errno.EXDEV,
                    "The cleanup quarantine parent is on a different filesystem",
                    str(quarantineParent),
                )
        elif expectedQuarantineParent is not None:
            parentStat = os.fstat(parentFd)
            if not _identityMatchesObject(
                expectedQuarantineParent,
                parentStat,
                path.parent,
                fileDescriptor=parentFd,
            ):
                raise OSError(
                    errno.EINVAL,
                    "The cleanup quarantine parent changed while it was being opened",
                    str(path.parent),
                )
    except Exception:
        if ownQuarantineParentFd and quarantineParentFd is not None:
            os.close(quarantineParentFd)
        if ownParentFd:
            os.close(parentFd)
        raise

    guardFd: Optional[int] = None
    quarantineFd: Optional[int] = None
    try:
        if os.stat in os.supports_dir_fd:
            pathStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
        else:
            pathStat = os.lstat(path)
        if expectedIdentity is None:
            expectedIdentity = fileIdentity(pathStat, path, dirFd=parentFd)
        if not _identityMatchesObject(expectedIdentity, pathStat, path, dirFd=parentFd):
            raise OSError(errno.EINVAL, "The file changed before it could be quarantined", str(path))

        # A descriptor pins the inode while it is moved. This prevents an
        # immediate unlink/recreate race from reusing the inode number.
        guardIdentity: Optional[FileIdentity] = None
        if stat.S_ISREG(pathStat.st_mode) or stat.S_ISDIR(pathStat.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if stat.S_ISDIR(pathStat.st_mode):
                flags |= getattr(os, "O_DIRECTORY", 0)
            try:
                if os.open in os.supports_dir_fd:
                    guardFd = os.open(Path(path.name), flags, dir_fd=parentFd)
                else:
                    guardFd = os.open(path, flags)
            except OSError:
                if guardFd is not None:
                    os.close(guardFd)
                    guardFd = None
                if requireEmpty:
                    raise
            else:
                guardStat = os.fstat(guardFd)
                guardIdentity = fileIdentity(guardStat, fileDescriptor=guardFd)
                if not _identityMatchesObject(expectedIdentity, guardStat, fileDescriptor=guardFd):
                    os.close(guardFd)
                    guardFd = None
                    raise OSError(errno.EINVAL, "The file changed before it could be quarantined", str(path))

        if requireEmpty:
            if guardFd is None:
                raise OSError(errno.ENOTSUP, "The empty directory could not be opened safely", str(path))
            if _descriptorHasEntries(guardFd):
                raise OSError(errno.ENOTEMPTY, "The directory is not empty", str(path))

        quarantineFd, quarantinePath = _openQuarantineDirectory(
            quarantineParentPath,
            quarantineParentFd,
        )
        sourceName = path.name
        moved = False
        quarantineName = ""
        for _ in range(10):
            quarantineName = f"entry-{uuid.uuid4().hex}.quarantine"
            moved = renameNoReplaceBetween(
                Path(sourceName),
                Path(quarantineName),
                sourceDirFd=parentFd,
                targetDirFd=quarantineFd,
            )
            if moved:
                break
        if not moved:
            raise OSError(errno.EEXIST, "Could not create a unique cleanup name", str(quarantinePath))

        quarantineStat = os.stat(quarantineName, dir_fd=quarantineFd, follow_symlinks=False)
        quarantineIdentity = fileIdentity(quarantineStat, Path(quarantineName), dirFd=quarantineFd)
        if guardIdentity is not None:
            identityMismatch = not _sameFileObject(quarantineIdentity, guardIdentity)
        else:
            identityMismatch = not _identityMatchesObject(
                expectedIdentity,
                quarantineStat,
                Path(quarantineName),
                dirFd=quarantineFd,
            )
        if identityMismatch:
            restored = _restoreQuarantinedEntry(
                quarantineName,
                quarantineFd,
                sourceName,
                parentFd,
                quarantineIdentity,
            )
            if restored:
                raise OSError(errno.EINVAL, "The file changed before it could be quarantined", str(path))
            retainedPath = quarantinePath / quarantineName
            raise OSError(
                errno.EINVAL,
                f"The file changed before it could be quarantined; the replacement is preserved at '{retainedPath}'",
                str(path),
            )

        if requireEmpty:
            try:
                quarantinedFd = openDirectoryAt(quarantineFd, quarantineName)
            except OSError:
                retainedPath = quarantinePath / quarantineName
                raise OSError(
                    errno.EINVAL,
                    f"The empty directory changed while it was being quarantined; it is preserved at '{retainedPath}'",
                    str(path),
                ) from None
            try:
                quarantinedStat = os.fstat(quarantinedFd)
                if not stat.S_ISDIR(quarantinedStat.st_mode) or not _identityMatchesObject(
                    quarantineIdentity,
                    quarantinedStat,
                    Path(quarantineName),
                    fileDescriptor=quarantinedFd,
                ):
                    raise OSError(
                        errno.EINVAL,
                        "The empty directory changed while it was being quarantined",
                        str(path),
                    )
                hasUnexpectedEntries = _descriptorHasEntries(quarantinedFd)
            finally:
                os.close(quarantinedFd)
            if hasUnexpectedEntries:
                retainedPath = quarantinePath / quarantineName
                restored = _restoreQuarantinedEntry(
                    quarantineName,
                    quarantineFd,
                    sourceName,
                    parentFd,
                    quarantineIdentity,
                )
                if restored:
                    raise OSError(errno.ENOTEMPTY, "The directory is not empty", str(path))
                raise OSError(
                    errno.ENOTEMPTY,
                    f"The directory is not empty and is preserved at '{retainedPath}'",
                    str(path),
                )

        retainedPath = quarantinePath / quarantineName
        logger.debug("Quarantined owned entry at: %s", retainedPath)
        return retainedPath
    finally:
        if quarantineFd is not None:
            os.close(quarantineFd)
        if guardFd is not None:
            os.close(guardFd)
        if ownQuarantineParentFd and quarantineParentFd is not None:
            os.close(quarantineParentFd)
        if ownParentFd:
            os.close(parentFd)


def unlinkEntryIfSameFile(
    path: Path,
    expectedIdentity: Optional[FileIdentity] = None,
    *,
    dirFd: Optional[int] = None,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> bool:
    """Remove a non-directory entry only when it has the expected identity.

    Windows deletes the exact object through a handle, so a concurrent
    pathname replacement is never removed. POSIX has no inode-bound unlink
    operation. The entry is therefore moved to a private quarantine name
    and retained there. This removes it from the requested namespace without
    ever deleting a pathname that may have acquired a replacement after the
    identity check.

    Unlike ``unlinkIfSameFile``, this helper can also quarantine a symbolic
    link without following it.
    """
    try:
        pathStat = _entryStat(path, dirFd)
    except FileNotFoundError:
        return True
    if stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The path is a directory", str(path))

    if expectedIdentity is None:
        if dirFd is not None:
            expectedIdentity = fileIdentity(pathStat, path, dirFd=dirFd)
        else:
            expectedIdentity = fileIdentity(pathStat, path)

    if os.name == "nt":
        _deleteWindowsEntryByHandle(path, expectedIdentity)
        return True

    _quarantineOwnedEntry(
        path,
        expectedIdentity,
        dirFd=dirFd,
        quarantineParent=quarantineParent,
        expectedQuarantineParent=expectedQuarantineParent,
    )
    return True


def unlinkIfSameFile(
    path: Path,
    expectedIdentity: Optional[FileIdentity] = None,
    *,
    dirFd: Optional[int] = None,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> bool:
    """Unlink a regular file only when it still has the expected identity."""
    try:
        pathStat = _entryStat(path, dirFd)
    except FileNotFoundError:
        return True
    if not stat.S_ISREG(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The path is not a regular file", str(path))
    return unlinkEntryIfSameFile(
        path,
        expectedIdentity,
        dirFd=dirFd,
        quarantineParent=quarantineParent,
        expectedQuarantineParent=expectedQuarantineParent,
    )


def removeTreeIfOwned(
    path: Path,
    expectedIdentity: FileIdentity,
    *,
    expectedParent: Optional[FileIdentity] = None,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> bool:
    """Remove an application-owned directory without following a replacement.

    Windows deletes the validated tree through native handles. POSIX has no
    inode-bound recursive deletion operation, so the validated root is moved
    into the retained quarantine directory instead. The requested pathname
    is removed from the project namespace without ever deleting a pathname
    that could have acquired an unexpected replacement.
    """
    try:
        pathStat = os.lstat(path)
    except FileNotFoundError:
        return True
    if isLinkLike(path) or not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The cleanup path is not a real directory", str(path))
    if not identityMatches(expectedIdentity, pathStat, path):
        raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

    if os.name == "nt":
        _removeWindowsTreeByHandle(path, expectedIdentity, expectedParent)
        return True

    retainedPath = _quarantineOwnedEntry(
        path,
        expectedIdentity,
        quarantineParent=quarantineParent,
        expectedQuarantineParent=expectedQuarantineParent,
    )
    logger.debug("Quarantined owned directory at: %s", retainedPath)
    return True


def removeEmptyDirectoryIfOwned(
    path: Path,
    expectedIdentity: FileIdentity,
    *,
    expectedParent: Optional[FileIdentity] = None,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> bool:
    """Remove an empty directory only when it is still the owned object.

    Windows deletes the exact directory through a native handle. POSIX
    moves the validated directory into the retained quarantine directory,
    because supported systems do not provide an inode-bound rmdir operation.
    """
    try:
        pathStat = os.lstat(path)
    except FileNotFoundError:
        if expectedParent is not None:
            parentStat = os.lstat(path.parent)
            if not _identityMatchesObject(expectedParent, parentStat, path.parent):
                raise OSError(
                    errno.EINVAL,
                    "The parent directory changed while it was being used",
                    str(path.parent),
                ) from None
        return True
    if isLinkLike(path) or not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The cleanup path is not a real directory", str(path))
    if not identityMatches(expectedIdentity, pathStat, path):
        raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

    parentStat = os.lstat(path.parent)
    if not stat.S_ISDIR(parentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The cleanup parent is not a directory", str(path.parent))
    parentIdentity = fileIdentity(parentStat, path.parent)
    if expectedParent is not None and not _identityMatchesObject(expectedParent, parentStat, path.parent):
        raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(path.parent))

    if os.name == "nt":
        _deleteWindowsEntryByHandle(path, expectedIdentity)
        return True

    if os.open in os.supports_dir_fd:
        parentFd = openDirectory(path.parent)
        try:
            openedParentStat = os.fstat(parentFd)
            if not _identityMatchesObject(
                parentIdentity,
                openedParentStat,
                path.parent,
                fileDescriptor=parentFd,
            ):
                raise OSError(errno.EINVAL, "The parent directory changed while it was being opened", str(path.parent))
            if expectedParent is not None and not _identityMatchesObject(
                expectedParent,
                openedParentStat,
                path.parent,
                fileDescriptor=parentFd,
            ):
                raise OSError(errno.EINVAL, "The parent directory changed while it was being opened", str(path.parent))
            retainedPath = _quarantineOwnedEntry(
                path,
                expectedIdentity,
                dirFd=parentFd,
                requireEmpty=True,
                quarantineParent=quarantineParent,
                expectedQuarantineParent=expectedQuarantineParent,
            )
            currentParentStat = os.lstat(path.parent)
            if not _identityMatchesObject(parentIdentity, currentParentStat, path.parent):
                raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(path.parent))
        finally:
            os.close(parentFd)
    else:
        retainedPath = _quarantineOwnedEntry(
            path,
            expectedIdentity,
            requireEmpty=True,
            quarantineParent=quarantineParent,
            expectedQuarantineParent=expectedQuarantineParent,
        )
    logger.debug("Quarantined owned empty directory at: %s", retainedPath)
    return True


def getDefaultDirectoryMode(
    parent: Path,
    *,
    expectedParent: Optional[FileIdentity] = None,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> int:
    """Return the directory mode created in a parent under its current policy.

    A temporary directory is used as a probe so the process-wide umask is
    never changed, even briefly, while another thread may be creating a
    file. On POSIX, the probe is created relative to an open directory
    descriptor and can be bound to an expected parent identity. Cleanup
    uses the same race-safe backend as other owned entries and requires a
    validated central quarantine parent, so it cannot create a nested
    quarantine directory beside the probed parent.
    """
    if os.name != "nt" and (quarantineParent is None or expectedQuarantineParent is None):
        raise ValueError("A validated central cleanup quarantine is required for the directory mode probe")

    if os.name != "nt" and os.mkdir in os.supports_dir_fd:
        parentFd = openDirectory(parent)
        try:
            parentStat = os.fstat(parentFd)
            if expectedParent is not None and not _identityMatchesObject(
                expectedParent,
                parentStat,
                parent,
                fileDescriptor=parentFd,
            ):
                raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(parent))
            for _ in range(10):
                probeName = f".umbraedit-mode-{uuid.uuid4().hex}"
                try:
                    os.mkdir(probeName, 0o777, dir_fd=parentFd)
                except FileExistsError:
                    continue
                probeStat = os.stat(probeName, dir_fd=parentFd, follow_symlinks=False)
                if not stat.S_ISDIR(probeStat.st_mode):
                    raise OSError(errno.ENOTDIR, "The mode probe is not a directory", probeName)
                probeIdentity = fileIdentity(probeStat, Path(probeName), dirFd=parentFd)
                mode = stat.S_IMODE(probeStat.st_mode)
                try:
                    _quarantineOwnedEntry(
                        Path(probeName),
                        probeIdentity,
                        dirFd=parentFd,
                        quarantineParent=quarantineParent,
                        expectedQuarantineParent=expectedQuarantineParent,
                    )
                except OSError as exc:
                    logger.warning("The directory mode probe could not be quarantined: %s", exc)
                return mode
            raise OSError(errno.EEXIST, "Could not create a directory mode probe", str(parent))
        finally:
            os.close(parentFd)

    parentStat = os.lstat(parent)
    if expectedParent is not None and not _identityMatchesObject(expectedParent, parentStat, parent):
        raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(parent))
    for _ in range(10):
        probePath = parent / f".umbraedit-mode-{uuid.uuid4().hex}"
        try:
            os.mkdir(probePath, 0o777)
        except FileExistsError:
            continue
        probeStat = os.lstat(probePath)
        if not stat.S_ISDIR(probeStat.st_mode):
            raise OSError(errno.ENOTDIR, "The mode probe is not a directory", str(probePath))
        mode = stat.S_IMODE(probeStat.st_mode)
        probeIdentity = fileIdentity(probeStat, probePath)
        try:
            removeEmptyDirectoryIfOwned(
                probePath,
                probeIdentity,
                expectedParent=expectedParent,
                quarantineParent=quarantineParent,
                expectedQuarantineParent=expectedQuarantineParent,
            )
        except OSError as exc:
            logger.warning("The directory mode probe could not be removed: %s", exc)
        return mode
    raise OSError(errno.EEXIST, "Could not create a directory mode probe", str(parent))


def _renameResult(result: int, target: Path) -> bool:
    """Interpret the result of an atomic no-replace rename."""
    if result == 0:
        return True
    errorNumber = ctypes.get_errno()
    if errorNumber in (errno.EEXIST, errno.ENOTEMPTY):
        return False
    if errorNumber in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise OSError(errorNumber, os.strerror(errorNumber), str(target))
    raise OSError(errorNumber, os.strerror(errorNumber), str(target))


def _setWindowsNativeRenameInformation(
    sourceHandle: int,
    buffer: Any,
    bufferSize: int,
    target: Path,
) -> bool:
    """Rename through the native path that honors ``RootDirectory``.

    Several Windows releases expose a Win32 compatibility defect:
    ``SetFileInformationByHandle(FileRenameInfo)`` rejects every non-null
    ``RootDirectory`` with ``ERROR_INVALID_PARAMETER`` even though the
    documented structure permits it. The native information class uses the
    same structure and does honor the directory handle. It is therefore used
    only as a compatibility fallback, with the exact same no-replace flags,
    source handle, parent handle, filename bytes, and buffer length.
    """
    ntdll = _windowsNtdll()
    setInformation = ntdll.NtSetInformationFile
    setInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsIoStatusBlock),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    setInformation.restype = ctypes.c_int32

    ioStatus = _WindowsIoStatusBlock()
    status = int(
        setInformation(
            sourceHandle,
            ctypes.byref(ioStatus),
            ctypes.byref(buffer),
            bufferSize,
            10,  # FileRenameInformation
        )
    )
    if status == _WINDOWS_STATUS_SUCCESS:
        return True

    unsignedStatus = status & 0xFFFFFFFF
    if unsignedStatus in (
        _WINDOWS_STATUS_OBJECT_NAME_COLLISION,
        _WINDOWS_STATUS_OBJECT_NAME_EXISTS,
    ):
        return False

    errorNumber = _windowsNtStatusToDosError(unsignedStatus)
    if errorNumber == _WINDOWS_ERROR_ACCESS_DENIED:
        # Some Windows filesystems report access denied rather than a
        # namespace collision when the destination already exists. Only
        # classify the error as a collision when the target is still
        # present; a genuine ACL failure must remain visible to the caller.
        try:
            os.lstat(target)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        else:
            return False
    if errorNumber == 0:
        errorNumber = errno.EIO
    raise _windowsError(errorNumber, target)


def _setWindowsRenameInformation(
    sourceHandle: int,
    targetParentHandle: int,
    targetName: str,
    target: Path,
) -> bool:
    """Rename an exact Windows object without replacing an existing target.

    The source object is bound to an open handle and the destination name is
    resolved relative to an open target-parent handle. ``ReplaceIfExists``
    remains false, so an existing target causes the operation to fail
    without modifying either namespace entry.
    """
    fileNameBytes = targetName.encode("utf-16-le")
    fileNameOffset = _WindowsFileRenameInfo.fileName.offset
    bufferSize = max(ctypes.sizeof(_WindowsFileRenameInfo), fileNameOffset + len(fileNameBytes) + 2)
    buffer = ctypes.create_string_buffer(bufferSize)
    information = _WindowsFileRenameInfo.from_buffer(buffer)
    information.flags = 0  # ReplaceIfExists is false.
    information.rootDirectory = targetParentHandle
    information.fileNameLength = len(fileNameBytes)
    ctypes.memmove(ctypes.byref(buffer, fileNameOffset), fileNameBytes, len(fileNameBytes))

    kernel32 = _windowsKernel32()
    setFileInformation = kernel32.SetFileInformationByHandle
    setFileInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    setFileInformation.restype = ctypes.c_int
    if setFileInformation(
        sourceHandle,
        3,  # FileRenameInfo
        ctypes.byref(buffer),
        bufferSize,
    ):
        return True

    errorNumber = _windowsLastError()
    if errorNumber == _WINDOWS_ERROR_INVALID_PARAMETER:
        # The Win32 wrapper rejects a non-null RootDirectory on affected
        # Windows releases. The native information class supports the same
        # handle-relative request and preserves the validated parent object.
        return _setWindowsNativeRenameInformation(sourceHandle, buffer, bufferSize, target)
    if errorNumber in (_WINDOWS_ERROR_FILE_EXISTS, _WINDOWS_ERROR_ALREADY_EXISTS):
        return False
    if errorNumber == _WINDOWS_ERROR_ACCESS_DENIED:
        # Some Windows filesystems report access denied rather than a
        # namespace collision when the destination already exists. Only
        # classify the error as a collision when the target is still
        # present; a genuine ACL failure must remain visible to the caller.
        try:
            os.lstat(target)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        else:
            return False
    raise _windowsError(errorNumber, target)


def _renameNoReplaceWindows(source: Path, target: Path) -> bool:
    """Atomically rename a Windows object without replacing its target.

    The source is opened with delete access and the target parent is opened
    separately. Both handles are checked against fresh path observations
    before the native rename, so a pathname replacement cannot silently
    redirect the operation to another object or parent.
    """
    targetName = target.name
    if not targetName or targetName in (".", "..") or "/" in targetName or "\\" in targetName:
        raise OSError(errno.EINVAL, "The rename target name is invalid", str(target))

    sourceStat = os.lstat(source)
    targetParentStat = os.lstat(target.parent)
    if stat.S_ISLNK(sourceStat.st_mode) or (
        getattr(sourceStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The rename source cannot be a link", str(source))
    if stat.S_ISLNK(targetParentStat.st_mode) or (
        getattr(targetParentStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The rename target parent cannot be a link", str(target.parent))
    if not (stat.S_ISREG(sourceStat.st_mode) or stat.S_ISDIR(sourceStat.st_mode)):
        raise OSError(errno.EINVAL, "The rename source is not a file or directory", str(source))
    if not stat.S_ISDIR(targetParentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The rename target parent is not a directory", str(target.parent))

    sourceIdentity = fileIdentity(sourceStat, source)
    targetParentIdentity = fileIdentity(targetParentStat, target.parent)
    sourceHandle: Optional[int] = None
    targetParentHandle: Optional[int] = None
    primaryFailure = False
    try:
        sourceHandle = _openWindowsDeleteHandle(source, directory=True)
        targetParentHandle = _openWindowsRenameParentHandle(target.parent)
        sourceInformation = _windowsHandleInformation(sourceHandle)
        targetParentInformation = _windowsHandleInformation(targetParentHandle)
        if sourceInformation.identity != sourceIdentity:
            raise OSError(errno.ESTALE, "The rename source changed before it could be renamed", str(source))
        if targetParentInformation.identity != targetParentIdentity:
            raise OSError(
                errno.ESTALE,
                "The rename target parent changed before it could be used",
                str(target.parent),
            )
        if sourceInformation.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(errno.ELOOP, "The rename source cannot be a link", str(source))
        if targetParentInformation.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(errno.ELOOP, "The rename target parent cannot be a link", str(target.parent))
        if not targetParentInformation.attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError(errno.ENOTDIR, "The rename target parent is not a directory", str(target.parent))
        if sourceInformation.identity.device != targetParentInformation.identity.device:
            raise OSError(errno.EXDEV, "The rename source and target are on different volumes", str(target))

        sourceFinalPath = _windowsHandleFinalPath(sourceHandle)
        if not _windowsPathsEqual(sourceFinalPath, source):
            raise OSError(errno.ESTALE, "The rename source moved before it could be renamed", str(source))
        targetParentFinalPath = _windowsHandleFinalPath(targetParentHandle)
        if not _windowsPathsEqual(targetParentFinalPath, target.parent):
            raise OSError(
                errno.ESTALE,
                "The rename target parent moved before it could be used",
                str(target.parent),
            )

        return _setWindowsRenameInformation(
            sourceHandle,
            targetParentHandle,
            targetName,
            target,
        )
    except BaseException:
        primaryFailure = True
        raise
    finally:
        closeError: Optional[OSError] = None
        for handle, description in (
            (sourceHandle, "source"),
            (targetParentHandle, "target-parent"),
        ):
            if handle is None:
                continue
            try:
                _closeWindowsHandle(handle)
            except OSError as exc:
                if closeError is None:
                    closeError = exc
                logger.warning("Could not close a Windows rename %s handle", description, exc_info=True)
        if closeError is not None and not primaryFailure:
            raise closeError


def _renameNoReplaceDarwin(source: Path, target: Path) -> bool:
    """Rename without replacement on macOS using renamex_np()."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameFunction = getattr(libc, "renamex_np", None)
    if renameFunction is None:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
    renameFunction.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renameFunction.restype = ctypes.c_int
    result = renameFunction(os.fsencode(source), os.fsencode(target), 0x00000004)
    return _renameResult(result, target)


def _renameNoReplaceDarwinAt(
    source: Path,
    target: Path,
    sourceDirFd: Optional[int] = None,
    targetDirFd: Optional[int] = None,
) -> bool:
    """Rename without replacement on macOS using renameatx_np()."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameFunction = getattr(libc, "renameatx_np", None)
    if renameFunction is None:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
    renameFunction.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameFunction.restype = ctypes.c_int

    effectiveSourceFd = _DARWIN_AT_FDCWD if sourceDirFd is None else sourceDirFd
    effectiveTargetFd = _DARWIN_AT_FDCWD if targetDirFd is None else targetDirFd
    sourcePath = Path(os.path.abspath(source)) if sourceDirFd is None else Path(source.name)
    targetPath = Path(os.path.abspath(target)) if targetDirFd is None else Path(target.name)
    result = renameFunction(
        effectiveSourceFd,
        os.fsencode(sourcePath),
        effectiveTargetFd,
        os.fsencode(targetPath),
        0x00000004,
    )
    return _renameResult(result, target)


def _renameNoReplaceLinux(
    source: Path,
    target: Path,
    sourceDirFd: Optional[int] = None,
    targetDirFd: Optional[int] = None,
) -> bool:
    """Rename without replacement on Linux using renameat2()."""
    libc = ctypes.CDLL(None, use_errno=True)
    effectiveSourceFd = _LINUX_AT_FDCWD if sourceDirFd is None else sourceDirFd
    effectiveTargetFd = _LINUX_AT_FDCWD if targetDirFd is None else targetDirFd
    sourcePath = source if sourceDirFd is None else Path(source.name)
    targetPath = target if targetDirFd is None else Path(target.name)

    renameFunction = getattr(libc, "renameat2", None)
    if renameFunction is not None:
        renameFunction.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameFunction.restype = ctypes.c_int
        result = renameFunction(
            effectiveSourceFd,
            os.fsencode(sourcePath),
            effectiveTargetFd,
            os.fsencode(targetPath),
            0x00000001,
        )
        try:
            return _renameResult(result, target)
        except OSError as exc:
            if exc.errno not in (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise

    syscallNumber = _LINUX_RENAMEAT2_SYSCALL.get(platform.machine())
    syscallFunction = getattr(libc, "syscall", None)
    if syscallNumber is None or syscallFunction is None:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
    syscallFunction.argtypes = [
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    syscallFunction.restype = ctypes.c_long
    result = syscallFunction(
        ctypes.c_long(syscallNumber),
        ctypes.c_int(effectiveSourceFd),
        os.fsencode(sourcePath),
        ctypes.c_int(effectiveTargetFd),
        os.fsencode(targetPath),
        ctypes.c_uint(0x00000001),
    )
    return _renameResult(int(result), target)


def renameNoReplace(source: Path, target: Path) -> bool:
    """Atomically rename a path without replacing an existing target.

    Returns ``True`` when the source was renamed and ``False`` when the
    target already exists. An OSError is raised if the platform does not
    provide an atomic no-replace rename operation.
    """
    if os.name == "nt":
        return _renameNoReplaceWindows(source, target)
    if sys.platform == "darwin":
        return _renameNoReplaceDarwin(source, target)
    if sys.platform.startswith("linux"):
        return _renameNoReplaceLinux(source, target)
    raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")


def renameNoReplaceAt(source: Path, targetName: str, targetDirFd: int) -> bool:
    """Atomically rename a file into an open directory without replacing it."""
    if os.name == "nt":
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
    sourcePath = Path(os.path.abspath(source))
    targetPath = Path(targetName)
    if sys.platform == "darwin":
        return _renameNoReplaceDarwinAt(sourcePath, targetPath, None, targetDirFd)
    if sys.platform.startswith("linux"):
        return _renameNoReplaceLinux(sourcePath, targetPath, None, targetDirFd)
    raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")


def renameNoReplaceBetween(
    source: Path,
    target: Path,
    *,
    sourceDirFd: Optional[int] = None,
    targetDirFd: Optional[int] = None,
) -> bool:
    """Atomically rename between two paths without replacing the target.

    When directory descriptors are supplied, both names are resolved
    relative to those descriptors. This keeps the operation bound to the
    directories that were validated by the caller even if either path is
    replaced concurrently. A side without a descriptor is resolved from
    the current working directory using its full path.
    """
    if sys.platform == "darwin":
        sourcePath = Path(os.path.abspath(source)) if sourceDirFd is None else Path(source.name)
        targetPath = Path(os.path.abspath(target)) if targetDirFd is None else Path(target.name)
        return _renameNoReplaceDarwinAt(sourcePath, targetPath, sourceDirFd, targetDirFd)

    if sys.platform.startswith("linux"):
        sourcePath = Path(os.path.abspath(source)) if sourceDirFd is None else Path(source.name)
        targetPath = Path(os.path.abspath(target)) if targetDirFd is None else Path(target.name)
        return _renameNoReplaceLinux(sourcePath, targetPath, sourceDirFd, targetDirFd)

    if os.name == "nt":
        if sourceDirFd is not None or targetDirFd is not None:
            raise OSError(errno.ENOTSUP, "Directory descriptors are not supported on Windows")
        return renameNoReplace(source, target)

    if sourceDirFd is None and targetDirFd is None:
        return renameNoReplace(source, target)
    raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")


def renameNoReplaceIfSameFile(
    source: Path,
    target: Path,
    expectedSourceIdentity: FileIdentity,
    *,
    sourceDirFd: Optional[int] = None,
    targetDirFd: Optional[int] = None,
) -> bool:
    """Move one expected regular file without replacing the target.

    The source is first moved to a private name in the same parent and
    its identity is checked there. Only the expected regular file is
    subsequently published. If the source entry was raced, the raced
    entry is restored to its original name instead of being deleted. The
    final publication is a no-replace rename and is descriptor-relative
    when both parent descriptors are available.

    Returns ``True`` when the expected file was moved and ``False`` when
    the target already existed. In the latter case the source is restored.
    """
    ownSourceFd = False
    ownTargetFd = False
    if os.name != "nt" and os.open in os.supports_dir_fd:
        if sourceDirFd is None:
            sourceDirFd = openDirectory(source.parent)
            ownSourceFd = True
        if targetDirFd is None:
            targetDirFd = openDirectory(target.parent)
            ownTargetFd = True

    sourceEntry = Path(source.name) if sourceDirFd is not None else source
    targetEntry = Path(target.name) if targetDirFd is not None else target
    quarantineName = f".umbraedit-rename-{uuid.uuid4().hex}"
    quarantineEntry = Path(quarantineName) if sourceDirFd is not None else source.parent / quarantineName

    def restoreQuarantine(identity: FileIdentity) -> bool:
        """Restore a known quarantine entry without replacing a new source."""
        try:
            currentStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            return False
        if not stat.S_ISREG(currentStat.st_mode) or not _entryIdentityMatches(
            identity, quarantineEntry, sourceDirFd, currentStat
        ):
            return False
        if sourceDirFd is not None:
            moved = renameNoReplaceBetween(
                quarantineEntry,
                sourceEntry,
                sourceDirFd=sourceDirFd,
                targetDirFd=sourceDirFd,
            )
        else:
            moved = renameNoReplaceBetween(quarantineEntry, sourceEntry)
        if not moved:
            return False
        try:
            restoredStat = _entryStat(sourceEntry, sourceDirFd)
        except OSError:
            return False
        return stat.S_ISREG(restoredStat.st_mode) and _entryIdentityMatches(
            identity,
            sourceEntry,
            sourceDirFd,
            restoredStat,
        )

    try:
        try:
            sourceStat = _entryStat(sourceEntry, sourceDirFd)
        except FileNotFoundError as exc:
            raise OSError(errno.ENOENT, "The source file does not exist", str(source)) from exc
        if not stat.S_ISREG(sourceStat.st_mode):
            raise OSError(errno.ESTALE, "The source is not a regular file", str(source))
        if not _entryIdentityMatches(expectedSourceIdentity, sourceEntry, sourceDirFd, sourceStat):
            raise OSError(errno.ESTALE, "The source file changed before it could be renamed", str(source))

        if sourceDirFd is not None:
            moved = renameNoReplaceBetween(
                sourceEntry,
                quarantineEntry,
                sourceDirFd=sourceDirFd,
                targetDirFd=sourceDirFd,
            )
        else:
            moved = renameNoReplaceBetween(sourceEntry, quarantineEntry)
        if not moved:
            raise OSError(errno.EEXIST, "Could not create a unique rename name", str(quarantineEntry))

        try:
            quarantineStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            raise
        quarantineIdentity = _entryIdentity(quarantineEntry, sourceDirFd, quarantineStat)
        if not stat.S_ISREG(quarantineStat.st_mode) or not _entryIdentityMatches(
            expectedSourceIdentity,
            quarantineEntry,
            sourceDirFd,
            quarantineStat,
        ):
            if restoreQuarantine(quarantineIdentity):
                raise OSError(errno.ESTALE, "The source file changed before it could be renamed", str(source))
            raise OSError(
                errno.ESTALE,
                "The source file changed before it could be renamed; the replacement is preserved at "
                f"'{quarantineEntry}'",
                str(source),
            )

        try:
            if sourceDirFd is not None and targetDirFd is not None:
                published = renameNoReplaceBetween(
                    quarantineEntry,
                    targetEntry,
                    sourceDirFd=sourceDirFd,
                    targetDirFd=targetDirFd,
                )
            elif sourceDirFd is not None:
                published = renameNoReplaceBetween(
                    quarantineEntry,
                    targetEntry,
                    sourceDirFd=sourceDirFd,
                    targetDirFd=None,
                )
            elif targetDirFd is not None:
                published = renameNoReplaceBetween(
                    quarantineEntry,
                    targetEntry,
                    sourceDirFd=None,
                    targetDirFd=targetDirFd,
                )
            else:
                published = renameNoReplaceBetween(quarantineEntry, targetEntry)
        except OSError as exc:
            if not restoreQuarantine(expectedSourceIdentity):
                raise OSError(
                    exc.errno or errno.EINVAL,
                    f"The rename failed and the expected file is preserved at '{quarantineEntry}'",
                    str(target),
                ) from exc
            raise

        if not published:
            if not restoreQuarantine(expectedSourceIdentity):
                raise OSError(
                    errno.EEXIST,
                    f"The target already exists and the expected file is preserved at '{quarantineEntry}'",
                    str(target),
                )
            return False

        try:
            targetStat = _entryStat(targetEntry, targetDirFd)
        except OSError:
            raise
        if not stat.S_ISREG(targetStat.st_mode) or not _entryIdentityMatches(
            expectedSourceIdentity,
            targetEntry,
            targetDirFd,
            targetStat,
        ):
            # The quarantine entry was replaced after it was validated, or
            # the published target was replaced immediately afterwards. A
            # path-based rename cannot bind the operation to an inode, so
            # preserve the unexpected object under a private name and leave
            # the requested target unoccupied. Never unlink it.
            conflictName = f".umbraedit-conflict-{uuid.uuid4().hex}"
            conflictEntry = Path(conflictName) if targetDirFd is not None else target.parent / conflictName
            conflictPath = target.parent / conflictName
            try:
                if targetDirFd is not None:
                    preserved = renameNoReplaceBetween(
                        targetEntry,
                        conflictEntry,
                        sourceDirFd=targetDirFd,
                        targetDirFd=targetDirFd,
                    )
                else:
                    preserved = renameNoReplaceBetween(targetEntry, conflictEntry)
            except OSError:
                preserved = False

            restored = restoreQuarantine(expectedSourceIdentity)
            if preserved:
                raise OSError(
                    errno.ESTALE,
                    "The renamed target does not match the expected file; "
                    f"the unexpected target is preserved at '{conflictPath}'",
                    str(target),
                )
            if restored:
                raise OSError(errno.ESTALE, "The renamed target does not match the expected file", str(target))
            raise OSError(
                errno.ESTALE,
                "The renamed target does not match the expected file; "
                f"the expected file is preserved at '{quarantineEntry}'",
                str(target),
            )
        return True
    finally:
        if ownTargetFd and targetDirFd is not None:
            os.close(targetDirFd)
        if ownSourceFd and sourceDirFd is not None:
            os.close(sourceDirFd)


def linkNoReplaceIfSameFile(
    source: Path,
    target: Path,
    expectedSourceIdentity: FileIdentity,
    *,
    sourceDirFd: Optional[int] = None,
    targetDirFd: Optional[int] = None,
) -> bool:
    """Publish an expected regular file with an atomic hard link.

    The source entry is first moved to a private name in the same parent
    and its identity is checked there. Only the expected file is linked to
    the target. If the source entry was raced, it is restored to its
    original name and never published. The target is never replaced.

    Returns ``True`` when the expected file was published and ``False``
    when the target already existed. The source entry is consumed on
    success. If the private source entry is raced after it has been
    validated, an unexpected target is moved out of the requested name
    and preserved.
    """
    ownSourceFd = False
    ownTargetFd = False
    if os.name != "nt" and os.open in os.supports_dir_fd:
        if sourceDirFd is None:
            sourceDirFd = openDirectory(source.parent)
            ownSourceFd = True
        if targetDirFd is None:
            targetDirFd = openDirectory(target.parent)
            ownTargetFd = True

    sourceEntry = Path(source.name) if sourceDirFd is not None else source
    targetEntry = Path(target.name) if targetDirFd is not None else target
    quarantineName = f".umbraedit-rename-{uuid.uuid4().hex}"
    quarantineEntry = Path(quarantineName) if sourceDirFd is not None else source.parent / quarantineName

    def renameEntry(
        entry: Path,
        destination: Path,
        *,
        entryDirFd: Optional[int],
        destinationDirFd: Optional[int],
    ) -> bool:
        """Rename an entry without replacing an existing destination."""
        if entryDirFd is not None and destinationDirFd is not None:
            return renameNoReplaceBetween(
                entry,
                destination,
                sourceDirFd=entryDirFd,
                targetDirFd=destinationDirFd,
            )
        if entryDirFd is not None:
            return renameNoReplaceBetween(
                entry,
                destination,
                sourceDirFd=entryDirFd,
                targetDirFd=None,
            )
        if destinationDirFd is not None:
            return renameNoReplaceBetween(
                entry,
                destination,
                sourceDirFd=None,
                targetDirFd=destinationDirFd,
            )
        return renameNoReplaceBetween(entry, destination)

    def restoreQuarantine(identity: Optional[FileIdentity] = None) -> bool:
        """Restore the private source entry without replacing a new one."""
        try:
            quarantineStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            return False
        quarantineIdentity = _entryIdentity(quarantineEntry, sourceDirFd, quarantineStat)
        if identity is not None and not _entryIdentityMatches(
            identity,
            quarantineEntry,
            sourceDirFd,
            quarantineStat,
        ):
            return False
        try:
            restored = renameEntry(
                quarantineEntry,
                sourceEntry,
                entryDirFd=sourceDirFd,
                destinationDirFd=sourceDirFd,
            )
        except OSError:
            return False
        if not restored:
            return False
        try:
            restoredStat = _entryStat(sourceEntry, sourceDirFd)
        except OSError:
            return False
        return _entryIdentityMatches(
            quarantineIdentity,
            sourceEntry,
            sourceDirFd,
            restoredStat,
        )

    def preserveUnexpectedTarget(targetIdentity: FileIdentity) -> None:
        """Move an unexpected target out of the requested name.

        If the target cannot be moved, it is left in place. It must never
        be unlinked because its identity no longer matches the validated
        publication.
        """
        conflictName = f".umbraedit-conflict-{uuid.uuid4().hex}"
        conflictEntry = Path(conflictName) if targetDirFd is not None else target.parent / conflictName
        with contextlib.suppress(OSError):
            renameEntry(
                targetEntry,
                conflictEntry,
                entryDirFd=targetDirFd,
                destinationDirFd=targetDirFd,
            )

    try:
        try:
            sourceStat = _entryStat(sourceEntry, sourceDirFd)
        except FileNotFoundError as exc:
            raise OSError(errno.ENOENT, "The source file does not exist", str(source)) from exc
        if not stat.S_ISREG(sourceStat.st_mode):
            raise OSError(errno.ESTALE, "The source is not a regular file", str(source))
        if not _entryIdentityMatches(expectedSourceIdentity, sourceEntry, sourceDirFd, sourceStat):
            raise OSError(errno.ESTALE, "The source file changed before it could be published", str(source))

        moved = renameEntry(
            sourceEntry,
            quarantineEntry,
            entryDirFd=sourceDirFd,
            destinationDirFd=sourceDirFd,
        )
        if not moved:
            raise OSError(errno.EEXIST, "Could not create a unique publication name", str(quarantineEntry))

        try:
            quarantineStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            raise
        quarantineIdentity = _entryIdentity(quarantineEntry, sourceDirFd, quarantineStat)
        if not stat.S_ISREG(quarantineStat.st_mode) or not _entryIdentityMatches(
            expectedSourceIdentity,
            quarantineEntry,
            sourceDirFd,
            quarantineStat,
        ):
            if not restoreQuarantine(quarantineIdentity):
                raise OSError(
                    errno.ESTALE,
                    "The source file changed before it could be published; "
                    f"the replacement is preserved at '{quarantineEntry}'",
                    str(source),
                )
            raise OSError(errno.ESTALE, "The source file changed before it could be published", str(source))

        try:
            if sourceDirFd is not None and targetDirFd is not None:
                os.link(
                    quarantineEntry,
                    targetEntry,
                    src_dir_fd=sourceDirFd,
                    dst_dir_fd=targetDirFd,
                    follow_symlinks=False,
                )
            else:
                os.link(quarantineEntry, targetEntry, follow_symlinks=False)
        except FileExistsError as exc:
            if not restoreQuarantine(expectedSourceIdentity):
                raise OSError(
                    errno.EEXIST,
                    f"The target already exists and the expected file is preserved at '{quarantineEntry}'",
                    str(target),
                ) from exc
            return False
        except OSError as exc:
            if not restoreQuarantine(expectedSourceIdentity):
                raise OSError(
                    errno.EINVAL,
                    f"The publication failed and the expected file is preserved at '{quarantineEntry}'",
                    str(source),
                ) from exc
            raise

        try:
            targetStat = _entryStat(targetEntry, targetDirFd)
        except OSError:
            targetStat = None
        try:
            currentQuarantineStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            currentQuarantineStat = None

        targetIdentity = _entryIdentity(targetEntry, targetDirFd, targetStat) if targetStat is not None else None
        currentQuarantineIdentity = (
            _entryIdentity(quarantineEntry, sourceDirFd, currentQuarantineStat)
            if currentQuarantineStat is not None
            else None
        )
        if (
            targetStat is None
            or targetIdentity is None
            or not _entryIdentityMatches(
                expectedSourceIdentity,
                targetEntry,
                targetDirFd,
                targetStat,
            )
        ):
            if (
                targetStat is not None
                and targetIdentity is not None
                and currentQuarantineIdentity is not None
                and _entryIdentityMatches(
                    currentQuarantineIdentity,
                    targetEntry,
                    targetDirFd,
                    targetStat,
                )
            ):
                preserveUnexpectedTarget(targetIdentity)
            if currentQuarantineIdentity is not None:
                restoreQuarantine(currentQuarantineIdentity)
            raise OSError(errno.ESTALE, "The published file does not match the expected file", str(target))

        if (
            currentQuarantineStat is None
            or currentQuarantineIdentity is None
            or not _entryIdentityMatches(
                expectedSourceIdentity,
                quarantineEntry,
                sourceDirFd,
                currentQuarantineStat,
            )
        ):
            # The expected file was already linked to the target. Preserve
            # the raced private entry instead of deleting an unknown file.
            if currentQuarantineIdentity is not None:
                restoreQuarantine(currentQuarantineIdentity)
            return True

        try:
            unlinkEntryIfSameFile(quarantineEntry, expectedSourceIdentity, dirFd=sourceDirFd)
        except OSError as exc:
            logger.warning("The staged file could not be removed after publication: %s", exc)
        return True
    finally:
        if ownTargetFd and targetDirFd is not None:
            os.close(targetDirFd)
        if ownSourceFd and sourceDirFd is not None:
            os.close(sourceDirFd)


def copyRegularFile(
    source: Path,
    target: Path,
    *,
    expectedParent: Optional[FileIdentity] = None,
    expectedSourceIdentity: Optional[FileIdentity] = None,
    expectedTargetParent: Optional[FileIdentity] = None,
    targetDirFd: Optional[int] = None,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> FileIdentity:
    """Copy a regular file to a new target without overwriting it.

    The source is opened without following links and can optionally be
    bound to the identity recorded by an earlier directory scan. The
    target is created exclusively, and is removed if the copy fails. On
    POSIX, a supplied target directory descriptor keeps all destination
    operations bound to the validated directory even if its path is
    replaced concurrently.
    """
    ownTargetFd = False
    if targetDirFd is None and os.name != "nt" and os.open in os.supports_dir_fd:
        targetDirFd = openDirectory(target.parent)
        ownTargetFd = True
    try:
        if targetDirFd is not None:
            targetParentStat = os.fstat(targetDirFd)
        else:
            targetParentStat = os.lstat(target.parent)
        if not stat.S_ISDIR(targetParentStat.st_mode):
            raise OSError(errno.ENOTDIR, "The target parent is not a directory", str(target.parent))
        targetParentIdentity = (
            fileIdentity(targetParentStat, fileDescriptor=targetDirFd)
            if targetDirFd is not None
            else fileIdentity(targetParentStat, target.parent)
        )
        if expectedTargetParent is not None and targetParentIdentity != expectedTargetParent:
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))

        targetIdentity: Optional[FileIdentity] = None
        with openRegularFile(
            source,
            expectedParent=expectedParent,
            expectedIdentity=expectedSourceIdentity,
        ) as inFile:
            sourceMode = stat.S_IMODE(os.fstat(inFile.fileno()).st_mode)
            if targetDirFd is not None:
                fileDesc = openExclusiveFile(Path(target.name), targetDirFd)
            else:
                fileDesc = openExclusiveFile(target)
            try:
                targetStat = os.fstat(fileDesc)
                targetIdentity = fileIdentity(targetStat, fileDescriptor=fileDesc)
            except Exception:
                os.close(fileDesc)
                raise
            try:
                with os.fdopen(fileDesc, mode="wb") as outFile:
                    shutil.copyfileobj(inFile, outFile, length=1024 * 1024)
                    outFile.flush()
                    os.fsync(outFile.fileno())
                    if hasattr(os, "fchmod"):
                        os.fchmod(outFile.fileno(), sourceMode)

                    currentStat = _entryStat(target, targetDirFd)
                    if not _entryIdentityMatches(targetIdentity, target, targetDirFd, currentStat):
                        raise OSError(errno.EINVAL, "The target file changed while it was being copied", str(target))
            except Exception:
                with contextlib.suppress(OSError):
                    unlinkIfSameFile(
                        target,
                        targetIdentity,
                        dirFd=targetDirFd,
                        quarantineParent=quarantineParent,
                        expectedQuarantineParent=expectedQuarantineParent,
                    )
                raise

        if targetDirFd is not None:
            currentParentStat = os.fstat(targetDirFd)
        else:
            currentParentStat = os.lstat(target.parent)
        if not _identityMatchesObject(
            targetParentIdentity,
            currentParentStat,
            target.parent,
            fileDescriptor=targetDirFd,
        ):
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
        try:
            pathParentStat = os.lstat(target.parent)
        except OSError:
            pathParentStat = None
        if pathParentStat is None or not _identityMatchesObject(
            targetParentIdentity,
            pathParentStat,
            target.parent,
        ):
            if targetIdentity is not None:
                with contextlib.suppress(OSError):
                    unlinkIfSameFile(
                        target,
                        targetIdentity,
                        dirFd=targetDirFd,
                        quarantineParent=quarantineParent,
                        expectedQuarantineParent=expectedQuarantineParent,
                    )
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
        if targetIdentity is None:
            raise OSError(errno.EINVAL, "The copied file identity could not be determined", str(target))
        return targetIdentity
    finally:
        if ownTargetFd and targetDirFd is not None:
            os.close(targetDirFd)


def writeFileAtomic(
    target: Path,
    data: bytes,
    *,
    mode: int = 0o666,
    expectedParent: Optional[FileIdentity] = None,
    expectedTarget: Optional[FileIdentity] = None,
    replaceExisting: bool = False,
    quarantineParent: Optional[Path] = None,
    expectedQuarantineParent: Optional[FileIdentity] = None,
) -> FileIdentity:
    """Write a file through a private staging file and publish it safely.

    An existing target is only replaced when ``replaceExisting`` is enabled
    and its identity was explicitly supplied and still matches. The old
    target is first moved to a unique quarantine name, and the staged file
    is then published with no-replace semantics. A concurrently installed
    target is therefore never overwritten. Without an expected identity,
    an existing target is treated as a namespace collision. The returned
    identity belongs to the published file.
    """
    parentStat = os.lstat(target.parent)
    if not stat.S_ISDIR(parentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The target parent is not a directory", str(target.parent))
    parentIdentity = fileIdentity(parentStat, target.parent)
    if expectedParent is not None and parentIdentity != expectedParent:
        raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
    parentFd: Optional[int] = None
    if os.name != "nt" and os.open in os.supports_dir_fd:
        parentFd = openDirectory(target.parent)
        if fileIdentity(os.fstat(parentFd), fileDescriptor=parentFd) != parentIdentity:
            os.close(parentFd)
            raise OSError(errno.EINVAL, "The target parent changed while it was being opened", str(target.parent))

    tempName = f".umbraedit-write-{uuid.uuid4().hex}.tmp"
    tempPath = target.parent / tempName
    fileDesc: Optional[int] = None
    tempIdentity: Optional[FileIdentity] = None
    quarantineName: Optional[str] = None
    quarantinePath: Optional[Path] = None
    quarantineIdentity: Optional[FileIdentity] = None
    published = False

    def restoreQuarantined() -> bool:
        """Restore the old target without replacing a concurrent entry."""
        if quarantinePath is None or quarantineIdentity is None or quarantineName is None:
            return True
        try:
            currentQuarantineStat = _entryStat(quarantinePath, parentFd)
        except OSError:
            return False
        if not stat.S_ISREG(currentQuarantineStat.st_mode) or not _entryIdentityMatches(
            quarantineIdentity,
            quarantinePath,
            parentFd,
            currentQuarantineStat,
        ):
            return False
        try:
            if parentFd is not None:
                restored = renameNoReplaceBetween(
                    Path(quarantineName),
                    Path(target.name),
                    sourceDirFd=parentFd,
                    targetDirFd=parentFd,
                )
            else:
                restored = renameNoReplaceBetween(quarantinePath, target)
        except OSError:
            return False
        if not restored:
            return False
        try:
            restoredStat = _entryStat(target, parentFd)
        except OSError:
            return False
        return stat.S_ISREG(restoredStat.st_mode) and _entryIdentityMatches(
            quarantineIdentity,
            target,
            parentFd,
            restoredStat,
        )

    try:
        if parentFd is not None:
            fileDesc = openExclusiveFile(Path(tempName), parentFd, mode=mode)
        else:
            fileDesc = openExclusiveFile(tempPath, mode=mode)
        try:
            tempStat = os.fstat(fileDesc)
        except Exception:
            os.close(fileDesc)
            fileDesc = None
            raise
        tempIdentity = fileIdentity(tempStat, fileDescriptor=fileDesc)

        with os.fdopen(fileDesc, mode="wb") as outFile:
            fileDesc = None
            outFile.write(data)
            outFile.flush()
            os.fsync(outFile.fileno())

        targetStat: Optional[os.stat_result]
        try:
            targetStat = _entryStat(target, parentFd)
        except FileNotFoundError:
            targetStat = None

        if (targetStat is None) != (expectedTarget is None):
            raise OSError(errno.EINVAL, "The target changed before it could be replaced", str(target))

        if targetStat is not None:
            if not replaceExisting:
                raise FileExistsError(errno.EEXIST, "The target already exists", str(target))
            if not stat.S_ISREG(targetStat.st_mode):
                raise OSError(errno.EINVAL, "The target is not a regular file", str(target))
            assert expectedTarget is not None
            if not _entryIdentityMatches(expectedTarget, target, parentFd, targetStat):
                raise OSError(errno.EINVAL, "The target changed before it could be replaced", str(target))

            quarantineName = f".umbraedit-replaced-{uuid.uuid4().hex}"
            quarantinePath = target.parent / quarantineName
            if parentFd is not None:
                moved = renameNoReplaceBetween(
                    Path(target.name),
                    Path(quarantineName),
                    sourceDirFd=parentFd,
                    targetDirFd=parentFd,
                )
            else:
                moved = renameNoReplaceBetween(target, quarantinePath)
            if not moved:
                quarantinePath = None
                quarantineName = None
                raise OSError(errno.EINVAL, "The target changed before it could be replaced", str(target))

            # The rename may have moved a concurrent replacement rather
            # than the expected old file. Bind the restore operation to
            # the object that was actually quarantined so it can be put
            # back without deleting the replacement.
            quarantineIdentity = expectedTarget
            try:
                quarantineStat = _entryStat(quarantinePath, parentFd)
            except OSError:
                raise
            quarantineIdentity = _entryIdentity(quarantinePath, parentFd, quarantineStat)
            if not stat.S_ISREG(quarantineStat.st_mode) or not _entryIdentityMatches(
                expectedTarget,
                quarantinePath,
                parentFd,
                quarantineStat,
            ):
                if not restoreQuarantined():
                    raise OSError(
                        errno.EINVAL,
                        "The target changed before it could be replaced; the replacement is preserved at "
                        f"'{quarantinePath}'",
                        str(target),
                    )
                quarantinePath = None
                quarantineName = None
                raise OSError(errno.EINVAL, "The target changed before it could be replaced", str(target))

        try:
            if parentFd is not None:
                moved = renameNoReplaceBetween(
                    Path(tempName),
                    Path(target.name),
                    sourceDirFd=parentFd,
                    targetDirFd=parentFd,
                )
            else:
                moved = renameNoReplaceBetween(tempPath, target)
        except Exception as exc:
            if quarantinePath is not None and not restoreQuarantined():
                raise OSError(
                    errno.EINVAL,
                    f"The write failed and the previous target is preserved at '{quarantinePath}'",
                    str(target),
                ) from exc
            raise

        if not moved:
            if quarantinePath is not None and not restoreQuarantined():
                raise OSError(
                    errno.EEXIST,
                    f"The target already exists and the previous target is preserved at '{quarantinePath}'",
                    str(target),
                )
            raise FileExistsError(errno.EEXIST, "The target already exists", str(target))
        published = True

        try:
            currentStat = _entryStat(target, parentFd)
        except OSError as exc:
            raise PublishedFileError(
                "The published file could not be verified",
                target,
                tempIdentity,
            ) from exc
        if not stat.S_ISREG(currentStat.st_mode) or not _entryIdentityMatches(
            tempIdentity,
            target,
            parentFd,
            currentStat,
        ):
            raise PublishedFileError(
                "The published file does not match the staged file",
                target,
                tempIdentity,
            )
        try:
            currentParentStat = os.lstat(target.parent)
        except OSError as exc:
            raise PublishedFileError(
                "The target parent could not be verified",
                target.parent,
                tempIdentity,
            ) from exc
        if not _identityMatchesObject(parentIdentity, currentParentStat, target.parent):
            raise PublishedFileError(
                "The target parent changed while it was being used",
                target.parent,
                tempIdentity,
            )

        if quarantinePath is not None and quarantineIdentity is not None:
            try:
                unlinkIfSameFile(
                    quarantinePath,
                    quarantineIdentity,
                    dirFd=parentFd,
                    quarantineParent=quarantineParent,
                    expectedQuarantineParent=expectedQuarantineParent,
                )
            except OSError as exc:
                logger.warning("The previous file is preserved at '%s': %s", quarantinePath, exc)
            quarantinePath = None
            quarantineName = None
        return tempIdentity
    finally:
        if fileDesc is not None:
            with contextlib.suppress(OSError):
                os.close(fileDesc)
        if not published and tempIdentity is not None:
            with contextlib.suppress(OSError):
                unlinkIfSameFile(
                    tempPath,
                    tempIdentity,
                    dirFd=parentFd,
                    quarantineParent=quarantineParent,
                    expectedQuarantineParent=expectedQuarantineParent,
                )
        if parentFd is not None:
            os.close(parentFd)


def publishRegularFileNoReplace(
    source: Path,
    target: Path,
    expectedSourceIdentity: FileIdentity,
    *,
    expectedSourceParent: Optional[FileIdentity] = None,
    expectedTargetParent: Optional[FileIdentity] = None,
) -> FileIdentity:
    """Publish a staged regular file without replacing an existing target.

    The source is quarantined and identity-checked before a hard link is
    created. If hard links are unavailable, an identity-checked atomic
    no-replace rename is used instead. The staged source is consumed by a
    successful publication.
    """
    _verifyParent(source, expectedSourceParent)
    sourceStat = os.lstat(source)
    if not stat.S_ISREG(sourceStat.st_mode) or not _identityMatchesObject(
        expectedSourceIdentity,
        sourceStat,
        source,
    ):
        raise OSError(errno.EINVAL, "The staged file changed before it could be published", str(source))

    targetParentStat = os.lstat(target.parent)
    if not stat.S_ISDIR(targetParentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The target parent is not a directory", str(target.parent))
    targetParentIdentity = fileIdentity(targetParentStat, target.parent)
    if expectedTargetParent is not None and targetParentIdentity != expectedTargetParent:
        raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))

    sourceFd: Optional[int] = None
    targetFd: Optional[int] = None
    if os.name != "nt" and os.open in os.supports_dir_fd:
        sourceFd = openDirectory(source.parent)
        try:
            sourceParentStat = os.fstat(sourceFd)
            sourceParentIdentity = fileIdentity(sourceParentStat, fileDescriptor=sourceFd)
            if sourceParentIdentity != fileIdentity(os.lstat(source.parent), source.parent):
                raise OSError(errno.EINVAL, "The source parent changed while it was being opened", str(source.parent))
            if expectedSourceParent is not None and sourceParentIdentity != expectedSourceParent:
                raise OSError(errno.EINVAL, "The source parent changed while it was being opened", str(source.parent))
            targetFd = openDirectory(target.parent)
            openedTargetParentIdentity = fileIdentity(os.fstat(targetFd), fileDescriptor=targetFd)
            if openedTargetParentIdentity != targetParentIdentity:
                raise OSError(errno.EINVAL, "The target parent changed while it was being opened", str(target.parent))
            if expectedTargetParent is not None and openedTargetParentIdentity != expectedTargetParent:
                raise OSError(errno.EINVAL, "The target parent changed while it was being opened", str(target.parent))
        except Exception:
            if targetFd is not None:
                os.close(targetFd)
            os.close(sourceFd)
            raise

    try:
        try:
            published = linkNoReplaceIfSameFile(
                source,
                target,
                expectedSourceIdentity,
                sourceDirFd=sourceFd,
                targetDirFd=targetFd,
            )
        except OSError as linkError:
            if getattr(linkError, "errno", None) not in (
                errno.EACCES,
                errno.EINVAL,
                errno.ENOSYS,
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
                errno.EPERM,
            ):
                raise
            published = renameNoReplaceIfSameFile(
                source,
                target,
                expectedSourceIdentity,
                sourceDirFd=sourceFd,
                targetDirFd=targetFd,
            )
        if not published:
            raise FileExistsError(errno.EEXIST, "The target already exists", str(target))

        currentStat = _entryStat(target, targetFd)
        if not stat.S_ISREG(currentStat.st_mode) or not _entryIdentityMatches(
            expectedSourceIdentity,
            target,
            targetFd,
            currentStat,
        ):
            raise OSError(errno.EINVAL, "The published file does not match the staged file", str(target))
        currentParentStat = os.lstat(target.parent)
        if not _identityMatchesObject(targetParentIdentity, currentParentStat, target.parent):
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
        return expectedSourceIdentity
    finally:
        if targetFd is not None:
            os.close(targetFd)
        if sourceFd is not None:
            os.close(sourceFd)
