"""Additive, transactional migration; no recreation of historical evidence."""
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

VERSION = 2


def migrate(con: sqlite3.Connection) -> None:
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='control_versions'").fetchone()
    if exists and con.execute("SELECT 1 FROM control_versions WHERE version=?", (VERSION,)).fetchone():
        return
    if con.in_transaction:
        raise RuntimeError("Migration requires a clean connection.")
    script = Path(__file__).with_name("control_schema.sql").read_text(encoding="utf-8")
    try:
        con.executescript("BEGIN IMMEDIATE;\n" + script)
        con.execute("INSERT OR IGNORE INTO control_versions VALUES (?,?)",
                    (VERSION, datetime.now(timezone.utc).isoformat()))
        con.commit()
    except BaseException:
        con.rollback()
        raise


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(database: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(database, timeout=30, factory=ManagedConnection)
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con)
    return con
