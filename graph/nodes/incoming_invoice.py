"""Process B (Eingangsrechnung / incoming invoice) nodes.

Cost-center assignment -> (on ambiguity) four-eyes approval -> archiving in
ELO. Imports only process B's own agents (`agents.incoming_invoice`) plus
the shared helpers in `graph.nodes.shared` -- nothing from process A.
"""

from __future__ import annotations

from langgraph.types import interrupt

from agents.incoming_invoice import archiving, cost_center, extraction
from contracts import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalTrigger,
    CaseOutcome,
    InterruptKind,
)
from governance.audit import Decision, log_entry
from governance.policy import check_approval
from governance import control
from graph.nodes.shared import case_reference, connection, note
from graph.state import Case


def node_invoice_extraction(state: Case) -> dict:
    """Use process B's independently configured extraction profile."""
    con = connection()
    try:
        result = extraction.extract_invoice(
            con, markdown=state["markdown"], actor=state["actor"],
            reference=case_reference(state),
            profile_snapshot=state.get("model_profiles"),
        )
    finally:
        con.close()
    if not result.succeeded:
        if result.unreachable:
            return {
                "completed": True,
                "outcome": CaseOutcome.MODEL_UNAVAILABLE.value,
                "error": result.escalation,
                "log": note(state, "extraktion_rechnung",
                            "Rechnungsextraktion nicht erreichbar – sicher angehalten."),
            }
        return {
            "number": None, "amount_eur": None, "supplier": None,
            "line_items": [], "cost_center_reference": None,
            "exception_case": True,
            "exception_reason": result.escalation or "Extraktion fehlgeschlagen",
            "escalation": result.escalation,
            "log": note(state, "extraktion_rechnung",
                        "Rechnungsdaten konnten nicht sicher ausgelesen werden."),
        }
    data = result.data
    return {
        "number": data.number,
        "amount_eur": data.amount_eur,
        "supplier": data.supplier,
        "line_items": data.line_items,
        "cost_center_reference": data.cost_center_reference,
        "log": note(state, "extraktion_rechnung", "Rechnungsdaten ausgelesen."),
    }


def route_invoice_extraction(state: Case) -> str:
    if state.get("completed"):
        return "ende"
    return "review" if state.get("exception_case") else "kostenstelle"


def node_invoice_extraction_review(state: Case) -> dict:
    """Human clarification after a schema-invalid invoice extraction.

    The reviewer confirms the small set of fields needed by the demo.  No
    archive candidate exists yet; the deterministic cost-centre lookup only
    starts after this clarification has produced structurally valid data.
    """
    from governance import identity
    from governance.step_policy import PolicyDenied

    request = ApprovalRequest(
        kind=InterruptKind.INVOICE_EXTRACTION_REVIEW,
        trigger=ApprovalTrigger.ESCALATION,
        filename=state.get("filename"),
        reason=state.get("exception_reason"),
        escalation=state.get("escalation"),
        number=state.get("number"),
        amount_eur=state.get("amount_eur"),
        supplier=state.get("supplier"),
        line_items=tuple(state.get("line_items") or ()),
        reference=state.get("cost_center_reference"),
    ).as_payload()
    raw = interrupt(request)
    con = connection()
    try:
        person = identity.principal(con)
        permission = check_approval(
            con, actor=person, agent_id="extraktion_rechnung",
            submitter=state.get("actor"),
        )
        if not permission.allowed:
            raise PolicyDenied(permission.reason)
        if raw.get("approver", person) != person:
            raise PolicyDenied("Sitzung und prüfende Person stimmen nicht überein.")
        if raw.get("decision") != ApprovalDecision.APPROVED.value:
            log_entry(
                con, actor=person, agent="extraktion_rechnung",
                action="rechnungsextraktion_manuell_geprueft",
                decision=Decision.DENIED,
                reason=raw.get("reason", "Vorgang verworfen."),
                reference=case_reference(state), outcome="rejected",
            )
            con.commit()
            return {
                "completed": True,
                "outcome": CaseOutcome.REJECTED.value,
                "log": note(state, "extraktion_rechnung", "Vorgang nach manueller Prüfung verworfen."),
            }

        number = str(raw.get("number") or "").strip()
        supplier = str(raw.get("supplier") or "").strip()
        if not number or not supplier:
            raise PolicyDenied("Rechnungsnummer und Lieferant müssen geprüft werden.")
        amount_eur = control.cents(raw.get("amount_eur")) / 100
        line_items = [str(item).strip() for item in (raw.get("line_items") or [])
                      if str(item).strip()]
        cost_center_reference = str(raw.get("cost_center_reference") or "").strip() or None

        log_entry(
            con, actor=person, agent="extraktion_rechnung",
            action="rechnungsextraktion_manuell_geprueft",
            decision=Decision.INFO,
            reason="Fehlgeschlagene Modellextraktion wurde durch eine Person korrigiert.",
            payload={
                "number": number,
                "amount_eur": amount_eur,
                "supplier": supplier,
                "line_items": line_items,
                "cost_center_reference": cost_center_reference,
            },
            reference=case_reference(state), outcome="corrected",
        )
        con.commit()
        return {
            "number": number,
            "amount_eur": amount_eur,
            "supplier": supplier,
            "line_items": line_items,
            "cost_center_reference": cost_center_reference,
            "exception_case": False,
            "exception_reason": "",
            "log": note(
                state, "extraktion_rechnung",
                "Rechnungsdaten wurden durch eine Person geprüft und ergänzt.",
            ),
        }
    except (PolicyDenied, identity.AuthenticationError, TypeError, ValueError) as error:
        log_entry(
            con, actor=raw.get("approver") or "unauthenticated",
            agent="extraktion_rechnung",
            action="rechnungsextraktion_manuell_verweigert",
            decision=Decision.DENIED, reason=str(error),
            reference=case_reference(state), outcome="rejected",
        )
        con.commit()
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "error": str(error),
            "log": note(state, "extraktion_rechnung", str(error)),
        }
    finally:
        con.close()


