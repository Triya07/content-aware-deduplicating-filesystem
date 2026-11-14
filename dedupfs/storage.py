from __future__ import annotations

import os
import sqlite3
from pathlib import Path, PurePosixPath

from .chunking import DEFAULT_CHUNK_SIZE, split_chunks
from .deduplication import ChunkRepository
from .hashing import sha256
from .metadata import SCHEMA
from .reference_counter import decrement, increment


class DedupStore:
    """Persistent chunk store and filename-to-chunk metadata database.

    Files are split into fixed-size chunks. The SHA-256 digest is the chunk
    identity, so equal chunks are stored once regardless of which file uses
    them. Metadata updates are committed in one SQLite transaction.
    """

    def __init__(self, root: str | os.PathLike[str], chunk_size: int = DEFAULT_CHUNK_SIZE):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.root = Path(root)
        self.chunks_dir = self.root / "chunks"
        self.database_path = self.root / "metadata.sqlite3"
        self.chunk_size = chunk_size
        self.root.mkdir(parents=True, exist_ok=True)
        self._chunks = ChunkRepository(self.chunks_dir)
        self._connection = sqlite3.connect(self.root / "metadata.sqlite3" , check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_database()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DedupStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize_database(self) -> None:
        self._connection.executescript(
            SCHEMA
        )
        self._connection.commit()

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path or not path.startswith("/"):
            raise ValueError("filesystem paths must start with '/'")
        normalized = str(PurePosixPath(path))
        if normalized == "/":
            raise IsADirectoryError(path)
        if normalized.startswith("/.dedupfs/") or normalized == "/.dedupfs":
            raise PermissionError("internal paths are reserved")
        return normalized

    def read(self, path: str) -> bytes:
        normalized = self._normalize_path(path)
        row = self._connection.execute(
            "SELECT path FROM files WHERE path = ?", (normalized,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError(path)
        chunks = self._connection.execute(
            "SELECT digest FROM file_chunks WHERE path = ? ORDER BY position",
            (normalized,),
        )
        return b"".join(self._chunks.get(row["digest"]) for row in chunks)

    def stat(self, path: str) -> sqlite3.Row:
        normalized = self._normalize_path(path)
        row = self._connection.execute(
            "SELECT size, mode FROM files WHERE path = ?", (normalized,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError(path)
        return row

    def is_directory(self, path: str) -> bool:
        if path == "/":
            return True
        prefix = path.rstrip("/") + "/"
        return self._connection.execute(
            "SELECT 1 FROM files WHERE path LIKE ? LIMIT 1", (prefix + "%",)
        ).fetchone() is not None

    def children(self, path: str) -> list[str]:
        if not self.is_directory(path):
            raise FileNotFoundError(path)
        prefix = "/" if path == "/" else path.rstrip("/") + "/"
        rows = self._connection.execute(
            "SELECT path FROM files WHERE path LIKE ? ORDER BY path",
            (prefix + "%",),
        ).fetchall()
        names = {row["path"][len(prefix) :].split("/", 1)[0] for row in rows}
        return sorted(names)

    def exists(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        return (
            self._connection.execute(
                "SELECT 1 FROM files WHERE path = ?", (normalized,)
            ).fetchone()
            is not None
        )

    def write(self, path: str, data: bytes, mode: int = 0o644) -> None:
        normalized = self._normalize_path(path)
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        chunks = [(sha256(chunk), chunk) for chunk in split_chunks(data, self.chunk_size)]
        existing_digests = {
            row["digest"]
            for row in self._connection.execute("SELECT digest FROM chunks")
        }
        for digest, chunk in chunks:
            self._chunks.put_if_missing(digest, chunk)

        with self._connection:
            old = self._connection.execute(
                "SELECT digest FROM file_chunks WHERE path = ?", (normalized,)
            ).fetchall()
            self._connection.execute("DELETE FROM files WHERE path = ?", (normalized,))
            self._connection.execute(
                "INSERT INTO files(path, size, mode) VALUES (?, ?, ?)",
                (normalized, len(data), mode & 0o7777),
            )
            for position, (digest, chunk) in enumerate(chunks):
                self._connection.execute(
                    "INSERT INTO file_chunks(path, position, digest) VALUES (?, ?, ?)",
                    (normalized, position, digest),
                )
                increment(self._connection, digest, len(chunk))
            self._record_activity(
                "file_written",
                f"File {'replaced' if old else 'uploaded'}: {normalized}",
                path=normalized,
            )
            self._record_activity(
                "chunks_generated",
                f"Generated {len(chunks)} chunk(s) for {normalized}",
                path=normalized,
            )
            for digest, chunk in chunks:
                reused = digest in existing_digests
                self._record_activity(
                    "hash_generated",
                    f"SHA-256 hash generated for chunk {digest[:12]}",
                    path=normalized,
                    digest=digest,
                )
                self._record_activity(
                    "duplicate_chunk_detected" if reused else "new_chunk_stored",
                    (
                        f"Duplicate chunk detected and reused for {normalized}"
                        if reused
                        else f"New chunk stored for {normalized}"
                    ),
                    path=normalized,
                    digest=digest,
                )
                self._record_activity(
                    "reference_count_increased",
                    f"Reference count increased for chunk {digest[:12]}",
                    path=normalized,
                    digest=digest,
                )
                existing_digests.add(digest)
            for row in old:
                self._decrement_chunk(row["digest"])

    def delete(self, path: str) -> None:
        normalized = self._normalize_path(path)
        old = self._connection.execute(
            "SELECT digest FROM file_chunks WHERE path = ?", (normalized,)
        ).fetchall()
        if not self.exists(normalized):
            raise FileNotFoundError(path)
        with self._connection:
            self._connection.execute("DELETE FROM files WHERE path = ?", (normalized,))
            self._record_activity(
                "file_deleted", f"File deleted: {normalized}", path=normalized
            )
            for row in old:
                digest = row["digest"]
                became_unused = self._decrement_chunk(digest)
                self._record_activity(
                    "unused_chunk_removed" if became_unused else "reference_count_decreased",
                    (
                        f"Unused chunk removed: {digest[:12]}"
                        if became_unused
                        else f"Reference count decreased for chunk {digest[:12]}"
                    ),
                    path=normalized,
                    digest=digest,
                )

    def _decrement_chunk(self, digest: str) -> bool:
        if decrement(self._connection, digest):
            self._chunks.remove(digest)
            return True
        return False

    def _record_activity(
        self,
        event_type: str,
        message: str,
        *,
        path: str | None = None,
        digest: str | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO activities(event_type, message, path, digest)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, message, path, digest),
        )

    def list_activities(self, limit: int = 100) -> list[sqlite3.Row]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return self._connection.execute(
            """
            SELECT id, event_type, message, path, digest, created_at
            FROM activities
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def list_files(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT path FROM files ORDER BY path"
        ).fetchall()
        return [row["path"] for row in rows]

    def chunk_refcount(self, digest: str) -> int:
        row = self._connection.execute(
            "SELECT ref_count FROM chunks WHERE digest = ?", (digest,)
        ).fetchone()
        return 0 if row is None else int(row["ref_count"])

    def fsck(self) -> list[str]:
        """Return metadata/storage inconsistencies without modifying anything."""
        errors: list[str] = []
        rows = self._connection.execute("SELECT digest, ref_count FROM chunks")
        for row in rows:
            path = self._chunks.path_for(row["digest"])
            if not path.is_file():
                errors.append(f"missing chunk {row['digest']}")
        referenced = self._connection.execute(
            "SELECT digest, COUNT(*) AS count FROM file_chunks GROUP BY digest"
        )
        for row in referenced:
            if self.chunk_refcount(row["digest"]) != row["count"]:
                errors.append(f"incorrect refcount {row['digest']}")
        return errors
