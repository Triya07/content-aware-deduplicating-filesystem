from __future__ import annotations

from collections.abc import Iterator

DEFAULT_CHUNK_SIZE = 4096


def split_chunks(data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
    """Yield fixed-size chunks, including a final partial chunk."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    for offset in range(0, len(data), chunk_size):
        yield data[offset : offset + chunk_size]
