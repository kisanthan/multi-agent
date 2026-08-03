"""Policy/governance component: deterministic RBAC/ABAC enforcement.

The thesis's central technical claim: permission and policy checks run as
regular logic, NOT inside the language model (section 7 of the functional
concept). This module therefore imports neither an LLM client nor anything
from `agents/` -- tests/test_layer_boundaries.py enforces this.

The practical evidence: every decision here is reproducibly verifiable with
a unit test. With a language model, it would not be.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum

from governance import ad
from registry import AutonomyLevel, OversightMode, get_config


class Outcome(str, Enum):
    ALLOWED = "erlaubt"
    APPROVAL_NEEDED = "freigabe_noetig"
    DENIED = "verweigert"


@dataclass(frozen=True)
class Ruling:
    """The result of a policy check.

    `rule` names the rule that fired. That is not logging luxury: the audit
    trail then records not only *that* something was denied, but *why* --
    and that is the traceability the thesis requires.
    """

    outcome: Outcome
    rule: str
    reason: str
    context: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome is Outcome.ALLOWED

    @property
    def needs_approval(self) -> bool:
        return self.outcome is Outcome.APPROVAL_NEEDED

    def __str__(self) -> str:
        return f"[{self.outcome.value}] {self.rule}: {self.reason}"


def check_write_action(
    con: sqlite3.Connection,
    *,
    agent_id: str,
    actor: str,
    action: str,
    amount_eur: float | None = None,
) -> Ruling:
    """Upfront check before EVERY write action.

    The rules are checked in this order; the first one that fires decides.
    The order is deliberately restrictive-first: the autonomy level is
    checked before the amount is even considered, so that a level-1 agent
    cannot write even at 0 EUR.
    """
    cfg = get_config(agent_id)
    base = {"agent": agent_id, "actor": actor, "action": action,
            "autonomy_level": cfg.autonomy_level.value if cfg.autonomy_level else None,
            "oversight": cfg.oversight.value}

    # Rule 1 -- Zero Trust: unknown actors abort the case.
    try:
        user = ad.load_user(con, actor)
    except ad.UnknownUser as e:
        return Ruling(Outcome.DENIED, "zero_trust", str(e), base)

    # Rule 2 -- Least Privilege: components without write access never write.
    if not cfg.can_write:
        return Ruling(
            Outcome.DENIED, "least_privilege",
            f"{cfg.name} hat kein Schreibrecht (Typ {cfg.type.value}).", base,
        )

    # Rule 3 -- Autonomy level: level 1 (read) and 2 (proposal) may not
    # execute, regardless of anything else.
    if cfg.autonomy_level is None or cfg.autonomy_level < AutonomyLevel.REVERSIBLE_WRITE:
        level = cfg.autonomy_level.value if cfg.autonomy_level else "keine"
        return Ruling(
            Outcome.DENIED, "autonomy_level",
            f"{cfg.name} hat Autonomiestufe {level}; Schreiben erfordert "
            f"mindestens Stufe {AutonomyLevel.REVERSIBLE_WRITE.value}.", base,
        )

    # Rule 4 -- oversight mode from the registry.
    # The booking agent is human-in-the-loop (Thesis §7.4): the financially
    # effective booking step always requires human approval, regardless of
    # amount. There is deliberately no amount-based threshold -- that would
    # weaken the continuous oversight the concept requires.
    if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP:
        context = {**base, "amount_eur": amount_eur}
        return Ruling(
            Outcome.APPROVAL_NEEDED, "oversight_mode",
            f"{cfg.name} ist Human-in-the-loop -- Freigabe erforderlich.", context,
        )
    if cfg.oversight is OversightMode.HUMAN_ON_THE_LOOP:
        return Ruling(
            Outcome.ALLOWED, "oversight_mode",
            f"{cfg.name} ist Human-on-the-loop -- Ausfuehrung mit Audit-Eintrag.",
            base,
        )

    # Rule 5 -- default deny. An uncovered oversight mode is a configuration
    # error and must not pass as a permission.
    return Ruling(
        Outcome.DENIED, "default_deny",
        f"Aufsichtsmodus {cfg.oversight.value} deckt keine Schreibaktion ab.", base,
    )


def check_approval(con: sqlite3.Connection, *, actor: str, agent_id: str) -> Ruling:
    """Checks whether a human may decide a HITL point (four-eyes principle)."""
    cfg = get_config(agent_id)
    result = ad.check_approval_permission(con, actor)
    context = {"agent": agent_id, "actor": actor, "oversight": cfg.oversight.value}
    if not result.allowed:
        return Ruling(Outcome.DENIED, "approval_rbac", result.reason, context)
    return Ruling(Outcome.ALLOWED, "approval_rbac", result.reason, context)


def check_reader_access(con: sqlite3.Connection, *, actor: str) -> Ruling:
    """Entry condition into the reader tool (scenario 5, governance demo)."""
    result = ad.check_reader_access(con, actor)
    context = {"agent": "reader", "actor": actor, "group": ad.READER_GROUP}
    if not result.allowed:
        return Ruling(Outcome.DENIED, "reader_rbac", result.reason, context)
    return Ruling(Outcome.ALLOWED, "reader_rbac", result.reason, context)
