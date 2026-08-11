"""Unit tests for the booking agent's write-site permission re-check.

`book()`'s `approved_by` branch is only reachable via the graph after
`node_exception_case`'s own `check_approval` gate
(graph/nodes/payment_confirmation.py) -- so under normal operation via the
graph, this module's re-check never actually denies anything (see
tests/test_scenarios.py for that path). It exists for exactly what the
graph cannot control: a direct call to `book()` -- a script, a future code
path, a test -- that passes a forged `approved_by` string. These tests are
the only way to exercise that branch at all.
"""

from __future__ import annotations

from agents.payment_confirmation import booking
from governance.audit import read_all, verify_chain


def _open_invoice(con, number="RE-TEST-0001", amount=500.0):
    con.execute(
        "INSERT INTO suppliers VALUES (?,?,?,?)",
        ("LIF-TEST", "Test Supplier GmbH", "DE000000000", "Teststr. 1, 12345 Testort"),
    )
    con.execute(
        "INSERT INTO invoices VALUES (?,?,?,?,?,?)",
        (number, amount, "2026-08-01", "offen", "LIF-TEST", None),
    )
    con.commit()


def _forbid_navision_call(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Navision must not be called when the approver is denied")
    monkeypatch.setattr("agents.payment_confirmation.booking.httpx.post", fail_if_called)


def test_approved_by_user_without_freigabe_group_is_denied_not_booked(con, monkeypatch):
    _open_invoice(con)
    _forbid_navision_call(monkeypatch)

    # Member of SG-CHG-DocIngest only (see tests/conftest.py) -- not SG-CHG-Freigabe.
    result = booking.book(con, number="RE-TEST-0001", amount_eur=500.0,
                          actor="einspeiser@chg-meridian.com", document="test.pdf",
                          approved_by="einspeiser@chg-meridian.com")

    assert result.booked is False
    assert result.approval_needed is False

    entries = [e for e in read_all(con) if e.action == "freigabe_verweigert"]
    assert any("SG-CHG-Freigabe" in e.reason for e in entries)
    assert verify_chain(con).valid


def test_approved_by_unknown_user_is_denied_not_booked(con, monkeypatch):
    _open_invoice(con)
    _forbid_navision_call(monkeypatch)

    result = booking.book(con, number="RE-TEST-0001", amount_eur=500.0,
                          actor="einspeiser@chg-meridian.com", document="test.pdf",
                          approved_by="unbekannt@nirgendwo.de")

    assert result.booked is False
    entries = [e for e in read_all(con) if e.action == "freigabe_verweigert"]
    assert any("Zero Trust" in e.reason for e in entries)
    assert verify_chain(con).valid


def test_approved_by_authorized_user_still_proceeds_to_booking(con, monkeypatch):
    """Sanity check: the re-verification must not break the legitimate path."""
    _open_invoice(con)
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {}

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr("agents.payment_confirmation.booking.httpx.post", fake_post)

    # Member of both SG-CHG-DocIngest and SG-CHG-Freigabe (see tests/conftest.py).
    result = booking.book(con, number="RE-TEST-0001", amount_eur=500.0,
                          actor="einspeiser@chg-meridian.com", document="test.pdf",
                          approved_by="pruefer@chg-meridian.com")

    assert calls, "Navision should have been called for an authorized approver"
    assert result.booked is True
    assert verify_chain(con).valid
