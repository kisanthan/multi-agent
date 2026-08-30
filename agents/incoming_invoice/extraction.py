"""Process-specific structured extraction for incoming invoices."""

from __future__ import annotations

import sqlite3

from agents.shared import classification
from agents.shared.schemas import InvoiceExtraction
from config import ProfileId
from governance.audit import NO_REFERENCE, CaseReference
from llm.extraction import ExtractionResult

AGENT_ID = "extraktion_rechnung"
SYSTEM = """Du extrahierst Daten aus einer deutschen Eingangsrechnung.
Erfinde nichts. Fehlende Werte sind null. Antworte ausschließlich als JSON
nach dem vorgegebenen Schema. Deutsche Zahlenschreibweise ist zu beachten."""


def extract_invoice(
    con: sqlite3.Connection, *, markdown: str, actor: str,
    reference: CaseReference = NO_REFERENCE,
    profile_snapshot: dict[str, dict[str, str]] | None = None,
) -> ExtractionResult:
    return classification.extract(
        con, agent_id=AGENT_ID, actor=actor, system=SYSTEM,
        prompt=f"Extrahiere die Rechnungsdaten:\n\n{markdown}",
        schema=InvoiceExtraction, reference=reference,
        profile_id=ProfileId.INVOICE, profile_snapshot=profile_snapshot,
    )