def node_cost_center(state: Case) -> dict:
    """Cost-center agent (level 2): exact referential lookup.

    Deterministic -- no language model (Thesis §7.4, see
    agents/incoming_invoice/cost_center.py). Resolves the reference
    extracted from the document against the catalog.
    """
    con = connection()
    try:
        control.authorize_read(con, state["case_id"], "B", "kostenstelle", state["actor"])
        z = cost_center.assign(con, cost_center_reference=state.get("cost_center_reference"),
                               actor=state["actor"],
                               line_items=state.get("line_items", []),
                               reference=case_reference(state))
        proposal = control.candidate(con, state["case_id"], "elo",
                                     control.archive_payload(con, state["case_id"], z.cost_center_id), not z.unique)
    finally:
        con.close()

    return {
        "approval_id": proposal["approval_id"], "candidate_version": proposal["version"],
        "cost_center_id": z.cost_center_id,
        "cost_center_reason": z.reason,
        "cost_center_unique": z.unique,
        "log": note(state, "kostenstelle", z.reason),
    }


def route_cost_center(state: Case) -> str:
    """Assignment unique? (diagram part 3).

    The cost-center agent is human-on-the-loop: if it resolves the document
    reference to a unique cost center, the case proceeds automatically to
    archiving. If the reference is missing or unknown, the four-eyes
    approval kicks in. Mirrors process A (number present? -> direct or
    exception case).
    """
    if state.get("cost_center_unique"):
        return "elo"
    return "freigabe"


