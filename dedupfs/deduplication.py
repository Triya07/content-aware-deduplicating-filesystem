from __future__ import annotations

import os
import tempfile
from pathlib import Path


class ChunkRepository:
    """Crash-safe content-addressed storage for unique chunks."""

    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        return self.directory / digest[:2] / digest[2:]

    def put_if_missing(self, digest: str, data: bytes) -> None:
        destination = self.path_for(digest)
        if destination.exists():
            return
        destination.parent.mkdir(exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".chunk-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.replace(temporary_name, destination)
            except FileExistsError:
                pass
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def get(self, digest: str) -> bytes:
        return self.path_for(digest).read_bytes()

    def remove(self, digest: str) -> None:
        self.path_for(digest).unlink(missing_ok=True)
