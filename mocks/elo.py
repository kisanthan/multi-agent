"""DMS-Mock: ELO (nur Prozess B, revisionssichere Archivierung).

`POST /archive` legt ein Dokument ab und gibt eine unveraenderliche Archiv-ID
zurueck. "Revisionssicher" heisst hier konkret: eine bereits vergebene Ablage
laesst sich nicht ueberschreiben, und der Dokument-Hash entscheidet ueber die
Identitaet -- dasselbe Dokument zweimal abzulegen liefert dieselbe ID zurueck,
statt eine Dublette anzulegen.

Start:  uvicorn mocks.elo:app --port 8002
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import DB_PFAD
from governance.audit import Entscheidung, protokolliere

app = FastAPI(title="ELO-Mock (DMS)", version="1.0")


def _con() -> sqlite3.Connection:
    return sqlite3.connect(DB_PFAD)


class Ablage(BaseModel):
    dateiname: str
    dokument_hash: str = Field(min_length=64, max_length=64,
                               description="SHA-256 des Rohdokuments")
    akteur: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "elo-mock"}


@app.post("/archive")
def archiviere(a: Ablage) -> dict:
    """Legt ein Dokument revisionssicher ab und liefert die Archiv-ID."""
    con = _con()
    try:
        vorhanden = con.execute(
            "SELECT archiv_id FROM archiv WHERE dokument_hash = ?", (a.dokument_hash,)
        ).fetchone()
        if vorhanden:
            # Idempotent: identisches Dokument -> bestehende ID. Kein Fehler,
            # aber auch keine zweite Ablage.
            protokolliere(con, akteur=a.akteur, agent="elo", aktion="dokument_archivieren",
                          entscheidung=Entscheidung.INFO,
                          begruendung=f"ELO: Dokument bereits abgelegt unter "
                                      f"{vorhanden[0]}.",
                          payload={"archiv_id": vorhanden[0], "dateiname": a.dateiname})
            con.commit()
            return {"archiv_id": vorhanden[0], "bereits_vorhanden": True}

        aid = f"ELO-{uuid.uuid4().hex[:12].upper()}"
        con.execute(
            "INSERT INTO archiv VALUES (?,?,?,?)",
            (aid, a.dateiname, a.dokument_hash, datetime.now(timezone.utc).isoformat()),
        )
        protokolliere(con, akteur=a.akteur, agent="elo", aktion="dokument_archivieren",
                      entscheidung=Entscheidung.ERLAUBT,
                      begruendung=f"ELO: {a.dateiname} revisionssicher abgelegt.",
                      payload={"archiv_id": aid, "dateiname": a.dateiname,
                               "dokument_hash": a.dokument_hash})
        con.commit()
        return {"archiv_id": aid, "bereits_vorhanden": False}
    finally:
        con.close()


@app.get("/archive/{archiv_id}")
def lies_ablage(archiv_id: str) -> dict:
    """Read-only-Abruf. Es gibt bewusst kein PUT/DELETE -- das ist der Kern
    von 'revisionssicher'."""
    con = _con()
    try:
        row = con.execute(
            "SELECT archiv_id, dateiname, dokument_hash, abgelegt_am FROM archiv "
            "WHERE archiv_id = ?", (archiv_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Archiv-ID {archiv_id} nicht gefunden")
        return {"archiv_id": row[0], "dateiname": row[1], "dokument_hash": row[2],
                "abgelegt_am": row[3]}
    finally:
        con.close()
