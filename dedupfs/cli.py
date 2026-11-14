from __future__ import annotations

import argparse

from .chunking import DEFAULT_CHUNK_SIZE
from .fuse_mount import mount
from .storage import DedupStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Content-aware deduplicating filesystem")
    parser.add_argument("--store", required=True, help="directory for chunks and metadata")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    mount_parser = subparsers.add_parser("mount")
    mount_parser.add_argument("mountpoint")
    subparsers.add_parser("fsck")
    args = parser.parse_args()
    if args.command == "mount":
        mount(args.store, args.mountpoint, args.chunk_size)
    else:
        with DedupStore(args.store, args.chunk_size) as store:
            errors = store.fsck()
            if errors:
                parser.error("\n".join(errors))


if __name__ == "__main__":
    main()
