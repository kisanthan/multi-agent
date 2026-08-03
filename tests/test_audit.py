"""Tests of the audit trail -- the thesis's tamper-evidence proof.

The core is test_verify_chain_detects_*: the chain must detect a subsequent
change. Without this proof, "tamper-evident" would just be a claim.
"""

from __future__ import annotations

import pytest

from governance.audit import (
    GENESIS_HASH,
    CaseReference,
    Decision,
    cases_in_trail,
    log_entry,
    read_all,
    verify_chain,
)


REFERENCE = CaseReference("vorgang-1", "a.pdf")


def _three_entries(con):
    log_entry(con, actor="einspeiser@chg-meridian.com", agent="reader",
             action="dokument_eingespeist", decision=Decision.ALLOWED,
             reason="AD-Check bestanden", payload={"datei": "a.pdf"},
             reference=REFERENCE, outcome="1 Seite(n) gelesen")
    log_entry(con, actor="einspeiser@chg-meridian.com", agent="abgleich",
             action="nummer_abgeglichen", decision=Decision.INFO,
             reason="RE-2026-4200 gefunden", payload={"nummer": "RE-2026-4200"},
             reference=REFERENCE, outcome="ok")
    log_entry(con, actor="einspeiser@chg-meridian.com", agent="buchung",
             action="zahlung_verbucht", decision=Decision.ALLOWED,
             reason="freigegeben", payload={"betrag": 1234.56},
             reference=REFERENCE, outcome="verbucht")
    con.commit()


def test_first_entry_points_to_genesis(con):
    e = log_entry(con, actor="a@b.c", action="start",
                 decision=Decision.INFO, reason="Systemstart")
    assert e.prev_hash == GENESIS_HASH


def test_chain_links_continuously(con):
    _three_entries(con)
    entries = read_all(con)

    assert len(entries) == 3
    assert entries[0].prev_hash == GENESIS_HASH
    # Every entry points to the hash of its predecessor.
    assert entries[1].prev_hash == entries[0].hash
    assert entries[2].prev_hash == entries[1].hash


def test_intact_chain_is_recognized_as_valid(con):
    _three_entries(con)
    result = verify_chain(con)
    assert result.valid
    assert result.checked == 3


def test_empty_chain_is_valid(con):
    assert verify_chain(con).valid


def test_trigger_prevents_update(con):
    """The database itself rejects an UPDATE -- append-only is enforced."""
    _three_entries(con)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE audit SET reason = 'manipuliert' WHERE id = 2")


def test_trigger_prevents_delete(con):
    _three_entries(con)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM audit WHERE id = 2")


def test_verify_chain_detects_content_tampering(con):
    """Core proof: a subsequent change breaks the chain.

    The triggers are deliberately bypassed here to simulate the case that
    someone with direct database access (i.e. bypassing the application)
    forges an entry. That is exactly what the hash chaining protects
    against -- the trigger alone would not catch it.
    """
    _three_entries(con)
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("UPDATE audit SET reason = 'war schon immer erlaubt' WHERE id = 2")
    con.commit()

    result = verify_chain(con)
    assert not result.valid
    assert result.broken_at == 2
    assert "Aenderung" in result.reason


def test_verify_chain_detects_changed_actor(con):
    """The actor is hashed too -- an attribution cannot be forged."""
    _three_entries(con)
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("UPDATE audit SET actor = 'jemand.anderes@chg-meridian.com' WHERE id = 3")
    con.commit()

    assert not verify_chain(con).valid


def test_verify_chain_detects_deleted_entry(con):
    """A removed entry leaves a gap in the chain."""
    _three_entries(con)
    con.execute("DROP TRIGGER audit_no_delete")
    con.execute("DELETE FROM audit WHERE id = 2")
    con.commit()

    result = verify_chain(con)
    assert not result.valid
    # Entry 3 now points to a predecessor that no longer exists.
    assert result.broken_at == 3
    assert "geloeschten oder eingefuegten" in result.reason


def test_verify_chain_detects_reassigned_case(con):
    """The case reference is hashed -- an entry cannot be reassigned.

    If `case_id` were excluded from the hash, a denied action could be
    attributed to a different case afterwards without breaking the chain --
    and the filtered trail would lie.
    """
    _three_entries(con)
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("UPDATE audit SET case_id = 'ein-anderer-vorgang' WHERE id = 2")
    con.commit()

    assert not verify_chain(con).valid


def test_verify_chain_detects_changed_source(con):
    _three_entries(con)
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("UPDATE audit SET source = 'ein_anderer_beleg.pdf' WHERE id = 1")
    con.commit()

    assert not verify_chain(con).valid


def test_verify_chain_detects_changed_outcome(con):
    """A subsequently whitewashed outcome must be noticed.

    Entry 3 is 'verbucht'; here it gets rewritten to 'abgelehnt' -- the
    direction does not matter, any change must break the chain.
    """
    _three_entries(con)
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("UPDATE audit SET outcome = 'abgelehnt' WHERE id = 3")
    con.commit()

    assert not verify_chain(con).valid


def test_entries_can_be_filtered_by_case(con):
    _three_entries(con)
    log_entry(con, actor="a@b.c", agent="reader", action="dokument_eingespeist",
             decision=Decision.ALLOWED, reason="anderer Lauf",
             reference=CaseReference("vorgang-2", "b.pdf"))
    con.commit()

    entries = read_all(con, case_id="vorgang-1")

    assert len(entries) == 3
    assert {e.case_id for e in entries} == {"vorgang-1"}
    assert sorted(cases_in_trail(con)) == ["vorgang-1", "vorgang-2"]


def test_entries_without_a_case_dont_disturb_the_filter(con):
    """An upload belongs to no case and must not show up in any."""
    log_entry(con, actor="a@b.c", action="datei_hochgeladen",
             decision=Decision.ALLOWED, reason="abgelegt",
             reference=CaseReference(None, "c.pdf"))
    con.commit()

    assert read_all(con, case_id="vorgang-1") == []
    assert cases_in_trail(con) == []
    assert verify_chain(con).valid


def test_payload_hash_is_order_independent(con):
    """Same content, different dict order -> same hash.

    Otherwise the chain would not be reproducibly verifiable.
    """
    a = log_entry(con, actor="a@b.c", action="x", decision=Decision.INFO,
                 reason="-", payload={"eins": 1, "zwei": 2})
    b = log_entry(con, actor="a@b.c", action="x", decision=Decision.INFO,
                 reason="-", payload={"zwei": 2, "eins": 1})
    assert a.payload_hash == b.payload_hash
