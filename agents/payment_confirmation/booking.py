"""Deterministic level-4 booking adapter. Names alone never authorize a write."""
from dataclasses import dataclass
import sqlite3
import httpx  # compatibility for existing transport injection
from contracts import CaseOutcome
from governance import control
from governance.audit import CaseReference, NO_REFERENCE, Decision, log_entry
from governance.policy import check_write_action, check_approval, Outcome
from governance.step_policy import PolicyDenied
from runtime.tool_gateway import dispatch

AGENT_ID = "buchung"


@dataclass(frozen=True)
class BookingResult:
    booked: bool
    approval_needed: bool
    reason: str
    number: str | None = None
    error: str | None = None
    outcome: CaseOutcome | None = None
    command_id: str | None = None


def book(con: sqlite3.Connection, *, number: str, amount_eur: float, actor: str,
         document: str, approved_by: str | None = None,
         reference: CaseReference = NO_REFERENCE, approval_id: str | None = None,
         candidate_version: int | None = None, command_id: str | None = None) -> BookingResult:
    ruling = check_write_action(con, agent_id=AGENT_ID, actor=actor, action="zahlung_verbuchen", amount_eur=amount_eur)
    if ruling.outcome is Outcome.DENIED:
        return BookingResult(False, False, ruling.reason, number, outcome=CaseOutcome.BOOKING_REFUSED)
    if not approval_id and not command_id:
        if approved_by:
            permission = check_approval(con, actor=approved_by, agent_id=AGENT_ID, submitter=actor)
            reason = permission.reason if not permission.allowed else "Ein Freigabename ersetzt keine strukturierte Freigabe."
            log_entry(con, actor=actor, agent=AGENT_ID, action="freigabe_verweigert", decision=Decision.DENIED,
                      reason=reason, reference=reference, outcome="rejected")
            con.commit()
            return BookingResult(False, False, reason, number, outcome=CaseOutcome.BOOKING_REFUSED)
        return BookingResult(False, True, ruling.reason, number)
    try:
        c = control.require_active(con, reference.case_id)
        if c["actor"] != actor:
            raise PolicyDenied("Einreicher wurde verändert.")
        proposal = control.get_candidate(con, reference.case_id, "buchung")
        if proposal["approval_id"] != approval_id or proposal["version"] != candidate_version:
            raise PolicyDenied("Freigabe gehört nicht zum aktuellen Vorschlag.")
        if proposal["approval_status"] == "requested":
            return BookingResult(False, True, "Buchung benötigt eine inhaltsgebundene Freigabe.", number)
        p = proposal["payload"]
        if p["number"] != number or p["amount_cents"] != control.cents(amount_eur) or p["document_hash"] != c["document_hash"]:
            raise PolicyDenied("Freigegebener Inhalt wurde verändert.")
        cid = command_id or control.prepare_command(con, proposal)
        receipt = dispatch(con, cid)
        success = receipt["status"] == "succeeded"
        unknown = receipt["status"] == "in_doubt"
        return BookingResult(success, False,
                             "Zahlung verbucht." if success else receipt.get("reason", "Zielsystem hat abgelehnt."),
                             number, receipt.get("reason") if not success else None,
                             CaseOutcome.BOOKED if success else CaseOutcome.EFFECT_UNCERTAIN if unknown else CaseOutcome.BOOKING_REFUSED,
                             cid)
    except PolicyDenied as error:
        return BookingResult(False, False, str(error), number, str(error), CaseOutcome.BOOKING_REFUSED, command_id)
