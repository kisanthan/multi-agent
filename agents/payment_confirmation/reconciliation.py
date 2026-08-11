"""Reconciliation agent (Shared Domain, level 1 = read access), process A.

Reconciles the extracted invoice/order number against the shared master
data and decides whether an exception case exists.

DEVIATION FROM THE FUNCTIONAL CONCEPT -- deliberate and documented
(docs/mapping.md): the configuration table assigns this agent a (small,
local) model. The reconciliation, however, is a lookup over a primary key.
A language model could contribute nothing here that SQL does not already do
exactly and reproducibly -- it could only hallucinate. The prototype
therefore implements the reconciliation deterministically.

This is itself a finding for the thesis: the agent typology states *which
role* a component has and *which autonomy level* it needs -- it does not
follow automatically that model inference is required. Autonomy level 1
(read access) and the oversight mode remain valid as-is; only the model
assignment falls away.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import Enum

from config import settings
from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry

AGENT_ID = "abgleich"


class Finding(str, Enum):
    OK = "ok"                          # number known, open, amount plausible
    UNKNOWN = "unbekannt"              # number not in the master data
    ALREADY_PAID = "bereits_bezahlt"   # duplicate
    AMOUNT_MISMATCH = "betrag_abweichend"
    NO_NUMBER = "keine_nummer"         # extraction returned no number


@dataclass(frozen=True)
class ReconciliationResult:
    finding: Finding
    number: str | None
    expected_amount_eur: float | None
    actual_amount_eur: float | None
    reason: str

    @property
    def is_exception_case(self) -> bool:
        return self.finding is not Finding.OK


def normalize(number: str) -> str:
    """Normalizes notation before comparison.

    The parser occasionally returns the number with extra characters from
    the markdown formatting ('**RE-2026-4200**') or with spaces. That is a
    formatting question, not a business one -- cleaning it up here is a
    different thing than vaguely guessing which invoice might be meant.
    """
    return re.sub(r"[^A-Z0-9-]", "", number.upper())


def reconcile(con: sqlite3.Connection, *, number: str | None, amount_eur: float | None,
              actor: str, reference: CaseReference = NO_REFERENCE) -> ReconciliationResult:
    """Checks the number against the master data. Read access only."""
    if not number:
        result = ReconciliationResult(
            Finding.NO_NUMBER, None, None, amount_eur,
            "Im Dokument wurde keine Rechnungs-/Bestellnummer gefunden.",
        )
        _log(con, actor, result, reference)
        return result

    norm = normalize(number)
    row = con.execute(
        "SELECT number, amount_eur, status FROM invoices WHERE number = ?", (norm,)
    ).fetchone()

    if row is None:
        result = ReconciliationResult(
            Finding.UNKNOWN, norm, None, amount_eur,
            f"Nummer {norm} ist in den Stammdaten nicht vorhanden.",
        )
    elif row[2] == "bezahlt":
        result = ReconciliationResult(
            Finding.ALREADY_PAID, norm, row[1], amount_eur,
            f"Nummer {norm} ist bereits als bezahlt erfasst (moegliche Dublette).",
        )
    elif (amount_eur is not None
          and abs(row[1] - amount_eur) > settings.amount_tolerance_eur):
        result = ReconciliationResult(
            Finding.AMOUNT_MISMATCH, norm, row[1], amount_eur,
            f"Zahlbetrag {amount_eur:.2f} EUR weicht vom Stammdatenbetrag "
            f"{row[1]:.2f} EUR ab.",
        )
    else:
        result = ReconciliationResult(
            Finding.OK, norm, row[1], amount_eur,
            f"Nummer {norm} gefunden, Status offen, Betrag stimmt ueberein.",
        )

    _log(con, actor, result, reference)
    return result


def _log(con: sqlite3.Connection, actor: str, r: ReconciliationResult,
         reference: CaseReference = NO_REFERENCE) -> None:
    log_entry(
        con, actor=actor, agent=AGENT_ID, action="nummer_abgleichen",
        decision=Decision.INFO, reason=r.reason,
        payload={"finding": r.finding.value, "number": r.number,
                 "expected_amount_eur": r.expected_amount_eur,
                 "actual_amount_eur": r.actual_amount_eur},
        reference=reference, outcome=r.finding.value,
    )
    con.commit()
