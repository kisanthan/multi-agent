"""DMS mock: ELO (process B only, tamper-evident archiving).

`POST /archive` files a document and returns an immutable archive ID.
"Tamper-evident" means concretely: a filing that has already been assigned
cannot be overwritten, and the document hash decides identity -- filing the
same document twice returns the same ID instead of creating a duplicate.

Start:  uvicorn mocks.elo:app --port 8002
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config
from data.bootstrap import ensure_configured_runtime
from governance.audit import CaseReference, Decision, log_entry

app = FastAPI(title="ELO-Mock (DMS)", version="1.0")


def _con() -> sqlite3.Connection:
    ensure_configured_runtime()
    return sqlite3.connect(config.DB_PATH)


class Filing(BaseModel):
    filename: str
    document_hash: str = Field(min_length=64, max_length=64,
                               description="SHA-256 des Rohdokuments")
    actor: str
    case_id: str | None = Field(
        default=None, description="Vorgang, zu dem die Ablage gehoert")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "elo-mock"}


@app.post("/archive")
def archive(a: Filing) -> dict:
    """Files a document tamper-evidently and returns the archive ID."""
    con = _con()
    reference = CaseReference(a.case_id, a.filename)
    try:
        existing = con.execute(
            "SELECT archive_id FROM archive WHERE document_hash = ?", (a.document_hash,)
        ).fetchone()
        if existing:
            # Idempotent: identical document -> existing ID. Not an error,
            # but no second filing either.
            log_entry(con, actor=a.actor, agent="elo", action="dokument_archivieren",
                      decision=Decision.INFO,
                      reason=f"ELO: Dokument bereits abgelegt unter "
                             f"{existing[0]}.",
                      payload={"archive_id": existing[0], "filename": a.filename},
                      reference=reference, outcome="bereits archiviert")
            con.commit()
            return {"archive_id": existing[0], "already_existed": True}

        aid = f"ELO-{uuid.uuid4().hex[:12].upper()}"
        con.execute(
            "INSERT INTO archive VALUES (?,?,?,?)",
            (aid, a.filename, a.document_hash, datetime.now(timezone.utc).isoformat()),
        )
        log_entry(con, actor=a.actor, agent="elo", action="dokument_archivieren",
                  decision=Decision.ALLOWED,
                  reason=f"ELO: {a.filename} revisionssicher abgelegt.",
                  payload={"archive_id": aid, "filename": a.filename,
                           "document_hash": a.document_hash},
                  reference=reference, outcome="archiviert")
        con.commit()
        return {"archive_id": aid, "already_existed": False}
    finally:
        con.close()


@app.get("/archive/{archive_id}")
def read_filing(archive_id: str) -> dict:
    """Read-only lookup. There is deliberately no PUT/DELETE -- that is the
    essence of 'tamper-evident'."""
    con = _con()
    try:
        row = con.execute(
            "SELECT archive_id, filename, document_hash, filed_at FROM archive "
            "WHERE archive_id = ?", (archive_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Archiv-ID {archive_id} nicht gefunden")
        return {"archive_id": row[0], "filename": row[1], "document_hash": row[2],
                "filed_at": row[3]}
    finally:
        con.close()
