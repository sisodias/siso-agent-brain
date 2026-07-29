#!/usr/bin/env python3
"""
spine_merge.py — idempotent union merge of SOURCE spine DB into TARGET spine DB.

Usage:
  python3 spine_merge.py --source /path/to/source.db --target /path/to/target.db [--apply]

Defaults to --dry-run (prints per-table would-insert counts). Pass --apply to write.

Design:
  - INSERT OR IGNORE by PK for the explicit durable-data allowlist.
  - Content-hash dedup for `memories`: skip source row if SHA256(content) already in target.
  - Schema guard: refuses if user_version differs AND is non-zero on both sides.
  - Integrity check before + after (--apply only).
  - Uses explicit column lists — never SELECT * — so extra columns on either side are safe.
  - Single connection per DB, WAL mode, PRAGMA busy_timeout=10000.
  - Allowlisted durable tables: tasks, memories, timeline_events, cost_events,
    and challenges. Runtime flags, fleet state, inboxes, questions, divisions,
    units, migration records, and unknown extension tables never merge.

stdlib only. Python 3.9+.
"""
import argparse
import hashlib
import sqlite3
import sys
from typing import Optional

MERGE_TABLES = frozenset({"tasks", "memories", "timeline_events", "cost_events", "challenges"})

# Tables with content-hash dedup (skip source row if hash of dedup_col already in target)
CONTENT_DEDUP = {
    "memories": "content",
}


def _open(path: str, readonly: bool = False) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro" if readonly else f"file:{path}"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    if not readonly:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    return con


