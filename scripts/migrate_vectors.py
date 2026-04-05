#!/usr/bin/env python3
"""
Migrate existing SQLite data into the Qdrant vector store.

Usage:
    python scripts/migrate_vectors.py          # full reindex
    python scripts/migrate_vectors.py --check  # show counts, don't rebuild

Idempotent — safe to re-run. Drops and recreates both collections.
"""

import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import db  # noqa: E402


def main():
    check_only = "--check" in sys.argv

    print("Initializing databases...")
    db.init_databases()

    if check_only:
        _show_counts()
        return

    print("\nReindexing all concepts and topics into the vector store...")
    print("(This will download the embedding model on first run — ~420MB)\n")

    start = time.time()
    from db.vectors import reindex_all

    result = reindex_all()
    elapsed = time.time() - start

    print(f"\n✅ Reindex complete in {elapsed:.1f}s")
    print(f"   Concepts indexed: {result['concepts']}")
    print(f"   Topics indexed:   {result['topics']}")

    _show_counts()


def _show_counts():
    """Show current vector store collection counts."""
    try:
        from db.vectors import CONCEPTS_COLLECTION, TOPICS_COLLECTION, get_collection_count

        print("\nVector store status:")
        print(f"  concepts collection: {get_collection_count(CONCEPTS_COLLECTION)} points")
        print(f"  topics collection:   {get_collection_count(TOPICS_COLLECTION)} points")
    except Exception as e:
        print(f"\n⚠ Could not read vector store: {e}")

    from db.core import _conn

    conn = _conn()
    c_count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    t_count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    conn.close()
    print("\nSQLite status:")
    print(f"  concepts: {c_count}")
    print(f"  topics:   {t_count}")


if __name__ == "__main__":
    main()
