from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Iterator

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from dedupfs.chunking import DEFAULT_CHUNK_SIZE
from dedupfs.storage import DedupStore

STORE_ROOT = os.environ.get("DEDUPFS_STORE", "storage")
MOUNTPOINT = os.environ.get("DEDUPFS_MOUNTPOINT", "mountpoint")
CHUNK_SIZE = int(os.environ.get("DEDUPFS_CHUNK_SIZE", str(DEFAULT_CHUNK_SIZE)))

app = FastAPI(
    title="Content-Aware Deduplicating Filesystem API",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("DEDUPFS_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

store = DedupStore(STORE_ROOT, CHUNK_SIZE)
write_lock = threading.RLock()


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(store.database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def safe_filename(filename: str) -> str:
    if not filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="A valid filename is required")
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Directory paths are not allowed")
    if filename.startswith(".dedupfs"):
        raise HTTPException(status_code=400, detail="Reserved filenames are not allowed")
    return str(PurePosixPath("/" + filename))


def file_payload(row: sqlite3.Row, chunk_count: int) -> dict[str, object]:
    return {
        "filename": row["path"].lstrip("/"),
        "path": row["path"],
        "size": row["size"],
        "mode": row["mode"],
        "chunk_count": chunk_count,
    }


def storage_stats(connection: sqlite3.Connection) -> dict[str, object]:
    files = connection.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS logical_size FROM files"
    ).fetchone()
    chunks = connection.execute(
        """
        SELECT COUNT(*) AS count,
               COALESCE(SUM(size), 0) AS physical_size,
               COALESCE(SUM(CASE WHEN ref_count > 1 THEN 1 ELSE 0 END), 0)
                   AS duplicate_chunks,
               COALESCE(SUM(CASE WHEN ref_count > 1 THEN ref_count - 1 ELSE 0 END), 0)
                   AS duplicate_references,
               COALESCE(SUM(ref_count), 0) AS total_references,
               COALESCE(AVG(ref_count), 0) AS average_references
        FROM chunks
        """
    ).fetchone()
    logical = int(files["logical_size"])
    physical = int(chunks["physical_size"])
    saved = max(logical - physical, 0)
    percentage = (saved / logical * 100) if logical else 0
    return {
        "total_files": int(files["count"]),
        "total_unique_chunks": int(chunks["count"]),
        "logical_storage": logical,
        "physical_storage": physical,
        "storage_saved": saved,
        "deduplication_percentage": round(percentage, 2),
        "duplicate_chunks": int(chunks["duplicate_chunks"]),
        "duplicate_references": int(chunks["duplicate_references"]),
        "total_references": int(chunks["total_references"]),
        "average_references_per_chunk": round(float(chunks["average_references"]), 2),
    }


@app.get("/api/dashboard")
def dashboard() -> dict[str, object]:
    with database() as connection:
        payload = storage_stats(connection)
    payload["filesystem_mounted"] = os.path.ismount(MOUNTPOINT)
    payload["mountpoint_configured"] = MOUNTPOINT
    payload["chunk_size"] = CHUNK_SIZE
    return payload


@app.get("/api/files")
def files() -> list[dict[str, object]]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT f.path, f.size, f.mode, COUNT(fc.digest) AS chunk_count
            FROM files f
            LEFT JOIN file_chunks fc ON fc.path = f.path
            GROUP BY f.path, f.size, f.mode
            ORDER BY f.path
            """
        ).fetchall()
    return [file_payload(row, int(row["chunk_count"])) for row in rows]


@app.post("/api/files/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> dict[str, object]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    results: list[dict[str, object]] = []
    with write_lock:
        for upload in files:
            filename = safe_filename(upload.filename or "")
            try:
                content = await upload.read()
                with DedupStore(STORE_ROOT, CHUNK_SIZE) as upload_store:
                    upload_store.write(filename, content)
                results.append({"filename": filename.lstrip("/"), "size": len(content), "status": "uploaded"})
            except (OSError, ValueError, RuntimeError) as error:
                results.append({"filename": filename.lstrip("/"), "status": "failed", "error": str(error)})
            finally:
                await upload.close()
    return {"files": results}


@app.get("/api/files/{filename:path}/download")
def download_file(filename: str) -> Response:
    path = safe_filename(filename)
    with write_lock:
        try:
            with DedupStore(STORE_ROOT, CHUNK_SIZE) as read_store:
                content = read_store.read(path)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="File not found") from error
    download_name = PurePosixPath(path).name.replace('"', "")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@app.delete("/api/files/{filename:path}")
def delete_file(filename: str) -> dict[str, str]:
    path = safe_filename(filename)
    with write_lock:
        try:
            with DedupStore(STORE_ROOT, CHUNK_SIZE) as delete_store:
                delete_store.delete(path)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="File not found") from error
    return {"filename": filename, "status": "deleted"}


@app.get("/api/chunks")
def chunks() -> list[dict[str, object]]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT c.digest, c.size, c.ref_count,
                   GROUP_CONCAT(REPLACE(f.path, '/', ''), ',') AS files
            FROM chunks c
            LEFT JOIN file_chunks fc ON fc.digest = c.digest
            LEFT JOIN files f ON f.path = fc.path
            GROUP BY c.digest, c.size, c.ref_count
            ORDER BY c.ref_count DESC, c.digest
            """
        ).fetchall()
    return [
        {
            "digest": row["digest"],
            "size": row["size"],
            "reference_count": row["ref_count"],
            "reused": row["ref_count"] > 1,
            "storage_location": f"chunks/{row['digest'][:2]}/{row['digest'][2:]}",
            "files": (row["files"] or "").split(",") if row["files"] else [],
        }
        for row in rows
    ]


