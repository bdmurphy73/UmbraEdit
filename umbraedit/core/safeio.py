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
import logging
import os
import platform
import shutil
import stat
import sys
import uuid

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

# Windows marks symbolic links, junctions, and other reparse points with
# this file attribute. Path.is_symlink() does not identify every kind of
# reparse point on Python 3.9.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Darwin and Linux use different values for AT_FDCWD. The Darwin value is
# required by renameatx_np(); using the Linux value there makes descriptor-
# relative calls with one descriptor-less side fail or resolve incorrectly.
_DARWIN_AT_FDCWD = -2
_LINUX_AT_FDCWD = -100

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

FileIdentity = tuple[int, int]

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


def fileIdentity(pathStat: os.stat_result) -> FileIdentity:
    """Return the device and inode identity of a stat result."""
    return pathStat.st_dev, pathStat.st_ino


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
    if fileIdentity(pathStat) != expectedIdentity:
        raise OSError(errno.EINVAL, "The path changed while it was being used", str(path))
    if expectedParent is not None:
        parentStat = os.lstat(path.parent)
        if fileIdentity(parentStat) != expectedParent:
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
    current = path
    while True:
        try:
            currentStat = os.stat(current)
        except FileNotFoundError:
            pass
        else:
            if os.path.samestat(ancestorStat, currentStat):
                return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


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

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fileDesc = os.open(path, flags)
    try:
        afterStat = os.fstat(fileDesc)
        if not stat.S_ISDIR(afterStat.st_mode) or not os.path.samestat(beforeStat, afterStat):
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
    if fileIdentity(parentStat) != expectedParent:
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
    if expectedIdentity is not None and fileIdentity(beforeStat) != expectedIdentity:
        raise OSError(errno.EINVAL, "The file changed before it could be opened", str(path))

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fileDesc = os.open(path, flags)
    try:
        afterStat = os.fstat(fileDesc)
        if not stat.S_ISREG(afterStat.st_mode) or not os.path.samestat(beforeStat, afterStat):
            raise OSError(errno.EINVAL, "The file changed while it was being opened", str(path))
        if expectedIdentity is not None and fileIdentity(afterStat) != expectedIdentity:
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
    return fileIdentity(pathStat)


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
            closeHandle = kernel32.CloseHandle
            closeHandle.argtypes = [ctypes.c_void_p]
            closeHandle.restype = ctypes.c_int
            closeHandle(handle)
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
                fileIdentities[entryPath.name] = fileIdentity(entryStat)

    afterStat = os.lstat(directory)
    if not os.path.samestat(beforeStat, afterStat):
        raise OSError(errno.EINVAL, "The directory changed while it was being scanned", str(directory))
    expectedLocation = Path(os.path.abspath(expectedPath)) if expectedPath is not None else None
    if expectedLocation is not None and directory.resolve() != expectedLocation:
        raise OSError(errno.EINVAL, "The directory resolves outside the expected location", str(directory))

    return DirectorySnapshot(
        path=directory,
        identity=fileIdentity(beforeStat),
        files=tuple(files),
        fileIdentities=fileIdentities,
    )


def _entryStat(path: Path, dirFd: Optional[int]) -> os.stat_result:
    """Return a no-follow stat result for a directory entry."""
    if dirFd is not None and os.stat in os.supports_dir_fd:
        return os.stat(path.name, dir_fd=dirFd, follow_symlinks=False)
    return os.lstat(path)


