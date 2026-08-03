"""Tests of the target-system effect.

The effect is the actual evidence of a run: CLI and UI both show this
query, so it must also answer the edge cases cleanly instead of raising.
"""

from __future__ import annotations

import pytest

from graph.effects import read_effect


@pytest.fixture
def master_data(con):
    con.execute("INSERT INTO suppliers VALUES ('L1','Musterlieferant GmbH',NULL,NULL)")
    con.executemany("INSERT INTO invoices VALUES (?,?,?,?,?,?)", [
        ("RE-2026-4200", 1341.96, "2026-08-01", "bezahlt", "L1", "2026-07-29T10:00:00"),
        ("RE-2026-4201", 500.00, "2026-08-01", "offen", "L1", None),
    ])
    con.execute("INSERT INTO archive VALUES ('ELO-2026-0001','b.pdf','abc123',"
                "'2026-07-29T11:00:00')")
    con.commit()
    return con


def test_booked_payment_shows_navision_status(master_data):
    w = read_effect(master_data, {"number": "RE-2026-4200"})

    assert w.navision_number == "RE-2026-4200"
    assert w.navision_status == "bezahlt"
    assert w.navision_paid_at == "2026-07-29T10:00:00"
    assert w.has_effect


def test_open_invoice_is_reported_as_open(master_data):
    w = read_effect(master_data, {"number": "RE-2026-4201"})

    assert w.navision_status == "offen"
    assert w.navision_paid_at is None


def test_unknown_number_is_not_an_error(master_data):
    """Scenario 2: the number is not in the master data.

    This is a regular business case (exception case) and must not break the
    display.
    """
    w = read_effect(master_data, {"number": "RE-9999-0000"})

    assert w.navision_status is None
    assert w.navision_number is None
    assert not w.has_effect


def test_archiving_shows_elo_reference(master_data):
    w = read_effect(master_data, {"archive_id": "ELO-2026-0001"})

    assert w.elo_archive_id == "ELO-2026-0001"
    assert w.elo_filed_at == "2026-07-29T11:00:00"
    assert w.has_effect


def test_case_without_target_system_contact(master_data):
    """Scenario 5 ends before any target system -- there is nothing to show."""
    w = read_effect(master_data, {"outcome": "zugriff_verweigert"})

    assert not w.has_effect
    assert w.navision_status is None
    assert w.elo_archive_id is None
