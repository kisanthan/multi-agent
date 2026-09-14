"""Precise user-facing result messages for process-specific failures."""

from ui.cases import process_views
from ui.shared import i18n


def test_unreachable_booking_system_explains_approval_and_missing_effect():
    i18n.set_language("de")
    text = process_views.result_text(
        "buchungssystem_nicht_erreichbar", "A"
    )

    assert "Freigabe wurde erteilt" in text
    assert "Navision" in text
    assert "nicht verbucht" in text
    assert "bleibt offen" in text


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
