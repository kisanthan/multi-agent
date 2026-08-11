"""Shared intake stretch: reader, classification, orchestrator routing.

These nodes and helpers are used by both processes -- that is exactly the
thesis's "shared components" claim (reader, classification, master data),
made concrete in code. Process-specific nodes live in
`payment_confirmation.py` and `incoming_invoice.py`; this module has no
dependency on either.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agents.shared import classification
from agents.shared.schemas import DocumentType
from config import DB_PATH
from contracts import CaseOutcome
from governance.audit import CaseReference
from graph.state import Case
from tools.reader import AccessDenied, read_document


def connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def case_reference(state: Case) -> CaseReference:
    """Case reference for the audit trail.

    Every entry of a run carries the same case ID and the same document --
    only that way can the trail later be filtered to exactly this case. The
    filename is only known after the reader; before that, the path is
    enough.
    """
    return CaseReference(
        case_id=state.get("case_id"),
        source=state.get("filename") or Path(state.get("path", "")).name,
    )


def _extracted_fields(d) -> str:
    """What the extraction agent found -- as a sentence, not a dump.

    The text appears in the detail view under "What happened so far". Raw
    field names and `None` would not belong there; whatever was not found
    is named as such.
    """
    found = []
    if d.number:
        found.append(f"Rechnungsnummer {d.number}")
    if d.amount_eur is not None:
        found.append(f"Betrag {d.amount_eur:.2f} EUR".replace(".", ","))
    if d.supplier:
        found.append(f"Lieferant {d.supplier}")
    if d.cost_center_reference:
        found.append(f"Kostenstelle {d.cost_center_reference}")

    if not found:
        return "Beleg ausgewertet, aber keine verwertbaren Angaben gefunden."
    return "Erkannt: " + ", ".join(found) + "."


def note(state: Case, node: str, text: str) -> list[dict]:
    """Appends a step to the run log (for UI and CLI output)."""
    return [*state.get("log", []), {"node": node, "text": text}]


def node_reader(state: Case) -> dict:
    """Reader tool. The AD check sits inside `read_document` (Least Privilege)."""
    con = connection()
    try:
        content = read_document(con, state["path"], actor=state["actor"],
                                reference=case_reference(state))
    except AccessDenied as e:
        # Scenario 5: end of the case. No parsing, no model, no target system.
        return {
            "completed": True,
            "outcome": CaseOutcome.ACCESS_DENIED.value,
            "error": str(e),
            "log": note(state, "reader",
                       f"Zugriff nicht erlaubt: {e}"),
        }
    finally:
        con.close()

    return {
        "markdown": content.markdown,
        "document_hash": content.document_hash,
        "filename": content.filename,
        "log": note(
            state, "reader",
            f"{content.filename} eingelesen, {content.pages} Seite(n)."),
    }


def node_classification(state: Case) -> dict:
    """Classification & extraction agent: type and fields in one pass."""
    con = connection()
    try:
        e = classification.classify(con, markdown=state["markdown"],
                                    actor=state["actor"],
                                    reference=case_reference(state))
    finally:
        con.close()

    if not e.succeeded:
        # R1: the model does not honor the schema -> exception case instead of guessing.
        return {
            "exception_case": True,
            "exception_reason": e.escalation or "Extraktion fehlgeschlagen",
            "escalation": e.escalation,
            "document_type": DocumentType.UNKNOWN.value,
            "log": note(
                state, "klassifikation",
                "Der Beleg konnte nicht ausgewertet werden – eine Person "
                "muss entscheiden."),
        }

    d = e.data
    return {
        "document_type": d.type.value,
        "number": d.number,
        "amount_eur": d.amount_eur,
        "supplier": d.supplier,
        "line_items": d.line_items,
        "cost_center_reference": d.cost_center_reference,
        "log": note(state, "klassifikation", _extracted_fields(d)),
    }


def route_document_type(state: Case) -> str:
    """Orchestrator agent: conditional edge on document type.

    No model call: the type is already known (the classification agent
    determined it). The orchestrator merely *routes* on it -- asking a
    model again here would be a second call with the potential to
    contradict the first.
    """
    if state.get("completed"):
        return "ende"
    if state.get("exception_case"):
        return "hitl"
    t = state.get("document_type")
    if t == DocumentType.PAYMENT_CONFIRMATION.value:
        return "prozess_a"
    if t == DocumentType.INCOMING_INVOICE.value:
        return "prozess_b"
    return "hitl"