def unlinkEntryIfSameFile(
    path: Path,
    expectedIdentity: Optional[FileIdentity] = None,
    *,
    dirFd: Optional[int] = None,
) -> bool:
    """Unlink a non-directory entry only when it has the expected identity.

    The directory entry is first moved to a unique quarantine name. The
    quarantined object is then checked again before it is unlinked. If a
    replacement was installed after the first check, it is restored to
    the original name and preserved. Unlike ``unlinkIfSameFile``, this
    helper can also remove a symbolic link without following it.
    """
    if dirFd is None and os.name != "nt" and os.open in os.supports_dir_fd:
        parentFd = openDirectory(path.parent)
        try:
            return unlinkEntryIfSameFile(path, expectedIdentity, dirFd=parentFd)
        finally:
            os.close(parentFd)

    try:
        pathStat = _entryStat(path, dirFd)
    except FileNotFoundError:
        return True
    if stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The path is a directory", str(path))
    if expectedIdentity is not None and fileIdentity(pathStat) != expectedIdentity:
        raise OSError(errno.EINVAL, "The file changed before it could be removed", str(path))

    quarantineName = f".umbraedit-unlink-{uuid.uuid4().hex}"
    quarantinePath = path.parent / quarantineName

    def restoreQuarantine() -> bool:
        """Restore the quarantined entry without replacing a new entry."""
        try:
            if dirFd is not None:
                return renameNoReplaceBetween(
                    Path(quarantineName),
                    Path(path.name),
                    sourceDirFd=dirFd,
                    targetDirFd=dirFd,
                )
            return renameNoReplace(quarantinePath, path)
        except OSError:
            return False

    if dirFd is not None:
        moved = renameNoReplaceBetween(
            Path(path.name),
            Path(quarantineName),
            sourceDirFd=dirFd,
            targetDirFd=dirFd,
        )
    else:
        moved = renameNoReplace(path, quarantinePath)
    if not moved:
        raise OSError(errno.EEXIST, "Could not create a unique cleanup name", str(quarantinePath))

    try:
        quarantineStat = _entryStat(quarantinePath, dirFd)
    except OSError:
        raise
    identityMismatch = expectedIdentity is not None and fileIdentity(quarantineStat) != expectedIdentity
    if identityMismatch:
        if not restoreQuarantine():
            raise OSError(
                errno.EINVAL,
                f"The file changed before it could be removed; the replacement is preserved at '{quarantinePath}'",
                str(path),
            )
        raise OSError(errno.EINVAL, "The file changed before it could be removed", str(path))

    try:
        if dirFd is not None and os.unlink in os.supports_dir_fd:
            os.unlink(quarantineName, dir_fd=dirFd)
        else:
            quarantinePath.unlink()
    except OSError as exc:
        if restoreQuarantine():
            raise OSError(exc.errno, exc.strerror, str(path)) from exc
        raise OSError(
            exc.errno,
            f"The file could not be removed; it is preserved at '{quarantinePath}'",
            str(quarantinePath),
        ) from exc
    return True


