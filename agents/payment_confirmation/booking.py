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
from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry
from governance.policy import Outcome, check_write_action

AGENT_ID = "buchung"


@dataclass(frozen=True)
class BookingResult:
    booked: bool
    approval_needed: bool
    reason: str
    number: str | None = None
    error: str | None = None


def book(con: sqlite3.Connection, *, number: str, amount_eur: float, actor: str,
         document: str, approved_by: str | None = None,
         reference: CaseReference = NO_REFERENCE) -> BookingResult:
    """Books a payment -- after a policy check.

    `approved_by` is set when a human has already decided the HITL point.
    In that case the policy approval check is skipped: the approval *is*
    the permission, otherwise the case would loop endlessly between
    approval and re-asking.
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
        log_entry(con, actor=approved_by, agent=AGENT_ID,
                  action="freigabe_erteilt", decision=Decision.ALLOWED,
                  reason=f"Buchung von {approved_by} freigegeben "
                         "(Vier-Augen-Prinzip).",
                  payload={"number": number, "amount_eur": amount_eur,
                           "einspeiser": actor},
                  reference=reference, outcome="freigegeben")
        con.commit()

    # The ERP call. The target system checks its own preconditions -- a 409
    # here is a business finding (duplicate), not a transport error.
    try:
        response = httpx.post(
            f"{settings.navision_url}/booking",
            json={"number": number, "amount_eur": amount_eur, "actor": actor,
                  "document": document, "case_id": reference.case_id},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        return BookingResult(
            False, False, f"Navision nicht erreichbar: {e}", number, error=str(e)
        )

    if response.status_code != 200:
        detail = response.json().get("detail", response.text)
        return BookingResult(False, False, f"Navision hat abgelehnt: {detail}",
                             number, error=detail)

    return BookingResult(
        True, False, f"Zahlung zu {number} verbucht, Status offen -> bezahlt.", number
    )
