"""Booking agent (Shared Domain, level 3 = reversible write), process A.

Books the payment in the ERP and sets the status from open to paid.

The financially effective booking step is human-in-the-loop (Thesis §7.4):
every booking requires human approval. The agent does not decide this
itself, but *asks the policy* (governance/policy.py). That is the core of
the architectural claim: governance does not sit in the agent, and
certainly not in the model.

The agent itself calls no language model. What happens here -- asking the
policy, an HTTP call to the ERP -- is deterministic. The FRONTIER model
class in the registry nonetheless remains correct: it describes the *risk
class* of the role and governs which model an agent at this level would
receive.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import httpx

from config import settings
from contracts import CaseOutcome
from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry
from governance.policy import Outcome, check_approval, check_write_action

AGENT_ID = "buchung"


@dataclass(frozen=True)
class BookingResult:
    booked: bool
    approval_needed: bool
    reason: str
    number: str | None = None
    error: str | None = None
    outcome: CaseOutcome | None = None


def book(con: sqlite3.Connection, *, number: str, amount_eur: float, actor: str,
         document: str, approved_by: str | None = None,
         reference: CaseReference = NO_REFERENCE) -> BookingResult:
    """Books a payment -- after a policy check.

    `approved_by` is set when a human has already decided the HITL point.
    In that case `check_write_action`'s amount/autonomy rules are skipped --
    the decision to book at all was already made -- but the approver's
    permission is re-verified via `check_approval`, the same
    write-site-check principle
    agents/incoming_invoice/archiving.py already applies: an approval
    earlier in the process does not replace the permission check at the
    point that actually writes. Without this, `book()` would trust
    whatever string a caller passes as `approved_by`.
    """
    if approved_by is None:
        decision = check_write_action(
            con, agent_id=AGENT_ID, actor=actor, action="zahlung_verbuchen",
            amount_eur=amount_eur,
        )

        if decision.outcome is Outcome.DENIED:
            log_entry(con, actor=actor, agent=AGENT_ID, action="zahlung_verbuchen",
                      decision=Decision.DENIED,
                      reason=decision.reason,
                      payload={"number": number, "rule": decision.rule},
                      reference=reference, outcome="verweigert")
            con.commit()
            return BookingResult(False, False, decision.reason, number)

        if decision.needs_approval:
            log_entry(con, actor=actor, agent=AGENT_ID, action="freigabe_angefordert",
                      decision=Decision.INFO, reason=decision.reason,
                      payload={"number": number, "amount_eur": amount_eur,
                               "rule": decision.rule},
                      reference=reference, outcome="freigabe_noetig")
            con.commit()
            return BookingResult(False, True, decision.reason, number)
    else:
        permission = check_approval(
            con, actor=approved_by, agent_id=AGENT_ID, submitter=actor
        )
        if not permission.allowed:
            log_entry(con, actor=approved_by, agent=AGENT_ID, action="freigabe_verweigert",
                      decision=Decision.DENIED, reason=permission.reason,
                      payload={"number": number, "amount_eur": amount_eur},
                      reference=reference, outcome="verweigert")
            con.commit()
            return BookingResult(False, False, permission.reason, number)

        log_entry(con, actor=approved_by, agent=AGENT_ID,
                  action="freigabe_erteilt", decision=Decision.ALLOWED,
                  reason=f"Buchung von {approved_by} freigegeben "
                         "(Vier-Augen-Prinzip).",
                  payload={"number": number, "amount_eur": amount_eur,
                           "einspeiser": actor},
                  reference=reference, outcome="freigegeben")
        con.commit()

    # The ERP call. The target system checks its own preconditions -- a 409
    # here is a business finding (duplicate), not a transport error, and
    # Navision logs its own accept/reject decision (mocks/navision.py) --
    # it has the same database access a real ERP integration would not
    # have, so re-logging that here would double the entry, not complete
    # it. An unreachable ERP is different: its handler never runs, so it
    # never gets the chance to log anything about it -- that gap is only
    # visible from this side of the call.
    endpoint = f"{settings.navision_url.rstrip('/')}/booking"
    try:
        response = httpx.post(
            endpoint,
            json={"number": number, "amount_eur": amount_eur, "actor": actor,
                  "document": document, "case_id": reference.case_id},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        reason = (
            f"Die Freigabe wurde erteilt, aber Navision ist unter "
            f"{settings.navision_url} nicht erreichbar. Die Zahlung wurde "
            "nicht verbucht; die Rechnung bleibt offen."
        )
        technical_error = f"Verbindungsaufbau zu {endpoint} fehlgeschlagen: {e}"
        log_entry(con, actor=actor, agent=AGENT_ID, action="zahlung_verbuchen",
                 decision=Decision.DENIED, reason=reason,
                 payload={"number": number, "amount_eur": amount_eur},
                 reference=reference,
                 outcome=CaseOutcome.BOOKING_UNAVAILABLE.value)
        con.commit()
        return BookingResult(
            False,
            False,
            reason,
            number,
            error=technical_error,
            outcome=CaseOutcome.BOOKING_UNAVAILABLE,
        )

    if response.status_code != 200:
        detail = response.json().get("detail", response.text)
        return BookingResult(
            False,
            False,
            f"Navision hat abgelehnt: {detail}",
            number,
            error=detail,
            outcome=CaseOutcome.BOOKING_REFUSED,
        )

    return BookingResult(
        True,
        False,
        f"Zahlung zu {number} verbucht, Status offen -> bezahlt.",
        number,
        outcome=CaseOutcome.BOOKED,
    )