def _tables(con: sqlite3.Connection) -> list[str]:
    return [
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def _integrity_check(con: sqlite3.Connection) -> bool:
    result = con.execute("PRAGMA integrity_check").fetchone()[0]
    return result == "ok"


def _user_version(con: sqlite3.Connection) -> int:
    return con.execute("PRAGMA user_version").fetchone()[0]


def _content_hash(value: Optional[str]) -> str:
    if value is None:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _build_target_content_hashes(tgt_con: sqlite3.Connection, table: str, col: str) -> set:
    """Return set of SHA256 hashes of all existing values of `col` in target table."""
    hashes = set()
    for (val,) in tgt_con.execute(f'SELECT "{col}" FROM "{table}"'):
        hashes.add(_content_hash(val))
    return hashes


def merge(
    source_path: str,
    target_path: str,
    apply: bool,
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Core merge logic. Returns per-table stats dict:
      { table_name: { "would_insert": int, "skipped_pk": int, "skipped_dedup": int } }
    """
    src = _open(source_path, readonly=True)
    tgt = _open(target_path, readonly=False)

    # Schema version guard: refuse if both sides have non-zero user_version and they differ.
    src_ver = _user_version(src)
    tgt_ver = _user_version(tgt)
    if src_ver != 0 and tgt_ver != 0 and src_ver != tgt_ver:
        src.close()
        tgt.close()
        raise SystemExit(
            f"ABORT: user_version mismatch — source={src_ver}, target={tgt_ver}. "
            "Run migrations to align schemas before merging."
        )

    if verbose:
        print(f"Source user_version={src_ver}  Target user_version={tgt_ver}")

    # Integrity check on target before any writes
    if not _integrity_check(tgt):
        src.close()
        tgt.close()
        raise SystemExit("ABORT: target DB failed integrity_check BEFORE merge. Do not proceed.")

    src_tables = set(_tables(src))
    tgt_tables = set(_tables(tgt))
    shared_tables = sorted((src_tables & tgt_tables) & MERGE_TABLES)

    if verbose:
        source_only = sorted((src_tables - tgt_tables) & MERGE_TABLES)
        target_only = sorted((tgt_tables - src_tables) & MERGE_TABLES)
        print(f"\nShared tables (will merge): {len(shared_tables)}")
        print(f"Allowlisted source-only tables (skip): {source_only}")
        print(f"Allowlisted target-only tables (skip): {target_only}")
        print(f"All non-allowlisted tables are excluded: {sorted((src_tables | tgt_tables) - MERGE_TABLES)}")
        print()

    stats = {}

    for table in shared_tables:
        src_cols = _columns(src, table)
        tgt_cols = _columns(tgt, table)

        # Use intersection of columns — so extra columns on either side are safely ignored.
        shared_cols = [c for c in src_cols if c in tgt_cols]
        if not shared_cols:
            if verbose:
                print(f"  {table}: no shared columns — skip")
            continue

        col_list = ", ".join(f'"{c}"' for c in shared_cols)
        pk_cols = ["id"]
        # Verify PK column(s) exist in shared columns
        missing_pks = [p for p in pk_cols if p not in shared_cols]
        if missing_pks:
            if verbose:
                print(f"  {table}: PK column(s) {missing_pks} not in shared cols — skip")
            stats[table] = {"would_insert": 0, "skipped_pk": 0, "skipped_dedup": 0, "skipped_missing_pk": True}
            continue

        # Load source rows
        src_rows = src.execute(
            f'SELECT {col_list} FROM "{table}"'
        ).fetchall()

        if not src_rows:
            if verbose:
                print(f"  {table}: 0 source rows — skip")
            stats[table] = {"would_insert": 0, "skipped_pk": 0, "skipped_dedup": 0}
            continue

        # Build set of existing PKs in target for fast lookup
        pk_clause = ", ".join(f'"{p}"' for p in pk_cols)
        existing_pks = set(
            tuple(r) if len(pk_cols) > 1 else r[0]
            for r in tgt.execute(f'SELECT {pk_clause} FROM "{table}"')
        )

        # Content-hash dedup (for memories + lessons)
        dedup_col = CONTENT_DEDUP.get(table)
        existing_hashes: set = set()
        dedup_col_idx = None
        if dedup_col and dedup_col in shared_cols:
            existing_hashes = _build_target_content_hashes(tgt, table, dedup_col)
            dedup_col_idx = shared_cols.index(dedup_col)

        would_insert = 0
        skipped_pk = 0
        skipped_dedup = 0
        rows_to_insert = []

        for row in src_rows:
            # Check PK collision
            if len(pk_cols) == 1:
                pk_val = row[shared_cols.index(pk_cols[0])]
                pk_key = pk_val
            else:
                pk_key = tuple(row[shared_cols.index(p)] for p in pk_cols)

            if pk_key in existing_pks:
                skipped_pk += 1
                continue

            # Content-hash dedup
            if dedup_col_idx is not None:
                h = _content_hash(row[dedup_col_idx])
                if h in existing_hashes:
                    skipped_dedup += 1
                    continue

            rows_to_insert.append(tuple(row))
            would_insert += 1

        stats[table] = {
            "would_insert": would_insert,
            "skipped_pk": skipped_pk,
            "skipped_dedup": skipped_dedup,
        }

        if verbose:
            print(
                f"  {table:35s}: +{would_insert:7d} rows  "
                f"(pk_dup={skipped_pk}, content_dup={skipped_dedup})"
            )

        if apply and rows_to_insert:
            placeholders = ", ".join("?" for _ in shared_cols)
            insert_sql = (
                f'INSERT OR IGNORE INTO "{table}" ({col_list}) VALUES ({placeholders})'
            )
            tgt.executemany(insert_sql, rows_to_insert)
            tgt.commit()

    if apply:
        # Integrity check after writes
        if verbose:
            print("\nRunning post-merge integrity_check...")
        if not _integrity_check(tgt):
            raise SystemExit(
                "ABORT: target DB failed integrity_check AFTER merge. "
                "Manual inspection required — do not proceed."
            )
        if verbose:
            print("integrity_check: ok")

    src.close()
    tgt.close()
    return stats


def main():
    p = argparse.ArgumentParser(description="Idempotent union-merge of SOURCE spine DB into TARGET.")
    p.add_argument("--source", required=True, help="Path to source DB (read-only)")
    p.add_argument("--target", required=True, help="Path to target DB (will be modified if --apply)")
    p.add_argument("--apply", action="store_true", default=False,
                   help="Actually write changes. Default is dry-run (print only).")
    p.add_argument("--quiet", action="store_true", default=False,
                   help="Suppress per-table output; print only summary.")
    args = p.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    if not args.quiet:
        print(f"\n{'='*60}")
        print(f"spine_merge.py  [{mode}]")
        print(f"  source: {args.source}")
        print(f"  target: {args.target}")
        print(f"{'='*60}\n")

    stats = merge(args.source, args.target, apply=args.apply, verbose=not args.quiet)

    total_insert = sum(v["would_insert"] for v in stats.values())
    total_pk_dup = sum(v["skipped_pk"] for v in stats.values())
    total_dedup = sum(v["skipped_dedup"] for v in stats.values())

    verb = "inserted" if args.apply else "would-insert"
    print(f"\nSUMMARY [{mode}]: {verb}={total_insert}  pk_dup={total_pk_dup}  content_dup={total_dedup}")

    if args.apply and total_insert == 0:
        print("(idempotent: 0 new rows — already in sync)")


if __name__ == "__main__":
    main()
