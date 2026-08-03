"""Tests of the process display.

The stepper is where a viewer reads off the flow -- a wrongly marked step
claims something that did not happen. Especially tricky: the booking node
runs twice (first "approval required", then the real attempt), and process
B skips the approval in the normal case.
"""

from __future__ import annotations

from graph.cases import Status
from ui.shared.formatting import format_euro, timestamp
from ui.cases.steps import StepStatus, steps_for


def _by_node(steps):
    return {s.node: s.status for s in steps}


def _log(*nodes: str) -> list[dict]:
    return [{"node": k, "text": "-"} for k in nodes]


# ------------------------------------------------------------- Process A

def test_process_a_waits_for_booking_approval():
    """After the first booking attempt, the case hangs at the approval point.

    The booking step must NOT count as done here -- nothing has been booked
    yet, the node only requested approval.
    """
    steps = steps_for(
        "A", _log("reader", "klassifikation", "abgleich", "buchung"),
        waiting_on="klaerfall", status=Status.WAITING_FOR_APPROVAL,
    )
    by_node = _by_node(steps)

    assert by_node["abgleich"] is StepStatus.DONE
    assert by_node["klaerfall"] is StepStatus.ACTIVE
    assert by_node["buchung"] is StepStatus.OPEN


def test_process_a_booked_after_approval():
    steps = steps_for(
        "A", _log("reader", "klassifikation", "abgleich", "buchung",
                  "klaerfall", "buchung"),
        status=Status.COMPLETED,
    )
    by_node = _by_node(steps)

    assert by_node["klaerfall"] is StepStatus.DONE
    assert by_node["buchung"] is StepStatus.DONE
    assert all(s.status is StepStatus.DONE for s in steps)


def test_process_a_target_system_rejects():
    """Navision rejects the booking -- the step has failed."""
    steps = steps_for(
        "A", _log("reader", "klassifikation", "abgleich", "buchung",
                  "klaerfall", "buchung"),
        status=Status.FAILED,
    )

    assert _by_node(steps)["buchung"] is StepStatus.FAILED


def test_rejected_case_does_not_book():
    steps = steps_for(
        "A", _log("reader", "klassifikation", "abgleich", "buchung", "klaerfall"),
        status=Status.REJECTED,
    )

    assert _by_node(steps)["buchung"] is StepStatus.OPEN


# ------------------------------------------------------------- Process B

def test_process_b_skips_approval_on_unique_reference():
    """The normal case in B: human-on-the-loop, no approval needed."""
    steps = steps_for(
        "B", _log("reader", "klassifikation", "kostenstelle", "elo"),
        status=Status.COMPLETED,
    )
    by_node = _by_node(steps)

    assert by_node["freigabe"] is StepStatus.SKIPPED
    assert by_node["elo"] is StepStatus.DONE


def test_process_b_waits_for_cost_center_approval():
    steps = steps_for(
        "B", _log("reader", "klassifikation", "kostenstelle"),
        waiting_on="kostenstellen_freigabe", status=Status.WAITING_FOR_APPROVAL,
    )
    by_node = _by_node(steps)

    assert by_node["kostenstelle"] is StepStatus.DONE
    assert by_node["freigabe"] is StepStatus.ACTIVE
    assert by_node["elo"] is StepStatus.OPEN


def test_process_b_archived_after_approval():
    steps = steps_for(
        "B", _log("reader", "klassifikation", "kostenstelle", "freigabe", "elo"),
        status=Status.COMPLETED,
    )

    assert _by_node(steps)["freigabe"] is StepStatus.DONE


# --------------------------------------------------- Shared stretch

def test_ad_check_denial_marks_reader_as_failed():
    """Scenario 5: the case ends at the first step."""
    steps = steps_for(None, _log("reader"), status=Status.DENIED)
    by_node = _by_node(steps)

    assert by_node["reader"] is StepStatus.FAILED
    assert by_node["klassifikation"] is StepStatus.OPEN


def test_before_classification_only_shared_stretch():
    """As long as the type is not known, the case belongs to no process."""
    steps = steps_for(None, _log("reader"), status=Status.RUNNING)

    assert [s.node for s in steps] == ["reader", "klassifikation"]


# ------------------------------------------------------------ Formatting

def test_format_euro_uses_german_notation():
    assert format_euro(1341.96) == "1.341,96 €"
    assert format_euro(35632.01) == "35.632,01 €"
    assert format_euro(5.0) == "5,00 €"


def test_format_euro_without_a_value():
    assert format_euro(None) == "—"


def test_timestamp_shortens_iso():
    assert timestamp("2026-07-29T17:27:49.123456+00:00") == "29.07.2026, 17:27"


def test_timestamp_stays_readable_on_unexpected_format():
    assert timestamp("kein Zeitstempel") == "kein Zeitstempel"
    assert timestamp(None) == "—"
