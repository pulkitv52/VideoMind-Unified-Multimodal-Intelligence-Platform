"""Read-only, descriptor-relative import confined to the operator's mount."""

from contextlib import contextmanager
import os
import errno
from pathlib import PurePosixPath
import stat
import time

from videomind.connectors.upload.validation import InvalidFile


def relative_folder(value):
    if value in {"", "."}:
        return ""
    parts = PurePosixPath(value).parts
    if (
        value.startswith("/")
        or "\\" in value
        or any(p in {"..", "."} for p in parts)
        or len(value) > 200
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise InvalidFile("INVALID_FOLDER")
    return "/".join(parts)


@contextmanager
def folder_fd(root, relative):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative_folder(relative).split("/"):
            if not part:
                continue
            next_fd = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def files(root, relative):
    with folder_fd(root, relative) as parent:
        count = 0
        directories = 0
        started = time.monotonic()
        for directory, dirs, names, fd in os.fwalk(
            ".", dir_fd=parent, follow_symlinks=False
        ):
            directories += 1
            if directories > 1000 or len(PurePosixPath(directory).parts) > 16:
                raise InvalidFile("FOLDER_DIRECTORY_LIMIT")
            if time.monotonic() - started > 180:
                raise InvalidFile("FOLDER_TIME_LIMIT")
            # Symlink directories are rejected explicitly rather than silently followed.
            for name in dirs:
                if stat.S_ISLNK(
                    os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
                ):
                    raise InvalidFile("SYMLINK_REJECTED")
            for name in sorted(names):
                count += 1
                if count > 200:
                    raise InvalidFile("FOLDER_FILE_LIMIT")
                try:
                    handle = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                    )
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise InvalidFile("SYMLINK_REJECTED") from None
                    raise
                try:
                    info = os.fstat(handle)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise InvalidFile("UNSAFE_FOLDER_ENTRY")
                    external = str(PurePosixPath(directory) / name)
                    with os.fdopen(os.dup(handle), "rb") as stream:
                        yield external, name, info.st_size, stream
                finally:
                    os.close(handle)
