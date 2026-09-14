"""Case detail view: stepper, approval, confirmation.

One view for all processes -- what differs by business (which fields
appear in the header) comes from `process_registry`, not from case
distinctions here.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

import process_registry
from contracts import (
    ApprovalDecision,
    ApprovalResponse,
    ApprovalTrigger,
    CaseOutcome,
)
from governance.audit import verify_chain
from governance.policy import check_approval
from graph.cases import Status, process_of, determine_status
from graph.effects import read_effect
from ui.shared import i18n
from ui.shared import style
from ui.shared import user
from ui.shared.formatting import field
from ui.shared.context import connection, show_audit_for
from ui.cases import approval_dialog, process_views
from ui.cases.run import resume
from ui.cases.steps import steps_for


def render(app, thread_id: str, *, upn: str, with_title: bool = True) -> None:
    """Renders a case in full."""
    snapshot = app.get_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values or {}

    if not values:
        st.warning(i18n.t("detail.no_data"))
        return

    request = snapshot.interrupts[0].value if snapshot.interrupts else None
    status = determine_status(values, waiting=bool(request))
    process = process_of(values)
    displayed_outcome = process_views.display_outcome(
        values.get("outcome", ""), process, values.get("error")
    )

    _header(values, status, process, thread_id, with_title=with_title)
    style.stepper(steps_for(process, values.get("log", []),
                            waiting_on=(request or {}).get("kind"), status=status,
                            outcome=displayed_outcome))

    if request:
        _waiting_card(app, thread_id, request, values, upn=upn)
    else:
        _outcome(values, status, process, displayed_outcome)

    # The step name is translated, the recorded text is not: what a node
    # wrote down is evidence and stays in the wording it was written in
    # (see ui/shared/i18n.py).
    with st.expander(i18n.t("detail.history")):
        for entry in values.get("log", []):
            st.markdown(
                f"**{i18n.step_title(entry['node'])}** — {entry['text']}")

    _document_preview(values.get("path"))

    if st.button(i18n.t("detail.audit_button"), key=f"audit_{thread_id}",
                 width="content",
                 help=i18n.t("detail.audit_button.help")):
        show_audit_for(thread_id)


def _header(values: dict, status: Status, process: str | None, thread_id: str, *,
           with_title: bool) -> None:
    config = process_registry.get_config(process) if process else None
    # The document kind, not the process name: this is about a single
    # document, and "Zahlungsbestätigung" says more about it than
    # "Zahlungseingang". No "Prozess A" -- the A/B assignment lives on the
    # architecture page.
    process_text = (i18n.process_text(config, "document_kind") if config
                    else i18n.t("detail.kind_detecting"))

    if with_title:
        st.subheader(values.get("filename") or thread_id)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.badge(i18n.status_label(status), color=style.badge_color(status))
        st.caption(process_text)

    # Which fields matter for the business is known by the process.
    business_fields = list(config.detail_fields) if config else ["number"]
    left, right = st.columns(2)
    with left:
        style.fields(values, ["actor", "started_at"])
    with right:
        style.fields(values, business_fields)


def _waiting_card(app, thread_id: str, request: dict, values: dict, *,
                  upn: str) -> None:
    """A waiting case: opens the modal, and keeps a way back to it.

    The decision itself belongs in the dialog (see
    `ui/cases/approval_dialog.py`) -- a case that stops must *look* like it
    stopped. What stays on the page is only the note that it is waiting,
    plus the button to reopen a dialog that was set aside.
    """
    headline, explanation, icon = approval_dialog.oversight_note(request)

    st.markdown(f"#### {icon} {headline}")
    st.info(explanation)

    submitter = values.get("actor")
    own_submission = bool(
        submitter and upn.casefold() == str(submitter).casefold()
    )

    # The uploader cannot approve their own document (four-eyes policy),
    # so interrupting them with an approval dialog would suggest an action
    # they cannot perform. Another eligible person still gets the dialog
    # automatically. The uploader may open it manually to inspect why the
    # case is waiting.
    if not own_submission and approval_dialog.should_open(thread_id):
        approval_dialog.open_decision(app, thread_id, request, values, upn=upn)
    elif st.button(i18n.t("detail.reopen"), type="primary",
                   key=f"reopen_{thread_id}", width="stretch"):
        approval_dialog.reset(thread_id)
        approval_dialog.open_decision(app, thread_id, request, values, upn=upn)


def _is_oversight_stop(request: dict) -> bool:
    """Did the agent's standing oversight mode stop this, or an escalation?"""
    return request.get("trigger") == ApprovalTrigger.OVERSIGHT_MODE.value