def unlinkIfSameFile(
    path: Path,
    expectedIdentity: Optional[FileIdentity] = None,
    *,
    dirFd: Optional[int] = None,
) -> bool:
    """Unlink a regular file only when it still has the expected identity."""
    try:
        pathStat = _entryStat(path, dirFd)
    except FileNotFoundError:
        return True
    if not stat.S_ISREG(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The path is not a regular file", str(path))
    return unlinkEntryIfSameFile(path, expectedIdentity, dirFd=dirFd)


def _removeTreeContents(dirFd: int) -> None:
    """Remove all entries below an open directory descriptor."""
    for name in os.listdir(dirFd):
        entryStat = os.stat(name, dir_fd=dirFd, follow_symlinks=False)
        if stat.S_ISDIR(entryStat.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            childFd = os.open(name, flags, dir_fd=dirFd)
            try:
                childStat = os.fstat(childFd)
                if not stat.S_ISDIR(childStat.st_mode) or not os.path.samestat(entryStat, childStat):
                    raise OSError(errno.EINVAL, "The cleanup directory changed while it was being removed", name)
                _removeTreeContents(childFd)
                currentStat = os.stat(name, dir_fd=dirFd, follow_symlinks=False)
                if not os.path.samestat(entryStat, currentStat):
                    raise OSError(errno.EINVAL, "The cleanup directory changed while it was being removed", name)

                quarantineName = f".umbraedit-cleanup-{uuid.uuid4().hex}"
                if not renameNoReplaceBetween(
                    Path(name),
                    Path(quarantineName),
                    sourceDirFd=dirFd,
                    targetDirFd=dirFd,
                ):
                    raise OSError(errno.EEXIST, "Could not create a unique cleanup name", quarantineName)
                quarantineStat = os.stat(
                    quarantineName,
                    dir_fd=dirFd,
                    follow_symlinks=False,
                )
                if not os.path.samestat(entryStat, quarantineStat):
                    restored = renameNoReplaceBetween(
                        Path(quarantineName),
                        Path(name),
                        sourceDirFd=dirFd,
                        targetDirFd=dirFd,
                    )
                    if not restored:
                        raise OSError(
                            errno.EINVAL,
                            f"The cleanup directory changed; the replacement is preserved at '{quarantineName}'",
                            name,
                        )
                    raise OSError(errno.EINVAL, "The cleanup directory changed while it was being removed", name)
                try:
                    os.rmdir(quarantineName, dir_fd=dirFd)
                except OSError as exc:
                    raise OSError(
                        exc.errno,
                        f"The cleanup directory could not be removed; it is preserved at '{quarantineName}'",
                        quarantineName,
                    ) from exc
            finally:
                os.close(childFd)
        else:
            unlinkEntryIfSameFile(Path(name), fileIdentity(entryStat), dirFd=dirFd)


def removeTreeIfOwned(path: Path, expectedIdentity: FileIdentity) -> bool:
    """Remove an application-owned directory without following a replacement."""
    try:
        pathStat = os.lstat(path)
    except FileNotFoundError:
        return True
    if isLinkLike(path) or not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The cleanup path is not a real directory", str(path))
    if fileIdentity(pathStat) != expectedIdentity:
        raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

    dirFdSupported = (
        os.name != "nt"
        and os.open in os.supports_dir_fd
        and os.listdir in os.supports_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
    )
    if dirFdSupported:
        parentFd = openDirectory(path.parent)
        try:
            currentStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
            if fileIdentity(currentStat) != expectedIdentity:
                raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            treeFd = os.open(path.name, flags, dir_fd=parentFd)
            try:
                treeStat = os.fstat(treeFd)
                if not stat.S_ISDIR(treeStat.st_mode) or not os.path.samestat(currentStat, treeStat):
                    raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))
                _removeTreeContents(treeFd)
                currentStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
                if fileIdentity(currentStat) != expectedIdentity:
                    raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))
                os.rmdir(path.name, dir_fd=parentFd)
            finally:
                os.close(treeFd)
        finally:
            os.close(parentFd)
    else:
        quarantineName = f".umbraedit-cleanup-{uuid.uuid4().hex}"
        quarantinePath = path.parent / quarantineName
        if not renameNoReplace(path, quarantinePath):
            raise OSError(errno.EEXIST, "Could not create a unique cleanup name", str(quarantinePath))
        try:
            quarantineStat = os.lstat(quarantinePath)
            if fileIdentity(quarantineStat) != expectedIdentity:
                restored = renameNoReplace(quarantinePath, path)
                if not restored:
                    raise OSError(
                        errno.EINVAL,
                        f"The cleanup path changed; the replacement is preserved at '{quarantinePath}'",
                        str(path),
                    )
                raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))
            shutil.rmtree(quarantinePath)
        except OSError as exc:
            if os.path.lexists(quarantinePath):
                raise OSError(
                    exc.errno,
                    f"The cleanup directory could not be removed; it is preserved at '{quarantinePath}'",
                    str(quarantinePath),
                ) from exc
            raise
    return True