@app.get("/api/analytics")
def analytics() -> dict[str, object]:
    with database() as connection:
        stats = storage_stats(connection)
        stats["comparison"] = [
            {"label": "Logical storage", "bytes": stats["logical_storage"]},
            {"label": "Physical storage", "bytes": stats["physical_storage"]},
            {"label": "Storage saved", "bytes": stats["storage_saved"]},
        ]
    return stats


@app.get("/api/reference-counts")
def reference_counts() -> list[dict[str, object]]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT c.digest, c.size, c.ref_count, f.path
            FROM chunks c
            JOIN file_chunks fc ON fc.digest = c.digest
            JOIN files f ON f.path = fc.path
            ORDER BY c.ref_count DESC, c.digest, f.path
            """
        ).fetchall()
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        item = grouped.setdefault(
            row["digest"],
            {
                "digest": row["digest"],
                "size": row["size"],
                "reference_count": row["ref_count"],
                "files": [],
            },
        )
        item["files"].append(row["path"].lstrip("/"))
    return list(grouped.values())


class LabRequest(BaseModel):
    filenames: list[str]


@app.post("/api/lab/analyze")
def lab_analyze(request: LabRequest) -> dict[str, object]:
    if not request.filenames:
        raise HTTPException(status_code=400, detail="Select at least one file")
    paths = [safe_filename(filename) for filename in request.filenames]
    placeholders = ",".join("?" for _ in paths)
    with database() as connection:
        file_rows = connection.execute(
            f"SELECT path, size FROM files WHERE path IN ({placeholders})", paths
        ).fetchall()
        if len(file_rows) != len(paths):
            raise HTTPException(status_code=404, detail="One or more selected files do not exist")
        chunk_rows = connection.execute(
            f"""
            SELECT fc.path, fc.digest, c.size, c.ref_count
            FROM file_chunks fc
            JOIN chunks c ON c.digest = fc.digest
            WHERE fc.path IN ({placeholders})
            """,
            paths,
        ).fetchall()
    logical = sum(int(row["size"]) for row in file_rows)
    unique_chunks = {row["digest"]: row for row in chunk_rows}
    total_chunks = len(chunk_rows)
    duplicate_chunks = total_chunks - len(unique_chunks)
    physical = sum(int(row["size"]) for row in unique_chunks.values())
    return {
        "files": [
            {
                "filename": row["path"].lstrip("/"),
                "size": row["size"],
                "chunk_count": sum(1 for chunk in chunk_rows if chunk["path"] == row["path"]),
            }
            for row in file_rows
        ],
        "total_files_processed": len(file_rows),
        "total_chunks_generated": total_chunks,
        "new_unique_chunks_stored": len(unique_chunks),
        "duplicate_chunks_detected": duplicate_chunks,
        "existing_chunks_reused": sum(1 for row in unique_chunks.values() if row["ref_count"] > 1),
        "total_reference_count": sum(int(row["ref_count"]) for row in unique_chunks.values()),
        "logical_storage": logical,
        "physical_storage": physical,
        "storage_saved": max(logical - physical, 0),
        "chunk_size": CHUNK_SIZE,
    }


class StressRequest(BaseModel):
    scenario: str
    count: int = 5


@app.post("/api/stress-tests")
def stress_test(request: StressRequest) -> dict[str, object]:
    allowed = {"identical", "different", "partial", "shared", "deletion", "modify"}
    if request.scenario not in allowed:
        raise HTTPException(status_code=400, detail="Unknown stress scenario")
    count = min(max(request.count, 2), 50)
    prefix = f"stress-{uuid.uuid4().hex[:10]}"
    paths = [f"/{prefix}-{index}.bin" for index in range(count)]
    common = _stress_block("common-content-block")

    def unique_block(index: int) -> bytes:
        return _stress_block(f"unique-content-block-{index}")

    try:
        with write_lock, DedupStore(STORE_ROOT, CHUNK_SIZE) as test_store:
            contents: dict[str, bytes] = {}
            for index, path in enumerate(paths):
                if request.scenario == "identical":
                    content = common + common
                elif request.scenario == "different":
                    content = unique_block(index) + unique_block(index + count)
                elif request.scenario in {"partial", "shared"}:
                    content = common + unique_block(index)
                else:
                    content = common + unique_block(index)
                contents[path] = content
                test_store.write(path, content)
            before = _stats_from_store(test_store)
            scenario_before = _stress_stats(test_store._connection, paths)
            safety_passed = True
            if request.scenario == "deletion":
                test_store.delete(paths[0])
                safety_passed = test_store.read(paths[1]) == contents[paths[1]]
            elif request.scenario == "modify":
                test_store.write(paths[0], b"modified-content")
                safety_passed = test_store.read(paths[1]) == contents[paths[1]]
            after = _stats_from_store(test_store)
            scenario_after = _stress_stats(test_store._connection, paths)
            for path in paths:
                if test_store.exists(path):
                    test_store.delete(path)
        return {
            "scenario": request.scenario,
            "files_processed": count,
            "passed": safety_passed,
            "before": before,
            "after": after,
            "scenario_before": scenario_before,
            "scenario_after": scenario_after,
        }
    except (OSError, RuntimeError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


def _stats_from_store(current_store: DedupStore) -> dict[str, object]:
    return storage_stats(current_store._connection)


def _stress_block(label: str) -> bytes:
    seed = label.encode()
    return (seed * ((CHUNK_SIZE // len(seed)) + 1))[:CHUNK_SIZE]


def _stress_stats(connection: sqlite3.Connection, paths: list[str]) -> dict[str, int]:
    placeholders = ",".join("?" for _ in paths)
    files = connection.execute(
        f"SELECT COALESCE(SUM(size), 0) AS logical FROM files WHERE path IN ({placeholders})",
        paths,
    ).fetchone()
    chunks = connection.execute(
        f"""
        SELECT fc.digest, COUNT(*) AS occurrences, c.size
        FROM file_chunks fc
        JOIN chunks c ON c.digest = fc.digest
        WHERE fc.path IN ({placeholders})
        GROUP BY fc.digest, c.size
        """,
        paths,
    ).fetchall()
    logical = int(files["logical"])
    references = sum(int(row["occurrences"]) for row in chunks)
    physical = sum(int(row["size"]) for row in chunks)
    return {
        "chunk_references": references,
        "unique_chunks": len(chunks),
        "shared_chunks": sum(row["occurrences"] > 1 for row in chunks),
        "duplicate_occurrences": references - len(chunks),
        "logical_storage": logical,
        "physical_storage": physical,
        "storage_saved": max(logical - physical, 0),
    }


@app.get("/api/activities")
def activities(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, object]]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT id, event_type, message, path, digest, created_at
            FROM activities ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "filesystem_mounted": os.path.ismount(MOUNTPOINT)}
