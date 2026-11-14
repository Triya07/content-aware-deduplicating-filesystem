from __future__ import annotations

import errno
import os
import stat
import time
from typing import Any

from .chunking import DEFAULT_CHUNK_SIZE
from .storage import DedupStore

try:
    from fuse import FUSE, FuseOSError, Operations
except ImportError:  # pragma: no cover - exercised only when fusepy is absent
    FUSE = None

    class FuseOSError(OSError):
        pass

    class Operations:
        pass


class DedupFuse(Operations):
    """Small FUSE adapter over :class:`DedupStore`."""

    def __init__(self, store: DedupStore):
        self.store = store

    def getattr(self, path: str, fh: Any = None) -> dict[str, int]:
        if self.store.is_directory(path):
            return {
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
                "st_size": 0,
                "st_ctime": time.time(),
                "st_mtime": time.time(),
                "st_atime": time.time(),
            }
        try:
            metadata = self.store.stat(path)
        except FileNotFoundError as error:
            raise FuseOSError(errno.ENOENT) from error
        return {
            "st_mode": stat.S_IFREG | metadata["mode"],
            "st_nlink": 1,
            "st_size": metadata["size"],
            "st_ctime": time.time(),
            "st_mtime": time.time(),
            "st_atime": time.time(),
        }

    def readdir(self, path: str, fh: Any) -> list[str]:
        try:
            return [".", ".."] + self.store.children(path)
        except FileNotFoundError as error:
            raise FuseOSError(errno.ENOENT) from error

    def open(self, path: str, flags: int) -> int:
        if not self.store.exists(path):
            raise FuseOSError(errno.ENOENT)
        return 0

    def create(self, path: str, mode: int, fi: Any = None) -> int:
        self.store.write(path, b"", mode)
        return 0

    def read(self, path: str, size: int, offset: int, fh: Any) -> bytes:
        try:
            return self.store.read(path)[offset : offset + size]
        except FileNotFoundError as error:
            raise FuseOSError(errno.ENOENT) from error

    def truncate(self, path: str, length: int, fh: Any = None) -> None:
        data = self.store.read(path)
        self.store.write(path, data[:length].ljust(length, b"\0"), self.store.stat(path)["mode"])

    def write(self, path: str, data: bytes, offset: int, fh: Any) -> int:
        current = bytearray(self.store.read(path))
        if offset > len(current):
            current.extend(b"\0" * (offset - len(current)))
        current[offset : offset + len(data)] = data
        self.store.write(path, bytes(current), self.store.stat(path)["mode"])
        return len(data)

    def unlink(self, path: str) -> None:
        try:
            self.store.delete(path)
        except FileNotFoundError as error:
            raise FuseOSError(errno.ENOENT) from error


def mount(store_root: str, mountpoint: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
    if FUSE is None:
        raise RuntimeError("fusepy is not installed; install dedupfs[fuse]")
    with DedupStore(store_root, chunk_size) as store:
        FUSE(DedupFuse(store), mountpoint, foreground=True)
