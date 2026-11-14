from __future__ import annotations

import sqlite3


def increment(connection: sqlite3.Connection, digest: str, size: int) -> None:
    connection.execute(
        """
        INSERT INTO chunks(digest, size, ref_count) VALUES (?, ?, 1)
        ON CONFLICT(digest) DO UPDATE SET ref_count = ref_count + 1
        """,
        (digest, size),
    )


def decrement(connection: sqlite3.Connection, digest: str) -> bool:
    """Release one reference and return whether the chunk became unused."""
    row = connection.execute(
        "SELECT ref_count FROM chunks WHERE digest = ?", (digest,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"missing metadata for chunk {digest}")
    if row["ref_count"] == 1:
        connection.execute("DELETE FROM chunks WHERE digest = ?", (digest,))
        return True
    connection.execute(
        "UPDATE chunks SET ref_count = ref_count - 1 WHERE digest = ?", (digest,)
    )
    return False
