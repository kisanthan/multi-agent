"""Tests of the case overview.

`determine_status` and `process_of` are the basis of the UI's case list.
They are kept pure, so exactly this is testable without LangGraph and
without Streamlit.
"""

from __future__ import annotations

from graph.cases import Status, process_of, determine_status


def test_waiting_case_needs_approval():
    """An active interrupt is the strongest statement about the status."""
    assert determine_status({}, waiting=True) is Status.WAITING_FOR_APPROVAL


def test_interrupt_overrides_old_outcome_value():
    """After a partial run, the state may still hold an old value.

    The case is nonetheless hanging at the approval point -- otherwise the
    queue would not show it and no one could resume it.
    """
    values = {"completed": True, "outcome": "verbucht"}
    assert determine_status(values, waiting=True) is Status.WAITING_FOR_APPROVAL


def test_running_case():
    assert determine_status({"document_type": "eingangsrechnung"}, waiting=False) is Status.RUNNING


def test_booked_payment_is_completed():
    values = {"completed": True, "outcome": "verbucht"}
    assert determine_status(values, waiting=False) is Status.COMPLETED


def test_archived_invoice_is_completed():
    """Process B ends at ELO -- that is a full-fledged completion."""
    values = {"completed": True, "outcome": "archiviert"}
    assert determine_status(values, waiting=False) is Status.COMPLETED


def test_rejected_case():
    values = {"completed": True, "outcome": "verworfen"}
    assert determine_status(values, waiting=False) is Status.REJECTED


def test_ad_check_denial_is_its_own_status():
    """Scenario 5 is not a failure, but an effective governance rule."""
    values = {"completed": True, "outcome": "zugriff_verweigert"}
    assert determine_status(values, waiting=False) is Status.DENIED


def test_target_system_rejection_is_failed():
    values = {"completed": True, "outcome": "abgelehnt"}
    assert determine_status(values, waiting=False) is Status.FAILED


def test_unreachable_booking_system_is_failed():
    values = {
        "completed": True,
        "outcome": "buchungssystem_nicht_erreichbar",
    }
    assert determine_status(values, waiting=False) is Status.FAILED


def test_unknown_outcome_does_not_count_as_success():
    """Default deny in the display too: nothing unexpected turns green."""
    values = {"completed": True, "outcome": "voellig_neuer_wert"}
    assert determine_status(values, waiting=False) is Status.FAILED


def test_closed_duplicate_is_a_completed_business_case():
    values = {"completed": True, "outcome": "dublette_geschlossen"}
    assert determine_status(values, waiting=False) is Status.COMPLETED


def test_open_statuses():
    assert Status.RUNNING.is_open
    assert Status.WAITING_FOR_APPROVAL.is_open
    assert not Status.COMPLETED.is_open
    assert not Status.DENIED.is_open


def test_process_assignment_by_document_type():
    assert process_of({"document_type": "zahlungsbestaetigung"}) == "A"
    assert process_of({"document_type": "eingangsrechnung"}) == "B"


def test_process_is_undetermined_before_classification():
    """On the shared intake stretch, the case belongs to no process."""
    assert process_of({}) is None
    assert process_of({"document_type": "unbekannt"}) is None