def decision_form(app, thread_id: str, request: dict, values: dict, *,
                  upn: str) -> bool:
    """The approval form itself. Returns whether a decision was submitted.

    Lives here rather than in the dialog module so the evidence rows, the
    per-process input, and the four-eyes handling exist exactly once --
    the dialog is the frame, this is the content.
    """
    kind = request.get("kind", "")
    config = process_registry.for_interrupt(kind)
    agent_id = (config.approval_agent_id if config else None) or "buchung"

    con = connection()
    try:
        person = user.load(con, upn)
        decision = check_approval(
            con, actor=upn, agent_id=agent_id, submitter=values.get("actor")
        )
    finally:
        con.close()

    # What appears here depends on who is looking: whoever may decide is
    # prompted to; whoever may not gets context instead of a prompt.
    if decision.allowed:
        st.markdown(f"#### {i18n.t('detail.your_decision')}")
    else:
        st.markdown(f"#### {i18n.t('detail.waiting')}")

    # `reason` is the policy's own wording, written verbatim into the audit
    # trail ("Buchungs-Agent ist Human-in-the-loop -- Freigabe
    # erforderlich"). That belongs in the trail, where it must not be
    # reworded, but not in front of an approver: it is the concept's
    # vocabulary (tests/test_ui_language.py), and for a standing
    # human-in-the-loop stop it only restates what the dialog's own
    # headline already says in plain language. On an escalation it carries
    # real evidence ("Der Beleg nennt keine Kostenstellenreferenz") and
    # stays -- and stays in its recorded wording, untranslated, for exactly
    # the same reason it is not reworded (see ui/shared/i18n.py).
    shown = ("finding", "escalation") if _is_oversight_stop(request) else (
        "reason", "finding", "escalation")
    rows = [field(s, request[s]) for s in shown if request.get(s)]
    if rows:
        with st.container(border=True):
            for label, value in rows:
                style.value_row(label, value)

    if request.get("line_items"):
        st.markdown(f"**{i18n.t('detail.line_items')}:** "
                    + ", ".join(request["line_items"]))

    view = process_views.for_interrupt(kind)
    extra_response = view.approval_inputs(request, thread_id=thread_id) if view else {}

    if decision.rule == "four_eyes":
        st.warning(person.own_document_hint)
    elif not decision.allowed:
        # No error bar: for this person, this is not an error, simply not
        # their task.
        st.info(person.confirm_hint)

    left, right = st.columns(2)
    with left:
        confirm = st.button(i18n.t("detail.confirm"), key=f"confirm_{thread_id}",
                            type="primary", disabled=not decision.allowed,
                            width="stretch")
    with right:
        reject = st.button(i18n.t("detail.reject"), key=f"reject_{thread_id}",
                           disabled=not decision.allowed,
                           width="stretch")

    if reject and not st.session_state.get(f"reject_confirmed_{thread_id}"):
        st.session_state[f"reject_confirmed_{thread_id}"] = True
        st.warning(i18n.t("detail.reject.again"))
        return False

    if confirm or reject:
        response = ApprovalResponse(
            decision=ApprovalDecision.APPROVED if confirm else ApprovalDecision.REJECTED,
            approver=upn,
            number=request.get("number"),
            cost_center_id=extra_response.get("cost_center_id"),
        ).as_resume()
        st.session_state.pop(f"reject_confirmed_{thread_id}", None)
        resume(app, thread_id=thread_id, response=response)
        st.rerun()

    return False


def _outcome(values: dict, status: Status, process: str | None,
             displayed_outcome: str) -> None:
    """Completion card: what actually happened in the end?"""
    if not values.get("completed"):
        st.info(i18n.t("detail.in_progress"))
        return

    text = process_views.result_text(displayed_outcome, process)

    st.markdown(f"#### {i18n.t('detail.result')}")
    if status is Status.COMPLETED:
        st.success(text)
    elif status is Status.REJECTED:
        st.warning(text)
    else:
        st.error(text)

    if values.get("error"):
        feedback_key = (
            "detail.technical_details"
            if displayed_outcome == CaseOutcome.BOOKING_UNAVAILABLE.value
            else "detail.feedback"
        )
        st.caption(i18n.t(feedback_key, error=values["error"]))

    if displayed_outcome == CaseOutcome.BOOKING_UNAVAILABLE.value:
        st.info(
            i18n.t("detail.booking_unavailable.next_step"),
            icon=":material/refresh:",
        )

    con = connection()
    try:
        effect = read_effect(con, values)
        chain = verify_chain(con)
    finally:
        con.close()

    if effect.has_effect:
        views = process_views.all_views()
        cols = st.columns(len(views))
        for col, view in zip(cols, views):
            metric = view.effect_metric(effect)
            if metric:
                col.metric(*metric)

    if values.get("approved_by"):
        st.caption(i18n.t("detail.approved_by", approver=values["approved_by"]))

    st.caption(
        i18n.t("detail.chain.valid") if chain.valid
        else i18n.t("detail.chain.broken", detail=chain)
    )


def _document_preview(path: str | None) -> None:
    """Shows the original PDF -- an approver does not decide without the document."""
    if not path or not Path(path).is_file():
        return
    preview = st.expander(i18n.t("detail.view_document"), on_change="rerun")
    if preview.open:
        with preview:
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            st.markdown(
                f'<iframe src="data:application/pdf;base64,{data}" '
                'width="100%" height="620" title="PDF"></iframe>',
                unsafe_allow_html=True,
            )