def removeEmptyDirectoryIfOwned(
    path: Path,
    expectedIdentity: FileIdentity,
    *,
    expectedParent: Optional[FileIdentity] = None,
) -> bool:
    """Remove an empty directory only when it is still the owned object.

    On POSIX, the directory is quarantined and removed relative to an
    open parent descriptor. This prevents a replaced parent path from
    redirecting the cleanup. The expected parent identity can be supplied
    when the caller has already validated that directory.
    """
    try:
        pathStat = os.lstat(path)
    except FileNotFoundError:
        if expectedParent is not None:
            parentStat = os.lstat(path.parent)
            if fileIdentity(parentStat) != expectedParent:
                raise OSError(
                    errno.EINVAL,
                    "The parent directory changed while it was being used",
                    str(path.parent),
                ) from None
        return True
    if isLinkLike(path) or not stat.S_ISDIR(pathStat.st_mode):
        raise OSError(errno.EINVAL, "The cleanup path is not a real directory", str(path))
    if fileIdentity(pathStat) != expectedIdentity:
        raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

    parentStat = os.lstat(path.parent)
    if not stat.S_ISDIR(parentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The cleanup parent is not a directory", str(path.parent))
    if expectedParent is not None and fileIdentity(parentStat) != expectedParent:
        raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(path.parent))

    descriptorCleanupSupported = (
        os.name != "nt"
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
    )
    if descriptorCleanupSupported:
        parentFd = openDirectory(path.parent)
        try:
            openedParentStat = os.fstat(parentFd)
            if not os.path.samestat(parentStat, openedParentStat):
                raise OSError(errno.EINVAL, "The parent directory changed while it was being opened", str(path.parent))
            if expectedParent is not None and fileIdentity(openedParentStat) != expectedParent:
                raise OSError(errno.EINVAL, "The parent directory changed while it was being opened", str(path.parent))

            currentStat = os.stat(path.name, dir_fd=parentFd, follow_symlinks=False)
            if not stat.S_ISDIR(currentStat.st_mode) or fileIdentity(currentStat) != expectedIdentity:
                raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

            quarantineName = f".umbraedit-rmdir-{uuid.uuid4().hex}"
            quarantinePath = path.parent / quarantineName
            moved = renameNoReplaceBetween(
                Path(path.name),
                Path(quarantineName),
                sourceDirFd=parentFd,
                targetDirFd=parentFd,
            )
            if not moved:
                raise OSError(errno.EEXIST, "Could not create a unique cleanup name", str(quarantinePath))

            quarantineStat = os.stat(quarantineName, dir_fd=parentFd, follow_symlinks=False)
            if fileIdentity(quarantineStat) != expectedIdentity:
                restored = renameNoReplaceBetween(
                    Path(quarantineName),
                    Path(path.name),
                    sourceDirFd=parentFd,
                    targetDirFd=parentFd,
                )
                if not restored:
                    raise OSError(
                        errno.EINVAL,
                        f"The cleanup path changed; the replacement is preserved at '{quarantinePath}'",
                        str(path),
                    )
                raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))

            try:
                os.rmdir(quarantineName, dir_fd=parentFd)
            except OSError as exc:
                restored = renameNoReplaceBetween(
                    Path(quarantineName),
                    Path(path.name),
                    sourceDirFd=parentFd,
                    targetDirFd=parentFd,
                )
                if not restored:
                    raise OSError(
                        exc.errno or errno.EINVAL,
                        f"The cleanup directory could not be removed; it is preserved at '{quarantinePath}'",
                        str(quarantinePath),
                    ) from exc
                raise OSError(exc.errno or errno.EINVAL, exc.strerror, str(path)) from exc

            currentParentStat = os.lstat(path.parent)
            if not os.path.samestat(parentStat, currentParentStat):
                raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(path.parent))
        finally:
            os.close(parentFd)
        return True

    quarantineName = f".umbraedit-rmdir-{uuid.uuid4().hex}"
    quarantinePath = path.parent / quarantineName
    if not renameNoReplace(path, quarantinePath):
        raise OSError(errno.EEXIST, "Could not create a unique cleanup name", str(quarantinePath))
    try:
        quarantineStat = os.lstat(quarantinePath)
        if fileIdentity(quarantineStat) != expectedIdentity:
            restored = renameNoReplace(quarantinePath, path)
            if not restored:
                raise OSError(
                    errno.EINVAL,
                    f"The cleanup path changed; the replacement is preserved at '{quarantinePath}'",
                    str(path),
                )
            raise OSError(errno.EINVAL, "The cleanup path changed before it could be removed", str(path))
        os.rmdir(quarantinePath)
    except OSError as exc:
        if os.path.lexists(quarantinePath):
            restored = renameNoReplace(quarantinePath, path)
            if not restored:
                raise OSError(
                    exc.errno or errno.EINVAL,
                    f"The cleanup directory could not be removed; it is preserved at '{quarantinePath}'",
                    str(quarantinePath),
                ) from exc
            raise OSError(exc.errno or errno.EINVAL, exc.strerror, str(path)) from exc
        raise
    return True


