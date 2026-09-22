"""Precise user-facing result messages for process-specific failures."""

from ui.cases import process_views
from ui.cases.process_views import payment_confirmation
from ui.shared import i18n


def test_unreachable_booking_system_explains_approval_and_missing_effect():
    i18n.set_language("de")
    text = process_views.result_text(
        "buchungssystem_nicht_erreichbar", "A"
    )

    assert "Freigabe wurde erteilt" in text
    assert "Navision" in text
    assert "Ausführungsbeleg" in text
    assert "nicht verbucht" not in text


def test_legacy_connection_refusal_is_displayed_as_unreachable():
    displayed = process_views.display_outcome(
        "abgelehnt",
        "A",
        "[WinError 10061] Der Zielcomputer hat die Verbindung verweigert",
    )

    assert displayed == "buchungssystem_nicht_erreichbar"


def test_business_rejection_stays_a_business_rejection():
    displayed = process_views.display_outcome(
        "abgelehnt",
        "A",
        "Rechnung ist bereits bezahlt",
    )

    assert displayed == "abgelehnt"


def test_duplicate_actions_cannot_look_like_a_posting_approval():
    actions = payment_confirmation.decision_actions(
        {"finding": "bereits_bezahlt", "trigger": "eskalation"},
        {"_changed": False},
    )

    assert actions["reject"] == "Als Dublette schließen"
    assert actions["confirm"] == "Korrigierte Daten erneut prüfen"
    assert actions["confirm_disabled"] is True


def test_normal_payment_names_the_financial_effect():
    actions = payment_confirmation.decision_actions(
        {"finding": "ok", "trigger": "aufsichtsmodus"},
        {"_changed": False},
    )

    assert actions["confirm"] == "Buchung freigeben"
    assert actions["reject"] == "Buchung ablehnen"
