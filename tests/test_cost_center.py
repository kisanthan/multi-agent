"""Unit tests for the cost-center agent (deterministic reference lookup).

Complements tests/test_scenarios.py, which exercises UNIQUE_MATCH (scenario
3) and MISSING_REFERENCE (scenario 4) end-to-end through the full graph.
Finding.UNKNOWN_REFERENCE -- a reference that IS present on the document but
does not resolve to any catalog entry -- had neither a fixture document nor
a test.
"""

from __future__ import annotations

from agents.incoming_invoice import cost_center

ACTOR = "einspeiser@chg-meridian.com"


def _add_cost_center(con, id_="KST-9000", name="Test-Kostenstelle", reference="KTR-TEST"):
    con.execute("INSERT INTO cost_centers VALUES (?,?,?,?)",
               (id_, name, reference, "test"))
    con.commit()


def test_known_reference_resolves_uniquely(con):
    _add_cost_center(con)

    result = cost_center.assign(con, cost_center_reference="KTR-TEST", actor=ACTOR)

    assert result.finding is cost_center.Finding.UNIQUE_MATCH
    assert result.unique is True
    assert result.cost_center_id == "KST-9000"


def test_missing_reference_is_not_unique(con):
    result = cost_center.assign(con, cost_center_reference=None, actor=ACTOR)

    assert result.finding is cost_center.Finding.MISSING_REFERENCE
    assert result.unique is False
    assert result.cost_center_id is None


def test_unknown_reference_is_not_unique(con):
    """A reference IS printed on the document but matches no catalog entry
    -- previously untested. Must fall into the same exception-case path as
    a missing reference (route_cost_center only checks `.unique`), not
    crash or silently resolve to nothing."""
    _add_cost_center(con)

    result = cost_center.assign(con, cost_center_reference="KTR-NICHT-VORHANDEN", actor=ACTOR)

    assert result.finding is cost_center.Finding.UNKNOWN_REFERENCE
    assert result.unique is False
    assert result.cost_center_id is None
    assert "KTR-NICHT-VORHANDEN" in result.reason


def test_reference_normalizes_markdown_artifacts(con):
    """The parser occasionally returns '**KTR-TEST**' -- normalize() must
    still resolve it."""
    _add_cost_center(con)

    result = cost_center.assign(con, cost_center_reference="**KTR-TEST**", actor=ACTOR)

    assert result.finding is cost_center.Finding.UNIQUE_MATCH
    assert result.cost_center_id == "KST-9000"
