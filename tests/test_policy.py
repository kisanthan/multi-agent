"""Tests of the policy engine.

Covers the combinations of role x autonomy level x amount. That these tests
are possible at all is itself the argument: a governance rule inside the
language model could not be checked this way.
"""

from __future__ import annotations

import pytest

from governance.policy import Outcome, check_approval, check_reader_access, check_write_action

SUBMITTER = "einspeiser@chg-meridian.com"
APPROVER = "pruefer@chg-meridian.com"
EXTERNAL = "extern@partner.de"


# ------------------------------------------------- Rule 1: Zero Trust

def test_unknown_actor_is_denied(con):
    e = check_write_action(con, agent_id="buchung", actor="niemand@nirgends.de",
                           action="verbuchen", amount_eur=100.0)
    assert e.outcome is Outcome.DENIED
    assert e.rule == "zero_trust"


# ------------------------------------- Rules 2/3: Least Privilege + level

@pytest.mark.parametrize("agent_id", ["reader", "orchestrator", "policy", "audit"])
def test_components_without_write_access_cannot_write(con, agent_id):
    e = check_write_action(con, agent_id=agent_id, actor=SUBMITTER, action="schreiben")
    assert e.outcome is Outcome.DENIED
    assert e.rule == "least_privilege"


@pytest.mark.parametrize("agent_id,level", [("abgleich", 1), ("klassifikation", 2),
                                            ("kostenstelle", 2)])
def test_level_1_and_2_cannot_write(con, agent_id, level):
    """A level 1/2 agent may not execute even at 0 EUR.

    The level is checked before the amount -- a small amount must not
    override a too-low autonomy level.
    """
    e = check_write_action(con, agent_id=agent_id, actor=SUBMITTER,
                           action="schreiben", amount_eur=0.0)
    assert e.outcome is Outcome.DENIED
    assert e.rule in ("least_privilege", "autonomy_level")


# ---------------------------------------- Booking agent: always HITL

@pytest.mark.parametrize("amount", [0.01, 1_500.0, 25_000.0, 500_000.0])
def test_booking_always_needs_approval(con, amount):
    """Thesis §7.4 / Table 11: the financially effective booking step is
    human-in-the-loop -- regardless of the amount. There is deliberately no
    threshold above which it would be booked automatically.
    """
    e = check_write_action(con, agent_id="buchung", actor=SUBMITTER,
                           action="verbuchen", amount_eur=amount)
    assert e.outcome is Outcome.APPROVAL_NEEDED
    assert e.rule == "oversight_mode"


def test_booking_needs_approval_even_without_amount(con):
    e = check_write_action(con, agent_id="buchung", actor=SUBMITTER,
                           action="verbuchen")
    assert e.outcome is Outcome.APPROVAL_NEEDED


# ------------------------------------------------ Rule 4: oversight mode

def test_elo_agent_is_on_the_loop_and_runs_automatically(con):
    """The ELO agent (level 3, human-on-the-loop) is the end of process B.

    The human approval in process B sits at the cost-center step before it,
    and only on ambiguity (four-eyes); archiving is not asked again.
    """
    e = check_write_action(con, agent_id="elo", actor=SUBMITTER, action="archivieren")
    assert e.outcome is Outcome.ALLOWED
    assert e.rule == "oversight_mode"


# --------------------------------------------------------- Reader access

def test_reader_access_for_group_member(con):
    assert check_reader_access(con, actor=SUBMITTER).outcome is Outcome.ALLOWED


def test_reader_access_without_group_is_denied(con):
    """Scenario 5 at the policy level."""
    e = check_reader_access(con, actor=EXTERNAL)
    assert e.outcome is Outcome.DENIED
    assert "SG-CHG-DocIngest" in e.reason


def test_reader_access_unknown_user_denied(con):
    e = check_reader_access(con, actor="niemand@nirgends.de")
    assert e.outcome is Outcome.DENIED


# ------------------------------------------- Approval / four-eyes principle

def test_approver_may_approve(con):
    assert check_approval(con, actor=APPROVER, agent_id="kostenstelle").allowed


def test_approver_may_not_approve_own_document(con):
    e = check_approval(
        con, actor=APPROVER, submitter=APPROVER, agent_id="kostenstelle"
    )

    assert e.outcome is Outcome.DENIED
    assert e.rule == "four_eyes"
    assert "verschiedene Personen" in e.reason


def test_submitter_may_not_approve(con):
    """Four-eyes principle: whoever submits does not also approve."""
    e = check_approval(con, actor=SUBMITTER, agent_id="kostenstelle")
    assert e.outcome is Outcome.DENIED
    assert "SG-CHG-Freigabe" in e.reason


def test_external_may_not_approve(con):
    assert not check_approval(con, actor=EXTERNAL, agent_id="kostenstelle").allowed


# ---------------------------------------------------------- Miscellaneous

def test_unknown_agent_is_a_programming_error(con):
    """No default fallback: the policy must not check against a guess."""
    with pytest.raises(KeyError, match="Unknown agent"):
        check_write_action(con, agent_id="gibt_es_nicht", actor=SUBMITTER, action="x")


def test_ruling_carries_reason_and_rule(con):
    """Every decision is auditably justified."""
    e = check_write_action(con, agent_id="abgleich", actor=SUBMITTER, action="schreiben")
    assert e.rule and e.reason
    assert e.context["agent"] == "abgleich"
