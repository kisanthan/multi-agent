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
from langchain_core.runnables import RunnableConfig

from agents.shared import classification
from agents.shared.schemas import Classification, DocumentType
import config
from contracts import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalTrigger,
    CaseOutcome,
    InterruptKind,
)
from governance.audit import CaseReference, Decision, log_entry
from governance import control, identity
from governance.policy import check_approval
from governance.step_policy import PolicyDenied
from data.migrations import connect
from graph.state import Case
from langgraph.types import interrupt
from tools.reader import AccessDenied, read_document


def connection() -> sqlite3.Connection:
    return connect(config.DB_PATH)


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


def _extracted_fields(d: Classification) -> str:
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


def node_reader(state: Case, config: RunnableConfig) -> dict:
    """Reader tool. The AD check sits inside `read_document` (Least Privilege)."""
    con = connection()
    case_id = state.get("case_id") or config["configurable"]["thread_id"]
    state = {**state, "case_id": case_id}
    try:
        if identity.principal(con) != state["actor"]:
            raise AccessDenied("Einreicher entspricht nicht der angemeldeten Person.")
        content = read_document(con, state["path"], actor=state["actor"],
                                reference=case_reference(state))
        control.register_case(con, case_id=case_id, actor=state["actor"],
                              document_hash=content.document_hash, filename=content.filename,
                              content=Path(state["path"]).read_bytes())
    except (AccessDenied, identity.AuthenticationError, PolicyDenied) as e:
        # Scenario 5: end of the case. No parsing, no model, no target system.
        return {
            "completed": True,
            "outcome": CaseOutcome.ACCESS_DENIED.value,
            "error": str(e),
            "log": note(state, "reader",
                       f"Zugriff nicht erlaubt: {e}"),
        }
    except (OSError, ValueError, RuntimeError) as e:
        return {"case_id": case_id, "completed": True, "outcome": CaseOutcome.PARSE_FAILED.value,
                "error": str(e), "log": note(state, "reader", "Dokument nicht lesbar.")}
    finally:
        con.close()

    return {
        "case_id": case_id,
        "markdown": content.markdown,
        "document_hash": content.document_hash,
        "filename": content.filename,
        "log": note(
            state, "reader",
            f"{content.filename} eingelesen, {content.pages} Seite(n)."),
    }


def node_classification(state: Case) -> dict:
    """Route the document to exactly one process without extracting fields."""
    con = connection()
    try:
        e = classification.route(
            con, markdown=state["markdown"], actor=state["actor"],
            reference=case_reference(state),
            profile_snapshot=state.get("model_profiles"),
        )
    finally:
        con.close()

    if not e.succeeded:
        if e.unreachable:
            return {
                "completed": True,
                "outcome": CaseOutcome.MODEL_UNAVAILABLE.value,
                "error": e.escalation,
                "log": note(state, "klassifikation",
                            "Belegarterkennung nicht erreichbar – der Vorgang "
                            "wurde sicher angehalten."),
            }
        # R1: the model does not honor the schema -> exception case instead of guessing.
        return {
            "exception_case": True,
            "exception_reason": e.escalation or "Extraktion fehlgeschlagen",
            "escalation": e.escalation,
            # The classification agent is human-on-the-loop; reaching a
            # human here means it escalated rather than guessed.
            "approval_trigger": ApprovalTrigger.ESCALATION.value,
            "document_type": DocumentType.UNKNOWN.value,
            "log": note(
                state, "klassifikation",
                "Der Beleg konnte nicht ausgewertet werden – eine Person "
                "muss entscheiden."),
        }

    d = e.data
    if d.type in (DocumentType.PAYMENT_CONFIRMATION, DocumentType.INCOMING_INVOICE):
        con = connection()
        try:
            control.select_process(con, state["case_id"], "A" if d.type is DocumentType.PAYMENT_CONFIRMATION else "B")
        finally:
            con.close()
    return {
        "document_type": d.type.value,
        "log": note(state, "klassifikation",
                    "Belegart erkannt: " +
                    ("Zahlungsbestätigung." if d.type is DocumentType.PAYMENT_CONFIRMATION
                     else "Eingangsrechnung.")),
    }


