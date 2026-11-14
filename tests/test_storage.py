from dedupfs.storage import DedupStore
from dedupfs.chunking import split_chunks
from dedupfs.hashing import sha256


def test_chunking_and_hashing():
    chunks = list(split_chunks(b"Hello World! This is our project.", 12))
    assert chunks == [b"Hello World!", b" This is our", b" project."]
    assert sha256(chunks[0]) == (
        "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
    )


def test_identical_chunks_are_stored_once(tmp_path):
    with DedupStore(tmp_path, chunk_size=4) as store:
        store.write("/first", b"abcdefgh")
        store.write("/second", b"abcdefgh")

        assert store.read("/first") == b"abcdefgh"
        digests = store._connection.execute(
            "SELECT digest, ref_count FROM chunks ORDER BY digest"
        ).fetchall()
        assert len(digests) == 2
        assert all(row["ref_count"] == 2 for row in digests)
        assert store.fsck() == []


def test_replace_and_delete_release_old_chunks(tmp_path):
    with DedupStore(tmp_path, chunk_size=4) as store:
        store.write("/file", b"aaaaBBBB")
        old_digests = [
            row["digest"]
            for row in store._connection.execute(
                "SELECT digest FROM file_chunks WHERE path = '/file'"
            )
        ]
        store.write("/file", b"ccccDDDD")
        assert all(store.chunk_refcount(digest) == 0 for digest in old_digests)
        assert store.read("/file") == b"ccccDDDD"
        store.delete("/file")
        assert store.list_files() == []
        assert store.fsck() == []


def test_sparse_write_preserves_existing_bytes(tmp_path):
    with DedupStore(tmp_path, chunk_size=4) as store:
        store.write("/file", b"hello")
        data = bytearray(store.read("/file"))
        data[1:4] = b"XYZ"
        store.write("/file", bytes(data))
        assert store.read("/file") == b"hXYZo"


def test_nested_virtual_directories(tmp_path):
    with DedupStore(tmp_path, chunk_size=4) as store:
        store.write("/docs/project/file.txt", b"content")
        assert store.is_directory("/docs")
        assert store.children("/") == ["docs"]
        assert store.children("/docs/project") == ["file.txt"]


def test_aligned_partial_files_have_real_chunk_level_deduplication(tmp_path):
    shared_a = b"A" * 4096
    unique_b = b"B" * 4096
    shared_c = b"C" * 4096
    unique_d = b"D" * 4096

    with DedupStore(tmp_path, chunk_size=4096) as store:
        store.write("/05_partial_B.bin", shared_a + unique_b + shared_c)
        store.write("/06_partial_C.bin", shared_a + unique_d + shared_c)

        file_rows = store._connection.execute(
            "SELECT path, size FROM files ORDER BY path"
        ).fetchall()
        chunk_references = store._connection.execute(
            "SELECT digest, COUNT(*) AS count FROM file_chunks GROUP BY digest"
        ).fetchall()
        chunk_rows = store._connection.execute(
            "SELECT size, ref_count FROM chunks"
        ).fetchall()

        assert [row["size"] for row in file_rows] == [12288, 12288]
        assert sum(row["count"] for row in chunk_references) == 6
        assert len(chunk_rows) == 4
        assert sum(row["ref_count"] > 1 for row in chunk_rows) == 2
        assert sum(row["ref_count"] - 1 for row in chunk_rows) == 2
        assert sum(row["ref_count"] for row in chunk_rows) == 6
        assert sum(row["size"] for row in chunk_rows) == 16384
