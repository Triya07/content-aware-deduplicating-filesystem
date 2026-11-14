# DedupFS

DedupFS is a content-aware filesystem prototype. It splits each file into fixed-size 4096-byte chunks by default, hashes every chunk with SHA-256, and stores each unique chunk once under `chunks/`. SQLite metadata maps a virtual filename to its ordered chunk hashes and tracks a reference count for every stored chunk.

When a file is replaced, the new chunks are written first. The metadata transaction then adds references to the new chunks and releases references to the old chunks. A chunk is physically removed only when its reference count reaches zero, so deleting or modifying one file cannot corrupt another file that shares the same data.

## Project layout

The implementation is split into the requested responsibilities:

- `dedupfs/chunking.py` - fixed-size chunking
- `dedupfs/hashing.py` - SHA-256 fingerprints
- `dedupfs/deduplication.py` - content-addressed physical chunk storage
- `dedupfs/metadata.py` - SQLite schema
- `dedupfs/reference_counter.py` - safe increment/decrement operations
- `dedupfs/storage.py` - integrated storage engine
- `dedupfs/fuse_mount.py` - FUSE filesystem adapter
- `tests/` - unit and integration tests

## Run the tests on Ubuntu

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,fuse]'
python -m pytest
```

Install the Linux FUSE packages first:

```bash
sudo apt update
sudo apt install -y fuse3
```

## Mount the filesystem

Create a mount point and start the filesystem:

```bash
mkdir -p storage mountpoint
dedupfs --store ./storage --chunk-size 4096 mount ./mountpoint
```

Then use it like a normal directory:

```bash
echo 'Hello World! This is our project.' > mountpoint/file1.txt
cp mountpoint/file1.txt mountpoint/file2.txt
cat mountpoint/file2.txt
```

Unmount it with:

```bash
fusermount3 -u mountpoint
```

Run an integrity check with:

```bash
dedupfs --store ./storage fsck
```

## Run the demonstration dashboard

Install the API dependencies in the existing virtual environment:

```bash
python -m pip install -e '.[api,fuse,test]'
```

Start the FUSE filesystem in terminal 1:

```bash
mkdir -p storage mountpoint
dedupfs --store ./storage mount ./mountpoint
```

Start the API in terminal 2:

```bash
DEDUPFS_STORE=./storage DEDUPFS_MOUNTPOINT=./mountpoint DEDUPFS_CHUNK_SIZE=4096 \
  uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Install and start the React dashboard in terminal 3:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in terminal 3, normally `http://localhost:5173`.
The FUSE process owns the mounted filesystem independently; the API uses the
same storage root and SQLite metadata for management and analytics.
