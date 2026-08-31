"""ERP mock: Microsoft Dynamics NAV ("Navision").

Models the booking interface process A needs: `POST /booking` (book a
payment, status open -> paid). Per diagram part 3, Navision is only
addressed in process A; process B ends with tamper-evident archiving in
ELO.

The mock is deliberately *strict*: it checks its own business preconditions
and rejects invalid bookings. A mock that accepts everything would
undermine the thesis's governance claim -- the demo would look successful
even though the real target system would have rejected the booking.

Start:  uvicorn mocks.navision:app --port 8001
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config
from data.bootstrap import ensure_configured_runtime
from governance.audit import CaseReference, Decision, log_entry

app = FastAPI(title="Navision-Mock (Dynamics NAV)", version="1.0")


def _con() -> sqlite3.Connection:
    ensure_configured_runtime()
    con = sqlite3.connect(config.DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


class Booking(BaseModel):
    """Process A: booking a received payment."""

    number: str = Field(description="Rechnungs-/Bestellnummer")
    amount_eur: float = Field(gt=0)
    actor: str = Field(description="UPN des verantwortlichen Nutzers")
    document: str = Field(description="Dateiname der Zahlungsbestaetigung")
    case_id: str | None = Field(
        default=None, description="Vorgang, zu dem die Buchung gehoert")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "navision-mock"}


@app.post("/booking")
def book_payment(b: Booking) -> dict:
    """Sets the status of an open invoice to 'bezahlt'.

    Two preconditions are checked here again, even though the
    reconciliation agent already checked them: the number must exist and
    must not already be paid. This is not redundancy but the role of the
    target system -- it does not rely on the caller having done clean work.
    """
    con = _con()
    reference = CaseReference(b.case_id, b.document)
    try:
        row = con.execute(
            "SELECT status, amount_eur FROM invoices WHERE number = ?", (b.number,)
        ).fetchone()

        if row is None:
            log_entry(con, actor=b.actor, agent="buchung", action="zahlung_verbuchen",
                      decision=Decision.DENIED,
                      reason=f"Navision: Nummer {b.number} unbekannt.",
                      payload={"number": b.number, "document": b.document},
                      reference=reference, outcome="abgelehnt: unbekannt")
            con.commit()
            raise HTTPException(404, f"Rechnung {b.number} nicht gefunden")

        status, expected_amount = row
        if status == "bezahlt":
            # Duplicate protection in the target system (incident 'duplicate').
            log_entry(con, actor=b.actor, agent="buchung", action="zahlung_verbuchen",
                      decision=Decision.DENIED,
                      reason=f"Navision: {b.number} ist bereits bezahlt.",
                      payload={"number": b.number, "document": b.document},
                      reference=reference, outcome="abgelehnt: Dublette")
            con.commit()
            raise HTTPException(409, f"Rechnung {b.number} ist bereits bezahlt")

        paid_at = datetime.now(timezone.utc).isoformat()
        con.execute(
            "UPDATE invoices SET status = 'bezahlt', paid_at = ? WHERE number = ?",
            (paid_at, b.number),
        )
        log_entry(con, actor=b.actor, agent="buchung", action="zahlung_verbuchen",
                  decision=Decision.ALLOWED,
                  reason=f"Navision: {b.number} offen -> bezahlt.",
                  payload={"number": b.number, "amount_eur": b.amount_eur,
                           "expected_amount_eur": expected_amount, "document": b.document},
                  reference=reference, outcome="verbucht")
        con.commit()
        return {"number": b.number, "status": "bezahlt", "paid_at": paid_at}
    finally:
        con.close()
