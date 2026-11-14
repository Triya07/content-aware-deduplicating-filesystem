import hashlib


def sha256(data: bytes) -> str:
    """Return the hexadecimal SHA-256 digest for a chunk."""
    return hashlib.sha256(data).hexdigest()
