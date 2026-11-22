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

import ctypes
import errno
import os
import shutil
import stat
import sys

from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from pathlib import Path

# Windows marks symbolic links, junctions, and other reparse points with
# this file attribute. Path.is_symlink() does not identify every kind of
# reparse point on Python 3.9.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


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


def openRegularFile(path: Path) -> BinaryIO:
    """Open a regular file without following symbolic links.

    The file identity is checked before and after opening it so a link
    cannot silently redirect the operation to another file.
    """
    beforeStat = os.lstat(path)
    if stat.S_ISLNK(beforeStat.st_mode) or (
        getattr(beforeStat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(errno.ELOOP, "The file cannot be a link", str(path))
    if not stat.S_ISREG(beforeStat.st_mode):
        raise OSError(errno.EINVAL, "The path is not a regular file", str(path))

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fileDesc = os.open(path, flags)
    try:
        afterStat = os.fstat(fileDesc)
        if not stat.S_ISREG(afterStat.st_mode) or not os.path.samestat(beforeStat, afterStat):
            raise OSError(errno.EINVAL, "The file changed while it was being opened", str(path))
        return os.fdopen(fileDesc, mode="rb")
    except Exception:
        os.close(fileDesc)
        raise


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

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        renameFunction = getattr(libc, "renamex_np", None)
        if renameFunction is None:
            raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
        renameFunction.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renameFunction.restype = ctypes.c_int
        result = renameFunction(os.fsencode(source), os.fsencode(target), 0x00000004)
    elif sys.platform.startswith("linux"):
        renameFunction = getattr(libc, "renameat2", None)
        if renameFunction is None:
            raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
        renameFunction.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameFunction.restype = ctypes.c_int
        result = renameFunction(-100, os.fsencode(source), -100, os.fsencode(target), 0x00000001)
    else:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")

    if result == 0:
        return True
    errorNumber = ctypes.get_errno()
    if errorNumber in (errno.EEXIST, errno.ENOTEMPTY):
        return False
    if errorNumber in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise OSError(errorNumber, os.strerror(errorNumber), str(target))
    raise OSError(errorNumber, os.strerror(errorNumber), str(target))


def renameNoReplaceAt(source: Path, targetName: str, targetDirFd: int) -> bool:
    """Atomically rename a file into an open directory without replacing it."""
    if os.name == "nt":
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
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
        result = renameFunction(-100, os.fsencode(source), targetDirFd, os.fsencode(targetName), 0x00000004)
    elif sys.platform.startswith("linux"):
        renameFunction = getattr(libc, "renameat2", None)
        if renameFunction is None:
            raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")
        renameFunction.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameFunction.restype = ctypes.c_int
        result = renameFunction(-100, os.fsencode(source), targetDirFd, os.fsencode(targetName), 0x00000001)
    else:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is not supported")

    if result == 0:
        return True
    errorNumber = ctypes.get_errno()
    if errorNumber in (errno.EEXIST, errno.ENOTEMPTY):
        return False
    if errorNumber in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise OSError(errorNumber, os.strerror(errorNumber), str(targetName))
    raise OSError(errorNumber, os.strerror(errorNumber), str(targetName))


def copyRegularFile(source: Path, target: Path) -> None:
    """Copy a regular file to a new target without overwriting it.

    The source is opened without following links. The target is created
    exclusively, and is removed if the copy fails.
    """
    with openRegularFile(source) as inFile:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fileDesc = os.open(target, flags, 0o600)
        targetStat = os.fstat(fileDesc)
        try:
            with os.fdopen(fileDesc, mode="wb") as outFile:
                shutil.copyfileobj(inFile, outFile, length=1024 * 1024)
                outFile.flush()
                os.fsync(outFile.fileno())
        except Exception:
            try:
                currentStat = os.stat(target, follow_symlinks=False)
                if os.path.samestat(targetStat, currentStat):
                    target.unlink()
            except OSError:
                pass
            raise