def node_cost_center_approval(state: Case) -> dict:
    """Choose, validate, then separately approve the exact archive assignment."""
    from governance import control, identity
    from governance.step_policy import PolicyDenied
    con = connection()
    try:
        catalog = cost_center.catalog(con)
        proposal = control.get_candidate(con, state["case_id"], "elo", state.get("candidate_version"))
    finally:
        con.close()
    request = ApprovalRequest(
        kind=InterruptKind.COST_CENTER_APPROVAL, trigger=ApprovalTrigger.ESCALATION,
        filename=state.get("filename"), supplier=state.get("supplier"), amount_eur=state.get("amount_eur"),
        line_items=tuple(state.get("line_items", [])), reference=state.get("cost_center_reference"),
        reason=state.get("cost_center_reason"), unique=state.get("cost_center_unique"),
        catalog=tuple({"id": k[0], "name": k[1], "reference": k[2]} for k in catalog),
    ).as_payload()
    request.update({k: proposal[k] for k in ("approval_id", "version", "payload_hash", "expires")})
    request["selected_cost_center"] = proposal["payload"]["cost_center_id"]
    raw = interrupt(request)
    con = connection()
    try:
        person = identity.principal(con)
        permission = check_approval(con, actor=person, agent_id="elo", submitter=state.get("actor"))
        if not permission.allowed:
            raise PolicyDenied(permission.reason)
        if raw.get("approver", person) != person or raw.get("approval_id") != proposal["approval_id"] or raw.get("version") != proposal["version"]:
            raise PolicyDenied("Sitzung oder Freigabegegenstand stimmt nicht überein.")
        if raw.get("decision") != ApprovalDecision.APPROVED.value:
            control.decide(con, proposal, approved=False, reason=raw.get("reason", "Verworfen"))
            return {"completed": True, "outcome": CaseOutcome.REJECTED.value, "approved_by": person,
                    "log": note(state, "freigabe", "Vorgang verworfen.")}
        selected = raw.get("cost_center_id") or proposal["payload"]["cost_center_id"]
        if not cost_center.exists(con, selected):
            raise PolicyDenied("Ausgewählte Kostenstelle ist nicht im aktuellen Katalog.")
        payload = control.archive_payload(con, state["case_id"], selected)
        control.validate_payload(con, "elo", payload)
        if payload != proposal["payload"]:
            replacement = control.candidate(con, state["case_id"], "elo", payload, True)
            return {"cost_center_id": selected, "candidate_version": replacement["version"],
                    "approval_id": replacement["approval_id"], "approval_decision": "",
                    "cost_center_reason": "Auswahl geprüft. Bitte die angezeigte Zuordnung bestätigen.",
                    "log": note(state, "freigabe", "Geprüfte Auswahl benötigt eine eigene Bestätigung.")}
        person = control.decide(con, proposal, approved=True, reason=raw.get("reason", "Zuordnung geprüft"))
        return {"cost_center_id": selected, "approved_by": person, "approval_id": proposal["approval_id"],
                "candidate_version": proposal["version"], "approval_decision": ApprovalDecision.APPROVED.value,
                "log": note(state, "freigabe", "Zuordnung freigegeben.")}
    except (PolicyDenied, identity.AuthenticationError) as error:
        log_entry(con, actor=raw.get("approver") or "unauthenticated", agent="elo", action="freigabe_verweigert",
                  decision=Decision.DENIED, reason=str(error), reference=case_reference(state), outcome="rejected")
        con.commit()
        return {"completed": True, "outcome": CaseOutcome.REJECTED.value, "error": str(error),
                "log": note(state, "freigabe", str(error))}
    finally:
        con.close()


def route_cost_center_approval(state: Case) -> str:
    if state.get("completed"):
        return "ende"
    return "elo" if state.get("approval_decision") == ApprovalDecision.APPROVED.value else "freigabe"


def node_elo(state: Case) -> dict:
    """ELO agent (level 3): tamper-evident archiving. End of process B.

    Per diagram part 3, process B ends here -- a balance-sheet-effective
    booking in Navision does not happen in process B. Navision (NAV) is only
    ever addressed in process A (booking agent, open -> paid).
    """
    con = connection()
    try:
        e = archiving.archive_document(con, filename=state["filename"],
                                       document_hash=state["document_hash"],
                                       actor=state["actor"], reference=case_reference(state),
                                       cost_center_id=state.get("cost_center_id"), approval_id=state.get("approval_id"),
                                       candidate_version=state.get("candidate_version"), command_id=state.get("command_id"))
    finally:
        con.close()

    if not e.successful:
        return {
            "completed": not e.uncertain, "command_id": e.command_id,
            "outcome": CaseOutcome.EFFECT_UNCERTAIN.value if e.uncertain else CaseOutcome.ARCHIVING_FAILED.value,
            "error": e.error,
            "log": note(state, "elo", e.reason),
        }
    return {
        "completed": True,
        "outcome": CaseOutcome.ARCHIVED.value, "command_id": e.command_id,
        "archive_id": e.reference_id,
        "log": note(state, "elo", e.reason),
    }
