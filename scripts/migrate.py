#!/usr/bin/env python3
"""Apply immutable SISO Agent Brain SQL migrations."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path.home() / ".local/share/siso-agent-brain/brain.db"


def migrate(database: Path) -> list[str]:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, digest TEXT NOT NULL, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    applied: list[str] = []
    try:
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode()).hexdigest()
            row = connection.execute("SELECT digest FROM schema_migrations WHERE name=?", (path.name,)).fetchone()
            if row:
                if row[0] != digest:
                    raise RuntimeError(f"applied migration changed: {path.name}")
                continue
            connection.executescript(sql)
            connection.execute("INSERT INTO schema_migrations(name,digest) VALUES(?,?)", (path.name, digest))
            connection.commit()
            applied.append(path.name)
    finally:
        connection.close()
    return applied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("SISO_DB", DEFAULT_DB)))
    args = parser.parse_args()
    applied = migrate(args.database.expanduser())
    print(f"MIGRATIONS_OK applied={len(applied)} database={args.database.expanduser()}")


if __name__ == "__main__":
    main()
