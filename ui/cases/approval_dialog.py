"""The approval point as a modal dialog.

Why a dialog and not a section on the page: human-in-the-loop means the
case *stops* and does not proceed without a decision. A modal reproduces
that on screen -- it covers the page and has to be dealt with. A form
further down a scrollable page reads like a suggestion, and the thesis's
claim (Abschnitt 2.2, 6.5) is precisely that this is not one.

The counterpart matters just as much: where an agent is human-*on*-the-loop,
nothing pops up during the run at all. The case goes through and reports
afterwards -- so the presence or absence of this dialog is itself the
visible difference between the two oversight modes.

When it does open, `oversight_note()` says which of the two rules produced
the stop:

- `OVERSIGHT_MODE` -- the agent stops every time, on the happy path too.
  Nothing went wrong (the booking agent).
- `ESCALATION` -- the agent normally runs through and could not decide
  this one (the cost-center and reconciliation agents).

It says so in plain language, not in the concept's vocabulary -- see
`oversight_note()`.

The dialog renders no fields of its own: it delegates to
`ui.cases.detail.decision_form`, so the modal and the inline form can
never drift apart.
"""

from __future__ import annotations

import streamlit as st

import agent_registry
import process_registry
from agent_registry import OversightMode
from contracts import ApprovalTrigger
from ui.shared import i18n

# Session key of the case whose dialog was dismissed with "Später". Keeps
# the modal from reopening on the very next rerun while the case stays in
# the queue -- dismissing is not deciding.
DISMISSED = "approval_dialog_dismissed"


def agent_of(request: dict) -> tuple[str, str | None]:
    """The agent whose oversight mode governs this approval point.

    Derived, not tabulated: the interrupt kind names the process
    (`process_registry.for_interrupt`), the process names the agent of its
    approval step (`approval_agent_id`), and the agent registry holds the
    oversight mode. Adding a process therefore needs no entry here.
    """
    config = process_registry.for_interrupt(request.get("kind"))
    agent_id = (config.approval_agent_id if config else None) or "buchung"
    return agent_id, (config.key if config else None)


def oversight_note(request: dict) -> tuple[str, str, str]:
    """Headline, explanation, and icon for the top of the dialog.

    Says what this stop *means*, not merely that it happened -- and says it
    without the concept's vocabulary. The words "Human-in-the-loop" and
    "Human-on-the-loop" do not appear here on purpose: they belong on the
    Architektur page, which explains them, and `tests/test_ui_language.py`
    keeps them off the working views. What the approver needs is not the
    label but its consequence, and that is exactly what distinguishes the
    two triggers:

    - stopping is this step's normal behaviour and nothing is wrong, or
    - the step normally runs through and did not manage this one.
    """
    agent_id, _ = agent_of(request)
    config = agent_registry.get_config(agent_id)
    trigger = request.get("trigger") or ApprovalTrigger.ESCALATION.value

    if trigger == ApprovalTrigger.OVERSIGHT_MODE.value:
        return (
            i18n.t("oversight.always.headline"),
            i18n.t("oversight.always.text"),
            "🔒",
        )

    runs_through_normally = config.oversight is OversightMode.HUMAN_ON_THE_LOOP
    return (
        i18n.t("oversight.stuck.headline"),
        i18n.t("oversight.stuck.text.usually_automatic" if runs_through_normally
               else "oversight.stuck.text.other"),
        "❓",
    )


def open_decision(app, thread_id: str, request: dict, values: dict, *,
                  upn: str) -> None:
    """The modal. Blocks the page until it is decided or set aside.

    `st.dialog` takes its title at decoration time, so the decorated
    function is built here on each call rather than once at import: only
    then can the title follow the language the user just switched to.
    """
    from ui.cases.detail import decision_form

    @st.dialog(i18n.t("dialog.title"), width="large")
    def _modal() -> None:
        headline, explanation, icon = oversight_note(request)
        st.markdown(f"### {icon} {headline}")
        st.info(explanation)

        if values.get("filename"):
            st.caption(i18n.t("dialog.document", filename=values["filename"]))

        # On a submitted decision this runs the graph and calls
        # `st.rerun()`, which ends the script -- so nothing below executes
        # in that case and the dialog closes on its own. Process A stops
        # twice (exception case, then booking approval); the second stop
        # opens a fresh dialog.
        decision_form(app, thread_id, request, values, upn=upn)

        st.divider()
        if st.button(i18n.t("dialog.later"), width="stretch",
                     key=f"later_{thread_id}"):
            # The case stays in the checkpoint and in the list. That it can
            # be set aside without being lost is the point of the
            # checkpointer.
            st.session_state[DISMISSED] = thread_id
            st.rerun()

    _modal()


def should_open(thread_id: str) -> bool:
    """Whether the modal may open for this case on this rerun."""
    return st.session_state.get(DISMISSED) != thread_id


def reset(thread_id: str) -> None:
    """Lets the modal open again for a case that was set aside."""
    if st.session_state.get(DISMISSED) == thread_id:
        st.session_state.pop(DISMISSED, None)