def getDefaultDirectoryMode(
    parent: Path,
    *,
    expectedParent: Optional[FileIdentity] = None,
) -> int:
    """Return the directory mode created in a parent under its current policy.

    A temporary directory is used as a probe so the process-wide umask is
    never changed, even briefly, while another thread may be creating a
    file. On POSIX, the probe is created relative to an open directory
    descriptor and can be bound to an expected parent identity.
    """
    if os.name != "nt" and os.mkdir in os.supports_dir_fd:
        parentFd = openDirectory(parent)
        try:
            parentStat = os.fstat(parentFd)
            if expectedParent is not None and fileIdentity(parentStat) != expectedParent:
                raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(parent))
            for _ in range(10):
                probeName = f".umbraedit-mode-{uuid.uuid4().hex}"
                try:
                    os.mkdir(probeName, 0o777, dir_fd=parentFd)
                except FileExistsError:
                    continue
                try:
                    probeStat = os.stat(probeName, dir_fd=parentFd, follow_symlinks=False)
                    if not stat.S_ISDIR(probeStat.st_mode):
                        raise OSError(errno.ENOTDIR, "The mode probe is not a directory", probeName)
                    return stat.S_IMODE(probeStat.st_mode)
                finally:
                    with contextlib.suppress(OSError):
                        os.rmdir(probeName, dir_fd=parentFd)
            raise OSError(errno.EEXIST, "Could not create a directory mode probe", str(parent))
        finally:
            os.close(parentFd)

    parentStat = os.lstat(parent)
    if expectedParent is not None and fileIdentity(parentStat) != expectedParent:
        raise OSError(errno.EINVAL, "The parent directory changed while it was being used", str(parent))
    for _ in range(10):
        probePath = parent / f".umbraedit-mode-{uuid.uuid4().hex}"
        try:
            os.mkdir(probePath, 0o777)
        except FileExistsError:
            continue
        try:
            probeStat = os.lstat(probePath)
            if not stat.S_ISDIR(probeStat.st_mode):
                raise OSError(errno.ENOTDIR, "The mode probe is not a directory", str(probePath))
            return stat.S_IMODE(probeStat.st_mode)
        finally:
            with contextlib.suppress(OSError):
                os.rmdir(probePath)
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
        try:
            os.rename(source, target)
        except FileExistsError:
            return False
        return True
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
    if os.name == "nt":
        if sourceDirFd is not None or targetDirFd is not None:
            raise OSError(errno.ENOTSUP, "Directory descriptors are not supported on Windows")
        return renameNoReplace(source, target)

    if sourceDirFd is None and targetDirFd is None:
        return renameNoReplace(source, target)

    sourcePath = Path(os.path.abspath(source)) if sourceDirFd is None else Path(source.name)
    targetPath = Path(os.path.abspath(target)) if targetDirFd is None else Path(target.name)

    if sys.platform == "darwin":
        return _renameNoReplaceDarwinAt(sourcePath, targetPath, sourceDirFd, targetDirFd)

    if sys.platform.startswith("linux"):
        return _renameNoReplaceLinux(sourcePath, targetPath, sourceDirFd, targetDirFd)
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
        if not stat.S_ISREG(currentStat.st_mode) or fileIdentity(currentStat) != identity:
            return False
        if sourceDirFd is not None:
            moved = renameNoReplaceBetween(
                quarantineEntry,
                sourceEntry,
                sourceDirFd=sourceDirFd,
                targetDirFd=sourceDirFd,
            )
        else:
            moved = renameNoReplace(quarantineEntry, sourceEntry)
        if not moved:
            return False
        try:
            restoredStat = _entryStat(sourceEntry, sourceDirFd)
        except OSError:
            return False
        return stat.S_ISREG(restoredStat.st_mode) and fileIdentity(restoredStat) == identity

    try:
        try:
            sourceStat = _entryStat(sourceEntry, sourceDirFd)
        except FileNotFoundError as exc:
            raise OSError(errno.ENOENT, "The source file does not exist", str(source)) from exc
        if not stat.S_ISREG(sourceStat.st_mode):
            raise OSError(errno.ESTALE, "The source is not a regular file", str(source))
        if fileIdentity(sourceStat) != expectedSourceIdentity:
            raise OSError(errno.ESTALE, "The source file changed before it could be renamed", str(source))

        if sourceDirFd is not None:
            moved = renameNoReplaceBetween(
                sourceEntry,
                quarantineEntry,
                sourceDirFd=sourceDirFd,
                targetDirFd=sourceDirFd,
            )
        else:
            moved = renameNoReplace(sourceEntry, quarantineEntry)
        if not moved:
            raise OSError(errno.EEXIST, "Could not create a unique rename name", str(quarantineEntry))

        try:
            quarantineStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            raise
        quarantineIdentity = fileIdentity(quarantineStat)
        if not stat.S_ISREG(quarantineStat.st_mode) or quarantineIdentity != expectedSourceIdentity:
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
                published = renameNoReplace(quarantineEntry, targetEntry)
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
        if not stat.S_ISREG(targetStat.st_mode) or fileIdentity(targetStat) != expectedSourceIdentity:
            # A concurrently installed target is deliberately left in
            # place. Only the expected identity may be considered moved.
            raise OSError(errno.ESTALE, "The renamed target does not match the expected file", str(target))
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
        return renameNoReplace(entry, destination)

    def restoreQuarantine(identity: Optional[FileIdentity] = None) -> bool:
        """Restore the private source entry without replacing a new one."""
        try:
            quarantineStat = _entryStat(quarantineEntry, sourceDirFd)
        except OSError:
            return False
        quarantineIdentity = fileIdentity(quarantineStat)
        if identity is not None and quarantineIdentity != identity:
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
        return fileIdentity(restoredStat) == quarantineIdentity

    def preserveUnexpectedTarget(targetIdentity: FileIdentity) -> None:
        """Move an unexpected target out of the requested name."""
        conflictName = f".umbraedit-conflict-{uuid.uuid4().hex}"
        conflictEntry = Path(conflictName) if targetDirFd is not None else target.parent / conflictName
        try:
            moved = renameEntry(
                targetEntry,
                conflictEntry,
                entryDirFd=targetDirFd,
                destinationDirFd=targetDirFd,
            )
        except OSError:
            moved = False
        if moved:
            return
        with contextlib.suppress(OSError):
            unlinkEntryIfSameFile(targetEntry, targetIdentity, dirFd=targetDirFd)

    try:
        try:
            sourceStat = _entryStat(sourceEntry, sourceDirFd)
        except FileNotFoundError as exc:
            raise OSError(errno.ENOENT, "The source file does not exist", str(source)) from exc
        if not stat.S_ISREG(sourceStat.st_mode):
            raise OSError(errno.ESTALE, "The source is not a regular file", str(source))
        if fileIdentity(sourceStat) != expectedSourceIdentity:
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
        quarantineIdentity = fileIdentity(quarantineStat)
        if not stat.S_ISREG(quarantineStat.st_mode) or quarantineIdentity != expectedSourceIdentity:
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

        targetIdentity = fileIdentity(targetStat) if targetStat is not None else None
        currentQuarantineIdentity = fileIdentity(currentQuarantineStat) if currentQuarantineStat is not None else None
        if targetIdentity != expectedSourceIdentity:
            if (
                targetIdentity is not None
                and currentQuarantineIdentity is not None
                and targetIdentity == currentQuarantineIdentity
            ):
                preserveUnexpectedTarget(targetIdentity)
            if currentQuarantineIdentity is not None:
                restoreQuarantine(currentQuarantineIdentity)
            raise OSError(errno.ESTALE, "The published file does not match the expected file", str(target))

        if currentQuarantineIdentity != expectedSourceIdentity:
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
        if expectedTargetParent is not None and fileIdentity(targetParentStat) != expectedTargetParent:
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
                targetIdentity = fileIdentity(targetStat)
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
                    if fileIdentity(currentStat) != targetIdentity:
                        raise OSError(errno.EINVAL, "The target file changed while it was being copied", str(target))
            except Exception:
                with contextlib.suppress(OSError):
                    unlinkIfSameFile(target, targetIdentity, dirFd=targetDirFd)
                raise

        if targetDirFd is not None:
            currentParentStat = os.fstat(targetDirFd)
        else:
            currentParentStat = os.lstat(target.parent)
        if not os.path.samestat(targetParentStat, currentParentStat):
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
        try:
            pathParentStat = os.lstat(target.parent)
        except OSError:
            pathParentStat = None
        if pathParentStat is None or not os.path.samestat(targetParentStat, pathParentStat):
            if targetIdentity is not None:
                with contextlib.suppress(OSError):
                    unlinkIfSameFile(target, targetIdentity, dirFd=targetDirFd)
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
) -> FileIdentity:
    """Write a file through a private staging file and publish it safely.

    An existing target is only replaced when ``replaceExisting`` is enabled
    and its identity was explicitly supplied and still matches. The old
    target is first moved to a unique quarantine name, and the staged file
    is then published with no-replace semantics. A concurrently installed
    target is therefore never overwritten. If ``replaceExisting`` is enabled
    without an expected identity, the current target identity is captured
    immediately before the replacement. The returned identity belongs to the
    published file.
    """
    parentStat = os.lstat(target.parent)
    if not stat.S_ISDIR(parentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The target parent is not a directory", str(target.parent))
    if expectedParent is not None and fileIdentity(parentStat) != expectedParent:
        raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
    if replaceExisting and expectedTarget is None:
        expectedTarget = captureRegularFileIdentity(target)

    parentFd: Optional[int] = None
    if os.name != "nt" and os.open in os.supports_dir_fd:
        parentFd = openDirectory(target.parent)
        if fileIdentity(os.fstat(parentFd)) != fileIdentity(parentStat):
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
        if not stat.S_ISREG(currentQuarantineStat.st_mode) or fileIdentity(currentQuarantineStat) != quarantineIdentity:
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
                restored = renameNoReplace(quarantinePath, target)
        except OSError:
            return False
        if not restored:
            return False
        try:
            restoredStat = _entryStat(target, parentFd)
        except OSError:
            return False
        return stat.S_ISREG(restoredStat.st_mode) and fileIdentity(restoredStat) == quarantineIdentity

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
        tempIdentity = fileIdentity(tempStat)

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
            if fileIdentity(targetStat) != expectedTarget:
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
                moved = renameNoReplace(target, quarantinePath)
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
            quarantineIdentity = fileIdentity(quarantineStat)
            if not stat.S_ISREG(quarantineStat.st_mode) or quarantineIdentity != expectedTarget:
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
                moved = renameNoReplace(tempPath, target)
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

        currentStat = _entryStat(target, parentFd)
        if not stat.S_ISREG(currentStat.st_mode) or fileIdentity(currentStat) != tempIdentity:
            raise OSError(errno.EINVAL, "The published file does not match the staged file", str(target))
        currentParentStat = os.lstat(target.parent)
        if not os.path.samestat(parentStat, currentParentStat):
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))

        if quarantinePath is not None and quarantineIdentity is not None:
            try:
                unlinkIfSameFile(quarantinePath, quarantineIdentity, dirFd=parentFd)
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
                unlinkIfSameFile(tempPath, tempIdentity, dirFd=parentFd)
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
    if not stat.S_ISREG(sourceStat.st_mode) or fileIdentity(sourceStat) != expectedSourceIdentity:
        raise OSError(errno.EINVAL, "The staged file changed before it could be published", str(source))

    targetParentStat = os.lstat(target.parent)
    if not stat.S_ISDIR(targetParentStat.st_mode):
        raise OSError(errno.ENOTDIR, "The target parent is not a directory", str(target.parent))
    if expectedTargetParent is not None and fileIdentity(targetParentStat) != expectedTargetParent:
        raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))

    sourceFd: Optional[int] = None
    targetFd: Optional[int] = None
    if os.name != "nt" and os.open in os.supports_dir_fd:
        sourceFd = openDirectory(source.parent)
        try:
            sourceParentStat = os.fstat(sourceFd)
            if fileIdentity(sourceParentStat) != fileIdentity(os.lstat(source.parent)):
                raise OSError(errno.EINVAL, "The source parent changed while it was being opened", str(source.parent))
            if expectedSourceParent is not None and fileIdentity(sourceParentStat) != expectedSourceParent:
                raise OSError(errno.EINVAL, "The source parent changed while it was being opened", str(source.parent))
            targetFd = openDirectory(target.parent)
            targetParentIdentity = fileIdentity(os.fstat(targetFd))
            if targetParentIdentity != fileIdentity(targetParentStat):
                raise OSError(errno.EINVAL, "The target parent changed while it was being opened", str(target.parent))
            if expectedTargetParent is not None and targetParentIdentity != expectedTargetParent:
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
        if not stat.S_ISREG(currentStat.st_mode) or fileIdentity(currentStat) != expectedSourceIdentity:
            raise OSError(errno.EINVAL, "The published file does not match the staged file", str(target))
        currentParentStat = os.lstat(target.parent)
        if not os.path.samestat(targetParentStat, currentParentStat):
            raise OSError(errno.EINVAL, "The target parent changed while it was being used", str(target.parent))
        return expectedSourceIdentity
    finally:
        if targetFd is not None:
            os.close(targetFd)
        if sourceFd is not None:
            os.close(sourceFd)