def route_document_type(state: Case) -> str:
    """Orchestrator agent: conditional edge on document type.

    No model call: the type is already known (the shared router determined
    it). The orchestrator merely *routes* on it -- asking a
    model again here would be a second call with the potential to
    contradict the first.
    """
    if state.get("completed"):
        return "ende"
    if state.get("exception_case"):
        return "review"
    t = state.get("document_type")
    if t == DocumentType.PAYMENT_CONFIRMATION.value:
        return "prozess_a"
    if t == DocumentType.INCOMING_INVOICE.value:
        return "prozess_b"
    return "review"


def node_classification_review(state: Case) -> dict:
    """Let a demo reviewer select the process when the model schema failed.

    This is deliberately a narrow clarification step, not a second
    classifier. It can only choose one of the two registered document
    types or end the case. No process-specific candidate and no target
    system command exists before this decision.
    """
    request = ApprovalRequest(
        kind=InterruptKind.DOCUMENT_TYPE_REVIEW,
        trigger=ApprovalTrigger.ESCALATION,
        filename=state.get("filename"),
        reason=state.get("exception_reason"),
        escalation=state.get("escalation"),
        document_type_options=(
            {"value": DocumentType.PAYMENT_CONFIRMATION.value,
             "label": "Zahlungsbestätigung"},
            {"value": DocumentType.INCOMING_INVOICE.value,
             "label": "Eingangsrechnung"},
        ),
    ).as_payload()
    raw = interrupt(request)
    con = connection()
    try:
        person = identity.principal(con)
        permission = check_approval(
            con, actor=person, agent_id="klassifikation",
            submitter=state.get("actor"),
        )
        if not permission.allowed:
            raise PolicyDenied(permission.reason)
        if raw.get("approver", person) != person:
            raise PolicyDenied("Sitzung und prüfende Person stimmen nicht überein.")
        if raw.get("decision") != ApprovalDecision.APPROVED.value:
            log_entry(
                con, actor=person, agent="klassifikation",
                action="dokumenttyp_manuell_geprueft",
                decision=Decision.DENIED,
                reason=raw.get("reason", "Vorgang verworfen."),
                reference=case_reference(state), outcome="rejected",
            )
            con.commit()
            return {
                "completed": True,
                "outcome": CaseOutcome.REJECTED.value,
                "approved_by": person,
                "log": note(state, "klassifikation", "Vorgang nach manueller Prüfung verworfen."),
            }

        document_type = DocumentType(raw.get("document_type", ""))
        if document_type not in {
            DocumentType.PAYMENT_CONFIRMATION,
            DocumentType.INCOMING_INVOICE,
        }:
            raise PolicyDenied("Unzulässiger Dokumenttyp.")
        process = "A" if document_type is DocumentType.PAYMENT_CONFIRMATION else "B"
        control.select_process(con, state["case_id"], process)
        log_entry(
            con, actor=person, agent="klassifikation",
            action="dokumenttyp_manuell_geprueft",
            decision=Decision.INFO,
            reason=f"Dokumenttyp manuell als {document_type.value} bestätigt.",
            payload={"document_type": document_type.value, "process": process},
            reference=case_reference(state), outcome="corrected",
        )
        con.commit()
        return {
            "document_type": document_type.value,
            "exception_case": False,
            "exception_reason": "",
            "log": note(
                state, "klassifikation",
                "Belegart wurde durch eine Person festgelegt: "
                + ("Zahlungsbestätigung." if process == "A" else "Eingangsrechnung."),
            ),
        }
    except (PolicyDenied, identity.AuthenticationError, ValueError) as error:
        log_entry(
            con, actor=raw.get("approver") or "unauthenticated",
            agent="klassifikation", action="dokumenttyp_manuell_verweigert",
            decision=Decision.DENIED, reason=str(error),
            reference=case_reference(state), outcome="rejected",
        )
        con.commit()
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "error": str(error),
            "log": note(state, "klassifikation", str(error)),
        }
    finally:
        con.close()
