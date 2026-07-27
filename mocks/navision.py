"""ERP-Mock: Microsoft Dynamics NAV ("Navision").

Bildet die Buchungsschnittstelle nach, die Prozess A braucht:
`POST /booking` (Zahlung verbuchen, Status offen -> bezahlt). Navision wird nach
dem Diagramm Teil 3 nur in Prozess A angesprochen; Prozess B endet bei der
revisionssicheren Archivierung in ELO.

Der Mock ist bewusst *streng*: er prueft fachliche Vorbedingungen selbst und
weist unzulaessige Buchungen ab. Ein Mock, der alles annimmt, wuerde die
Governance-Aussage der Arbeit untergraben -- die Demo saehe erfolgreich aus,
obwohl das Zielsystem in Wirklichkeit abgelehnt haette.

Start:  uvicorn mocks.navision:app --port 8001
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import DB_PFAD
from governance.audit import Entscheidung, protokolliere

app = FastAPI(title="Navision-Mock (Dynamics NAV)", version="1.0")


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PFAD)
    con.execute("PRAGMA foreign_keys = ON")
    return con


class Buchung(BaseModel):
    """Prozess A: Verbuchung einer eingegangenen Zahlung."""

    nummer: str = Field(description="Rechnungs-/Bestellnummer")
    betrag_eur: float = Field(gt=0)
    akteur: str = Field(description="UPN des verantwortlichen Nutzers")
    beleg: str = Field(description="Dateiname der Zahlungsbestaetigung")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "navision-mock"}


@app.post("/booking")
def verbuche_zahlung(b: Buchung) -> dict:
    """Setzt den Status einer offenen Rechnung auf 'bezahlt'.

    Zwei Vorbedingungen werden hier erneut geprueft, obwohl der Abgleich-Agent
    sie bereits geprueft hat: die Nummer muss existieren und darf nicht bereits
    bezahlt sein. Das ist keine Redundanz, sondern die Rolle des Zielsystems --
    es verlaesst sich nicht darauf, dass der Aufrufer sauber gearbeitet hat.
    """
    con = _con()
    try:
        row = con.execute(
            "SELECT status, betrag_eur FROM rechnungen WHERE nummer = ?", (b.nummer,)
        ).fetchone()

        if row is None:
            protokolliere(con, akteur=b.akteur, agent="buchung", aktion="zahlung_verbuchen",
                          entscheidung=Entscheidung.VERWEIGERT,
                          begruendung=f"Navision: Nummer {b.nummer} unbekannt.",
                          payload={"nummer": b.nummer, "beleg": b.beleg})
            con.commit()
            raise HTTPException(404, f"Rechnung {b.nummer} nicht gefunden")

        status, soll_betrag = row
        if status == "bezahlt":
            # Dublettenschutz im Zielsystem (Stoerfall 'dublette').
            protokolliere(con, akteur=b.akteur, agent="buchung", aktion="zahlung_verbuchen",
                          entscheidung=Entscheidung.VERWEIGERT,
                          begruendung=f"Navision: {b.nummer} ist bereits bezahlt.",
                          payload={"nummer": b.nummer, "beleg": b.beleg})
            con.commit()
            raise HTTPException(409, f"Rechnung {b.nummer} ist bereits bezahlt")

        bezahlt_am = datetime.now(timezone.utc).isoformat()
        con.execute(
            "UPDATE rechnungen SET status = 'bezahlt', bezahlt_am = ? WHERE nummer = ?",
            (bezahlt_am, b.nummer),
        )
        protokolliere(con, akteur=b.akteur, agent="buchung", aktion="zahlung_verbuchen",
                      entscheidung=Entscheidung.ERLAUBT,
                      begruendung=f"Navision: {b.nummer} offen -> bezahlt.",
                      payload={"nummer": b.nummer, "betrag_eur": b.betrag_eur,
                               "soll_betrag_eur": soll_betrag, "beleg": b.beleg})
        con.commit()
        return {"nummer": b.nummer, "status": "bezahlt", "bezahlt_am": bezahlt_am}
    finally:
        con.close()
